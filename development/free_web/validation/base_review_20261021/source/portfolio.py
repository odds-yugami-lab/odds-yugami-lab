"""Recalculate identical fixed-rule portfolios for same-input original and candidate."""
import os
os.environ.setdefault('OMP_NUM_THREADS','1');os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import concurrent.futures,datetime as dt,json,sys
from pathlib import Path
sys.path.insert(0,'decomposition_20261021')
from portfolio import one,aggregate
ROOT=Path('base_review_20261021')

def main():
    selection=json.loads((ROOT/'public/selection.json').read_text());name=selection['selected_family']
    original=json.loads(Path('correction_20261021/private_assets/correction_coefficients.json').read_text())
    parameters={'incumbent_frozen':[original['alpha_ai'],original['beta_market']],
        'shared_ai_market':selection['final_2025_fits'][name]['parameters']}
    races=json.loads((ROOT/'private_assets/races_2026.json').read_text())
    official={r['race_code']:r for r in json.loads(Path('bias_20261020/official_results.json').read_text())['races']}
    tasks=[(str(ROOT),r,method,params,official[r['race_code']])
        for method,params in parameters.items() for r in races['incumbent_same_input' if method=='incumbent_frozen' else 'candidate']]
    rows=[];errors=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(one,t):(t[1]['race_code'],t[2]) for t in tasks}
        for f in concurrent.futures.as_completed(futures):
            try:rows.append(f.result())
            except Exception as e:errors.append({'case':futures[f],'error':str(e)})
    if errors:
        (ROOT/'public/portfolio_errors.json').write_text(json.dumps(errors,indent=2)+'\n')
        raise RuntimeError(str(errors))
    assert len(rows)==206
    names={'incumbent_frozen':'incumbent_same_input','shared_ai_market':'candidate'}
    archive_codes={r['race_code'] for r in races['candidate'] if r['input_source']=='archive'}
    report={'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'test_only':True,'final_odds_used':True,
        'aggregate':{names[m]:aggregate([r for r in rows if r['method']==m]) for m in names},
        'archive96_only':{names[m]:aggregate([r for r in rows if r['method']==m and r['race_code'] in archive_codes]) for m in names},
        'halves':{half:{names[m]:aggregate([r for r in rows if r['method']==m and (r['date']<'2026-07-01')==early]) for m in names} for half,early in [('H1',True),('H2',False)]},
        'unchanged_rule':'balanced_A_v3, 10000 yen, exact minimum stakes; original solver time limits',
        'archived_previous_baseline_ROI_percent':79.19417475728156,'production_or_automation_changed':False}
    (ROOT/'public/portfolio_comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    compact=[{**{k:r[k] for k in ['race_code','date','race_name','ticket_count','stake_yen','payout_yen','any_hit','predicted_hit_probability']},'method':names[r['method']]} for r in rows]
    (ROOT/'public/portfolio_races.json').write_text(json.dumps(compact,ensure_ascii=False,indent=2)+'\n')
    print('SUMMARY',json.dumps(report),flush=True)

if __name__=='__main__':main()
