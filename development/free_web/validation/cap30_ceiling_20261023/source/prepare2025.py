"""Annual2025 forecasts calibrated with2024 only; no2025 label fitting."""
import concurrent.futures,datetime as dt,json,sys
from pathlib import Path
import duckdb,joblib,lightgbm as lgb,numpy as np,pandas as pd
sys.path.insert(0,'base_review_20261021');from features import matrix
sys.path.insert(0,'decomposition_20261021');from train_cv import calibrate,make_races
from rankwise import fit
sys.path.insert(0,'correction_20261021');from collect_market import parse_market
sys.path.insert(0,'correction_20261021/runtime');from source_bundle import download
from result_store import text
ROOT=Path('cap30_ceiling_20261023');PRIVATE=ROOT/'private_assets';PUBLIC=ROOT/'public'
PARAMS=dict(objective='binary',n_estimators=368,learning_rate=.025,num_leaves=24,max_depth=8,
 min_child_samples=200,subsample=.85,colsample_bytree=.8,reg_alpha=.5,reg_lambda=2.,random_state=20261002,n_jobs=2,verbosity=-1)
META=['race_code','race_date','ketto_toroku_bango','umaban','field_size','grade_code','target_finish_position','target_win','target_top3']

def clean(data):
    flat=data[pd.to_numeric(data.track_code).between(10,29)]
    groups=flat.groupby('race_code').agg(rows=('umaban','size'),numbers=('umaban','nunique'),horses=('ketto_toroku_bango','nunique'),
        fmin=('field_size','min'),fmax=('field_size','max'),w=('target_win','sum'),t=('target_top3','sum'))
    ok=(groups.rows==groups.fmin)&(groups.rows==groups.fmax)&(groups.rows==groups.numbers)&(groups.rows==groups.horses)&(groups.w==1)&(groups.t==3)
    return flat[flat.race_code.isin(groups.index[ok])].sort_values(['race_code','umaban']).reset_index(drop=True)

def market(code):
    path=Path('correction_20261021/cache/market')/(code+'.json')
    if path.exists():return json.loads(path.read_text())
    url='https://sports.yahoo.co.jp/keiba/race/denma/'+code[2:4]+code[8:]
    page,stamp,digest=download(url);obj=parse_market(page,code,text)
    obj.update(source_url=url,retrieved_at=stamp,page_sha256=digest)
    path.write_text(json.dumps(obj,ensure_ascii=False)+'\n');return obj

