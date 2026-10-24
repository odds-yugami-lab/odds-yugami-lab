"""Read supported official desktop entry identities and participation status.

Historical pages may test parsing, but cannot certify current live status.
No cancellation is inferred from missing weight/odds. Explicit labels only.
"""
import datetime as dt
import hashlib
import re
import urllib.parse
import urllib.request
import urllib.error
from result_store import text
from official_results import VENUES

def fetch(source_url,race_code,historical_test=False,include_page=False):
    if urllib.parse.urlparse(source_url).hostname not in {'jra.jp','www.jra.jp','jra.go.jp','www.jra.go.jp'}:
        raise ValueError('Official entry URL required')
    req=urllib.request.Request(source_url,headers={'User-Agent':'Mozilla/5.0','Cache-Control':'no-cache'})
    try:
        with urllib.request.urlopen(req,timeout=25) as response:
            raw=response.read();final=response.url;charset=response.headers.get_content_charset()
    except urllib.error.HTTPError as exc:
        location=urllib.parse.urlsplit(source_url)
        raise RuntimeError(f'OFFICIAL_ENTRY_HTTP_ERROR host={location.hostname} path={location.path} status={exc.code}') from exc
    if not charset:
        m=re.search(br'charset=["\x27]?([A-Za-z0-9_-]+)',raw[:2000],re.I)
        charset=m.group(1).decode() if m else 'utf-8'
    page=raw.decode(charset)
    result=parse(page,race_code,final,dt.datetime.now(dt.timezone.utc).isoformat(),historical_test)
    result['raw_page_sha256']=hashlib.sha256(raw).hexdigest()
    if include_page:result['entry_page']=page
    return result

