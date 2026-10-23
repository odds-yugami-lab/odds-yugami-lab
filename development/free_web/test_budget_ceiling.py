import datetime as dt,unittest
from cap30_budget_ceiling import VERSION,validate_record_budget
from publication import request
from settlement import settle

class CeilingPublication(unittest.TestCase):
    def record(self):
        return {'race_code':'2026101808040711','race_name':'過去動作確認','race_start_at':'2026-10-18T15:40:00+09:00',
            'status':'prepared_not_published','schema_version':7,'allocation_rule':VERSION,
            'total_stake_yen':100,'budget_limit_yen':10000,'unspent_yen':9900,
            'probability_method':'original_saved52','probability_correction_parameters_sha256':None,
            'tickets':[{'bet_type':'umaren','kumiban':'0102','stake':100,'decimal_odds':100.}]}
    def test_publish_and_settle_actual_spend(self):
        record=self.record();write=request(record,'test',test_only=True)
        self.assertIn('9900',write['content'])
        result=settle(record,{'race_code':record['race_code'],'official_verified':True,'source_url':'https://www.jra.go.jp/test',
            'payouts_per_100_yen':{'umaren':{'0102':10000},'sanrenpuku':{}}},test_only=True)
        self.assertEqual(result['investment_yen'],100);self.assertEqual(result['unspent_yen'],9900)
        self.assertEqual(result['recovery_percent'],10000.)
    def test_extra_stake_and_wrong_cash_are_rejected(self):
        record=self.record();record['unspent_yen']=0
        with self.assertRaises(ValueError):validate_record_budget(record)
        record=self.record();record.update(total_stake_yen=200,unspent_yen=9800);record['tickets'][0]['stake']=200
        with self.assertRaises(ValueError):validate_record_budget(record)
    def test_legacy_budget_stays_exact(self):
        record=self.record();record['allocation_rule']='cap30_minimum_E50'
        with self.assertRaises(ValueError):validate_record_budget(record)

if __name__=='__main__':unittest.main()