def main():
    con=duckdb.connect()
    data=con.execute("""SELECT *,date_diff('day',previous_race_date,race_date) AS days_since_previous_race
        FROM read_parquet(?) WHERE analysis_eligible AND keibajo_code BETWEEN '01' AND '10'
        AND race_date<='2024-12-31' AND target_win IS NOT NULL AND target_top3 IS NOT NULL""",
        ['bias_20261020/private_assets/race_features.parquet']).fetchdf()
    data.days_since_previous_race=data.days_since_previous_race.astype('float32')
    filtered=clean(data);cal=filtered[filtered.race_date.dt.year==2024].copy()
    spec=json.loads(Path('repair_20261020/private_assets/JRA_free_model_52_20261013/feature_spec.json').read_text())
    frames={};modelsdir=PRIVATE/'calibration2024';modelsdir.mkdir(exist_ok=True)
    for method in ['incumbent','candidate']:
        path=modelsdir/(method+'_raw2024.pkl')
        if path.exists():frames[method]=pd.read_pickle(path);continue
        train=(data[data.race_date<'2024-01-01'] if method=='incumbent' else filtered[filtered.race_date.between('2019-01-01','2023-12-31')])
        assert train.race_date.max()<pd.Timestamp('2024-01-01')
        x,maps=matrix(train,spec['features'],spec['categorical']);v,_=matrix(cal,spec['features'],spec['categorical'],maps)
        out=cal[META].copy()
        for label in ['win','top3']:
            print('TRAIN2023',method,label,len(train),flush=True)
            model=lgb.LGBMClassifier(**PARAMS);model.fit(x,train['target_'+label].astype('int8'),categorical_feature=spec['categorical'])
            out['raw_'+label]=model.predict_proba(v)[:,1]
            joblib.dump(model,modelsdir/(method+'_'+label+'_through2023.joblib'),compress=3)
        out.to_pickle(path);frames[method]=out
    candidates=set(cal[cal.grade_code.isin(['A','B','C'])].race_code)
    failures=[];valid=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures={pool.submit(market,c):c for c in sorted(candidates)}
        for f in concurrent.futures.as_completed(futures):
            code=futures[f]
            try:
                m=f.result();g=cal[cal.race_code==code]
                assert set(g.umaban.astype(int))=={r['umaban'] for r in m['runners']}
                ids={r['umaban']:r['horse_id'] for r in m['runners']}
                assert all(str(r.ketto_toroku_bango)==ids[int(r.umaban)] for r in g.itertuples())
                order=g[g.target_finish_position.between(1,3)].sort_values('target_finish_position').target_finish_position.tolist()
                assert order==[1,2,3]
                valid.append(code)
            except Exception as e:failures.append({'race_code':code,'reason':str(e) or type(e).__name__})
    assert len(valid)>=50,'Insufficient2024 correction races'
    fixed=json.loads(Path('correction_20261021/private_assets/correction_coefficients.json').read_text())
    targetcodes=set(fixed['fit_race_codes']);assert len(targetcodes)==119
    out_races={};coefficients={}
    for method,frame in frames.items():
        probabilities,platt=calibrate(frame,np.ones(len(frame),bool))
        fitted=fit(make_races(frame,probabilities,set(valid)),'shared_ai_market');coefficients[method]=fitted
        raw2025=pd.read_pickle('decomposition_20261021/private_assets/raw_predictions_2025.pkl' if method=='incumbent' else 'base_review_20261021/private_assets/recent52_through2024/raw_predictions.pkl')
        p2025={}
        for label,model in platt.items():
            raw=np.clip(raw2025['raw_'+label].to_numpy(),1e-7,1-1e-7)
            p2025[label]=model.predict_proba(np.log(raw/(1-raw)).reshape(-1,1))[:,1]
            joblib.dump(model,modelsdir/(method+'_'+label+'_platt2024.joblib'),compress=3)
        races=make_races(raw2025,p2025,targetcodes);assert len(races)==119
        # Outcomes are retained in a separate local file for later official checks.
        (PRIVATE/('labels2025_'+method+'.json')).write_text(json.dumps(races)+'\n')
        out_races[method]=[{k:r[k] for k in ['race_code','date','numbers','win','top3','odds']}|{'input_source':'archive2025'} for r in races]
    (PRIVATE/'forecast_inputs2025.json').write_text(json.dumps(out_races)+'\n')
    report={'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'test_only':True,
        'base_training_end_for2025':'2024-12-31','base_training_end_for_calibration2024':'2023-12-31',
        'calibration_year':2024,'market_correction_year':2024,'2025_labels_used_to_fit':False,
        '2025_portfolios_evaluated':False,'2024_calibration_rows':len(cal),'2024_correction_races':len(valid),
        '2024_exclusions':failures,'2025_expected_races':119,'2025_archive_graded_races':130,'2025_exclusions':fixed['exclusions'],
        'parameters':{m:x['parameters'] for m,x in coefficients.items()},'fit_details':coefficients,
        'prior_model_family_selection_used2025':True,'2025_not_independent_of_prior_research':True,
        'point_in_time_source_features_certified':False}
    (PUBLIC/'fit2024_for2025.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('2025_READY',json.dumps({k:report[k] for k in ['2024_correction_races','2025_expected_races','parameters']}),flush=True)

if __name__=='__main__':main()
