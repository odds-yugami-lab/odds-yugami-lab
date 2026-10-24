"""Parse complete WIN odds and verify clock/source/official identities separately."""
import datetime as dt
import re
from result_store import text

JST=dt.timezone(dt.timedelta(hours=9))

def parse(page,race_code,active_numbers):
    web=race_code[2:4]+race_code[8:]
    if '/keiba/race/odds/tfw/'+web not in page:raise ValueError('WIN odds race mismatch')
    plain=text(page);date=re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日',plain)
    if not date or dt.date(*map(int,date.groups())).strftime('%Y%m%d')!=race_code[:8]:raise ValueError('WIN odds date mismatch')
    rows=[]
    tables=[t for t in re.findall(r'<table\b[^>]*>(.*?)</table>',page,re.S) if '単勝' in t and '馬番' in t and '複勝' in t]
    if len(tables)!=1:raise ValueError('WIN odds table missing or ambiguous')
    body=re.search(r'<tbody\b[^>]*>(.*?)</tbody>',tables[0],re.S)
    if not body:raise ValueError('WIN odds table body missing')
    for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>',body[1],re.S):
        cells=re.findall(r'<td\b[^>]*>(.*?)</td>',tr,re.S)
        if len(cells) not in (5,6):raise ValueError('Unexpected WIN odds columns')
        offset=len(cells)-5;number=text(cells[offset+1])
        if not number.isdigit():raise ValueError('Invalid WIN horse number')
        number=int(number)
        if number not in active_numbers:continue # independently verified active set only
        price=text(cells[offset+3]);horse=re.findall(r'/directory/horse/(\d+)/',cells[offset+2])
        if not re.fullmatch(r'\d+(?:\.\d+)?',price) or float(price)<1 or len(set(horse))!=1:
            raise ValueError('Missing active WIN odds or horse identity')
        rows.append({'race_code':race_code,'umaban':number,'horse_id':horse[0],'decimal_odds':float(price)})
    if len(rows)!=len(active_numbers) or {r['umaban'] for r in rows}!=set(active_numbers):raise ValueError('Incomplete/duplicate WIN odds')
    update=re.search(r'(\d{4}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2})\s*更新',plain)
    if not update:raise ValueError('WIN source update time unavailable')
    stamp=dt.datetime.strptime(update[1],'%Y/%m/%d %H:%M').replace(tzinfo=JST)
    return {'race_code':race_code,'rows':rows,'status':'final_postrace' if '確定オッズ' in plain else 'unverified_live',
        'source_updated_at':stamp.isoformat(),'source_updated_at_text':update[1]}

def verify_snapshot(snapshot,metadata,runners,now):
    if now.tzinfo is None:raise ValueError('WIN verification clock timezone required')
    if snapshot.get('status')!='verified_live':raise ValueError('WIN odds have not passed live source verification')
    if snapshot.get('race_code')!=metadata['race_code']:raise ValueError('WIN metadata race mismatch')
    start=dt.datetime.fromisoformat(metadata['race_start_at'])
    if start.tzinfo is None or start.astimezone(JST).date()!=now.astimezone(JST).date() or start-now<dt.timedelta(minutes=12):
        raise ValueError('WIN odds not current before publication deadline')
    obtained=dt.datetime.fromisoformat(snapshot['retrieved_at']);updated=dt.datetime.fromisoformat(snapshot['source_updated_at'])
    if obtained.tzinfo is None or updated.tzinfo is None or not updated<=obtained<=now or now-updated>dt.timedelta(seconds=90) or now-obtained>dt.timedelta(seconds=90):
        raise ValueError('Stale/future WIN odds')
    expected={int(r['umaban']):r['ketto_toroku_bango'] for r in runners}
    if len(snapshot['rows'])!=len(expected) or {int(r['umaban']):r['horse_id'] for r in snapshot['rows']}!=expected:
        raise ValueError('WIN odds and official active identities differ')
    if any(not 1<=r['decimal_odds']<float('inf') for r in snapshot['rows']):raise ValueError('Invalid WIN odds')
    web=metadata['race_code'][2:4]+metadata['race_code'][8:]
    if snapshot.get('source_url')!='https://sports.yahoo.co.jp/keiba/race/odds/tfw/'+web+'?ninki=0':raise ValueError('Unexpected WIN source URL')
    if not re.fullmatch(r'[a-f0-9]{64}',snapshot.get('page_sha256','')):raise ValueError('WIN source evidence missing')
    return True

def acquire(race,official,runners,now=None):
    from source_bundle import download
    now=now or dt.datetime.now(dt.timezone.utc)
    if official.get('verified') is not True or official.get('historical_test'):
        raise ValueError('Current verified official entries required for WIN odds')
    url='https://sports.yahoo.co.jp/keiba/race/odds/tfw/'+race[2:4]+race[8:]+'?ninki=0'
    page,stamp,sha=download(url, phase='win_odds')
    snapshot=parse(page,race,[int(r['umaban']) for r in runners])
    if snapshot['status']!='unverified_live':raise ValueError('Final WIN odds forbidden in live mode')
    # Promote only inside this acquisition layer, then immediately validate all
    # evidence with the actual wall clock. No caller may relabel historical data.
    snapshot.update(status='verified_live',retrieved_at=stamp,source_url=url,page_sha256=sha)
    verify_snapshot(snapshot,{'race_code':race,'race_start_at':official['race_start_at']},runners,dt.datetime.now(dt.timezone.utc))
    return snapshot
