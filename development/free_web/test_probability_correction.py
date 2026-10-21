"""Probability coherence, source identity and failure gates for the candidate."""
import copy, datetime as dt, unittest, tempfile,json
from pathlib import Path
from unittest.mock import patch
import numpy as np,pandas as pd
from strength_calibration import corrected_strength,probability_tables
from balanced_A_v3_explicit import _ordered_outcomes
from win_odds import parse,verify_snapshot,acquire

NOW=dt.datetime(2026,10,24,5,50,tzinfo=dt.timezone.utc)
RACE='2026102405040811'

def runners():
    return [{'umaban':i,'ketto_toroku_bango':str(i)} for i in (1,2,3)]

def snapshot():
    return {'race_code':RACE,'status':'verified_live','retrieved_at':NOW.isoformat(),'source_updated_at':NOW.isoformat(),
        'source_url':'https://sports.yahoo.co.jp/keiba/race/odds/tfw/2605040811?ninki=0','page_sha256':'a'*64,
        'rows':[dict(race_code=RACE,umaban=i,horse_id=str(i),decimal_odds=4.) for i in (1,2,3)]}

def metadata():return {'race_code':RACE,'race_start_at':'2026-10-24T15:30:00+09:00'}

class CoherenceTests(unittest.TestCase):
    def test_four_equal_horses_known_marginals(self):
        h=pd.DataFrame({'race_code':[RACE]*4,'umaban':[4,2,3,1],'win_probability':[.25]*4,'top3_probability':[.75]*4})
        h,c=probability_tables(h,np.ones(4)/4)
        np.testing.assert_allclose(h.win_probability,.25);np.testing.assert_allclose(h.top3_probability,.75)
        np.testing.assert_allclose(c[c.bet_type=='umaren'].ai_probability,1/6)
        np.testing.assert_allclose(c[c.bet_type=='sanrenpuku'].ai_probability,1/4)
        for row in c.itertuples():
            slot=2 if row.bet_type=='umaren' else 4
            mass=sum(s[0] for s in _ordered_outcomes(h) if s[slot]==row.kumiban)
            self.assertAlmostEqual(mass,row.ai_probability)

    def test_market_limit_and_duplicate_identity(self):
        h=pd.DataFrame({'race_code':[RACE]*4,'umaban':[1,2,3,4],'win_probability':[.25]*4,'top3_probability':[.75]*4})
        np.testing.assert_allclose(corrected_strength(h,[2,4,8,8],0,1),[.5,.25,.125,.125])
        h.loc[0,'umaban']=2
        with self.assertRaisesRegex(ValueError,'identities'):probability_tables(h,np.ones(4))

    def test_settlement_preserves_new_probability_cohort_without_changing_legacy_shape(self):
        from settlement import settle
        record={'race_code':RACE,'tickets':[{'bet_type':'umaren','kumiban':'0102','stake':10000}]}
        payout={'race_code':RACE,'official_verified':True,'source_url':'https://www.jra.go.jp/test',
            'payouts_per_100_yen':{'umaren':{'0102':210},'sanrenpuku':{'010203':500}}}
        old=settle(record,payout,test_only=True)
        self.assertNotIn('probability_method',old)
        record.update(schema_version=6,probability_method='candidate',probability_correction_parameters_sha256='a'*64)
        new=settle(record,payout,test_only=True)
        self.assertEqual(new['probability_method'],'candidate')
        self.assertEqual(new['probability_correction_parameters_sha256'],'a'*64)
        self.assertEqual(new['payout_yen'],old['payout_yen'])

class SourceTests(unittest.TestCase):
    def test_valid_snapshot(self):self.assertTrue(verify_snapshot(snapshot(),metadata(),runners(),NOW))
    def test_stale_WIN_blocks_even_if_other_odds_fresh(self):
        s=snapshot();s['source_updated_at']=(NOW-dt.timedelta(seconds=91)).isoformat()
        with self.assertRaisesRegex(ValueError,'Stale'):verify_snapshot(s,metadata(),runners(),NOW)
    def test_future_WIN_timestamp(self):
        s=snapshot();s['retrieved_at']=(NOW+dt.timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(ValueError,'future'):verify_snapshot(s,metadata(),runners(),NOW)
    def test_wrong_horse_ID_or_missing_horse_blocks(self):
        for mutation in ['identity','missing']:
            s=snapshot()
            if mutation=='identity':s['rows'][0]['horse_id']='other'
            else:s['rows'].pop()
            with self.assertRaisesRegex(ValueError,'identities'):verify_snapshot(s,metadata(),runners(),NOW)
    def test_final_odds_cannot_be_used_live(self):
        s=snapshot();s['status']='final_postrace'
        with self.assertRaisesRegex(ValueError,'live source'):verify_snapshot(s,metadata(),runners(),NOW)
    def test_deadline_and_wrong_date_block(self):
        for stamp in [NOW+dt.timedelta(minutes=40),NOW-dt.timedelta(days=1)]:
            with self.assertRaisesRegex(ValueError,'current before'):verify_snapshot(snapshot(),metadata(),runners(),stamp)
    def test_historical_official_entries_never_promoted(self):
        with self.assertRaisesRegex(ValueError,'Current verified'):
            acquire(RACE,{'verified':True,'historical_test':True},runners())

    def test_WIN_is_rechecked_after_calculation_separately(self):
        from itertools import combinations
        from calibrated_pre_race import prepare
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'manifest.json').write_text('{"package":"unit"}');(root/'feature_spec.json').write_text('{}')
            required=['keibajo_code','track_code','distance_m','grade_code','field_size','wakuban','sex_code','age',
                'carried_weight_kg','sire_code','body_weight_kg','body_weight_change_kg','jockey_code','trainer_code']
            entries=[dict({k:1 for k in required},race_code=RACE,stage='entries',umaban=i,ketto_toroku_bango=str(i)) for i in (1,2,3)]
            pair_triple={kind:{'status':'verified_live','retrieved_at':NOW.isoformat(),'source_updated_at':NOW.isoformat(),
                'source_url':'https://example.test','page_sha256':'a'*64,
                'rows':[{'race_code':RACE,'bet_type':kind,'kumiban':''.join(f'{n:02d}' for n in ns),'decimal_odds':2.}
                    for ns in combinations((1,2,3),size)]} for kind,size in [('umaren',2),('sanrenpuku',3)]}
            meta=dict(metadata(),race_name='Unit',features_obtained_at=NOW.isoformat(),active_horse_numbers=[1,2,3])
            win=snapshot();win['source_updated_at']=(NOW-dt.timedelta(seconds=15)).isoformat()
            tickets=pd.DataFrame([{'bet_type':'umaren','kumiban':'0102','stake':10000,'decimal_odds':2.}])
            with patch('calibrated_pre_race.predict',side_effect=AssertionError('Incompatible model reached inference')):
                with self.assertRaisesRegex(ValueError,'incompatible'):
                    prepare(root,entries,pair_triple,meta,win,now=NOW)
            with patch('calibrated_pre_race.MODEL_SHA256',{}), \
                 patch('calibrated_pre_race.predict',return_value={'win':[.3,.3,.4],'top3':[1.,1.,1.]}), \
                 patch('calibrated_pre_race.allocate_balanced',return_value=(tickets,{})):
                with self.assertRaisesRegex(ValueError,'Stale/future WIN'):
                    prepare(root,entries,pair_triple,meta,win,now=NOW,clock=lambda:NOW+dt.timedelta(seconds=80))

if __name__=='__main__':unittest.main(verbosity=2)
