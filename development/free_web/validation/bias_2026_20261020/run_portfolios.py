from runtime_paths import ROOT, MODULES, MODEL, HISTORY, HISTORY_DIR, BUNDLE, ASSETS
"""Retrospective 2026 frozen-current-rule bias audit. No live records written."""
import os
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
from pathlib import Path
import concurrent.futures,datetime as dt,hashlib,json,sys,time,traceback
import pandas as pd
ROOT=ROOT;DEST=ROOT/'portfolio_results';DEST.mkdir(parents=True,exist_ok=True)
MODULES=MODULES;sys.path.insert(0,str(MODULES))
from corrected_v2_core import generate_combinations
from balanced_A_v3 import allocate_balanced

def run_one(data):
    official,horse_rows=data
    code=official['race_code'];out=DEST/(code+'.json')
    if out.exists():return json.loads(out.read_text())
    odds_path=ROOT/'public_cache/odds'/(code+'.json')
    started=time.monotonic()
    while not odds_path.exists():
        if time.monotonic()-started>600:raise RuntimeError('Historical final odds unavailable: '+code)
        time.sleep(1)
    sources=json.loads(odds_path.read_text())['snapshots']
    h=pd.DataFrame(horse_rows).rename(columns={'horse_id':'ketto_toroku_bango'})
    rows=[r for s in sources.values() for r in s['rows']]
    combo=generate_combinations(h).merge(pd.DataFrame(rows),on=['race_code','bet_type','kumiban'],
        how='outer',validate='one_to_one',indicator=True)
    if not combo._merge.eq('both').all():raise ValueError('Missing/extra final odds')
    combo=combo.drop(columns='_merge')
    mismatches=[]
    for kind,values in official['payouts_per_100_yen'].items():
        for key,yen in values.items():
            price=float(combo.loc[(combo.bet_type==kind)&(combo.kumiban==key),'decimal_odds'].iloc[0])
            if abs(price*100-yen)>1e-5:
                mismatches.append({'bet_type':kind,'kumiban':key,'odds_times_100':price*100,'official_per100':yen})
    begin=time.monotonic()
    tickets,audit=allocate_balanced(combo,h) # frozen current defaults, no re-tuning
    result_rows=[]
    for t in tickets.to_dict('records'):
        got=official['payouts_per_100_yen'][t['bet_type']].get(t['kumiban'],0)*int(t['stake'])//100
        t.update(stake=int(t['stake']),payout_yen=int(got))
        result_rows.append(t)
    report={'race_code':code,'race_name':official['name'],'date':official['date'],'grade':official['grade'],
        'record_type':'retrospective_final_odds_bias_audit','test_only':True,'live_performance':False,
        'allocation_rule':'balanced_A_v3','rule_sha256':hashlib.sha256((MODULES/'balanced_A_v3.py').read_bytes()).hexdigest(),
        'runners':len(h),'all_combinations':len(combo),'ticket_count':len(tickets),
        'stake_yen':int(tickets.stake.sum()),'payout_yen':sum(t['payout_yen'] for t in result_rows),
        'any_hit':any(t['payout_yen']>0 for t in result_rows),
        'predicted_hit_probability':audit['probability_any_win'],
        'predicted_expected_payout_yen':audit['model_expected_payout_yen_full_actual_odds'],
        'allocation_seconds':time.monotonic()-begin,'input_sources':sorted(set(h.source)),
        'official_final_odds_payout_mismatches':mismatches,
        'odds_sources':{k:{n:s[n] for n in ['source_url','retrieved_at','page_sha256','source_updated_at_text']}
                        for k,s in sources.items()},
        'result_source_url':official['source_url'],'audit':audit,'tickets':result_rows}
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    return report

if __name__=='__main__':
    official=json.loads((ROOT/'official_results.json').read_text())['races']
    predictions=json.loads((ROOT/'horse_predictions_all.json').read_text())
    tasks=[(o,[h for h in predictions if h['race_code']==o['race_code']]) for o in official]
    completed=[];failures=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(run_one,t):t[0]['race_code'] for t in tasks}
        for f in concurrent.futures.as_completed(futures):
            try:
                r=f.result();completed.append(r)
                print('PORTFOLIO',len(completed),r['race_code'],r['ticket_count'],r['payout_yen'],round(r.get('allocation_seconds',0),2),flush=True)
            except Exception as e:
                failure={'race_code':futures[f],'error':str(e),'traceback':traceback.format_exc()[-700:]}
                failures.append(failure);print('PORTFOLIO_FAILED',json.dumps(failure),flush=True)
    (ROOT/'portfolio_run_status.json').write_text(json.dumps({'completed':len(completed),'failures':failures},ensure_ascii=False,indent=2)+'\n')
    print('PORTFOLIOS_DONE',len(completed),'failed',len(failures),flush=True)
