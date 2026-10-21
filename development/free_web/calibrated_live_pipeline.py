"""Compose official entries, public previous results, history and saved model.

Supports the public collector for cloud runtimes that cannot reach JRA/Yahoo
directly. Collector output contains public sources only, never model/history.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path
from feature_pipeline import assemble
from pre_race_record import timestamp
from calibrated_pre_race import prepare
from win_odds import acquire as acquire_win_odds


def check_window(start, window):
    import re
    if not re.fullmatch(r'\d{2}:\d{2}-\d{2}:\d{2}', window):
        raise ValueError('Invalid official-start window')
    low, high = window.split('-')
    clock = timestamp(start).astimezone(dt.timezone(dt.timedelta(hours=9))).strftime('%H:%M')
    if not low <= clock <= high:
        raise ValueError('Official start outside this task window')


def prepare_from_sources(bundle, model_dir, history_dir, pedigree_paths=(), coverage_check=None):
    if bundle.get('mode') != 'live' or bundle.get('race_code') != bundle['official_participation']['race_code']:
        raise ValueError('Current live collector output required')
    if bundle.get('unresolved_previous'):
        raise ValueError('Previous race evidence unresolved; no stored-value substitution')
    history_dir = Path(history_dir)
    coverage = json.loads((history_dir / 'coverage_manifest.json').read_text())
    history = history_dir / 'history.parquet'
    if hashlib.sha256(history.read_bytes()).hexdigest() != coverage['history_sha256']:
        raise ValueError('History bytes differ from coverage manifest')
    spec = json.loads((Path(model_dir) / 'feature_spec.json').read_text())
    race = bundle['race_code']
    official = bundle['official_participation']
    rows = bundle['active_entries']
    from history_coverage import effective_coverage
    now = dt.datetime.now(dt.timezone.utc)
    yesterday = now.astimezone(dt.timezone(dt.timedelta(hours=9))).date() - dt.timedelta(days=1)
    checked_through, calendar_evidence = coverage_check or effective_coverage(coverage['history_complete_through'], yesterday.isoformat())
    assembly = assemble('', race[2:4] + race[8:], 'entries', history, spec, [],
        dt.datetime.now(dt.timezone.utc).isoformat(), checked_through,
        pedigree_paths=pedigree_paths, participation_snapshot=official,
        previous_overrides=bundle['previous_evidence'], entry_rows=rows+bundle['withdrawn_entries'])
    if not assembly['prediction_ready']:
        missing = {r['ketto_toroku_bango']: r['unpublished_or_unresolved']
                   for r in assembly['runners'] if r['unpublished_or_unresolved']}
        raise ValueError('Features not ready: ' + str(assembly['blockers']) + '; missing=' + str(missing))
    numbers = {int(r['umaban']) for r in rows}
    evidenced = {r['horse_id'] for r in bundle['previous_evidence']}
    if evidenced != {r['ketto_toroku_bango'] for r in rows}:
        raise ValueError('All active horses need publicly verified previous evidence')
    metadata = {'race_code': race, 'race_name': official['race_name'],
        'race_start_at': official['race_start_at'],
        'participation_obtained_at': official['obtained_at'],
        'features_obtained_at': assembly['features_obtained_at'],
        'active_horse_numbers': sorted(numbers)}
    win_snapshot=acquire_win_odds(race,official,rows)
    record, _, _ = prepare(model_dir, assembly['runners'], bundle['odds_snapshots'], metadata,win_snapshot)
    record['history_coverage_check'] = {'results_complete_through':coverage['history_complete_through'],
        'calendar_checked_through':checked_through,'non_race_gap_evidence':calendar_evidence}
    record['entry_sources'] = {'official':{k:official[k] for k in ['source_url','obtained_at','page_sha256']},
        'public':{'source_url':bundle['entry_source_url'],'obtained_at':bundle['entry_retrieved_at'],
                  'page_sha256':bundle['entry_page_sha256']}}
    return record


def prepare_live(race, model_dir, history_dir, pedigree_paths=(), window=None):
    from public_live_collector import collect_live
    from history_coverage import effective_coverage
    coverage = json.loads((Path(history_dir) / 'coverage_manifest.json').read_text())
    yesterday = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date() - dt.timedelta(days=1)
    coverage_check = effective_coverage(coverage['history_complete_through'], yesterday.isoformat())
    bundle = collect_live(race)
    if window: check_window(bundle['official_participation']['race_start_at'], window)
    return prepare_from_sources(bundle, model_dir, history_dir, pedigree_paths, coverage_check)
