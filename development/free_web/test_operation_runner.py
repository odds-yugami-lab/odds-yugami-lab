"""Failure-injection tests for delivery and immutable settlement."""
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
from operation_runner import publish, settle_saved, paths, dumps, BRANCH, GitHub
from pre_race_record import prepare

NOW = dt.datetime(2026, 10, 24, 5, 50, tzinfo=dt.timezone.utc)


def record():
    return {'status': 'prepared_not_published', 'race_code': '2026102405040811',
        'race_name': 'Delivery test', 'race_start_at': '2026-10-24T15:30:00+09:00',
        'prediction_finalized_at': NOW.isoformat(), 'total_stake_yen': 10000,
        'tickets': [{'bet_type': 'umaren', 'kumiban': '0102', 'stake': 10000, 'decimal_odds': 2.0}]}


class MemoryGitHub:
    def __init__(self, failure=None):
        self.files = {}; self.commits = {}; self.created = 0; self.failure = failure
        self.events = []

    def save(self, path, content, message):
        self.events.append(path)
        if 'receipt' in path and self.failure == 'receipt_write':
            raise RuntimeError('Injected receipt write failure')
        if path in self.files:
            sha, old = self.files[path]
            if old != content: raise ValueError('Existing append-only record differs')
        else:
            self.created += 1
            sha = f'{self.created:040x}'
            self.files[path] = sha, content
            self.commits[sha] = (NOW + dt.timedelta(seconds=self.created)).isoformat()
        return sha, self.verify(path, content, sha)

    def optional(self, path):
        return self.files[path][1] if path in self.files else None

    def content(self, path, sha):
        actual, content = self.files[path]
        if actual != sha: raise ValueError('Wrong immutable commit')
        return content

    def verify(self, path, content, sha):
        if 'receipt' in path and self.failure == 'branch_readback':
            raise ValueError('Receipt branch differs from commit')
        assert self.content(path, sha) == content
        return content, content, self.commits[sha]

    def commit_time(self, sha):
        return self.commits[sha]


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.clock = lambda: NOW + dt.timedelta(seconds=10)

    def test_success_requires_both_saves(self):
        git = MemoryGitHub()
        out = publish(record(), git, clock=self.clock)
        self.assertEqual(git.created, 2)
        self.assertEqual(out['status'], 'published')
        self.assertIn(out['prediction_commit_sha'], out['x_draft'])
        self.assertIn('receipts', git.events[-1])

    def test_receipt_write_failure_releases_nothing(self):
        with self.assertRaisesRegex(RuntimeError, 'receipt write'):
            publish(record(), MemoryGitHub('receipt_write'), clock=self.clock)

    def test_receipt_branch_failure_releases_nothing(self):
        with self.assertRaisesRegex(ValueError, 'branch differs'):
            publish(record(), MemoryGitHub('branch_readback'), clock=self.clock)

    def test_retry_reuses_original_two_commits(self):
        git = MemoryGitHub()
        first = publish(record(), git, clock=self.clock)
        second = publish(record(), git, clock=self.clock)
        self.assertEqual(first, second)
        self.assertEqual(git.created, 2)

    def test_different_forecast_never_overwrites(self):
        git = MemoryGitHub(); publish(record(), git, clock=self.clock)
        changed = record(); changed['tickets'][0]['decimal_odds'] = 3.0
        with self.assertRaisesRegex(ValueError, 'append-only'):
            publish(changed, git, clock=self.clock)
        self.assertEqual(git.created, 2)

    def test_expired_forecast_does_not_write(self):
        git = MemoryGitHub()
        with self.assertRaisesRegex(ValueError, 'deadline'):
            publish(record(), git, clock=lambda: NOW + dt.timedelta(minutes=30))
        self.assertEqual(git.created, 0)

    def test_deadline_expiring_during_writes_blocks_draft(self):
        times = iter([self.clock(), self.clock(), NOW + dt.timedelta(minutes=30)])
        with self.assertRaisesRegex(ValueError, 'deadline'):
            publish(record(), MemoryGitHub(), clock=lambda: next(times))

    def test_test_only_has_no_x_and_no_production_path(self):
        git = MemoryGitHub()
        out = publish(record(), git, test_only=True, run_id='unit', clock=self.clock)
        self.assertIsNone(out['x_draft'])
        self.assertTrue(all(p.startswith('development/free_web/publication_tests/') for p in git.files))

    def test_settlement_uses_original_amounts(self):
        git = MemoryGitHub(); publish(record(), git, clock=self.clock)
        payouts = {'race_code': record()['race_code'], 'official_verified': True,
            'source_url': 'https://www.jra.go.jp/test',
            'payouts_per_100_yen': {'umaren': {'0102': 210}, 'sanrenpuku': {'010203': 300}},
            'refunded_horse_numbers': []}
        result = settle_saved(record()['race_code'], git, payouts)
        self.assertEqual(result['result']['payout_yen'], 21000)
        self.assertEqual(result['result']['profit_yen'], 11000)

    def test_wrong_receipt_hash_blocks_settlement(self):
        git = MemoryGitHub(); publish(record(), git, clock=self.clock)
        path = paths(record()['race_code'])[1]
        sha, content = git.files[path]; receipt = json.loads(content)
        receipt['content_sha256'] = '0' * 64
        git.files[path] = sha, dumps(receipt)
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            settle_saved(record()['race_code'], git, {})

    def test_missing_receipt_does_not_create_backdated_record(self):
        git = MemoryGitHub()
        with self.assertRaisesRegex(ValueError, 'receipt missing'):
            settle_saved(record()['race_code'], git)
        self.assertEqual(git.created, 0)

    def test_non_ancestor_commit_rejected(self):
        class WrongBranch(GitHub):
            def content(self, path, ref): return 'body'
            def snapshot(self): return '2' * 40, {'path': {}}
            def get(self, suffix): return {'status': 'diverged'}
        with self.assertRaisesRegex(ValueError, 'not reachable'):
            WrongBranch(None).verify('path', 'body', '1' * 40)


