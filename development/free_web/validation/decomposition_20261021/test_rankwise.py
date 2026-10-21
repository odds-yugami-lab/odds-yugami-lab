import copy,unittest
import numpy as np,pandas as pd
from rankwise import distribution,observed_losses,probability_tables,scores
from train_cv import calibrate
from allocation_scenarios import allocate_balanced

RACE={'race_code':'2026010101010111','numbers':[1,2,3,4],'win':[.1,.2,.3,.4],
    'top3':[.4,.7,.9,1.],'odds':[8,4,3,2],'order':[3,2,1]}

class RankTests(unittest.TestCase):
    def test_uniform_known_probabilities(self):
        order,mass,win,top=distribution(np.zeros((3,4)))
        np.testing.assert_allclose(mass,1/24);np.testing.assert_allclose(win,.25);np.testing.assert_allclose(top,.75)
        h,c,s=probability_tables(RACE,np.zeros((3,4)))
        np.testing.assert_allclose(c[c.bet_type=='umaren'].ai_probability,1/6)
        np.testing.assert_allclose(c[c.bet_type=='sanrenpuku'].ai_probability,1/4)

    def test_rank_dependent_order_probability_matches_loss(self):
        score=np.log([[1,2,3,4],[4,3,2,1],[2,1,4,3]])
        order,mass,win,top=distribution(score);chosen=[3,0,2]
        p=mass[np.all(order==chosen,axis=1)][0]
        self.assertAlmostEqual(-np.log(p),sum(observed_losses(score,chosen)))
        np.testing.assert_allclose(win,[.1,.2,.3,.4]);self.assertAlmostEqual(sum(top),3)

    def test_result_labels_cannot_change_probability(self):
        a=copy.deepcopy(RACE);b=copy.deepcopy(RACE);b['order']=[0,1,2];b['target_win']=[1,0,0,0]
        np.testing.assert_allclose(scores(a,'stage_two_heads',[.2,.3,.9,.8,.6]),scores(b,'stage_two_heads',[.2,.3,.9,.8,.6]))

    def test_future_labels_cannot_change_past_fold_calibrator(self):
        rows=40;frame=pd.DataFrame({'raw_win':np.linspace(.01,.7,rows),'raw_top3':np.linspace(.1,.9,rows),
            'target_win':[0,1]*20,'target_top3':[1,0]*20})
        train=np.arange(rows)<20
        _,before=calibrate(frame,train)
        frame.loc[~train,['target_win','target_top3']]=1-frame.loc[~train,['target_win','target_top3']]
        _,after=calibrate(frame,train)
        for key in before:
            np.testing.assert_array_equal(before[key].coef_,after[key].coef_)
            np.testing.assert_array_equal(before[key].intercept_,after[key].intercept_)

    def test_explicit_scenarios_match_known_full_coverage_allocation(self):
        h,c,scenario=probability_tables(RACE,np.zeros((3,4)));c['decimal_odds']=10.
        tickets,audit=allocate_balanced(c,h,outcome_scenarios=scenario)
        self.assertEqual(len(tickets),10);self.assertEqual(int(tickets.stake.sum()),10000)
        self.assertAlmostEqual(audit['probability_any_win'],1.)
        self.assertTrue((tickets.stake==1000).all())
        malformed=list(scenario);first=list(malformed[0]);first[0]*=2;malformed[0]=tuple(first)
        with self.assertRaisesRegex(ValueError,'does not sum'):
            allocate_balanced(c,h,outcome_scenarios=malformed)

if __name__=='__main__':unittest.main(verbosity=2)
