"""Public-only web collector for the ChatGPT cloud Python runner.

No private model/history/fixture is read or accepted. Same-day sources are
refreshed AFTER previous-race downloads. The cloud runner does the inference.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
from source_bundle import acquire, download
from entry_link_resolver import resolve
from official_entries import fetch as fetch_entries
from public_previous import acquire as acquire_previous


def collect_live(race):
    link = resolve(race)
    if link['status'] != 'published':
        raise ValueError('Official entry link unavailable: ' + link['status'])
    initial = fetch_entries(link['entry_url'], race, include_page=True)
    previous, unresolved = acquire_previous(initial['entry_page'], link['entry_url'],
        dt.datetime.strptime(race[:8], '%Y%m%d').date().isoformat())
    current = acquire(race, link['entry_url'])
    active_ids = {r['ketto_toroku_bango'] for r in current['active_entries']}
    return {'mode': 'live', 'race_code': race,
        'official_participation': current['official_participation'],
        'active_entries': current['active_entries'],
        'withdrawn_entries': current['withdrawn_entries'],
        'previous_evidence': [r for r in previous if r['horse_id'] in active_ids],
        'unresolved_previous': [r for r in unresolved if r['horse_id'] in active_ids],
        'odds_snapshots': current['odds_snapshots'],
        'entry_source_url': current['entry_source_url'],
        'entry_retrieved_at': current['entry_retrieved_at'],
        'entry_page_sha256': current['entry_page_sha256'],
        'obtained_at': current['obtained_at']}


def historical_sources(race):
    from odds import parse
    from official_results import fetch_for_race
    if dt.datetime.strptime(race[:8], '%Y%m%d').date() >= dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date():
        raise ValueError('Historical collector requires a past race')
    payouts = fetch_for_race(race)
    # Official result establishes all starter numbers (including unplaced).
    numbers = sorted(int(r['horse_number']) for r in payouts['finish_rows']
                     if r['finish_status'] not in {'取消', '除外'})
    snapshots = {}
    web = race[2:4] + race[8:]
    for kind, part in [('umaren', 'ur'), ('sanrenpuku', 'sf')]:
        url = f'https://sports.yahoo.co.jp/keiba/race/odds/{part}/{web}?ninki=0'
        page, stamp, sha = download(url)
        snapshot = parse(page, race, kind, numbers)
        if snapshot['status'] != 'final_postrace':
            raise ValueError('Expected final historical odds')
        snapshots[kind] = dict(snapshot, source_url=url, retrieved_at=stamp, page_sha256=sha)
    return {'mode': 'historical_rehearsal', 'race_code': race, 'test_only': True,
            'odds_snapshots': snapshots, 'payout_snapshot': payouts,
            'obtained_at': dt.datetime.now(dt.timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('request')
    parser.add_argument('output')
    args = parser.parse_args()
    path = Path(args.request)
    data = json.loads(path.read_text())
    if set(data) != {'race_code', 'mode', 'run_id'}:
        raise ValueError('Only public collector parameters are accepted')
    race, mode, run_id = data['race_code'], data['mode'], data['run_id']
    if not re.fullmatch(r'\d{16}', race) or not re.fullmatch(r'[A-Za-z0-9_-]+', run_id) or path.stem != run_id:
        raise ValueError('Invalid public collector request')
    try:
        if mode == 'live':
            result = collect_live(race)
        elif mode == 'historical_rehearsal':
            result = historical_sources(race)
        else:
            raise ValueError('Unsupported collector mode')
        result.update(status='collected', run_id=run_id)
    except Exception as exc:
        result = {'status': 'failed', 'race_code': race, 'mode': mode, 'run_id': run_id,
                  'error_type': type(exc).__name__, 'error': str(exc)[:500]}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True,
                                          indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