def parse(page,race_code,source_url,obtained_at,historical_test=False,preliminary=False):
    if urllib.parse.urlparse(source_url).hostname not in {'jra.jp','www.jra.jp','jra.go.jp','www.jra.go.jp'}:
        raise ValueError('Official entry source required')
    stamp=dt.datetime.fromisoformat(obtained_at)
    if stamp.tzinfo is None:raise ValueError('Timezone required')
    date=dt.datetime.strptime(race_code[:8],'%Y%m%d').date()
    tables=[t for t in re.findall(r'<table\b[^>]*>(.*?)</table>',page,re.S)
            if 'class="past p1"' in t and '馬番' in t and '騎手名' in t]
    if len(tables)!=1:raise ValueError('Full official entries missing or expired')
    table=tables[0];plain=text(table)
    meeting=f'{int(race_code[10:12])}回{VENUES[race_code[8:10]]}{int(race_code[12:14])}日'
    if f'{date.year}年{date.month}月{date.day}日' not in plain or meeting not in plain or f'alt="{int(race_code[14:])}レース"' not in table:
        raise ValueError('Official entry race mismatch')
    start=re.search(r'発走時刻：\s*(\d+)時(\d+)分',plain)
    if not start:raise ValueError('Start time missing')
    start_at=dt.datetime.combine(date,dt.time(*map(int,start.groups())),dt.timezone(dt.timedelta(hours=9)))
    if preliminary and (historical_test or stamp>=start_at):
        raise ValueError('Preliminary snapshot must precede race and cannot be historical')
    if not historical_test and not preliminary and not (stamp.astimezone(start_at.tzinfo).date()==date and stamp<start_at):
        raise ValueError('Not a current pre-race entry snapshot')
    body=re.search(r'<tbody\b[^>]*>(.*?)</tbody>',table,re.S)
    if not body:raise ValueError('Official entry body missing')
    rows=[]
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',body.group(1),re.S):
        cells=dict((name,content) for name,content in re.findall(r'<td\b[^>]*class="([^"]+)"[^>]*>(.*?)</td>',row,re.S))
        if 'num' not in cells or 'horse' not in cells or 'jockey' not in cells:raise ValueError('Unexpected entry row')
        num=text(cells['num'])
        horse=re.findall(r'pw01dud00(\d{10})/',cells['horse'])
        jockey=re.findall(r'pw04kmk0(\d{5})/',cells['jockey'])
        trainer=re.findall(r'pw05cmk0(\d{5})/',cells['horse'])
        name_line=re.search(r'<div class="name_line">(.*?)</div>\s*(?:<div|<p)',cells['horse'],re.S)
        # Status labels must be inside this horse's present-entry cells.
        current=text(cells['horse'])+' '+text(cells['jockey'])
        status='cancelled' if re.search(r'(?:出走取消|取消)',current) else 'excluded' if re.search(r'(?:競走除外|除外)',current) else 'active'
        if len(set(horse))!=1:raise ValueError('Invalid entry identity')
        number=int(num) if num.isdigit() and 1<=int(num)<=18 else None
        if number is None and (not preliminary or num):raise ValueError('Invalid entry identity')
        horse_names=re.findall(r'<a\b[^>]*href="[^"]*pw01dud00\d{10}/[^"]*"[^>]*>(.*?)</a>',cells['horse'],re.S)
        if len(horse_names)!=1 or not text(horse_names[0]):raise ValueError('Horse name missing or ambiguous')
        frame=re.search(r'alt="([1-8])枠"',cells.get('waku',''))
        jockey_name=re.search(r'<p class="jockey"[^>]*>(.*?)</p>',cells['jockey'],re.S)
        trainer_name=re.search(r'<p class="trainer"[^>]*>(.*?)</p>',cells['horse'],re.S)
        jname=text(jockey_name.group(1)) if jockey_name else None
        tname=text(re.sub(r'<span\b.*?</span>','',trainer_name.group(1),flags=re.S)) if trainer_name else None
        if status=='active' and (not jname or not tname):raise ValueError('Current participant missing')
        weight=re.search(r'class="cell weight"[^>]*>(.*?)</div>',cells['horse'],re.S)
        bw=re.fullmatch(r'(\d+)kg\s*\(([+-]?\d+)\)',text(weight.group(1))) if weight else None
        rows.append({'ketto_toroku_bango':horse[0],'umaban':number,
                     'horse_name':text(horse_names[0]),'wakuban':int(frame.group(1)) if frame else None,
                     'jockey_code':jockey[0] if jockey else None,'trainer_code':trainer[0] if trainer else None,
                     'jockey_name':jname,'trainer_name':tname,
                     'body_weight_kg':int(bw.group(1)) if bw else None,
                     'body_weight_change_kg':int(bw.group(2)) if bw else None,'participation_status':status})
    numbers=[r['umaban'] for r in rows if r['umaban'] is not None]
    if not rows or len(set(numbers))!=len(numbers) or len({r['ketto_toroku_bango'] for r in rows})!=len(rows):
        raise ValueError('Duplicate/empty official entries')
    race_name=re.search(r'<span class="race_name"[^>]*>(.*?)</span>',table,re.S)
    return {'race_code':race_code,'race_name':text(race_name.group(1)) if race_name else race_code,
            'obtained_at':stamp.isoformat(),'source_url':source_url,
            'verified':not historical_test and not preliminary,'historical_test':historical_test,
            'preliminary':preliminary,
            'horse_statuses':{r['ketto_toroku_bango']:r['participation_status'] for r in rows},
            'rows':rows,'race_start_at':start_at.isoformat(),
            'page_sha256':hashlib.sha256(page.encode()).hexdigest()}

def match_free_entries(free_rows,official):
    if {r['ketto_toroku_bango'] for r in free_rows}!=set(official['horse_statuses']):
        raise ValueError('Free/official horse sets differ')
    by_id={r['ketto_toroku_bango']:r for r in official['rows']}
    for row in free_rows:
        confirmed=by_id[row['ketto_toroku_bango']]
        if int(row['umaban'])!=confirmed['umaban']:raise ValueError('Horse number mismatch')
        if confirmed['participation_status']!='active':continue
        for field in ['jockey_code','trainer_code']:
            if confirmed[field] is None:
                name=field.replace('_code','_name')
                normalize=lambda value:re.sub(r'\s+','',value or '')
                if not row.get(name) or normalize(row[name])!=normalize(confirmed[name]):raise ValueError('Participant name mismatch')
            elif row.get(field)!=confirmed[field]:raise ValueError('Participant ID mismatch')
        for field in ['body_weight_kg','body_weight_change_kg']:
            if row.get(field)!=confirmed[field]:raise ValueError('Current entry differs: '+field)
    return True
