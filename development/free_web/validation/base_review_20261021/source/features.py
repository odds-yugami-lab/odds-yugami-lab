"""Research-only race-relative features; never uses labels or other races."""
import pandas as pd
RATE_COLUMNS = [prefix + suffix for prefix in ['horse_prior_','horse_distance_prior_',
    'horse_course_track_prior_','jockey_prior_','trainer_prior_','sire_prior_']
    for suffix in ['win_rate','top3_rate']]
RELATIVE_COLUMNS = RATE_COLUMNS + ['previous_finish_position']

def augment(frame):
    frame=frame.copy()
    for col in RELATIVE_COLUMNS:
        values=pd.to_numeric(frame[col],errors='raise')
        grouped=values.groupby(frame.race_code)
        # Larger rank means stronger; lower previous finish is stronger.
        frame[col+'_field_percentile']=grouped.rank(method='average',pct=True,
            ascending=(col!='previous_finish_position'))
        frame[col+'_field_centered']=values-grouped.transform('mean')
    return frame

def feature_names(base,relative):
    return list(base)+([col+suffix for col in RELATIVE_COLUMNS
        for suffix in ['_field_percentile','_field_centered']] if relative else [])

def matrix(frame,features,categorical,maps=None):
    x=frame[features].copy();out={}
    for col in categorical:
        values=x[col].astype('string').fillna('__MISSING__')
        cats=(list(dict.fromkeys(values.tolist()+['__UNSEEN__'])) if maps is None else maps[col])
        x[col]=pd.Categorical(values.where(values.isin(cats),'__UNSEEN__'),categories=cats)
        out[col]=cats
    for col in features:
        if col not in categorical:x[col]=pd.to_numeric(x[col],errors='raise').astype('float64')
    return x,out
