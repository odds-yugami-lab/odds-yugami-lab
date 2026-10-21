"""Re-infer every 2025 row with the reconstructed <=2024 base models.

This permits calibration inside each chronological fold, avoiding the use of
an all-2025 Platt fit when validating within 2025. No production model changes.
"""
import argparse,datetime as dt,hashlib,json
from pathlib import Path
import duckdb,joblib,numpy as np,pandas as pd

def main(workdir,source,model_dir,checkpoint_dir):
    root=Path(workdir);model_dir=Path(model_dir);check=Path(checkpoint_dir)
    spec=json.loads((model_dir/'feature_spec.json').read_text());con=duckdb.connect()
    df=con.execute("""SELECT *,date_diff('day',previous_race_date,race_date) AS days_since_previous_race
        FROM read_parquet(?) WHERE analysis_eligible
        AND keibajo_code IN ('01','02','03','04','05','06','07','08','09','10')
        AND race_date BETWEEN '2025-01-01' AND '2025-12-31'
        AND target_win IS NOT NULL AND target_top3 IS NOT NULL""",[source]).fetchdf()
    assert len(df)==47497 and not df.duplicated(['race_code','ketto_toroku_bango']).any()
    df['days_since_previous_race']=df['days_since_previous_race'].astype('float32')
    out=df[['race_code','race_date','ketto_toroku_bango','umaban','field_size','grade_code',
        'target_finish_position','target_win','target_top3']].copy()
    reproduction={}
    prior=pd.read_json(check/'predictions_2025.json',dtype={'race_code':str,'ketto_toroku_bango':str})
    for label in ['win','top3']:
        model=joblib.load(check/('calibration_2024_'+label+'.joblib'))
        x=df[spec['features']].copy()
        categorical=[f for f in spec['features'] if f in spec['categorical']]
        for field,cats in zip(categorical,model.booster_.pandas_categorical):
            values=x[field].astype('string').fillna('__MISSING__')
            x[field]=pd.Categorical(values.where(values.isin(cats),'__UNSEEN__'),categories=cats)
        for field in spec['features']:
            if field not in categorical:x[field]=pd.to_numeric(x[field],errors='raise').astype('float64')
        raw=np.clip(model.predict_proba(x)[:,1],1e-7,1-1e-7)
        out['raw_'+label]=raw
        calibrator=joblib.load(check/('calibration_2024_'+label+'_platt.joblib'))
        out['cal_'+label]=calibrator.predict_proba(np.log(raw/(1-raw)).reshape(-1,1))[:,1]
        compare=out[['race_code','ketto_toroku_bango','cal_'+label]].merge(
            prior[['race_code','ketto_toroku_bango',label+'_probability']],on=['race_code','ketto_toroku_bango'],validate='one_to_one')
        delta=float(np.abs(compare['cal_'+label]-compare[label+'_probability']).max())
        assert len(compare)==1931 and delta<1e-8,(label,delta)
        reproduction[label]={'checked_horses':len(compare),'max_calibrated_probability_difference':delta,
            'checkpoint_sha256':hashlib.sha256((check/('calibration_2024_'+label+'.joblib')).read_bytes()).hexdigest()}
    out.to_pickle(root/'private_assets/raw_predictions_2025.pkl')
    report={'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'rows':len(out),
        'races':int(out.race_code.nunique()),'base_training_end':'2024-12-31','prediction_period':'2025',
        'fold_specific_Platt_possible':True,'reproduction':reproduction,'source_sha256':hashlib.sha256(Path(source).read_bytes()).hexdigest(),
        'production_model_changed':False}
    (root/'public/raw_prediction_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ['workdir','source','model_dir','checkpoint_dir']:p.add_argument(key)
    a=p.parse_args();main(a.workdir,a.source,a.model_dir,a.checkpoint_dir)
