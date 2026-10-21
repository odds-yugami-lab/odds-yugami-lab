import copy,unittest
import numpy as np
from run import boosted_stage
from rankwise import distribution

class PopularityBoost(unittest.TestCase):
    def race(self):
        return {'win':[.3,.2,.1,.05],'top3':[.7,.6,.4,.2],'odds':[2.,4.,8.,20.],
            'popularity':[1,2,3,4],'target_win':[1,0,0,0]}
    def test_exact_strength_ratio_and_normalization(self):
        race=self.race();base=boosted_stage(race,[.2,.73],'no_extra_boost')
        for method,mask in [('favorite_only',np.array([True,False,False,False])),
                            ('top3_favorites',np.array([True,True,True,False]))]:
            stage=boosted_stage(race,[.2,.73],method)
            np.testing.assert_allclose(np.exp(stage-base),np.repeat(np.where(mask,1.2,1.)[None,:],3,axis=0))
            _,mass,w,t=distribution(stage)
            self.assertAlmostEqual(float(mass.sum()),1.);self.assertAlmostEqual(float(w.sum()),1.);self.assertAlmostEqual(float(t.sum()),3.)
    def test_outcome_labels_do_not_affect_boost(self):
        race=self.race();changed=copy.deepcopy(race);changed['target_win']=[0,0,0,1]
        for method in ['no_extra_boost','favorite_only','top3_favorites']:
            np.testing.assert_array_equal(boosted_stage(race,[.2,.73],method),boosted_stage(changed,[.2,.73],method))

if __name__=='__main__':unittest.main()
