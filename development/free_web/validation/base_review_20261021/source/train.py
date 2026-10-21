"""Prespecified base learner review. Select on 2025 only, never on 2026."""
import datetime as dt,hashlib,json,sys,time
from pathlib import Path
import duckdb,joblib,lightgbm as lgb,numpy as np,pandas as pd
from features import augment,feature_names,matrix
sys.path.insert(0,'decomposition_20261021')
from train_cv import calibrate,make_races
from rankwise import fit,scores,observed_losses,distribution
ROOT=Path('base_review_20261021');PRIVATE=ROOT/'private_assets';PUBLIC=ROOT/'public'
MODEL=Path('repair_20261020/private_assets/JRA_free_model_52_20261013')
PARAMS=dict(objective='binary',n_estimators=368,learning_rate=.025,num_leaves=24,
    max_depth=8,min_child_samples=200,subsample=.85,colsample_bytree=.8,
    reg_alpha=.5,reg_lambda=2.,random_state=20261002,n_jobs=2,verbosity=-1)
META=['race_code','race_date','ketto_toroku_bango','umaban','field_size','grade_code',
    'target_finish_position','target_win','target_top3']

def cohort():
    con=duckdb.connect()
    data=con.execute("""SELECT *,date_diff('day',previous_race_date,race_date) AS days_since_previous_race
      FROM read_parquet(?) WHERE analysis_eligible AND keibajo_code BETWEEN '01' AND '10'
      AND race_date BETWEEN '2020-01-01' AND '2025-12-31'
      AND target_win IS NOT NULL AND target_top3 IS NOT NULL""",
      ['bias_20261020/private_assets/race_features.parquet']).fetchdf()
    data.days_since_previous_race=data.days_since_previous_race.astype('float32')
    flat=data[pd.to_numeric(data.track_code).between(10,29)].copy()
    grouped=flat.groupby('race_code').agg(rows=('umaban','size'),numbers=('umaban','nunique'),
        horses=('ketto_toroku_bango','nunique'),field_min=('field_size','min'),field_max=('field_size','max'),
        wins=('target_win','sum'),top3=('target_top3','sum'))
    ok=(grouped.rows==grouped.field_min)&(grouped.rows==grouped.field_max)&(grouped.numbers==grouped.rows)&(grouped.horses==grouped.rows)&(grouped.wins==1)&(grouped.top3==3)
    clean=flat[flat.race_code.isin(grouped.index[ok])].sort_values(['race_code','umaban']).reset_index(drop=True)
    report={'source_rows_2020_2025':len(data),'flat_rows':len(flat),'clean_rows':len(clean),
        'excluded_flat_races':int((~ok).sum()),'exclusion_not_automatically_data_error':'Includes dead heats, incomplete fields, other target-count exceptions.',
        'rows_by_year':{str(k):int(v) for k,v in clean.groupby(clean.race_date.dt.year).size().items()},
        'future_previous_dates':int((clean.previous_race_date>=clean.race_date).sum()),
        'negative_days':int((clean.days_since_previous_race<0).sum()),
        'rate_columns_outside_0_1':{},'feature_point_in_time_certified':False}
    for col in [x for x in clean if x.endswith('_rate')]:
        report['rate_columns_outside_0_1'][col]=int((clean[col].notna()&~clean[col].between(0,1)).sum())
    assert report['future_previous_dates']==0 and report['negative_days']==0
    (PUBLIC/'cohort_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    return augment(clean)

def build(family,train,test,spec,tag):
    path=PRIVATE/(family+'_'+tag);path.mkdir(exist_ok=True)
    features=feature_names(spec['features'],family!='recent52')
    cats=[x for x in spec['features'] if x in spec['categorical']]
    a,maps=matrix(train,features,cats);b,_=matrix(test,features,cats,maps)
    params=PARAMS.copy()
    if family=='relative78_detail':params.update(n_estimators=600,num_leaves=31,min_child_samples=80)
    out=test[META].copy()
    for label in ['win','top3']:
        print('FIT',family,tag,label,len(train),len(features),flush=True);started=time.time()
        model=lgb.LGBMClassifier(**params)
        model.fit(a,train['target_'+label].astype('int8').to_numpy(),categorical_feature=cats)
        out['raw_'+label]=np.clip(model.predict_proba(b)[:,1],1e-7,1-1e-7)
        joblib.dump(model,path/(label+'_model.joblib'),compress=3)
        print('SAVED',family,label,round(time.time()-started,1),'seconds',flush=True)
    (path/'feature_spec.json').write_text(json.dumps({'features':features,'categorical':cats,'category_map':maps},indent=2)+'\n')
    out.to_pickle(path/'raw_predictions.pkl')
    return out

def main():
    data=cohort();cal=data[data.race_date.dt.year==2025].copy();train=data[data.race_date.dt.year<2025]
    spec=json.loads((MODEL/'feature_spec.json').read_text())
    fixed=json.loads(Path('correction_20261021/private_assets/correction_coefficients.json').read_text())
    codes=set(fixed['fit_race_codes']);assert len(codes)==119
    assert codes<=set(cal.race_code)
    incumbent=pd.read_pickle('decomposition_20261021/private_assets/raw_predictions_2025.pkl')
    keys=cal[['race_code','ketto_toroku_bango']]
    incumbent=keys.merge(incumbent,on=['race_code','ketto_toroku_bango'],validate='one_to_one')
    families={'incumbent':incumbent}
    for family in ['recent52','relative78','relative78_detail']:
        saved=PRIVATE/(family+'_through2024/raw_predictions.pkl')
        families[family]=pd.read_pickle(saved) if saved.exists() else build(family,train,cal,spec,'through2024')
    folds=json.loads(Path('decomposition_20261021/public/protocol.json').read_text())['folds']
    reports=[];details=[];final_fits={}
    for family,frame in families.items():
        for fold_no,fold in enumerate(folds,1):
            mask=(frame.race_date<=fold['train_end']).to_numpy()
            probabilities,_=calibrate(frame,mask);races=make_races(frame,probabilities,codes)
            fit_races=[r for r in races if r['date']<=fold['train_end']]
            validation=[r for r in races if fold['validate_start']<=r['date']<=fold['validate_end']]
            fitted=fit(fit_races,'shared_ai_market');reports.append({'family':family,'fold':fold_no,'fit':fitted,
                'calibration_rows':int(mask.sum()),'fit_races':len(fit_races),'validation_races':len(validation)})
            for race in validation:
                stage=scores(race,'shared_ai_market',fitted['parameters']);_,_,w,t=distribution(stage)
                details.append({'family':family,'fold':fold_no,'race_code':race['race_code'],
                    'ordered_nll':sum(observed_losses(stage,race['order'])),
                    'raw_WIN_brier':float(np.mean((np.asarray(race['win'])-race['target_win'])**2)),
                    'raw_TOP3_brier':float(np.mean((np.asarray(race['top3'])-race['target_top3'])**2)),
                    'WIN_brier':float(np.mean((w-race['target_win'])**2)),
                    'TOP3_brier':float(np.mean((t-race['target_top3'])**2))})
            print('CV',family,fold_no,len(validation),flush=True)
        probabilities,platt=calibrate(frame,np.ones(len(frame),bool))
        final_fits[family]=fit(make_races(frame,probabilities,codes),'shared_ai_market')
        for label,m in platt.items():joblib.dump(m,PRIVATE/(family+'_2025_'+label+'_platt.joblib'),compress=3)
    table=pd.DataFrame(details);ranking=[]
    for family,g in table.groupby('family',sort=False):
        assert len(g)==74
        ranking.append({'family':family,'validation_races':len(g),**{col:float(g[col].mean()) for col in ['ordered_nll','raw_WIN_brier','raw_TOP3_brier','WIN_brier','TOP3_brier']}})
    new=[r for r in ranking if r['family']!='incumbent'];best=min(r['ordered_nll'] for r in new)
    selected=min([r for r in new if r['ordered_nll']<=best+1e-6],
        key=lambda r:['recent52','relative78','relative78_detail'].index(r['family']))['family']
    selection={'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'selection_year':2025,'2026_used_for_selection':False,
        'selected_family':selected,'ranking':ranking,'folds':reports,'final_2025_fits':final_fits,
        'protocol_sha256':hashlib.sha256((PUBLIC/'protocol.json').read_bytes()).hexdigest(),
        'production_changed':False,'research_candidate_only':True}
    (PUBLIC/'selection.json').write_text(json.dumps(selection,indent=2)+'\n')
    (PUBLIC/'cv_races.json').write_text(json.dumps(details,indent=2)+'\n')
    print('FROZEN',json.dumps(selection),flush=True)
    # Refitting uses no 2026 inputs/labels and does not alter selection.
    final_train=data[data.race_date.dt.year>=2021]
    build(selected,final_train,cal.iloc[:1],spec,'through2025')

if __name__=='__main__':main()
