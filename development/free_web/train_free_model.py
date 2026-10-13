"""Build a separate no-workout model from the supplied historical features.

Same parameters and temporal split as the archived live-model exporter.
Does not inherit its ROI, prove source data is leak-free, or publish predictions.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import platform
import duckdb
import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import sklearn
from sklearn.linear_model import LogisticRegression

PARAMS = dict(objective='binary',n_estimators=368,learning_rate=0.025,
              num_leaves=24,max_depth=8,min_child_samples=200,subsample=0.85,
              colsample_bytree=0.80,reg_alpha=0.5,reg_lambda=2.0,
              random_state=20261002,n_jobs=2,verbosity=-1)

def prepare(train,test,features,categorical):
    a=train[features].copy();b=test[features].copy();maps={}
    for name in categorical:
        av=a[name].astype('string').fillna('__MISSING__')
        bv=b[name].astype('string').fillna('__MISSING__')
        cats=pd.Index(av.unique())
        bv=bv.where(bv.isin(cats),'__UNSEEN__')
        cats=cats.append(pd.Index(['__UNSEEN__'])).unique()
        maps[name]=list(map(str,cats))
        a[name]=pd.Categorical(av,categories=cats)
        b[name]=pd.Categorical(bv,categories=cats)
    return a,b,maps

def fit(train,test,target,features,categorical):
    a,b,maps=prepare(train,test,features,categorical)
    model=lgb.LGBMClassifier(**PARAMS)
    model.fit(a,train[target].astype('int8').to_numpy(),categorical_feature=categorical)
    return model,model.predict_proba(b)[:,1],maps

def platt(raw,y):
    p=np.clip(raw,1e-7,1-1e-7)
    model=LogisticRegression(C=1e6,solver='lbfgs',max_iter=2000)
    model.fit(np.log(p/(1-p)).reshape(-1,1),y.astype('int8').to_numpy())
    return model

def build(source,spec_path,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    old=json.loads(Path(spec_path).read_text())
    features=[f for f in old['features'] if 'workout' not in f]
    categorical=[f for f in old['categorical'] if f in features]
    if len(features)!=52:
        raise ValueError('Expected 52 no-workout features')
    c=duckdb.connect()
    df=c.execute('''SELECT *,date_diff('day',previous_race_date,race_date)
          AS days_since_previous_race FROM read_parquet(?)
          WHERE analysis_eligible AND keibajo_code IN ('01','02','03','04','05','06','07','08','09','10')
          AND race_date<='2025-12-31' AND target_win IS NOT NULL AND target_top3 IS NOT NULL''',[str(source)]).fetchdf()
    df['days_since_previous_race']=df['days_since_previous_race'].astype('float32')
    if df.duplicated(['race_code','ketto_toroku_bango']).any():
        raise ValueError('Duplicate labeled training records')
    before=df[df['race_date']<='2024-12-31'];cal=df[df['race_date'].between('2025-01-01','2025-12-31')]
    if before.empty or cal.empty or df['race_date'].max()>pd.Timestamp('2025-12-31'):
        raise ValueError('Invalid temporal split')
    print('Rows train<=2024',len(before),'calibration2025',len(cal),'final<=2025',len(df),flush=True)
    maps_final=None
    for label,target in [('win','target_win'),('top3','target_top3')]:
        print(label,'calibration model fitting',flush=True)
        _,raw,_=fit(before,cal,target,features,categorical)
        calibrator=platt(raw,cal[target])
        print(label,'final model fitting',flush=True)
        model,_,maps=fit(df,df.iloc[:1],target,features,categorical)
        if maps_final is not None and maps!=maps_final:
            raise ValueError('Category map mismatch')
        maps_final=maps
        joblib.dump(model,out/(label+'_model.joblib'),compress=3)
        joblib.dump(calibrator,out/(label+'_platt.joblib'),compress=3)
        print(label,'saved',flush=True)
    (out/'feature_spec.json').write_text(json.dumps({'features':features,'categorical':categorical,'category_map':maps_final},ensure_ascii=False,indent=2))
    versions={'python':platform.python_version(),'duckdb':duckdb.__version__,'lightgbm':lgb.__version__,'numpy':np.__version__,'pandas':pd.__version__,'scikit_learn':sklearn.__version__,'joblib':joblib.__version__}
    manifest={'package':'JRA_FREE_NO_WORKOUT_52_20261013','created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
              'training_end':'2025-12-31','calibration_year':2025,'calibration_model_training_end':'2024-12-31',
              'feature_count':52,'removed_features':[f for f in old['features'] if 'workout' in f],
              'source_sha256':hashlib.sha256(Path(source).read_bytes()).hexdigest(),
              'training_rows':len(df),'calibration_rows':len(cal),'parameters':PARAMS,'versions':versions,
              '2026_results_used_for_training':False,'2026_results_used_for_calibration':False,
              'historical_ROI_not_inherited':True,'source_feature_point_in_time_proven':False,
              'live_operation_ready':False,'purpose':'free-data model candidate; inference verification pending'}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    (out/'requirements.txt').write_text('\n'.join(name.replace('_','-')+'=='+version for name,version in versions.items() if name!='python')+'\n')
    print('Model package saved',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('spec');p.add_argument('out');args=p.parse_args()
    build(args.source,args.spec,args.out)
