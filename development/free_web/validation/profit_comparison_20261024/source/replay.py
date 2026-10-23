"""2x2 EV filter vs net-profit objective; fixed correction50%, no outcome inputs."""
import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
import concurrent.futures,datetime,hashlib,importlib.util,json,math,sys
from pathlib import Path
import numpy as np,pandas as pd
spec=importlib.util.spec_from_file_location('strength_study','correction_strength_20261024/replay.py')
study=importlib.util.module_from_spec(spec);spec.loader.exec_module(study)
sys.path.insert(0,'profit_comparison_20261024')
from allocator_research import allocate
R=Path('profit_comparison_20261024');P=R/'public';A=R/'private_assets'
VARIANTS=['A_current','B_filter_gross','C_net_all','D_filter_net','E_delete_only']
def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def measure(tickets,events,scale,net):
    active={(t['bet_type'],t['kumiban']) for t in tickets}
    h=float(sum(e[0] for e in events if (e[1],e[2]) in active or (e[3],e[4]) in active))
    stake=sum(int(t['stake']) for t in tickets);gross=sum(t['stake']*t['ai_probability']*t['decimal_odds'] for t in tickets)
    economic=gross-stake if net else gross
    return {'stake_yen':stake,'unspent_yen':10000-stake,'ticket_count':len(tickets),'expected_payout_yen':gross,
      'expected_net_profit_yen':gross-stake,'probability_any_hit':h,'objective_value':.5*economic/scale+.5*h,
      'below_one_ev_tickets':sum(t['ai_probability']*t['decimal_odds']<1-1e-10 for t in tickets),
      'below_one_ev_stake_yen':sum(t['stake'] for t in tickets if t['ai_probability']*t['decimal_odds']<1-1e-10)}
def one(task):
    year,race,prior,prior_sha=task;code=race['race_code'];dest=A/'predictions'/str(year)/(code+'.json')
    if dest.exists():return {'year':year,'race_code':code,'sha256':sha(dest)}
    assert set(race)<=set(['race_code','date','numbers','win','top3','odds','input_source'])
    assert hashlib.sha256(json.dumps(race,sort_keys=True).encode()).hexdigest()==prior['input_sha256']
    h,c,events=study.probability_tables(race,study.scores(race,'shared_ai_market',study.coefficients(year,.5)))
    op=Path('bias_20261020/public_cache/odds')/(code+'.json') if year==2026 else study.base.OLD/'cache2025'/(code+'_odds.json')
    assert sha(op)==prior['odds_sha256'];snap=json.loads(op.read_text())['snapshots'];assert all(v['status']=='final_postrace' for v in snap.values())
    odds=pd.DataFrame([x for v in snap.values() for x in v['rows']]);combined=c.merge(odds,on=['race_code','bet_type','kumiban'],validate='one_to_one');assert len(combined)==len(c)
    scale=float((combined.ai_probability*combined.decimal_odds).max()*10000)
    lookup={(x.bet_type,x.kumiban):x.ai_probability for x in c.itertuples()};old=prior['variants']['050']
    assert abs(scale-old['allocation_audit']['expected_payout_scale_explicit'])<1e-7
    for t in old['tickets']:assert abs(t['ai_probability']-lookup[(t['bet_type'],t['kumiban'])])<1e-10
    variants={'A_current':{'tickets':old['tickets'],'metrics':measure(old['tickets'],events,scale,False),'allocation_audit':old['allocation_audit'],'reused_hash_verified':True}}
    errors=[]
    for name,net,flt in [('B_filter_gross',False,True),('C_net_all',True,False),('D_filter_net',True,True)]:
        try:
            t,a=allocate(combined,race['numbers'],events,expected_payout_scale=scale,time_limit=30.,mip_relative_gap=.01,net_profit=net,nonnegative_only=flt)
            ts=t.to_dict('records');m=measure(ts,events,scale,net)
            assert abs(m['objective_value']-a['objective_value'])<1e-9
            assert 1<=len(ts)<=30 and 0<m['stake_yen']<=10000
            if flt:assert m['below_one_ev_tickets']==0
            variants[name]={'tickets':ts,'metrics':m,'allocation_audit':a,'reused_hash_verified':False}
        except Exception as e:errors.append({'variant':name,'reason':str(e)})
    ts=[t for t in old['tickets'] if t['ai_probability']*t['decimal_odds']>=1-1e-10]
    variants['E_delete_only']={'tickets':ts,'metrics':measure(ts,events,scale,False),'allocation_audit':None,'reused_hash_verified':True,'reallocated':False}
    for v in variants.values():
        for t in v['tickets']:assert t['stake']==100*max(1,math.ceil(100/t['decimal_odds']-1e-12))
    record={'test_only':True,'year':year,'race_code':code,'date':race['date'],'variants':variants,'failures':errors,
       'prior_prediction_sha256':prior_sha,'input_sha256':prior['input_sha256'],'odds_sha256':prior['odds_sha256'],
       'correction_strength':.5,'expected_payout_scale_all_combinations':scale,'outcome_fields_passed_to_allocator':False}
    save(dest,record);return {'year':year,'race_code':code,'sha256':sha(dest),'failures':errors}
