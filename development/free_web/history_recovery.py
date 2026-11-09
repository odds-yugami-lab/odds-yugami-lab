"""Resumable public-source staging BEFORE history verification and prediction.

This private directory is not a publication target. Staging never certifies
coverage: pedigree resolution, official cross-checks, append and private
archive readback must still finish before history_preflight can pass.
"""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
from entries import parse as parse_entries
from result_store import parse_result
from source_bundle import download
from resilience import atomic_json, Journal


def cached(directory, url):
    key = hashlib.sha256(url.encode()).hexdigest()
    path = directory / (key + '.json')
    if path.exists():
        value = json.loads(path.read_text(encoding='utf-8'))
        if value['source_url'] != url or hashlib.sha256(value['page'].encode()).hexdigest() != value['text_sha256']:
            raise ValueError('Staged source integrity mismatch')
        return value
    page, stamp, sha = download(url, phase='history_recovery')
    value = {'source_url': url, 'retrieved_at': stamp, 'page_sha256': sha,
             'text_sha256': hashlib.sha256(page.encode()).hexdigest(), 'page': page}
    atomic_json(path, value)
    return value


def stage(date, meetings, directory):
    day = dt.date.fromisoformat(date)
    if day >= dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date():
        raise ValueError('Only completed past dates can be staged')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with Journal(directory, day.strftime('%Y%m%d')).locked():
        expected = []
        for meeting in meetings:
            if not re.fullmatch(r'\d{8}', meeting) or meeting[:2] != day.strftime('%y'):
                raise ValueError('Invalid meeting identity')
            source = cached(directory, 'https://sports.yahoo.co.jp/keiba/race/list/' + meeting)
            races = sorted(set(re.findall(r'/keiba/race/(?:index|result|denma)/(\d{10})', source['page'])))
            races = [race for race in races if race.startswith(meeting)]
            if races != [meeting + f'{n:02d}' for n in range(1, 13)]:
                raise ValueError('Full meeting listing not established')
            expected.extend(races)
        if len(set(expected)) != len(expected):
            raise ValueError('Duplicate meeting')
        def acquire(race):
            evidence = {}
            for kind in ('result', 'denma'):
                evidence[kind] = cached(directory, 'https://sports.yahoo.co.jp/keiba/race/' + kind + '/' + race)
            results = parse_result(evidence['result']['page'], race)
            errors = []
            try:
                entries = parse_entries(evidence['denma']['page'], race, 'entries')
                if any(row['race_date'] != date for row in entries):
                    raise ValueError('Staged entry date mismatch')
                if {(r['horse_id'], r['horse_number'], r['jockey_id'], r['trainer_id']) for r in results} != {
                    (r['ketto_toroku_bango'], int(r['umaban']), r['jockey_code'], r['trainer_code']) for r in entries}:
                    raise ValueError('Result/entry field mismatch')
            except ValueError as exc:
                entries = []
                errors.append(str(exc))
            value = {'race_id': race, 'date': date, 'results': results, 'entries': entries,
                'errors': errors, 'history_verified': False,
                'evidence': {k: {n:v for n,v in s.items() if n != 'page'} for k,s in evidence.items()}}
            atomic_json(directory / (race + '_staged.json'), value)
            return {'race_id': race, 'result_rows': len(results), 'entry_rows': len(entries), 'errors': errors}
        races, failures = [], []
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            jobs = {pool.submit(acquire, race): race for race in expected}
            for future in concurrent.futures.as_completed(jobs):
                try:
                    races.append(future.result())
                except Exception as exc:
                    failures.append({'race_id': jobs[future], 'error_type': type(exc).__name__, 'error': str(exc)[:500]})
                atomic_json(directory / 'progress.json', {'date':date, 'staged':len(races), 'failures':failures})
        summary = {'date': date, 'expected_races': len(expected), 'staged_races': len(races),
            'result_rows': sum(r['result_rows'] for r in races),
            'entry_rows': sum(r['entry_rows'] for r in races), 'races': sorted(races,key=lambda r:r['race_id']),
            'failures': failures, 'history_updated': False, 'coverage_promoted': False,
            'private_archive_saved': False, 'status': 'staged_not_history_complete'}
        atomic_json(directory / 'summary.json', summary)
        return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', required=True)
    parser.add_argument('--meetings', nargs='+', required=True)
    parser.add_argument('--private-dir', required=True)
    args = parser.parse_args()
    report = stage(args.date, args.meetings, args.private_dir)
    print(json.dumps({k:report[k] for k in ('date','expected_races','staged_races','result_rows','entry_rows','status')}))
    raise SystemExit(1 if report['failures'] else 0)
