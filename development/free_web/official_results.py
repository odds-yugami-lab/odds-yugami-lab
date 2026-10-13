"""Fetch/parse supported JRA official desktop result HTML.

Supports tested static G1/G2 and correct linked desktop result pages.
Does not support pre-race participation acquisition.
Unsupported pages fail closed. PDF digit extraction is not trusted.
"""
import datetime as dt
import hashlib
import re
import urllib.parse
import urllib.request
from result_store import text

VENUES={'01':'札幌','02':'函館','03':'福島','04':'新潟','05':'東京',
        '06':'中山','07':'中京','08':'京都','09':'阪神','10':'小倉'}

def result_url(index_page,race_code):
    date=dt.datetime.strptime(race_code[:8],'%Y%m%d').date()
    candidates=[]
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',index_page,re.S):
        date_cell=re.search(r'<td\b[^>]*class="date"[^>]*>(.*?)</td>',row,re.S)
        place=re.search(r'<td\b[^>]*class="place"[^>]*>(.*?)</td>',row,re.S)
        if not date_cell or not place:continue
        if not re.match(f'{date.month}月{date.day}日(?:[^0-9]|$)',text(date_cell.group(1))):continue
        if text(place.group(1))!=VENUES[race_code[8:10]]:continue
        if not re.search(r'grade_icon g[123]"',row):continue
        result=re.search(r'<td\b[^>]*class="result"[^>]*>(.*?)</td>',row,re.S)
        links=re.findall(r'href="([^"]+)"',result.group(1)) if result else []
        if len(links)==1:candidates.append(urllib.parse.urljoin('https://www.jra.go.jp',links[0]))
    if len(candidates)!=1:raise ValueError('Official graded result unavailable or ambiguous')
    return candidates[0]

def fetch_for_race(race_code):
    index_url=f'https://www.jra.go.jp/datafile/seiseki/replay/{race_code[:4]}/jyusyo.html'
    request=urllib.request.Request(index_url,headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(request,timeout=25) as response:
        raw=response.read();charset=response.headers.get_content_charset() or 'shift_jis'
    url=result_url(raw.decode(charset),race_code)
    return fetch(url,race_code)

def parse(page,race_code,source_url,obtained_at):
    host=urllib.parse.urlparse(source_url).hostname
    if host not in {'www.jra.go.jp','jra.go.jp','www.jra.jp','jra.jp'}:
        raise ValueError('Official JRA source required')
    if not re.fullmatch(r'\d{16}',race_code):raise ValueError('Invalid race code')
    stamp=dt.datetime.fromisoformat(obtained_at)
    if stamp.tzinfo is None:raise ValueError('Timezone required')
    tables=[t for t in re.findall(r'<table\b[^>]*>(.*?)</table>',page,re.S) if '着順' in t and '馬名' in t]
    if len(tables)!=1:raise ValueError('Unsupported official result table')
    table=tables[0];plain=text(table)
    expected_date=dt.datetime.strptime(race_code[:8],'%Y%m%d').date()
    expected_header=f'{expected_date.year}年{expected_date.month}月{expected_date.day}日'
    meeting=f'{int(race_code[10:12])}回{VENUES[race_code[8:10]]}{int(race_code[12:14])}日'
    if expected_header not in plain or meeting not in plain or f'alt="{int(race_code[14:])}レース"' not in table:
        raise ValueError('Official result identity mismatch')
    body=re.search(r'<tbody\b[^>]*>(.*?)</tbody>',table,re.S)
    if not body:raise ValueError('No completed results')
    finishes=[];refunds=[]
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',body.group(1),re.S):
        rank=re.search(r'<td\b[^>]*class="place"[^>]*>(.*?)</td>',row,re.S)
        horse=re.search(r'<td\b[^>]*class="num"[^>]*>(.*?)</td>',row,re.S)
        if not rank or not horse:raise ValueError('Unsupported result row')
        n=int(text(horse.group(1)));value=text(rank.group(1))
        if not 1<=n<=18:raise ValueError('Invalid horse number')
        if value in {'取消','除外'}:refunds.append(n)
        elif value in {'中止','失格'} or value.isdigit():pass
        else:raise ValueError('Unknown finish status')
        finishes.append({'horse_number':n,'finish_status':value})
    if len({r['horse_number'] for r in finishes})!=len(finishes) or not any(r['finish_status']=='1' for r in finishes):
        raise ValueError('Incomplete results')
    payouts={}
    for cls,kind,size in [('umaren','umaren',2),('trio','sanrenpuku',3)]:
        blocks=re.findall(r'<li\b[^>]*class="'+cls+r'"[^>]*>(.*?)</li>',page,re.S)
        if len(blocks)!=1:raise ValueError('Official payout missing')
        nums=re.findall(r'<div\b[^>]*class="num"[^>]*>(.*?)</div>',blocks[0],re.S)
        amounts=re.findall(r'<div\b[^>]*class="yen"[^>]*>(.*?)</div>',blocks[0],re.S)
        if not nums or len(nums)!=len(amounts):raise ValueError('Incomplete payout lines')
        values={}
        for num,amount in zip(nums,amounts):
            tokens=text(num).split('-')
            if len(tokens)!=size or not all(x.isdigit() for x in tokens):raise ValueError('Invalid payout key')
            numbers=sorted(map(int,tokens));key=''.join(f'{x:02d}' for x in numbers)
            yen=re.sub(r'\s+','',text(amount))
            if len(set(numbers))!=size or not all(1<=x<=18 for x in numbers) or not re.fullmatch(r'[\d,]+円',yen):raise ValueError('Invalid payout')
            value=int(yen[:-1].replace(',',''))
            if value<=0 or key in values:raise ValueError('Duplicate/invalid payout')
            values[key]=value
        payouts[kind]=values
    return {'race_code':race_code,'official_verified':True,'source_url':source_url,
            'obtained_at':stamp.isoformat(),'page_sha256':hashlib.sha256(page.encode()).hexdigest(),
            'payouts_per_100_yen':payouts,'refunded_horse_numbers':refunds,
            'finish_rows':finishes,'source_format':'JRA_desktop_result_HTML',
            'usable_for_pre_race_participation':False}

def fetch(source_url,race_code):
    if urllib.parse.urlparse(source_url).hostname not in {'www.jra.go.jp','jra.go.jp','www.jra.jp','jra.jp'}:
        raise ValueError('Official URL required')
    request=urllib.request.Request(source_url,headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(request,timeout=25) as response:
        raw=response.read();final=response.url
        charset=response.headers.get_content_charset()
    if not charset:
        match=re.search(br'charset=["\x27]?([A-Za-z0-9_-]+)',raw[:2000],re.I)
        charset=match.group(1).decode() if match else 'utf-8'
    page=raw.decode(charset,errors='strict')
    result=parse(page,race_code,final,dt.datetime.now(dt.timezone.utc).isoformat())
    result['raw_page_sha256']=hashlib.sha256(raw).hexdigest()
    return result
