"""119 complete2025 graded races; parameters frozen from2024 before settlement."""
import concurrent.futures,datetime as dt,hashlib,json,math,sys
from pathlib import Path
import numpy as np,pandas as pd
from allocator import allocate
from replay2026 import save,sha,aggregate,verify_prediction
sys.path.insert(0,'decomposition_20261021');from rankwise import scores,probability_tables
sys.path.insert(0,'correction_20261021/runtime')
from source_bundle import download
from odds import parse
from official_results import fetch_for_race
ROOT=Path('cap30_ceiling_20261023');PRIVATE=ROOT/'private_assets';PUBLIC=ROOT/'public'
CACHE=ROOT/'cache2025';CACHE.mkdir(exist_ok=True)

def collect(code):
    path=CACHE/(code+'_odds.json')
    if path.exists():return {'race_code':code,'status':'cached'}
    market=json.loads((Path('correction_20261021/cache/market')/(code+'.json')).read_text())
    numbers=[r['umaban'] for r in market['runners']];snapshots={}
    for kind,short in [('umaren','ur'),('sanrenpuku','sf')]:
        url='https://sports.yahoo.co.jp/keiba/race/odds/'+short+'/'+code[2:4]+code[8:]+'?ninki=0'
        page,stamp,digest=download(url);obj=parse(page,code,kind,numbers)
        if obj['status']!='final_postrace':raise ValueError('Expected final historical odds')
        obj.update(source_url=url,retrieved_at=stamp,page_sha256=digest);snapshots[kind]=obj
    save(path,{'race_code':code,'snapshots':snapshots})
    return {'race_code':code,'status':'downloaded'}

def collect_all():
    fixed=json.loads(Path('correction_20261021/private_assets/correction_coefficients.json').read_text())
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures={pool.submit(collect,c):c for c in fixed['fit_race_codes']}
        for f in concurrent.futures.as_completed(futures):
            try:results.append(f.result())
            except Exception as e:results.append({'race_code':futures[f],'status':'failed','reason':str(e)})
            if len(results)%20==0:print('ODDS2025',len(results),flush=True)
    save(PUBLIC/'odds_collection2025.json',results)
    print('ODDS_COMPLETE',len(results),'failures',sum(r['status']=='failed' for r in results),flush=True)

def one(task):
    method,race,params,fit_hash=task;code=race['race_code'];path=PRIVATE/'predictions2025'/method/(code+'.json')
    if path.exists():return {'method':method,'race_code':code,'sha256':sha(path)}
    assert not any(k in race for k in ['order','target_win','target_top3'])
    stage=scores(race,'shared_ai_market',params);_,combos,scenarios=probability_tables(race,stage)
    sources=json.loads((CACHE/(code+'_odds.json')).read_text())['snapshots']
    odds=pd.DataFrame([r for s in sources.values() for r in s['rows']])
    merged=combos.merge(odds,on=['race_code','bet_type','kumiban'],validate='one_to_one');assert len(merged)==len(combos)
    scale=float((merged.ai_probability*merged.decimal_odds).max()*10000)
    tickets,audit=allocate(merged,race['numbers'],scenarios,expected_payout_scale=scale,time_limit=30.,mip_relative_gap=.01)
    record={'test_only':True,'is_live_prediction':False,'method':method,'race_code':code,'date':race['date'],
        'fit2024_sha256':fit_hash,'prepared_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'stake_yen':int(tickets.stake.sum()),'unspent_yen':10000-int(tickets.stake.sum()),
        'ticket_count':len(tickets),'allocation_audit':audit,'tickets':tickets.to_dict('records'),
        'odds_status':'final_postrace','2025_results_used_to_fit':False,'result_labels_passed_to_allocator':False}
    save(path,record);return {'method':method,'race_code':code,'sha256':sha(path)}

