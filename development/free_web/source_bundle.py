"""Acquire matching current entries and complete, fresh in-sale odds.

Current-race execution has not yet been demonstrated. This is a source
validation layer, not evidence that a scheduled forecast was published.
The official entry URL must be resolved from actual JRA links, never guessed.
"""
import concurrent.futures
import datetime as dt
import hashlib
import urllib.request
from entries import parse as parse_entries
from official_entries import fetch as fetch_official,match_free_entries
from odds import parse as parse_odds
from entry_changes import reconcile

JST=dt.timezone(dt.timedelta(hours=9))

def download(url):
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Cache-Control':'no-cache'})
    with urllib.request.urlopen(req,timeout=25) as response:
        raw=response.read();encoding=response.headers.get_content_charset() or 'utf-8'
    return raw.decode(encoding),dt.datetime.now(dt.timezone.utc).isoformat(),hashlib.sha256(raw).hexdigest()

def verify_odds(parsed,official_snapshot,retrieved_at,page_sha256,source_url,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or official_snapshot.get('verified') is not True or official_snapshot.get('historical_test'):
        raise ValueError('Current verified official entries required')
    start=dt.datetime.fromisoformat(official_snapshot['race_start_at'])
    if now.astimezone(JST).date()!=start.astimezone(JST).date() or start-now<dt.timedelta(minutes=12):
        raise ValueError('Not a current race before deadline')
    if parsed['status']!='unverified_live':raise ValueError('Final/post-race odds forbidden')
    update=dt.datetime.strptime(parsed['source_updated_at_text'],'%Y/%m/%d %H:%M').replace(tzinfo=JST)
    acquired=dt.datetime.fromisoformat(retrieved_at)
    official_time=dt.datetime.fromisoformat(official_snapshot['obtained_at'])
    if acquired.tzinfo is None or official_time.tzinfo is None:raise ValueError('Timezone required')
    if not update<=acquired<=now or not official_time<=now or now-update>dt.timedelta(seconds=90) or now-acquired>dt.timedelta(seconds=90) or now-official_time>dt.timedelta(seconds=90):
        raise ValueError('Stale/future source data')
    race=official_snapshot['race_code']
    if not parsed['rows'] or any(r['race_code']!=race for r in parsed['rows']):raise ValueError('Odds race mismatch')
    return dict(parsed,status='verified_live',source_url=source_url,retrieved_at=acquired.isoformat(),
                source_updated_at=update.isoformat(),page_sha256=page_sha256,
                official_entry_page_sha256=official_snapshot['page_sha256'])

def acquire(race_code,official_entry_url):
    # Resolve official URL outside this function through published JRA links.
    official=fetch_official(official_entry_url,race_code,include_page=True)
    official_page=official.pop('entry_page')
    web_id=race_code[2:4]+race_code[8:]
    denma_url=f'https://sports.yahoo.co.jp/keiba/race/denma/{web_id}'
    page,entry_time,entry_sha=download(denma_url)
    runners=parse_entries(page,web_id,'entries')
    expected_start=dt.datetime.fromisoformat(official['race_start_at']).astimezone(JST).strftime('%H:%M')
    if any(r['race_code']!=race_code or r['start_time']!=expected_start for r in runners):
        raise ValueError('Entry date/start mismatch')
    match_free_entries(runners,official)
    active,withdrawn=reconcile(runners,official)
    horses=[int(r['umaban']) for r in active]
    def odds(kind):
        part={'umaren':'ur','sanrenpuku':'sf'}[kind]
        url=f'https://sports.yahoo.co.jp/keiba/race/odds/{part}/{web_id}?ninki=0'
        html,retrieved,sha=download(url)
        parsed=parse_odds(html,race_code,kind,horses)
        return kind,verify_odds(parsed,official,retrieved,sha,url)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        snapshots=dict(pool.map(odds,['umaren','sanrenpuku']))
    return {'race_code':race_code,'official_participation':official,'official_entry_page':official_page,'entry_page':page,
            'entry_source_url':denma_url,'entry_retrieved_at':entry_time,'entry_page_sha256':entry_sha,
            'active_entries':active,'withdrawn_entries':withdrawn,'odds_snapshots':snapshots,
            'obtained_at':dt.datetime.now(dt.timezone.utc).isoformat()}
