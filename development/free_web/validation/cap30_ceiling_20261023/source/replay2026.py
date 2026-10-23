"""Outcome-isolated prediction phase, sealed prediction files, then settlement.

Retrospective 2026 final-odds comparison of a reconstruction, not a live record.
Both models retain their previously frozen2025 market correction coefficients;
only the allocation rule changes relative to the 79.21/88.28 comparison.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
import argparse,concurrent.futures,datetime as dt,hashlib,json,math,sys
from pathlib import Path
import numpy as np,pandas as pd
sys.path.insert(0,'rule_restoration_20261022');sys.path.insert(0,'decomposition_20261021')
from allocator import allocate
from rankwise import scores,probability_tables
ROOT=Path('cap30_ceiling_20261023');PRIVATE=ROOT/'private_assets';PUBLIC=ROOT/'public'
METHODS=['incumbent','candidate']

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write_new(path,content):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:f.write(content)
def save(path,obj):write_new(path,json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def prediction_input(source):
    return {key:source[key] for key in ['race_code','date','numbers','win','top3','odds','input_source']}

def predict_one(task):
    method,race,parameters,protocol_hash=task;code=race['race_code']
    path=PRIVATE/'predictions'/method/(code+'.json')
    if path.exists():
        prior=json.loads(path.read_text())
        if prior['protocol_sha256']!=protocol_hash:raise ValueError('Existing prediction uses different protocol')
        return {'method':method,'race_code':code,'sha256':sha(path),'status':'prepared'}
    # Full race ordering/outcome labels are not carried into this function.
    assert not any(k.startswith('target_') or k in {'order','payouts_per_100_yen','finish_status'} for k in race)
    stage=scores(race,'shared_ai_market',parameters)
    _,combos,scenarios=probability_tables(race,stage)
    source=json.loads((Path('bias_20261020/public_cache/odds')/(code+'.json')).read_text())['snapshots']
    assert all(v['status']=='final_postrace' for v in source.values())
    odds=pd.DataFrame([r for snapshot in source.values() for r in snapshot['rows']])
    merged=combos.merge(odds,on=['race_code','bet_type','kumiban'],how='outer',indicator=True,validate='one_to_one')
    assert merged._merge.eq('both').all();merged=merged.drop(columns='_merge')
    scale=float((merged.ai_probability*merged.decimal_odds).max()*10000)
    tickets,audit=allocate(merged,race['numbers'],scenarios,expected_payout_scale=scale,time_limit=30.,mip_relative_gap=.01)
    rows=tickets.to_dict('records')
    assert len(rows)<=30 and 0<sum(int(r['stake']) for r in rows)<=10000
    for r in rows:
        assert r['stake']==100*max(1,math.ceil(100/r['decimal_odds']-1e-12))
    record={'record_type':'retrospective_prediction','test_only':True,'is_live_prediction':False,
        'method':method,'race_code':code,'date':race['date'],'input_source':race['input_source'],
        'prepared_at':dt.datetime.now(dt.timezone.utc).isoformat(),'protocol_sha256':protocol_hash,
        'input_sha256':hashlib.sha256(json.dumps(race,sort_keys=True).encode()).hexdigest(),
        'market_correction_parameters':parameters,'odds_status':'final_postrace',
        'source_odds_sha256':sha(Path('bias_20261020/public_cache/odds')/(code+'.json')),
        'stake_yen':int(tickets.stake.sum()),'unspent_yen':int(10000-tickets.stake.sum()),'ticket_count':len(rows),'tickets':rows,'allocation_audit':audit,
        'outcome_labels_passed_to_allocator':False,'settled':False}
    save(path,record)
    return {'method':method,'race_code':code,'sha256':sha(path),'status':'prepared'}

def predict_all():
    protocol=json.loads((PUBLIC/'protocol.json').read_text());assert (PUBLIC/'protocol_commit.json').exists()
    raw=Path('base_review_20261021/private_assets/races_2026.json')
    assert sha(raw)==protocol['probability_source_sha256']
    assert sha('cap30_ceiling_20261023/allocator.py')==protocol['allocation_source_sha256']
    sources=json.loads(raw.read_text());protocol_hash=sha(PUBLIC/'protocol.json');tasks=[]
    for method,key in [('incumbent','incumbent_same_input'),('candidate','candidate')]:
        assert len(sources[key])==103
        for r in sources[key]:tasks.append((method,prediction_input(r),protocol['parameters'][method],protocol_hash))
    results=[];errors=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(predict_one,t):(t[0],t[1]['race_code']) for t in tasks}
        for future in concurrent.futures.as_completed(futures):
            try:results.append(future.result())
            except Exception as e:
                errors.append({'method':futures[future][0],'race_code':futures[future][1],
                    'stage':'allocation','error_type':type(e).__name__,'error':str(e)})
            if (len(results)+len(errors))%20==0:print('PROGRESS',len(results),'prepared',len(errors),'errors',flush=True)
    manifest={'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'test_only':True,
        'protocol_sha256':protocol_hash,'expected_cases':206,'prepared_cases':len(results),
        'complete':len(results)==206 and not errors,'outcomes_loaded_in_prediction_phase':False,
        'predictions':sorted(results,key=lambda r:(r['method'],r['race_code'])),'failures':errors}
    save(PUBLIC/'prediction_manifest.json',manifest)
    print('PREDICTIONS_SEALED',manifest['prepared_cases'],'of206; failures',len(errors),flush=True)

def verify_prediction(path,expected_sha):
    if sha(path)!=expected_sha:raise ValueError('Prediction content changed after seal')
    return json.loads(Path(path).read_text())

def aggregate(rows):
    if not rows:return {'races':0}
    stake=sum(r['stake_yen'] for r in rows);payout=sum(r['payout_yen'] for r in rows)
    return {'races':len(rows),'stake_yen':stake,'payout_yen':payout,'profit_yen':payout-stake,
        'budget_limit_total_yen':len(rows)*10000,'unspent_yen':len(rows)*10000-stake,
        'recovery_percent':100*payout/stake,'hit_races':sum(r['any_hit'] for r in rows),
        'hit_rate':float(np.mean([r['any_hit'] for r in rows])),
        'ticket_count_min':min(r['ticket_count'] for r in rows),'ticket_count_max':max(r['ticket_count'] for r in rows),
        'ticket_count_mean':float(np.mean([r['ticket_count'] for r in rows])),
        'races_with_25_to_30_tickets':sum(25<=r['ticket_count']<=30 for r in rows),
        'model_mean_hit_probability':float(np.mean([r['predicted_hit_probability'] for r in rows])),
        'zero_gap_solutions':sum(r['solver_gap']<1e-9 for r in rows)}

def settle_all():
    # A GitHub commit of the manifest must exist before outcome loading.
    seal=json.loads((PUBLIC/'prediction_seal_commit.json').read_text())
    assert sha(PUBLIC/'prediction_manifest.json')==seal['manifest_sha256']
    manifest=json.loads((PUBLIC/'prediction_manifest.json').read_text())
    # Every available prediction is authenticated before reading official results.
    prepared=[]
    for item in manifest['predictions']:
        path=PRIVATE/'predictions'/item['method']/(item['race_code']+'.json')
        prepared.append(verify_prediction(path,item['sha256']))
    officials={r['race_code']:r for r in json.loads(Path('bias_20261020/official_results.json').read_text())['races']}
    rows=[]
    for record in prepared:
        official=officials[record['race_code']];settled=[]
        for ticket in record['tickets']:
            payout=int(official['payouts_per_100_yen'][ticket['bet_type']].get(ticket['kumiban'],0))*int(ticket['stake'])//100
            settled.append(dict(ticket,payout_yen=payout))
        row={'race_code':record['race_code'],'date':record['date'],'race_name':official['name'],'method':record['method'],
            'input_source':record['input_source'],'stake_yen':record['stake_yen'],'unspent_yen':record['unspent_yen'],'ticket_count':len(settled),
            'payout_yen':sum(r['payout_yen'] for r in settled),'any_hit':any(r['payout_yen']>0 for r in settled),
            'predicted_hit_probability':record['allocation_audit']['probability_any_win'],
            'solver_gap':record['allocation_audit']['actual_mip_gap'],'tickets':settled}
        save(PRIVATE/'settlements'/row['method']/(row['race_code']+'.json'),row);rows.append(row)
    by={m:sorted([r for r in rows if r['method']==m],key=lambda r:r['race_code']) for m in METHODS}
    common=set(r['race_code'] for r in by['incumbent'])&set(r['race_code'] for r in by['candidate'])
    paired={m:[r for r in v if r['race_code'] in common] for m,v in by.items()}
    differences=[]
    old={r['race_code']:r for r in paired['incumbent']}
    for r in paired['candidate']:
        prior=old[r['race_code']]
        differences.append({'race_code':r['race_code'],'date':r['date'],'race_name':r['race_name'],
            'incumbent_payout_yen':prior['payout_yen'],'candidate_payout_yen':r['payout_yen'],
            'difference_yen':r['payout_yen']-prior['payout_yen']})
    differences.sort(key=lambda r:r['difference_yen'],reverse=True)
    bootstrap=None
    if common:
        values=np.asarray([r['difference_yen'] for r in differences]);rng=np.random.default_rng(20261022)
        means=values[rng.integers(0,len(values),size=(10000,len(values)))].mean(axis=1)
        bootstrap={'paired_races':len(common),'mean_payout_difference_yen_per_race':float(values.mean()),
            'bootstrap95CI_yen_per_race':np.quantile(means,[.025,.975]).tolist()}
    report={'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'test_only':True,
        'status':'all103_completed' if manifest['complete'] else 'incomplete_report_failures_explicitly',
        'allocation_rule':'cap30_budget_ceiling_E50_v1_20261023','max_tickets':30,
        'original_policy_exactly_verified':False,'same_model_probabilities_as_prior_79_21_88_28':True,
        'probability_method':'same prior2025-frozen market correction for each model; no extra popularity boost',
        'prediction_manifest_commit':seal['commit_sha'],'sealed_prediction_files_verified':len(prepared),
        'aggregate_all_prepared':{m:aggregate(v) for m,v in by.items()},
        'common_races':len(common),'aggregate_common_cases':{m:aggregate(v) for m,v in paired.items()},
        'halves_common_cases':{half:{m:aggregate([r for r in v if (r['date']<'2026-07-01')==early]) for m,v in paired.items()} for half,early in [('H1',True),('H2',False)]},
        'archive_only_common_cases':{m:aggregate([r for r in v if r['input_source']=='archive']) for m,v in paired.items()},
        'failures':manifest['failures'],'payout_difference_bootstrap':bootstrap,
        'better_cases':sum(r['difference_yen']>0 for r in differences),'worse_cases':sum(r['difference_yen']<0 for r in differences),
        'same_payout_cases':sum(r['difference_yen']==0 for r in differences),
        'payout_difference_contributors':differences,
        'final_odds_and_final_starters_used':True,'2026_previously_inspected':True,
        'original_source_point_in_time_certified':False,'production_or_automations_changed':False,
        'no_2026_parameter_tuning':True,'no_original_predictions_overwritten':True,'2025_replay_performed':False}
    save(PUBLIC/'comparison.json',report)
    compact=[{k:v for k,v in r.items() if k!='tickets'} for r in rows]
    save(PUBLIC/'race_results.json',compact)
    print('SETTLED',json.dumps({'status':report['status'],'common':len(common),'aggregate':report['aggregate_common_cases'],'failures':report['failures']},ensure_ascii=False),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['predict','settle']);args=parser.parse_args()
    predict_all() if args.phase=='predict' else settle_all()
