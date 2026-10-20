from runtime_paths import ROOT, MODULES, MODEL, HISTORY, HISTORY_DIR, BUNDLE, ASSETS
"""Read private feature archives and identify complete 2026 official flat races.
No training, rule change, live publication, or current result label as feature.
"""
from pathlib import Path
import sys,json,datetime as dt
import pandas as pd,numpy as np,duckdb
ROOT=ROOT
MODULES=MODULES
sys.path.insert(0,str(MODULES))
from infer_free_model import predict
MODEL=MODEL
SPEC=json.loads((MODEL/'feature_spec.json').read_text())

def clean_scalar(v):
    if isinstance(v,(dt.datetime,dt.date,pd.Timestamp)):return v.isoformat()[:10]
    if v is None or pd.isna(v):return None
    if isinstance(v,np.generic):return v.item()
    return v

def main():
    official=json.loads((ROOT/'official_results.json').read_text())['races']
    if any('error' in r for r in official):raise ValueError('Official result collection incomplete')
    assert len({r['race_code'] for r in official})==103
    valid_codes={r['race_code'] for r in official}
    c=duckdb.connect()
    sources={}
    for source in ['race_features.parquet','jra_features_pilot_2025_2026.parquet']:
        f=c.execute("SELECT *,date_diff('day',previous_race_date,race_date) AS days_since_previous_race FROM read_parquet(?) WHERE race_date BETWEEN DATE '2026-01-01' AND DATE '2026-10-18' AND keibajo_code BETWEEN '01' AND '10' AND grade_code IN ('A','B','C')",[str(ROOT/'private_assets'/source)]).fetchdf()
        f=f[f.race_code.isin(valid_codes)]
        f=f[f.umaban.astype('string').str.fullmatch(r'0?[1-9]|1[0-8]',na=False)]
        f=f[~f.is_cancelled_or_excluded.fillna(False)]
        f=f[(f.field_size>=3)&f.body_weight_kg.notna()&f.jockey_code.notna()&f.wakuban.notna()]
        f['_source']=source
        sources[source]=f
    joined=pd.concat(sources.values(),ignore_index=True)
    joined=joined.drop_duplicates(['race_code','ketto_toroku_bango'],keep='first')
    reports=[];good=[];missing=[]
    for result in official:
        race=result['race_code']; rows=joined[joined.race_code==race].copy()
        expected={r['horse_number'] for r in result['finish_rows'] if r['finish_status'] not in {'取消','除外'}}
        actual=set(pd.to_numeric(rows.umaban).astype(int))
        complete=(actual==expected and not rows.umaban.duplicated().any())
        audit={'race_code':race,'name':result['name'],'expected_runners':len(expected),
               'complete_feature_runners':len(rows),'missing_numbers':sorted(expected-actual),
               'status':'complete' if complete else 'needs_supplement'}
        reports.append(audit)
        if complete:good.extend(rows.to_dict('records'))
        else:missing.append(audit)
    frame=pd.DataFrame(good)
    probs=predict(MODEL,frame)
    rows=[]
    by_code={x['race_code']:x for x in official}
    for (_,r),w,t in zip(frame.iterrows(),probs['win'],probs['top3']):
        code=r.race_code;num=int(r.umaban)
        result=next(x for x in by_code[code]['runners'] if x['umaban']==num)
        status=result['finish_status']
        rows.append({'race_code':code,'umaban':num,'horse_id':r.ketto_toroku_bango,
            'win_probability':float(w),'top3_probability':float(t),
            'finish_status':status,'target_win':status=='1',
            'target_top3':status.isdigit() and int(status)<=3,
            'popularity':result['popularity'],'grade':by_code[code]['grade'],
            'source':r['_source']})
    (ROOT/'horse_predictions.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'input_audit.json').write_text(json.dumps({'official_flat_races':103,'complete_archive_races':len(reports)-len(missing),
        'missing':missing,'races':reports,'feature_count':52,
        'source_point_in_time_proven':False,'training_end':'2025-12-31','test_year':2026},ensure_ascii=False,indent=2)+'\n')
    print('INPUTS',len(reports)-len(missing),'complete',len(rows),'horses; missing:',json.dumps(missing,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
