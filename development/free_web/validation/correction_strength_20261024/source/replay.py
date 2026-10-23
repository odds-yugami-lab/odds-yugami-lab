"""Preregistered strength sweep; unchanged incumbent inputs and cap30 allocator."""
import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
import concurrent.futures,hashlib,json,math,sys,datetime
from pathlib import Path
import numpy as np,pandas as pd
sys.path.insert(0,'correction_ablation_20261024')
import replay as base
from rankwise import scores,probability_tables
from allocator import allocate
from replay2026 import aggregate,sha,save
R=Path('correction_strength_20261024');P=R/'public';A=R/'private_assets'
LEVELS=[0,.25,.5,.75,1]
def key(s):return f'{round(s*100):03d}'
def coefficients(y,s):
    a,b=base.params(y)
    return [(1-s)+s*a,s*b]
def one(t):
    y,r=t;code=r['race_code'];path=A/'predictions'/str(y)/(code+'.json')
    if path.exists():return {'year':y,'race_code':code,'sha256':sha(path)}
    assert set(r)<=set(['race_code','date','numbers','win','top3','odds','input_source'])
    oldpath=base.A/'predictions'/str(y)/(code+'.json');manifest=json.loads((base.P/'prediction_manifest.json').read_text())
    item=next(x for x in manifest['predictions'] if x['year']==y and x['race_code']==code)
    assert sha(oldpath)==item['sha256'];old=json.loads(oldpath.read_text())
    assert old['input_sha256']==hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest()
    op=Path('bias_20261020/public_cache/odds')/(code+'.json') if y==2026 else base.OLD/'cache2025'/(code+'_odds.json')
    assert sha(op)==old['odds_sha256'];sources=json.loads(op.read_text())['snapshots']
    assert all(x['status']=='final_postrace' for x in sources.values())
    odds=pd.DataFrame([x for s in sources.values() for x in s['rows']]);variants={}
    for strength in LEVELS:
        h,c,events=probability_tables(r,scores(r,'shared_ai_market',coefficients(y,strength)))
        if strength in [0,1]:
            x=old['baseline' if strength==0 else 'corrected'];lookup={(x.bet_type,x.kumiban):x.ai_probability for x in c.itertuples()}
            for ticket in x['tickets']:assert abs(ticket['ai_probability']-lookup[(ticket['bet_type'],ticket['kumiban'])])<1e-10
            obj=dict(x,reused_hash_verified=True)
        else:
            merged=c.merge(odds,on=['race_code','bet_type','kumiban'],validate='one_to_one');assert len(merged)==len(c)
            scale=float((merged.ai_probability*merged.decimal_odds).max()*10000)
            tickets,audit=allocate(merged,r['numbers'],events,expected_payout_scale=scale,time_limit=30.,mip_relative_gap=.01)
            obj={'tickets':tickets.to_dict('records'),'allocation_audit':audit,'stake_yen':int(tickets.stake.sum()),
                'unspent_yen':10000-int(tickets.stake.sum()),'ticket_count':len(tickets),'reused_hash_verified':False}
        obj.update(parameters=coefficients(y,strength),strength=strength,horse_probabilities=h.to_dict('records'))
        ts=obj['tickets'];total=sum(int(t['stake']) for t in ts)
        assert len(ts)<=30 and 0<total<=10000 and total==obj['stake_yen'] and obj['unspent_yen']==10000-total
        for t in ts:assert t['stake']==100*max(1,math.ceil(100/t['decimal_odds']-1e-12))
        variants[key(strength)]=obj
    save(path,{'test_only':True,'year':y,'race_code':code,'date':r['date'],'variants':variants,
       'horse_numbers':r['numbers'],'win_odds':r['odds'],'input_sha256':old['input_sha256'],
       'odds_sha256':old['odds_sha256'],'prior_prediction_sha256':sha(oldpath),'outcomes_passed_to_allocator':False})
    return {'year':y,'race_code':code,'sha256':sha(path)}
def predict():
    assert (P/'protocol_commit.json').exists();done=[];bad=[]
    tasks=[(y,r) for y in [2025,2026] for r in base.inputs(y)]
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
        fs={pool.submit(one,t):(t[0],t[1]['race_code']) for t in tasks}
        for f in concurrent.futures.as_completed(fs):
            try:done.append(f.result())
            except Exception as e:bad.append({'year':fs[f][0],'race_code':fs[f][1],'error':str(e)})
            if (len(done)+len(bad))%10==0:print('PREDICT',len(done),'failed',len(bad),flush=True)
    save(P/'prediction_manifest.json',{'test_only':True,'expected_races':222,'prepared_races':len(done),
       'new_allocations_expected':666,'reused_allocations_expected':444,'outcomes_passed_to_allocator':False,
       'predictions':sorted(done,key=lambda x:(x['year'],x['race_code'])),'failures':bad})
    print('SEALED',len(done),bad,flush=True)
def records():
    seal=json.loads((P/'prediction_seal_commit.json').read_text());assert sha(P/'prediction_manifest.json')==seal['manifest_sha256']
    m=json.loads((P/'prediction_manifest.json').read_text());out=[]
    for x in m['predictions']:
        path=A/'predictions'/str(x['year'])/(x['race_code']+'.json');assert sha(path)==x['sha256'];out.append(json.loads(path.read_text()))
    return out,m
def official(y,c):
    if y==2025:
        path=base.OLD/'cache2025'/(c+'_official.json')
        if not path.exists():return None
        o=json.loads(path.read_text());assert o['official_verified'];return o
    return next(x for x in json.loads(Path('bias_20261020/official_results.json').read_text())['races'] if x['race_code']==c)
