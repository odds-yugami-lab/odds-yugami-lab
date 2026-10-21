"""Fixed-rule portfolio replay for the 2025-selected method and incumbent."""
import os
os.environ.setdefault('OMP_NUM_THREADS','1');os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import argparse,concurrent.futures,datetime as dt,json,math,time
from pathlib import Path
import numpy as np,pandas as pd
from rankwise import scores,probability_tables
from allocation_scenarios import allocate_balanced

def one(task):
    root_string,race,method,parameters,official=task;root=Path(root_string)
    dest=root/'private_assets/portfolios'/method;dest.mkdir(parents=True,exist_ok=True)
    path=dest/(race['race_code']+'.json')
    if path.exists():return json.loads(path.read_text())
    stage=scores(race,'shared_ai_market' if method=='incumbent_frozen' else method,parameters)
    horses,combo,scenario=probability_tables(race,stage)
    source=json.loads((Path('bias_20261020/public_cache/odds')/(race['race_code']+'.json')).read_text())['snapshots']
    odds=pd.DataFrame([r for s in source.values() for r in s['rows']])
    merged=combo.merge(odds,on=['race_code','bet_type','kumiban'],how='outer',validate='one_to_one',indicator=True)
    assert merged._merge.eq('both').all();merged=merged.drop(columns='_merge')
    begin=time.monotonic();tickets,audit=allocate_balanced(merged,horses,outcome_scenarios=scenario)
    rows=[]
    for t in tickets.to_dict('records'):
        stake=int(t['stake']);price=float(t['decimal_odds'])
        assert stake==100*max(1,math.ceil(10000/(100*price)-1e-12))
        payout=int(official['payouts_per_100_yen'][t['bet_type']].get(t['kumiban'],0))*stake//100
        rows.append(dict(t,stake=stake,payout_yen=payout))
    assert sum(t['stake'] for t in rows)==10000
    result={'race_code':race['race_code'],'date':race['date'],'race_name':official['name'],'method':method,
        'test_only':True,'is_live_prediction':False,'final_odds_used':True,'stake_yen':10000,
        'ticket_count':len(rows),'payout_yen':sum(t['payout_yen'] for t in rows),'any_hit':any(t['payout_yen'] for t in rows),
        'predicted_hit_probability':audit['probability_any_win'],
        'model_expected_payout_yen':audit['model_expected_payout_yen_full_actual_odds'],
        'stake_at_100x_or_more':sum(t['stake'] for t in rows if t['decimal_odds']>=100),
        'seconds':time.monotonic()-begin,'allocation_audit':audit,'tickets':rows}
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('PORTFOLIO',method,race['race_code'],len(rows),result['payout_yen'],flush=True)
    return result

def aggregate(rows):
    investment=sum(r['stake_yen'] for r in rows);payout=sum(r['payout_yen'] for r in rows)
    actual=np.mean([r['any_hit'] for r in rows]);estimated=np.mean([r['predicted_hit_probability'] for r in rows])
    return {'races':len(rows),'tickets':sum(r['ticket_count'] for r in rows),'stake_yen':investment,'payout_yen':payout,
        'recovery_percent':100*payout/investment,'hit_races':sum(r['any_hit'] for r in rows),
        'actual_hit_rate':float(actual),'mean_predicted_hit_probability':float(estimated),
        'absolute_hit_calibration_gap':abs(float(actual-estimated)),
        'stake_share_at_100x_or_more':sum(r['stake_at_100x_or_more'] for r in rows)/investment,
        'maximum_allocation_seconds':max(r['seconds'] for r in rows)}

def main(workdir):
    root=Path(workdir);selection=json.loads((root/'public/selection.json').read_text());chosen=selection['selected_method']
    original=json.loads(Path('correction_20261021/private_assets/correction_coefficients.json').read_text())
    configurations={chosen:selection['final_full2025_fits'][chosen]['parameters'],
        'incumbent_frozen':[original['alpha_ai'],original['beta_market']]}
    races=json.loads((root/'private_assets/races_2026.json').read_text())
    official={r['race_code']:r for r in json.loads(Path('bias_20261020/official_results.json').read_text())['races']}
    tasks=[(str(root),r,m,p,official[r['race_code']]) for m,p in configurations.items() for r in races]
    rows=[];errors=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(one,t):(t[1]['race_code'],t[2]) for t in tasks}
        for f in concurrent.futures.as_completed(futures):
            try:rows.append(f.result())
            except Exception as e:
                errors.append({'case':futures[f],'error':str(e)});print('PORTFOLIO_FAILED',str(futures[f]),str(e),flush=True)
    if errors:
        (root/'public/portfolio_errors.json').write_text(json.dumps(errors,indent=2));raise RuntimeError('Portfolio evaluation incomplete')
    assert len(rows)==206
    by_method={m:sorted([r for r in rows if r['method']==m],key=lambda r:r['race_code']) for m in configurations}
    prior_base=json.loads(Path('correction_20261021/public/comparison.json').read_text())['aggregate']
    variability=[]
    for r in rows:
        earlier_name='market' if r['method']=='market_PL' else 'corrected' if r['method']=='incumbent_frozen' else None
        if earlier_name is None:continue
        prior=json.loads((Path('correction_20261021/private_assets/evaluation')/r['race_code']/(earlier_name+'.json')).read_text())
        a={(x['bet_type'],x['kumiban'],x['stake']) for x in r['tickets']}
        b={(x['bet_type'],x['kumiban'],x['stake']) for x in prior['tickets']}
        if a!=b:variability.append({'method':r['method'],'race_code':r['race_code'],'previous_tickets':len(b),
            'new_tickets':len(a),'previous_payout_yen':prior['payout_yen'],'new_payout_yen':r['payout_yen']})
    report={'test_only':True,'selected_before_2026_evaluation':chosen,'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'allocation_rule_unchanged':'balanced_A_v3 objective/constraints/default solver; only scenario probabilities supplied explicitly',
        'aggregate':{m:aggregate(r) for m,r in by_method.items()},
        'halves':{half:{m:aggregate([r for r in values if (r['date']<'2026-07-01')==early]) for m,values in by_method.items()}
            for half,early in [('H1',True),('H2',False)]},
        'approximate_solver_variations_vs_previous_runs':variability,
        'prior_saved_comparison_ROI':{'incumbent':prior_base['corrected']['portfolio']['recovery_percent'],
            'market':prior_base['market']['portfolio']['recovery_percent']},
        'original_records_overwritten':False,'production_or_automation_changed':False}
    (root/'public/portfolio_comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    compact=[{k:r[k] for k in ['race_code','date','race_name','method','ticket_count','stake_yen','payout_yen','any_hit','predicted_hit_probability']} for r in rows]
    (root/'public/portfolio_races_206.json').write_text(json.dumps(compact,ensure_ascii=False,indent=2)+'\n')
    print('PORTFOLIO_SUMMARY',json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('workdir');a=p.parse_args();main(a.workdir)
