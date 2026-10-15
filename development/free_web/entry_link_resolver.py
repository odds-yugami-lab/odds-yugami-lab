"""Resolve official entry links through actual published JRA anchors.

An unpublished entry hub is a normal explicit status, never a guessed URL.
No CNAME/checksum is constructed independently of published links.
"""
import re
import urllib.parse
from official_results import VENUES
from public_previous import race_code_from_link
from result_store import text
from source_bundle import download

BASE='https://www.jra.go.jp'

def landing_url(index_page,race_code):
    month=int(race_code[4:6]);day=int(race_code[6:8]);matches=[]
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',index_page,re.S):
        d=re.search(r'<td\b[^>]*class="date"[^>]*>(.*?)</td>',row,re.S)
        venue=re.search(r'<td\b[^>]*class="place"[^>]*>(.*?)</td>',row,re.S)
        race=re.search(r'<td\b[^>]*class="race"[^>]*>(.*?)</td>',row,re.S)
        if not d or not venue or not race:continue
        if not re.match(f'{month}月{day}日(?:[^0-9]|$)',text(d.group(1))) or text(venue.group(1))!=VENUES[race_code[8:10]]:continue
        if not re.search(r'grade_icon g[123]"',race.group(1)):continue
        links=re.findall(r'href="([^"]+)"',race.group(1))
        if len(links)==1:matches.append(urllib.parse.urljoin(BASE,links[0]))
    if len(matches)!=1:raise ValueError('Graded race landing unavailable or ambiguous')
    return matches[0]

def hub_url(landing_page,landing_source):
    prefix=urllib.parse.urlparse(landing_source).path.removesuffix('.html')+'/'
    links={urllib.parse.urljoin(landing_source,link) for link in re.findall(r'href="([^"]+)"',landing_page)
           if urllib.parse.urlparse(urllib.parse.urljoin(landing_source,link)).path.endswith('/syutsuba.html')
           and urllib.parse.urlparse(urllib.parse.urljoin(landing_source,link)).path.startswith(prefix)}
    if len(links)!=1:raise ValueError('Official entry hub absent or ambiguous')
    return next(iter(links))

def from_hub(page,source_url,race_code):
    candidates=set()
    for link in re.findall(r'(?:href|src)="([^"]*accessD\.html\?[^\"]+)"',page):
        candidates.add(urllib.parse.urljoin(source_url,link))
    for path,cname in re.findall(r'doAction\(\s*[\x27"]([^\x27"]*accessD\.html)[\x27"]\s*,\s*[\x27"](pw01dde[^\x27"]+)[\x27"]\s*\)',page):
        candidates.add(urllib.parse.urljoin(source_url,path)+'?'+urllib.parse.urlencode({'CNAME':cname}))
    matching=[]
    for url in candidates:
        try:
            if race_code_from_link(url.replace('pw01dde','pw01sde',1))==race_code:matching.append(url)
        except ValueError:continue
    if matching:
        preferred=[u for u in matching if 'pw01dde10' in u]
        values=preferred or matching
        if len(set(values))!=1:raise ValueError('Ambiguous official entry links')
        return {'race_code':race_code,'status':'published','entry_url':values[0],'entry_hub_url':source_url}
    plain=text(page)
    unpublished=re.search(r'出馬表は、\s*(\d{4})年(\d{1,2})月(\d{1,2})日.*?公開予定',plain)
    if unpublished:
        y,m,d=map(int,unpublished.groups())
        return {'race_code':race_code,'status':'not_yet_published','entry_url':None,
                'entry_hub_url':source_url,'expected_publication_date':f'{y:04d}-{m:02d}-{d:02d}'}
    return {'race_code':race_code,'status':'unresolved','entry_url':None,'entry_hub_url':source_url}

def resolve(race_code):
    index=f'{BASE}/datafile/seiseki/replay/{race_code[:4]}/jyusyo.html'
    page,_,_=download(index);landing=landing_url(page,race_code)
    page,stamp,digest=download(landing)
    direct=from_hub(page,landing,race_code)
    if direct['status']=='published':
        direct.update(official_index_url=index,landing_url=landing,retrieved_at=stamp,
                      page_sha256=digest,link_location='race_landing_page')
        return direct
    try:hub=hub_url(page,landing)
    except ValueError:
        return {'race_code':race_code,'status':'unresolved','entry_url':None,
                'landing_url':landing,'reason':'entry_hub_not_linked_or_archived'}
    page,stamp,digest=download(hub);result=from_hub(page,hub,race_code)
    result.update(official_index_url=index,landing_url=landing,retrieved_at=stamp,page_sha256=digest)
    return result