class FinalizationTests(unittest.TestCase):
    def test_clock_is_rechecked_after_calculation(self):
        from itertools import combinations
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'manifest.json').write_text('{"package":"unit"}')
            (root / 'feature_spec.json').write_text('{}')
            race = record()['race_code']
            required = ['keibajo_code','track_code','distance_m','grade_code','field_size',
                'wakuban','sex_code','age','carried_weight_kg','sire_code',
                'body_weight_kg','body_weight_change_kg','jockey_code','trainer_code']
            runners = [dict({k:1 for k in required},race_code=race,stage='entries',
                       umaban=str(i),ketto_toroku_bango=str(i)) for i in (1,2,3)]
            snapshots = {}
            for kind, size in [('umaren',2),('sanrenpuku',3)]:
                rows = [{'race_code':race,'bet_type':kind,
                    'kumiban':''.join(f'{n:02d}' for n in ns),'decimal_odds':2.0}
                    for ns in combinations((1,2,3),size)]
                snapshots[kind] = {'status':'verified_live','retrieved_at':NOW.isoformat(),
                    'source_updated_at':NOW.isoformat(),'source_url':'https://example.test',
                    'page_sha256':'a'*64,'rows':rows}
            metadata = dict(record(),features_obtained_at=NOW.isoformat(),active_horse_numbers=[1,2,3])
            tickets = pd.DataFrame(record()['tickets'])
            with patch('pre_race_record.predict',return_value={'win':[.3,.3,.4],'top3':[1.,1.,1.]}), \
                 patch('pre_race_record.allocate_balanced',return_value=(tickets,{})):
                with self.assertRaisesRegex(ValueError, 'stale during calculation'):
                    prepare(directory,runners,snapshots,metadata,now=NOW,
                            clock=lambda:NOW+dt.timedelta(seconds=91))
                with self.assertRaisesRegex(ValueError, 'outside publication deadline'):
                    prepare(directory,runners,snapshots,metadata,now=NOW,
                            clock=lambda:NOW+dt.timedelta(minutes=30))


class CalendarAndRoutingTests(unittest.TestCase):
    def test_non_race_gap_is_allowed_but_missing_race_day_is_rejected(self):
        from history_coverage import check
        pages={'202610':[{'month':'10','data':[
            {'date':'18','info':[{'race':[{'name':'東京'}]}]},
            {'date':'24','info':[{'race':[{'name':'東京'}]}]}]}]}
        self.assertEqual(check('2026-10-18','2026-10-23',pages),'2026-10-23')
        with self.assertRaisesRegex(ValueError,'missing completed JRA race days'):
            check('2026-10-18','2026-10-24',pages)

    def test_empty_calendar_is_not_non_race_proof(self):
        from history_coverage import check
        with self.assertRaisesRegex(ValueError,'Empty official calendar'):
            check('2026-10-18','2026-10-23',{'202610':[{'month':'10','data':[]}]})

    def test_official_start_controls_task_routing(self):
        from live_pipeline import check_window
        check_window('2026-10-18T15:40:00+09:00','15:36-15:42')
        with self.assertRaisesRegex(ValueError,'outside this task'):
            check_window('2026-10-18T15:40:00+09:00','15:43-23:59')

    def test_historical_record_cannot_be_published_as_live(self):
        from publication import request
        data=record();data['odds_status']='final_postrace'
        with self.assertRaisesRegex(ValueError,'Historical/test'):
            request(data,BRANCH,now=NOW)


if __name__ == '__main__':
    unittest.main(verbosity=2)
