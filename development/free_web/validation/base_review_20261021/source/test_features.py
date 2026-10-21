import unittest
import numpy as np,pandas as pd
from features import augment,RELATIVE_COLUMNS,matrix

class FeatureSafety(unittest.TestCase):
    def sample(self):
        x=pd.DataFrame({'race_code':['old','old','new','new'],'horse':[1,2,3,4]})
        for col in RELATIVE_COLUMNS:x[col]=[.1,.9,.2,np.nan] if col!='previous_finish_position' else [1,5,2,np.nan]
        x['target_win']=[1,0,0,1]
        return x
    def test_other_races_and_labels_do_not_change_features(self):
        x=self.sample();a=augment(x)
        x.loc[x.race_code=='new',RELATIVE_COLUMNS]=999;x.target_win=1-x.target_win;b=augment(x)
        pd.testing.assert_frame_equal(a[a.race_code=='old'].drop(columns='target_win'),b[b.race_code=='old'].drop(columns='target_win'))
    def test_order_invariance_and_missing(self):
        x=self.sample();a=augment(x).sort_values('horse');b=augment(x.iloc[::-1]).sort_values('horse')
        pd.testing.assert_frame_equal(a,b)
        self.assertTrue(pd.isna(a.iloc[3].previous_finish_position_field_percentile))
        self.assertGreater(a.iloc[0].previous_finish_position_field_percentile,a.iloc[1].previous_finish_position_field_percentile)
    def test_categories_are_training_only(self):
        a,maps=matrix(pd.DataFrame({'cat':['a',None],'value':[1.,2.]}),['cat','value'],['cat'])
        b,_=matrix(pd.DataFrame({'cat':['future'],'value':[3.]}),['cat','value'],['cat'],maps)
        self.assertEqual(str(b.cat.iloc[0]),'__UNSEEN__');self.assertNotIn('future',maps['cat'])

if __name__=='__main__':unittest.main()
