import copy,datetime as dt,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np,pandas as pd
from two_researchers import prepare,HALF,PARAM_HASH,VERSION,POLICIES,allocate_two,validate,dumps
from two_researcher_runner import publish_pair,settle_pair
from probability_correction import MODEL_SHA256
from strength_calibration import corrected_strength,probability_tables
from test_operation_runner import MemoryGitHub,NOW

def fixture():
    h=pd.DataFrame({'race_code':['2026102405040811']*3,'umaban':[1,2,3],
       'win_probability':[1/3]*3,'top3_probability':[1.]*3})
    h,c=probability_tables(h,corrected_strength(h,[3.,3.,3.],HALF['alpha_ai'],HALF['beta_market']))
    c['decimal_odds']=np.where(c.bet_type.eq('sanrenpuku'),100.,2.)
    allocations=allocate_two(c,h);researchers={}
    src={'source_url':'https://example.test','page_sha256':'a'*64,'source_updated_at':(NOW-dt.timedelta(seconds=20)).isoformat(),'retrieved_at':(NOW-dt.timedelta(seconds=10)).isoformat()}
    for key,(t,a) in allocations.items():
        total=int(t.stake.sum());researchers[key]={'schema_version':8,'race_code':'2026102405040811','race_name':'試験',
          'race_start_at':'2026-10-24T15:30:00+09:00','prediction_finalized_at':NOW.isoformat(),
          'researcher_name':'一郎研究員' if key=='ichiro' else 'マツイ研究員',
          'features_obtained_at':NOW.isoformat(),'active_horse_numbers':[1,2,3],'horse_probabilities':h.to_dict('records'),
          'model_file_sha256':MODEL_SHA256,'input_snapshot_sha256':'b'*64,'odds_sources':{'umaren':src,'sanrenpuku':src},
          'win_odds_source':src,'probability_method':HALF['version'],'probability_correction_parameters_sha256':PARAM_HASH,
          'correction_strength':.5,'correction_parameters':HALF,'allocation_rule':POLICIES[key],
          'allocation_core_sha256':hashlib.sha256(Path(__file__).with_name('two_researcher_allocator.py').read_bytes()).hexdigest(),
          'budget_limit_yen':10000,'tickets':t.to_dict('records'),'total_stake_yen':total,'unspent_yen':10000-total,
          'allocation_audit':a,'is_pre_race_prediction':True,'model_package':'test'}
    return {'policy_version':VERSION,'test_only':False,'race_code':'2026102405040811','race_name':'試験',
      'race_start_at':'2026-10-24T15:30:00+09:00','prediction_finalized_at':NOW.isoformat(),'researchers':researchers}

class DualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.record=fixture()
    def pair(self):return copy.deepcopy(self.record)
    def test_cost_objective_distinction_and_same_sources(self):
        p=self.pair();validate(p,now=NOW)
        self.assertGreater(p['researchers']['ichiro']['total_stake_yen'],p['researchers']['matsui']['total_stake_yen'])
    def test_prepare_invokes_legacy_inference_once_and_parameters_are_explicit(self):
        p=self.pair();base=p['researchers']['ichiro'];t=pd.DataFrame(base['tickets']);m=pd.DataFrame(p['researchers']['matsui']['tickets'])
        with patch('calibrated_pre_race.prepare',return_value=(base,'',None)) as call,patch('two_researchers.allocate_two',return_value={'ichiro':(t,base['allocation_audit']),'matsui':(m,p['researchers']['matsui']['allocation_audit'])}):
            # Execute allocation callback from the mocked prepare to populate its shared cache.
            def fake(*args,**kw):kw['allocation_function'](None,None);return base,'',None
            call.side_effect=fake;result,_,_=prepare(None,[],{},None,None,now=NOW)
            self.assertEqual(call.call_count,1);self.assertEqual(call.call_args.kwargs['correction_parameters'],HALF)
            validate(result,now=NOW)
    def test_different_sources_and_bad_probability_rejected(self):
        for what in ['input_snapshot_sha256','probability_correction_parameters_sha256']:
            p=self.pair();p['researchers']['matsui'][what]='tampered'
            with self.assertRaises(ValueError):validate(p,now=NOW)
        p=self.pair();p['researchers']['matsui']['tickets'][0]['ai_probability']=.2
        with self.assertRaises(ValueError):validate(p,now=NOW)
    def test_receipt_failure_never_releases_draft(self):
        with self.assertRaises(RuntimeError):publish_pair(self.pair(),MemoryGitHub('receipt_write'),clock=lambda:NOW)
    def test_deadline_and_stale_sources_rejected(self):
        with self.assertRaises(ValueError):publish_pair(self.pair(),MemoryGitHub(),clock=lambda:NOW+dt.timedelta(hours=1))
        p=self.pair()
        for r in p['researchers'].values():r['win_odds_source']['source_updated_at']=(NOW-dt.timedelta(minutes=5)).isoformat()
        with self.assertRaises(ValueError):validate(p,now=NOW)
    def test_publish_settle_result_drafts_and_idempotence(self):
        git=MemoryGitHub();p=self.pair();first=publish_pair(p,git,clock=lambda:NOW+dt.timedelta(seconds=10))
        second=publish_pair(p,git,clock=lambda:NOW+dt.timedelta(seconds=10));self.assertEqual(first,second)
        official={'race_code':p['race_code'],'official_verified':True,'source_url':'https://www.jra.go.jp/test',
          'payouts_per_100_yen':{'umaren':{'0102':1000},'sanrenpuku':{'010203':10000}},'refunded_horse_numbers':[]}
        a=settle_pair(p['race_code'],git,official);b=settle_pair(p['race_code'],git,official);self.assertEqual(a,b)
        self.assertIn('一郎研究員',a['x_draft']);self.assertIn('マツイ研究員',a['x_draft']);self.assertEqual(git.created,5)
        self.assertGreater(a['result']['researchers']['matsui']['profit_yen'],0)
    def test_legacy_or_missing_receipt_never_repredicted(self):
        with self.assertRaises(ValueError):settle_pair(self.pair()['race_code'],MemoryGitHub())
    def test_test_only_drafts_cannot_masquerade_as_live(self):
        out=publish_pair(self.pair(),MemoryGitHub(),test_only=True,run_id='unit_test')
        self.assertIn('テスト',out['x_draft']);self.assertTrue(out['test_only'])
if __name__=='__main__':unittest.main()
