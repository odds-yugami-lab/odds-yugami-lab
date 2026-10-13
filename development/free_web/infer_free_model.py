"""Load the separate 52-feature model; probability computation only.

Does not certify data freshness, prediction completeness or publication.
Missing numeric historical values are retained as NaN, never zero-filled.
"""
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd

def predict(model_dir,records):
    model_dir=Path(model_dir)
    spec=json.loads((model_dir/'feature_spec.json').read_text())
    df=pd.DataFrame(records)
    absent=[f for f in spec['features'] if f not in df.columns]
    if absent:
        raise ValueError('Missing input columns: '+str(absent))
    x=df[spec['features']].copy()
    for name in spec['features']:
        if name in spec['categorical']:
            values=x[name].astype('string').fillna('__MISSING__')
            categories=spec['category_map'][name]
            values=values.where(values.isin(categories),'__UNSEEN__')
            x[name]=pd.Categorical(values,categories=categories)
        else:
            x[name]=pd.to_numeric(x[name],errors='raise').astype('float64')
    out={}
    for label in ['win','top3']:
        model=joblib.load(model_dir/(label+'_model.joblib'))
        if list(model.feature_name_)!=spec['features']:
            raise ValueError('Model feature order mismatch')
        raw=np.clip(model.predict_proba(x)[:,1],1e-7,1-1e-7)
        calibration=joblib.load(model_dir/(label+'_platt.joblib'))
        probabilities=calibration.predict_proba(np.log(raw/(1-raw)).reshape(-1,1))[:,1]
        if not np.isfinite(probabilities).all() or not ((probabilities>=0)&(probabilities<=1)).all():
            raise ValueError('Invalid probability output')
        out[label]=probabilities
    return out
