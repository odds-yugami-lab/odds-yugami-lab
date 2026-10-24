"""Cloud-runner orchestration. All writes are append-only and read back.

Use connector_bridge.js for GitHub access; no local PC or embedded token.
No X sending or ticket purchasing. Private inputs never cross the RPC boundary.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.parse
from publication import request, confirm, x_draft_after_receipt, REPOSITORY
from pre_race_record import timestamp

BRANCH = 'dev/free-windows-probe-20261011'
API = 'https://api.github.com/repos/' + REPOSITORY


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n'


class GitHub:
    def __init__(self, call):
        self.call = call
        self.stage = None

    def get(self, suffix):
        result = self.call('fetch', {'url': API + suffix})
        content = result.get('content')
        return json.loads(content) if isinstance(content, str) else result

    def snapshot(self):
        branches = self.get('/branches?per_page=100')
        selected = [b for b in branches if b['name'] == BRANCH]
        if len(selected) != 1:
            raise ValueError('Pinned publication branch missing or ambiguous')
        head = selected[0]['commit']['sha']
        tree = self.get('/git/trees/' + head + '?recursive=1')
        if tree.get('truncated') is not False:
            raise ValueError('Incomplete GitHub tree; absence not established')
        return head, {r['path']: r for r in tree['tree'] if r['type'] == 'blob'}

    def content(self, path, ref):
        result = self.call('fetch_file', {'repository_full_name': REPOSITORY,
                                        'path': path, 'ref': ref})
        content = result.get('content')
        if not isinstance(content, str) or not content:
            raise ValueError('Empty GitHub readback: ' + path)
        expected = hashlib.sha1(('blob ' + str(len(content.encode())) + '\0').encode() + content.encode()).hexdigest()
        if result.get('sha') != expected:
            raise ValueError('Git blob/content mismatch: ' + path)
        return content

    def optional(self, path):
        head, tree = self.snapshot()
        if path not in tree:
            return None
        return self.content(path, head)

    def commit_time(self, sha):
        result = self.call('fetch_commit', {'repo_full_name': REPOSITORY, 'commit_sha': sha})
        return result['commit']['created_at']

    def verify(self, path, content, sha):
        if not re.fullmatch('[0-9a-f]{40}', sha):
            raise ValueError('Missing immutable commit SHA')
        by_commit = self.content(path, sha)
        head, tree = self.snapshot()
        if path not in tree:
            raise ValueError('Saved file absent from publication branch')
        by_branch = self.content(path, head)
        if not by_commit == by_branch == content:
            raise ValueError('Commit/branch/content readbacks differ')
        comparison = self.get('/compare/' + sha + '...' + head)
        if comparison.get('status') not in ('ahead', 'identical'):
            raise ValueError('Commit not reachable from publication branch')
        return by_commit, by_branch, self.commit_time(sha)

    def save(self, path, content, message):
        """Reuse identical existing bytes, but never overwrite a different file."""
        self.stage = 'existence_check:' + path
        current = self.optional(path)
        if current is not None:
            if current != content:
                raise ValueError('Existing append-only record differs: ' + path)
            query = urllib.parse.urlencode({'sha': BRANCH, 'path': path, 'per_page': 1})
            commits = self.get('/commits?' + query)
            if not commits:
                raise ValueError('Existing file commit could not be established')
            sha = commits[0]['sha']
        else:
            self.stage = 'create_file:' + path
            result = self.call('create_file', {'repository_full_name': REPOSITORY,
                'branch': BRANCH, 'path': path, 'content': content, 'message': message})
            sha = result['commit_sha']
        self.stage = 'readback_ancestry_server_time:' + path
        return sha, self.verify(path, content, sha)


def paths(race, test_only=False, run_id=None):
    if not re.fullmatch(r'\d{16}', race):
        raise ValueError('Invalid race code')
    if test_only:
        if not run_id or not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
            raise ValueError('Unique test run ID required')
        root = 'development/free_web/publication_tests/' + run_id
        return root + '/' + race + '.json', root + '/' + race + '_receipt.json'
    return 'predictions/free52/' + race + '.json', 'predictions/free52_receipts/' + race + '.json'


def publish(record, github, test_only=False, run_id=None, clock=None):
    clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
    write = request(record, BRANCH, now=clock(), test_only=test_only)
    prediction_path, receipt_path = paths(record['race_code'], test_only, run_id)
    write['path'] = prediction_path
    sha, (_, _, committed_at) = github.save(prediction_path, write['content'], write['message'])
    receipt, chat, _ = confirm(write, sha, write['content'], committed_at, now=clock())
    receipt_content = dumps(receipt)
    receipt_sha, (by_commit, by_branch, receipt_time) = github.save(
        receipt_path, receipt_content, 'Confirm publication ' + record['race_code'])
    # BOTH writes, all byte readbacks, ancestry and server timestamps precede delivery.
    draft = None
    if not test_only:
        draft = x_draft_after_receipt(record, receipt, receipt_sha, by_commit, by_branch,
                                      receipt_time, now=clock())
    elif json.loads(by_commit) != receipt or by_commit != by_branch:
        raise ValueError('Test receipt readback mismatch')
    return {'status': 'test_complete' if test_only else 'published',
            'race_code': record['race_code'], 'test_only': test_only,
            'prediction_commit_sha': sha, 'receipt_commit_sha': receipt_sha,
            'record_url': receipt['record_url'], 'receipt': receipt,
            'chat_listing': chat, 'x_draft': draft}


def settle_saved(race, github, payout_snapshot=None, test_only=False, run_id=None):
    from settlement import settle
    prediction_path, receipt_path = paths(race, test_only, run_id)
    receipt_bytes = github.optional(receipt_path)
    if receipt_bytes is None:
        raise ValueError('Publication receipt missing; do not recreate a pre-race record after the race')
    receipt = json.loads(receipt_bytes)
    if receipt.get('race_code') != race or receipt.get('test_only') is not test_only:
        raise ValueError('Receipt identity mismatch')
    record_bytes = github.content(prediction_path, receipt['commit_sha'])
    github.verify(prediction_path, record_bytes, receipt['commit_sha'])
    if hashlib.sha256(record_bytes.encode()).hexdigest() != receipt['content_sha256']:
        raise ValueError('Publication content hash mismatch')
    if timestamp(github.commit_time(receipt['commit_sha'])) != timestamp(receipt['recorded_at']):
        raise ValueError('Publication receipt/server time mismatch')
    # Authenticate the receipt itself against its branch history, even on retries.
    receipt_sha, (_, _, receipt_saved_at) = github.save(receipt_path, receipt_bytes, 'Confirm publication ' + race)
    record = json.loads(record_bytes)
    if not test_only:
        deadline = timestamp(record['race_start_at']) - dt.timedelta(minutes=12)
        if not timestamp(record['prediction_finalized_at']) <= timestamp(receipt['recorded_at']) <= timestamp(receipt_saved_at) <= deadline:
            raise ValueError('Pre-race publication evidence is late or invalid')
    if payout_snapshot is None:
        from official_results import fetch_for_race
        payout_snapshot = fetch_for_race(race)
    result = settle(record, payout_snapshot, publication=receipt, test_only=test_only)
    path = ('development/free_web/publication_tests/' + run_id + '/' + race + '_settlement.json'
            if test_only else 'results/free52/' + race + '.json')
    sha, _ = github.save(path, dumps(result), 'Settle published prediction ' + race)
    return {'status': 'settled', 'test_only': test_only, 'result': result,
            'commit_sha': sha, 'receipt_commit_sha': receipt_sha,
            'record_url': 'https://github.com/' + REPOSITORY + '/blob/' + sha + '/' + path}


class ConnectorRPC:
    """One-line JSON over a noncanonical, non-echoing terminal; no tokens."""
    def __init__(self):
        if sys.stdin.isatty():
            import termios
            attr = termios.tcgetattr(0)
            attr[3] &= ~(termios.ECHO | termios.ICANON)
            attr[6][termios.VMIN] = 1
            attr[6][termios.VTIME] = 0
            termios.tcsetattr(0, termios.TCSANOW, attr)
        self.sequence = 0

    def __call__(self, method, args):
        if method not in {'fetch', 'fetch_file', 'fetch_commit', 'create_file'}:
            raise ValueError('RPC method not allowed')
        self.sequence += 1
        print('JRA_RPC ' + json.dumps({'id': self.sequence, 'method': method, 'args': args}), flush=True)
        response = json.loads(sys.stdin.readline())
        if response.get('id') != self.sequence or response.get('error'):
            raise RuntimeError('GitHub ' + method + ' failed: ' + str(response.get('error', 'RPC ID mismatch')))
        return response['result']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['publish', 'settle', 'live'])
    parser.add_argument('--record')
    parser.add_argument('--race')
    parser.add_argument('--payout')
    parser.add_argument('--test-only', action='store_true')
    parser.add_argument('--run-id')
    parser.add_argument('--probability-method', choices=['original','market_corrected_v1'], default='original')
    parser.add_argument('--model-dir')
    parser.add_argument('--history-dir')
    parser.add_argument('--pedigree', action='append', default=[])
    parser.add_argument('--window', help='Official JST start range, e.g. 15:36-15:42')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    github = GitHub(ConnectorRPC())
    stage = args.action
    try:
        if args.action == 'settle':
            payouts = json.loads(Path(args.payout).read_text()) if args.payout else None
            outcome = settle_saved(args.race, github, payouts, args.test_only, args.run_id)
        else:
            if args.action == 'live':
                if args.test_only:
                    raise ValueError('Live acquisition cannot use test-only flag')
                path, _ = paths(args.race)
                existing = github.optional(path)
                if existing is not None:
                    record = json.loads(existing)
                    for key in ('record_type', 'is_pre_race_prediction'):
                        record.pop(key, None)
                else:
                    if args.probability_method=='market_corrected_v1':
                        from calibrated_live_pipeline import prepare_live
                    else:
                        from live_pipeline import prepare_live
                    stage = 'live_sources_features_inference_allocation'
                    github.stage = None
                    record = prepare_live(args.race, args.model_dir, args.history_dir, args.pedigree, args.window)
            else:
                record = json.loads(Path(args.record).read_text())
            if args.action == 'live' and args.window:
                from live_pipeline import check_window
                check_window(record['race_start_at'], args.window)
            stage = 'github_prediction_receipt_readback_and_delivery'
            outcome = publish(record, github, args.test_only, args.run_id)
        Path(args.output).write_text(dumps(outcome), encoding='utf-8')
        print('JRA_DONE ' + json.dumps({'status': outcome['status'], 'output': args.output}), flush=True)
    except Exception as exc:
        # Public diagnostics contain stage/type only; never dump private input values.
        failure = {'status': 'failed', 'stage': github.stage or stage, 'error_type': type(exc).__name__,
                   'error': str(exc)[:500], 'race_code': args.race,
                   'diagnostic_hint': 'Inspect host/path/status/phase in error; access block is not a missed deadline',
                   'failed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                   'x_draft': None, 'completed': False}
        # Persist a small append-only incident whenever GitHub remains reachable.
        # No prediction or receipt is fabricated and no private row is published.
        incident_path = ('development/free_web/incidents/operation_runs/' +
            failure['failed_at'][:10].replace('-', '') + '/' +
            (args.race or 'unknown') + '_' +
            dt.datetime.now(dt.timezone.utc).strftime('%H%M%S%f') + '.json')
        try:
            incident_sha, _ = github.save(incident_path, dumps(failure), 'Record interrupted operation')
            failure['incident_url'] = 'https://github.com/' + REPOSITORY + '/blob/' + incident_sha + '/' + incident_path
        except Exception:
            failure['incident_saved'] = False
        Path(args.output).write_text(dumps(failure), encoding='utf-8')
        print('JRA_FAILED ' + json.dumps(failure), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