def rows_for_year(year,rs):
    rows=[];horses=[];bad=[]
    for r in rs:
        if r['year']!=year:continue
        c=r['race_code'];o=official(year,c)
        if o is None:bad.append({'race_code':c,'reason':'Same pre-existing unresolved official result'});continue
        status={int(x['horse_number']):x['finish_status'] for x in o['finish_rows']}
        assert set(r['horse_numbers'])==set(status)-set(o.get('refunded_horse_numbers',[]))
        pop={num:i+1 for i,num in enumerate(sorted(r['horse_numbers'],key=lambda n:(r['win_odds'][r['horse_numbers'].index(n)],n)))}
        for k,v in r['variants'].items():
            pay=sum(int(o['payouts_per_100_yen'][t['bet_type']].get(t['kumiban'],0))*int(t['stake'])//100 for t in v['tickets'])
            rows.append({'year':year,'method':k,'race_code':c,'date':r['date'],'stake_yen':v['stake_yen'],'unspent_yen':v['unspent_yen'],
             'payout_yen':pay,'any_hit':pay>0,'ticket_count':v['ticket_count'],'predicted_hit_probability':v['allocation_audit']['probability_any_win'],
             'solver_gap':v['allocation_audit']['actual_mip_gap']})
            for h in v['horse_probabilities']:
                n=int(h['umaban']);s=status[n]
                horses.append({'race_code':c,'method':k,'popularity':pop[n],'win':h['win_probability'],'top3':h['top3_probability'],
                    'y_win':int(s=='1'),'y_top3':int(s in ['1','2','3'])})
    return rows,horses,bad
def metrics(horses,k):
    v=[x for x in horses if x['method']==k];out={}
    for head in ['win','top3']:
        q=np.clip([x[head] for x in v],1e-12,1-1e-12);y=np.asarray([x['y_'+head] for x in v]);out[head]={'brier':float(np.mean((q-y)**2)),'logloss':float(np.mean(-y*np.log(q)-(1-y)*np.log1p(-q)))}
    out['popularity_groups']={}
    for lo,hi in [(1,1),(2,3),(4,6),(7,18)]:
        v2=[x for x in v if lo<=x['popularity']<=hi]
        out['popularity_groups'][f'{lo}-{hi}']={'horses':len(v2),**{h:{'predicted':float(np.mean([x[h] for x in v2])),
           'observed':float(np.mean([x['y_'+h] for x in v2]))} for h in ['win','top3']}}
    return out
def select():
    rs,m=records();rows,horses,bad=rows_for_year(2025,rs)
    totals={key(s):aggregate([x for x in rows if x['method']==key(s)]) for s in LEVELS}
    # Rule preregistered: highest actual-stake ROI in2025; exact tie retains stronger/current correction.
    chosen=max(totals,key=lambda k:(totals[k]['recovery_percent'],int(k)))
    save(P/'selection2025.json',{'test_only':True,'selected_strength':int(chosen)/100,'selected_key':chosen,
       'selection_rule':'highest2025 actual-stake ROI; exact tie higher strength','selection_uses2026_results':False,
       'portfolio':totals,'horse_metrics':{key(s):metrics(horses,key(s)) for s in LEVELS},'exclusions':bad,
       '2025_previously_inspected':True,'not_new_independent_training_or_selection_dataset':True})
    save(A/'settlement_rows2025.json',rows);print('SELECT2025',chosen,totals,flush=True)
def finish():
    assert (P/'selection2025_commit.json').exists();rs,m=records();rows,horses,bad=rows_for_year(2026,rs)
    selection=json.loads((P/'selection2025.json').read_text());sel_seal=json.loads((P/'selection2025_commit.json').read_text());assert sha(P/'selection2025.json')==sel_seal['sha256']
    annual={2025:selection['portfolio'],2026:{key(s):aggregate([x for x in rows if x['method']==key(s)]) for s in LEVELS}}
    prior=json.loads((base.P/'comparison.json').read_text())
    for y,a in annual.items():
        for k,v in [('000','baseline'),('100','corrected')]:
            for f in ['races','stake_yen','payout_yen','hit_races']:
                assert a[k][f]==prior['annual'][str(y)]['portfolio'][v][f]
    allrows=json.loads((A/'settlement_rows2025.json').read_text())+rows
    out={'test_only':True,'strengths':LEVELS,'annual':annual,'selected_on2025':selection['selected_strength'],
       'selection_commit':sel_seal['commit_sha'],'2026_horse_metrics':{key(s):metrics(horses,key(s)) for s in LEVELS},
       'halves':{str(y):{half:{key(s):aggregate([x for x in allrows if x['year']==y and x['method']==key(s) and (x['date']<f'{y}-07-01')==early]) for s in LEVELS} for half,early in [('H1',True),('H2',False)]} for y in [2025,2026]},
       'prediction_failures':m['failures'],'2026_exclusions':bad,'same_2025_exclusions':selection['exclusions'],
       'original_endpoint_results_reproduced':True,'no_production_or_automation_changes':True,
       '2026_already_inspected_not_independent_holdout':True,'final_odds_and_final_starters_used':True,
       'future_feature_point_in_time_not_certified':True,'new_allocations':666,'reused_hash_verified_allocations':444}
    save(P/'comparison.json',out);save(P/'race_results.json',allrows);save(A/'horse_metrics_rows2026.json',horses)
    print('RESULT',json.dumps({'annual':annual,'selected':selection['selected_strength']}),flush=True)
if __name__=='__main__':{'predict':predict,'select':select,'finish':finish}[sys.argv[1]]()
