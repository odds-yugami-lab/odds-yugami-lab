"""Build previous-start features from linked official JRA result pages.

Race IDs come from the actual result link in the official current entry.
Local/unlinked/unsupported starts are returned as unresolved, not guessed.
"""
import concurrent.futures
import datetime as dt
import hashlib
import re
import urllib.parse
import urllib.request
from entries import TRACKS
from official_results import parse as official_result
from result_store import text
from running_style import classify

def references(page,base_url):
    result=[]
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',page,re.S):
        cells=dict(re.findall(r'<td\b[^>]*class="([^"]+)"[^>]*>(.*?)</td>',row,re.S))
        horse=cells.get('horse','');ids=re.findall(r'pw01dud00(\d{10})/',horse)
        previous=[v for k,v in cells.items() if k.split()[:2]==['past','p1']]
        if not ids or not previous:continue
        if len(set(ids))!=1 or len(previous)!=1:raise ValueError('Ambiguous previous entry')
        name=re.search(r'<div class="name"[^>]*>(.*?)</div>',horse,re.S)
        prev=previous[0];links=re.findall(r'href="([^"]*accessS\.html\?[^\"]+)"',prev)
        if len(links)>1:raise ValueError('Ambiguous previous result link')
        result.append({'horse_id':ids[0],'horse_name':text(name.group(1)),
                       'source_url':urllib.parse.urljoin(base_url,links[0]) if links else None})
    return result

def race_code_from_link(url):
    cname=urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get('CNAME',[''])[0]
    m=re.fullmatch(r'pw01sde\d{2}(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})/[0-9A-F]{2}',cname)
    if not m:raise ValueError('Unsupported official result link')
    venue,year,meeting,day,number,date=m.groups()
    if date[:4]!=year:raise ValueError('Previous link year mismatch')
    return date+venue+meeting+day+number

def resolve(page,reference,target_race_date):
    race=race_code_from_link(reference['source_url'])
    previous=dt.datetime.strptime(race[:8],'%Y%m%d').date();target=dt.date.fromisoformat(target_race_date)
    if previous>=target:raise ValueError('Previous source is not earlier')
    verified=official_result(page,race,reference['source_url'],dt.datetime.now(dt.timezone.utc).isoformat())
    tables=[t for t in re.findall(r'<table\b[^>]*>(.*?)</table>',page,re.S) if '着順' in t and '馬名' in t]
    table=tables[0]
    course=re.search(r'<div class="cell course"[^>]*>(.*?)</div>',table,re.S)
    label=text(course.group(1)) if course else ''
    meta=re.search(r'([\d,]+)\s*メートル\s*（([^）]+)）',label)
    if not meta:raise ValueError('Previous course missing')
    track=meta.group(2).replace('右 外','右・外').replace('左 外','左・外').replace(' ','')
    if track not in TRACKS:raise ValueError('Unsupported previous track')
    body=re.search(r'<tbody[^>]*>(.*?)</tbody>',table,re.S).group(1)
    rows=[]
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',body,re.S):
        cells=dict(re.findall(r'<td\b[^>]*class="([^"]+)"[^>]*>(.*?)</td>',row,re.S))
        rows.append(cells)
    found=[r for r in rows if text(r.get('horse',''))==reference['horse_name']]
    if len(found)!=1:raise ValueError('Previous horse name absent/ambiguous')
    row=found[0];finish=text(row['place']);weight=re.fullmatch(r'(\d+)(?:\(([+-]?\d+)\))?',re.sub(r'\s+','',text(row['h_weight'])))
    corners=list(map(int,re.findall(r'<li\b[^>]*title="[^"]*コーナー通過順位"[^>]*>(\d+)</li>',row.get('corner',''))))
    starters=sum(text(r['place']) not in {'取消','除外'} for r in rows)
    if any(n<1 or n>starters for n in corners):raise ValueError('Invalid previous corners')
    style=classify(corners,starters,finish)
    if style is None:raise ValueError('Individual previous style unavailable')
    elapsed=(target-previous).days
    return {'horse_id':reference['horse_id'],'previous_race_date':previous.isoformat(),
            'days_since_last_race':elapsed,'days_since_previous_race':elapsed,
            'previous_finish_position':int(finish) if finish.isdigit() else None,
            'previous_running_style_code':style,'previous_distance_m':int(meta.group(1).replace(',','')),
            'previous_keibajo_code':race[8:10],'previous_track_code':TRACKS[track],
            'previous_body_weight_kg':int(weight.group(1)) if weight else None,
            'previous_body_weight_change_kg':int(weight.group(2)) if weight and weight.group(2) is not None else None,
            'source_url':reference['source_url'],'page_sha256':hashlib.sha256(page.encode()).hexdigest(),
            'official_previous_fields_matched':True}

def acquire(page,official_entry_url,target_race_date):
    refs=references(page,official_entry_url)
    def get(url):
        request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(request,timeout=25) as response:
            raw=response.read();charset=response.headers.get_content_charset()
        if not charset:
            m=re.search(br'charset=["\x27]?([A-Za-z0-9_-]+)',raw[:2000],re.I);charset=m.group(1).decode() if m else 'utf-8'
        return url,raw.decode(charset)
    urls=sorted({r['source_url'] for r in refs if r['source_url']})
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:pages=dict(pool.map(get,urls))
    evidence=[];unresolved=[]
    for ref in refs:
        if not ref['source_url']:unresolved.append({'horse_id':ref['horse_id'],'reason':'no_official_JRA_previous_link'});continue
        try:evidence.append(resolve(pages[ref['source_url']],ref,target_race_date))
        except ValueError as error:unresolved.append({'horse_id':ref['horse_id'],'reason':str(error)})
    return evidence,unresolved
