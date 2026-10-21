import tempfile,unittest
from pathlib import Path
from run import prediction_input,verify_prediction,sha

class Isolation(unittest.TestCase):
    def test_only_whitelisted_prerace_inputs_survive(self):
        row={k:None for k in ['race_code','date','numbers','win','top3','odds','input_source']}
        row.update(target_win=[1],order=[0],payouts_per_100_yen={'umaren':{'0102':10000}})
        clean=prediction_input(row)
        self.assertEqual(set(clean),{'race_code','date','numbers','win','top3','odds','input_source'})
    def test_sealed_prediction_modification_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'p.json';p.write_text('{"stake":100}')
            original=sha(p);self.assertEqual(verify_prediction(p,original),{'stake':100})
            p.write_text('{"stake":200}')
            with self.assertRaisesRegex(ValueError,'changed after seal'):verify_prediction(p,original)

if __name__=='__main__':unittest.main()
