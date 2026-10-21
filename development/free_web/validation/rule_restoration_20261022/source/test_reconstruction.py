import sys,unittest
from itertools import combinations
import numpy as np
from cap30_reconstruction import allocate
sys.path.insert(0,'decomposition_20261021')
from rankwise import probability_tables

def fixture(n,odds):
    race={'race_code':'2026101808040711','numbers':list(range(1,n+1))}
    strength=np.arange(n,0,-1,dtype=float)
    stage=np.repeat(np.log(strength)[None,:],3,axis=0)
    _,combo,scenario=probability_tables(race,stage);combo['decimal_odds']=float(odds)
    return race,combo,scenario

class ReconstructionConstraints(unittest.TestCase):
    def test_matches_brute_force_on_small_field(self):
        race,combo,scenario=fixture(4,2.)
        tickets,audit=allocate(combo,race['numbers'],scenario,expected_payout_scale=10000)
        self.assertEqual(len(tickets),2);self.assertEqual(int(tickets.stake.sum()),10000)
        best=-np.inf
        for indices in combinations(range(len(combo)),2):
            active={(combo.iloc[i].bet_type,combo.iloc[i].kumiban) for i in indices}
            e=sum(combo.iloc[i].ai_probability*2*5000 for i in indices)
            h=sum(r[0] for r in scenario if (r[1],r[2]) in active or (r[3],r[4]) in active)
            best=max(best,.5*e/10000+.5*h)
        self.assertAlmostEqual(audit['objective_value'],best,places=9)
    def test_no_fallback_when_thirty_minimum_stakes_cannot_spend_budget(self):
        race,combo,scenario=fixture(9,100.)
        with self.assertRaisesRegex(RuntimeError,'within30'):
            allocate(combo,race['numbers'],scenario,expected_payout_scale=10000)
    def test_refuses_outcome_labels(self):
        race,combo,scenario=fixture(4,2.);combo['target_win']=0
        with self.assertRaisesRegex(ValueError,'outcomes'):
            allocate(combo,race['numbers'],scenario,expected_payout_scale=10000)
    def test_requires_explicit_unrecovered_scale(self):
        race,combo,scenario=fixture(4,2.)
        with self.assertRaises(TypeError):allocate(combo,race['numbers'],scenario)
    def test_invalid_joint_mass_is_rejected(self):
        race,combo,scenario=fixture(4,2.);bad=[(r[0]*.5,*r[1:]) for r in scenario]
        with self.assertRaisesRegex(ValueError,'joint mass'):
            allocate(combo,race['numbers'],bad,expected_payout_scale=10000)

if __name__=='__main__':unittest.main()
