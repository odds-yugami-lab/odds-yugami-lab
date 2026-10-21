"""Reconstruct out-of-time 2025 predictions; never replace saved production models."""
import argparse, datetime as dt, hashlib, importlib.util, json, sys
from pathlib import Path
import duckdb, joblib, numpy as np, pandas as pd

def main(source, model_dir, workdir):
    source, model_dir, root = map(Path, (source, model_dir, workdir))
    out = root/'private_assets'; out.mkdir(parents=True,exist_ok=True)
    spec=json.loads((model_dir/'feature_spec.json').read_text())
    module_spec=importlib.util.spec_from_file_location('archived_train',model_dir/'train_free_model.py')
    train=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(train)
    con=duckdb.connect()
    df=con.execute("""SELECT *,date_diff('day',previous_race_date,race_date)
        AS days_since_previous_race FROM read_parquet(?)
        WHERE analysis_eligible AND keibajo_code IN ('01','02','03','04','05','06','07','08','09','10')
        AND race_date<='2025-12-31' AND target_win IS NOT NULL AND target_top3 IS NOT NULL""",[str(source)]).fetchdf()
    df['days_since_previous_race']=df['days_since_previous_race'].astype('float32')
    assert not df.duplicated(['race_code','ketto_toroku_bango']).any()
    before=df[df.race_date<='2024-12-31'];cal=df[df.race_date.between('2025-01-01','2025-12-31')]
    manifest=json.loads((model_dir/'manifest.json').read_text())
    assert len(df)==manifest['training_rows'] and len(cal)==manifest['calibration_rows']
    graded=cal[cal.grade_code.isin(['A','B','C'])].copy()
    print('TEMPORAL_ROWS',len(before),len(cal),'GRADED',len(graded),graded.race_code.nunique(),flush=True)
    out_frame=graded[['race_code','race_date','ketto_toroku_bango','umaban','field_size','grade_code','target_finish_position','target_win','target_top3']].copy()
    calibration_reproduction={}
    for label,target in [('win','target_win'),('top3','target_top3')]:
        print('FIT_OUT_OF_TIME',label,flush=True)
        checkpoint=out/('calibration_2024_'+label+'.joblib')
        raw_path=out/('raw_2025_'+label+'.npy')
        if checkpoint.exists() and raw_path.exists():
            model=joblib.load(checkpoint);raw=np.load(raw_path)
        else:
            model,raw,maps=train.fit(before,cal,target,spec['features'],spec['categorical'])
            joblib.dump(model,checkpoint,compress=3);np.save(raw_path,raw)
        saved=joblib.load(model_dir/(label+'_platt.joblib'))
        fitted=train.platt(raw,cal[target])
        diff=float(np.max(np.abs(saved.coef_-fitted.coef_)))
        diff=max(diff,float(np.max(np.abs(saved.intercept_-fitted.intercept_))))
        calibration_reproduction[label]={'max_parameter_difference':diff,'reproduced':diff<1e-7}
        # Same parameters/split need not yield byte-identical training across
        # runtime/row/category ordering. Fit the recreated model's own 2025
        # calibrator rather than silently declaring the saved one reproduced.
        prob=fitted.predict_proba(np.log(np.clip(raw,1e-7,1-1e-7)/(1-np.clip(raw,1e-7,1-1e-7))).reshape(-1,1))[:,1]
        out_frame[label+'_probability']=prob[cal.grade_code.isin(['A','B','C']).to_numpy()]
        joblib.dump(fitted,out/('calibration_2024_'+label+'_platt.joblib'),compress=3)
        print('FIT_DONE',label,'CALIBRATOR_DIFF',diff,flush=True)
    out_frame['race_date']=out_frame.race_date.dt.strftime('%Y-%m-%d')
    out_frame.to_json(out/'predictions_2025.json',orient='records',force_ascii=False,indent=2)
    report={'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'training_end':'2024-12-31','prediction_year':2025,
        'training_rows':len(before),'calibration_rows':len(cal),'graded_horses':len(graded),'graded_races':int(graded.race_code.nunique()),
        'original_calibrators_reproduced':calibration_reproduction,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'production_model_modified':False,
        'reconstruction_scope':'Same archived algorithm, features, row counts and temporal split; exact historical fitted parameters are checked separately and are not assumed identical.',
        'recreated_predictions_use':'Their own Platt calibrator fitted on 2025; all correction parameters fitted in 2025 only.'}
    (root/'public/reconstruction_report.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('model_dir');p.add_argument('workdir');a=p.parse_args()
    main(a.source,a.model_dir,a.workdir)