def predict_all():
    assert (PUBLIC/'fit2024_commit.json').exists()
    fitted=json.loads((PUBLIC/'fit2024_for2025.json').read_text());inputs=json.loads((PRIVATE/'forecast_inputs2025.json').read_text())
    results=[];errors=[];fit_hash=sha(PUBLIC/'fit2024_for2025.json')
    tasks=[(m,r,fitted['parameters'][m],fit_hash) for m,values in inputs.items() for r in values]
    with concurrent.futures.ProcessPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(one,t):(t[0],t[1]['race_code']) for t in tasks}
        for f in concurrent.futures.as_completed(futures):
            try:results.append(f.result())
            except Exception as e:errors.append({'method':futures[f][0],'race_code':futures[f][1],'reason':str(e)})
            if (len(results)+len(errors))%20==0:print('PREDICT2025',len(results),'errors',len(errors),flush=True)
    save(PUBLIC/'prediction_manifest2025.json',{'test_only':True,'prepared_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'expected_cases':238,'predictions':sorted(results,key=lambda r:(r['method'],r['race_code'])),
        'failures':errors,'result_labels_loaded':False,'fit2024_sha256':fit_hash})

def official(code):
    path=CACHE/(code+'_official.json')
    if path.exists():return json.loads(path.read_text())
    obj=fetch_for_race(code);assert obj['official_verified'];save(path,obj);return obj

def settle_all():
    seal=json.loads((PUBLIC/'prediction_seal2025_commit.json').read_text())
    assert sha(PUBLIC/'prediction_manifest2025.json')==seal['manifest_sha256']
    manifest=json.loads((PUBLIC/'prediction_manifest2025.json').read_text());records=[]
    for p in manifest['predictions']:records.append(verify_prediction(PRIVATE/'predictions2025'/p['method']/(p['race_code']+'.json'),p['sha256']))
    codes=sorted({r['race_code'] for r in records});payouts={};errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures={pool.submit(official,c):c for c in codes}
        for f in concurrent.futures.as_completed(futures):
            try:payouts[futures[f]]=f.result()
            except Exception as e:errors.append({'race_code':futures[f],'stage':'official_settlement','reason':str(e)})
    rows=[]
    for r in records:
        if r['race_code'] not in payouts:continue
        o=payouts[r['race_code']];pay=sum(o['payouts_per_100_yen'][x['bet_type']].get(x['kumiban'],0)*int(x['stake'])//100 for x in r['tickets'])
        rows.append({'method':r['method'],'race_code':r['race_code'],'date':r['date'],'stake_yen':r['stake_yen'],
            'unspent_yen':r['unspent_yen'],'payout_yen':pay,'any_hit':pay>0,'ticket_count':r['ticket_count'],
            'predicted_hit_probability':r['allocation_audit']['probability_any_win'],'solver_gap':r['allocation_audit']['actual_mip_gap']})
    by={m:[r for r in rows if r['method']==m] for m in ['incumbent','candidate']}
    common=set(r['race_code'] for r in by['incumbent'])&set(r['race_code'] for r in by['candidate'])
    report={'test_only':True,'status':'completed119' if len(common)==119 else 'incomplete_with_explicit_exclusions',
        'aggregate_common':{m:aggregate([r for r in v if r['race_code'] in common]) for m,v in by.items()},
        'halves':{half:{m:aggregate([r for r in v if r['race_code'] in common and (r['date']<'2025-07-01')==early]) for m,v in by.items()} for half,early in [('H1',True),('H2',False)]},
        'prediction_failures':manifest['failures'],'settlement_failures':errors,'common_races':len(common),
        '2025_results_used_to_fit':False,'prior_family_selection_used2025':True,
        'seal_commit':seal['commit_sha'],'official_results_verified':len(payouts),
        'coverage':'119 complete races across2025;11 existing data/completeness exclusions from130 graded archive identities',
        'production_or_automations_changed':False,'original_rule_equivalence_unverified':True}
    save(PUBLIC/'comparison2025.json',report);save(PUBLIC/'race_results2025.json',rows)
    print('2025_RESULT',json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':
    {'odds':collect_all,'predict':predict_all,'settle':settle_all}[sys.argv[1]]()
