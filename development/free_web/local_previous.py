"""Resolve a supported local previous start from official JRA/NAR evidence.

Currently tested for Oi dirt-right only. NAR IDs are never equated with JRA
horse IDs; the current official entry's horse ID/name and previous fields
are matched against the single NAR result row.
"""
import datetime as dt
import hashlib
import re
import urllib.parse
from result_store import text
from running_style import classify

def reference_from_jra(page,horse_id):
    matches=[]
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',page,re.S):
        cells=dict(re.findall(r'<td\b[^>]*class="([^"]+)"[^>]*>(.*?)</td>',row,re.S))
        horse=cells.get('horse','')
        if f'pw01dud00{horse_id}/' not in horse:continue
        previous=[v for k,v in cells.items() if k.split()[:2]==['past','p1']]
        if len(previous)!=1:raise ValueError('Missing previous start in official entries')
        name=re.search(r'<div class="name"[^>]*>(.*?)</div>',horse,re.S)
        hname=text(name.group(1)) if name else None
        prev=previous[0]
        def field(tag,cls):
            m=re.search(r'<'+tag+r'\b[^>]*class="'+cls+r'"[^>]*>(.*?)</'+tag+'>',prev,re.S)
            if not m:raise ValueError('Previous field missing: '+cls)
            return text(m.group(1))
        date=field('div','date');venue=field('div','rc');rank=field('div','place')
        distance=field('span','dist');weight=field('p','h_weight')
        d=re.fullmatch(r'(\d+)年(\d+)月(\d+)日',date);f=re.fullmatch(r'(\d+)\s*着',rank)
        km=re.fullmatch(r'(\d+)ダ',distance);bw=re.fullmatch(r'(\d+)\s*kg',weight)
        if not all([d,f,km,bw]) or venue!='大井':raise ValueError('Unsupported local previous start')
        matches.append({'horse_id':horse_id,'horse_name':hname,'race_date':dt.date(*map(int,d.groups())).isoformat(),
                        'venue':'大井','venue_code':'44','finish':int(f.group(1)),
                        'distance_m':int(km.group(1)),'body_weight_kg':int(bw.group(1))})
    if len(matches)!=1:raise ValueError('Ambiguous official horse/previous reference')
    return matches[0]

def resolve(page,source_url,reference,target_race_date,jra_source_url):
    url=urllib.parse.urlparse(source_url);params=urllib.parse.parse_qs(url.query)
    if url.hostname not in {'www.keiba.go.jp','keiba.go.jp'} or not url.path.endswith('/RaceMarkTable'):
        raise ValueError('Official NAR result source required')
    expected=reference['race_date'].replace('-','/')
    if params.get('k_raceDate')!=[expected] or params.get('k_babaCode')!=['20']:
        raise ValueError('NAR race/date/venue mismatch')
    race_no=params.get('k_raceNo',[''])[0]
    if not race_no.isdigit() or not 1<=int(race_no)<=12:raise ValueError('NAR race number missing')
    previous_date=dt.date.fromisoformat(reference['race_date']);target=dt.date.fromisoformat(target_race_date)
    if previous_date>=target:raise ValueError('Not a previous start')
    plain=text(page);date_label=f'{previous_date.year}年{previous_date.month}月{previous_date.day}日'
    if date_label not in plain or f'第{int(race_no)}競走' not in plain or not re.search(r'ダート\s*'+str(reference['distance_m'])+r'ｍ（外コース・右）',plain):
        raise ValueError('Unsupported NAR header/course')
    tables=[t for t in re.findall(r'<table\b[^>]*>(.*?)</table>',page,re.S) if '着順' in t and 'corner_position' in t]
    if len(tables)!=1:raise ValueError('NAR result table missing')
    rows=[]
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',tables[0],re.S):
        cells=re.findall(r'<td\b[^>]*>(.*?)</td>',row,re.S)
        if not cells:continue
        if len(cells)!=16:raise ValueError('Unexpected NAR result columns')
        rows.append([text(c) for c in cells])
    matches=[r for r in rows if r[3]==reference['horse_name']]
    if len(matches)!=1:raise ValueError('NAR horse name absent/ambiguous')
    row=matches[0];weight=re.fullmatch(r'(\d+)\s*\(([+-]?\d+)\)',re.sub(r'\s+','',row[9]))
    if not weight or not row[0].isdigit():raise ValueError('NAR previous result missing')
    if int(row[0])!=reference['finish'] or int(weight.group(1))!=reference['body_weight_kg']:
        raise ValueError('JRA/NAR previous start differs')
    corners=list(map(int,row[13].split('-'))) if re.fullmatch(r'\d+(?:-\d+)+',row[13]) else []
    starters=sum(r[0] not in {'取消','除外'} for r in rows)
    if not corners or any(n<1 or n>starters for n in corners):raise ValueError('NAR individual corners missing')
    style=classify(corners,starters,row[0]);elapsed=(target-previous_date).days
    return {'horse_id':reference['horse_id'],'previous_race_date':reference['race_date'],
            'days_since_last_race':elapsed,'days_since_previous_race':elapsed,
            'previous_finish_position':int(row[0]),'previous_running_style_code':style,
            'previous_distance_m':reference['distance_m'],'previous_keibajo_code':'44','previous_track_code':'24',
            'previous_body_weight_kg':int(weight.group(1)),'previous_body_weight_change_kg':int(weight.group(2)),
            'source_url':source_url,'jra_source_url':jra_source_url,
            'page_sha256':hashlib.sha256(page.encode()).hexdigest(),'jra_nar_previous_fields_matched':True}
