import sys,unittest
import numpy as np
from allocator import allocate
sys.path.insert(0,'decomposition_20261021')
from rankwise import probability_tables

class BudgetCeiling(unittest.TestCase):
    def test_all_high_odds_can_leave_cash(self):
        race={'race_code':'2026101808040711','numbers':list(range(1,10))}
        _,combo,scenarios=probability_tables(race,np.zeros((3,9)));combo['decimal_odds']=100.
        tickets,audit=allocate(combo,race['numbers'],scenarios,expected_payout_scale=10000)
        self.assertEqual(len(tickets),30);self.assertTrue(tickets.stake.eq(100).all())
        self.assertEqual(tickets.stake.sum(),3000);self.assertEqual(audit['unspent_yen'],7000)
    def test_spend_is_capped_without_topups(self):
        race={'race_code':'2026101808040711','numbers':[1,2,3,4]}
        _,combo,scenarios=probability_tables(race,np.zeros((3,4)));combo['decimal_odds']=2.
        tickets,audit=allocate(combo,race['numbers'],scenarios,expected_payout_scale=10000)
        self.assertLessEqual(tickets.stake.sum(),10000);self.assertTrue(tickets.stake.eq(5000).all())
        self.assertEqual(audit['unspent_yen'],10000-tickets.stake.sum())

if __name__=='__main__':unittest.main()