def predict():
    assert (P/'protocol_commit.json').exists();rs,_=study.records();source={(r['year'],r['race_code']):r for r in rs}
    manifest=json.loads((study.P/'prediction_manifest.json').read_text());hashes={(x['year'],x['race_code']):x['sha256'] for x in manifest['predictions']}
    tasks=[(y,r,source[y,r['race_code']],hashes[y,r['race_code']]) for y in [2025,2026] for r in study.base.inputs(y)]
    done=[];bad=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
        fs={pool.submit(one,t):(t[0],t[1]['race_code']) for t in tasks}
        for f in concurrent.futures.as_completed(fs):
            try:done.append(f.result())
            except Exception as e:bad.append({'year':fs[f][0],'race_code':fs[f][1],'error':str(e)})
            if (len(done)+len(bad))%10==0:print('PREDICT',len(done),'failed',len(bad),flush=True)
    save(P/'prediction_manifest.json',{'test_only':True,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'expected_races':222,'prepared_races':len(done),'predictions':sorted(done,key=lambda x:(x['year'],x['race_code'])),'failures':bad,
      'expected_new_allocations':666,'original_allocations_hash_verified':222,'outcomes_used_in_allocation':False})
    print('SEALED',len(done),'failed',bad,flush=True)
def records():
    seal=json.loads((P/'prediction_seal_commit.json').read_text());assert sha(P/'prediction_manifest.json')==seal['manifest_sha256']
    m=json.loads((P/'prediction_manifest.json').read_text());rs=[]
    for x in m['predictions']:
        p=A/'predictions'/str(x['year'])/(x['race_code']+'.json');assert sha(p)==x['sha256'];rs.append(json.loads(p.read_text()))
    return rs,m
def agg(rows):
    if not rows:return {'races':0}
    stake=sum(x['stake_yen'] for x in rows);pay=sum(x['payout_yen'] for x in rows)
    return {'races':len(rows),'stake_yen':stake,'payout_yen':pay,'profit_yen':pay-stake,'recovery_percent':100*pay/stake if stake else None,
      'unspent_yen':len(rows)*10000-stake,'hit_races':sum(x['any_hit'] for x in rows),'hit_rate':float(np.mean([x['any_hit'] for x in rows])),
      'mean_ticket_count':float(np.mean([x['ticket_count'] for x in rows])),'min_ticket_count':min(x['ticket_count'] for x in rows),'max_ticket_count':max(x['ticket_count'] for x in rows),
      'mean_stake_yen':stake/len(rows),'bad_tickets':sum(x['below_one_ev_tickets'] for x in rows),'bad_stake_yen':sum(x['below_one_ev_stake_yen'] for x in rows),
      'predicted_hit_probability_mean':float(np.mean([x['probability_any_hit'] for x in rows])),'expected_profit_yen':sum(x['expected_net_profit_yen'] for x in rows)}
def settle():
    rs,m=records();rows=[];errors=[];exclusions=[]
    for r in rs:
        y=r['year'];code=r['race_code'];o=study.official(y,code)
        if o is None:exclusions.append({'year':y,'race_code':code,'reason':'Same pre-existing unresolved official result'});continue
        if r['failures']:errors.append({'year':y,'race_code':code,'failures':r['failures']});continue
        for name,v in r['variants'].items():
            pay=sum(int(o['payouts_per_100_yen'][t['bet_type']].get(t['kumiban'],0))*int(t['stake'])//100 for t in v['tickets'])
            row=dict(v['metrics'],year=y,race_code=code,date=r['date'],variant=name,payout_yen=pay,any_hit=pay>0)
            a=v['allocation_audit'];row['solver_gap']=a['actual_mip_gap'] if a else None;rows.append(row)
    annual={str(y):{v:agg([x for x in rows if x['year']==y and x['variant']==v]) for v in VARIANTS} for y in [2025,2026]}
    old=json.loads((study.P/'comparison.json').read_text());audit=json.loads(Path('expected_value_audit_20261024/public/comparison.json').read_text())
    for y in [2025,2026]:
        if annual[str(y)]['A_current']['races'] in [117,103]:
            a=annual[str(y)]['A_current'];b=old['annual'][str(y)]['050'];assert a['stake_yen']==b['stake_yen'] and a['payout_yen']==b['payout_yen']
            a=annual[str(y)]['E_delete_only'];b=audit['annual'][str(y)];assert a['stake_yen']==b['retained_stake_yen_if_delete_bad_no_reallocation'] and a['payout_yen']==b['retained_actual_payout_yen_if_delete_bad_no_reallocation']
    report={'test_only':True,'annual':annual,'variant_descriptions':{'A_current':'Gross E50+H50,all tickets,prior sealed original','B_filter_gross':'Gross E50+H50,EV>=1 filter,reoptimize','C_net_all':'Net E50+H50,all tickets,reoptimize','D_filter_net':'Net E50+H50,EV>=1 filter,reoptimize','E_delete_only':'Delete EV<1 fromA,no reallocation,prior reference'},
      'correction_strength':.5,'max_tickets':30,'budget_limit_yen':10000,'exact_minimum_stakes':True,
      'normalizer_frozen_same_all_combination_gross_scale_across_variants':True,
      'prediction_failures':m['failures'],'allocation_failures':errors,'official_exclusions':exclusions,
      'halves':{str(y):{half:{v:agg([x for x in rows if x['year']==y and x['variant']==v and (x['date']<f'{y}-07-01')==early]) for v in VARIANTS} for half,early in [('H1',True),('H2',False)]} for y in [2025,2026]},
      'no_production_or_automation_change':True,'final_odds_used':True,'previously_inspected_periods_not_new_holdout':True,
      'all_fixed_thresholds_and_candidates':True,'source_feature_point_in_time_not_fully_certified':True,
      'prediction_seal_commit':json.loads((P/'prediction_seal_commit.json').read_text())['commit_sha']}
    save(P/'comparison.json',report);save(P/'race_results.json',rows)
    print('RESULT',json.dumps({'annual':annual,'errors':errors,'exclusions':exclusions}),flush=True)
if __name__=='__main__':{'predict':predict,'settle':settle}[sys.argv[1]]()
