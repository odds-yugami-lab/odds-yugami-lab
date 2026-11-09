"""Run before prediction slots. Never updates history from inside live inference."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from resilience import atomic_json

JST = dt.timezone(dt.timedelta(hours=9))


def check(history_dir, required_through=None, calendar_check=None):
    from history_coverage import effective_coverage
    root = Path(history_dir)
    manifest = json.loads((root / 'coverage_manifest.json').read_text(encoding='utf-8'))
    digest = hashlib.sha256((root / 'history.parquet').read_bytes()).hexdigest()
    if digest != manifest['history_sha256']:
        raise ValueError('History bytes differ from coverage manifest')
    needed = required_through or (dt.datetime.now(JST).date() - dt.timedelta(days=1)).isoformat()
    through, evidence = (calendar_check or effective_coverage)(manifest['history_complete_through'], needed)
    if through < needed:
        raise ValueError('History preflight is incomplete')
    certificate = {'schema_version': 1, 'history_sha256': digest,
        'manifest_sha256': hashlib.sha256((root / 'coverage_manifest.json').read_bytes()).hexdigest(),
        'required_through': needed, 'checked_through': through,
        'calendar_evidence': evidence, 'prepared_at': dt.datetime.now(dt.timezone.utc).isoformat()}
    atomic_json(root / 'preflight.json', certificate)
    return certificate


def ready(history_dir, required_through=None):
    root = Path(history_dir)
    certificate = json.loads((root / 'preflight.json').read_text(encoding='utf-8'))
    needed = required_through or (dt.datetime.now(JST).date() - dt.timedelta(days=1)).isoformat()
    if certificate['schema_version'] != 1 or certificate['required_through'] != needed:
        raise ValueError('Run independent history preflight before the prediction slot')
    if certificate['checked_through'] < needed:
        raise ValueError('History preflight incomplete')
    if hashlib.sha256((root / 'history.parquet').read_bytes()).hexdigest() != certificate['history_sha256']:
        raise ValueError('History changed after preflight')
    if hashlib.sha256((root / 'coverage_manifest.json').read_bytes()).hexdigest() != certificate['manifest_sha256']:
        raise ValueError('History manifest changed after preflight')
    return certificate['checked_through'], certificate['calendar_evidence']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--history-dir', required=True)
    args = parser.parse_args()
    check(args.history_dir)
    print('HISTORY_READY')
