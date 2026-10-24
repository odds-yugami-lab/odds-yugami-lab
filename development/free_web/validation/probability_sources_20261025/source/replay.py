"""AI-only vs market-only vs fixed50% mix, same filtered net-E50+H50 rule."""
import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
import concurrent.futures,datetime,hashlib,importlib.util,json,math,sys
from pathlib import Path
import numpy as np,pandas as pd
spec=importlib.util.spec_from_file_location('profit_study','profit_comparison_20261024/replay.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
study=old.study
from allocator_research import allocate
R=Path('probability_sources_20261025');P=R/'public';A=R/'private_assets'
METHODS=['ai_only','market_only','ai_market50']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
def stage_scores(race,year,method):
    if method=='ai_only':return study.scores(race,'shared_ai_market',[1.,0.])
    if method=='market_only':return study.scores(race,'market_PL',[])
    return study.scores(race,'shared_ai_market',study.coefficients(year,.5))
def one(task):
    year,race,prior,prior_sha=task;code=race['race_code'];dest=A/'predictions'/str(year)/(code+'.json')
    if dest.exists():return {'year':year,'race_code':code,'sha256':sha(dest)}
    assert set(race)<=set(['race_code','date','numbers','win','top3','odds','input_source'])
    assert hashlib.sha256(json.dumps(race,sort_keys=True).encode()).hexdigest()==prior['input_sha256']
    op=Path('bias_20261020/public_cache/odds')/(code+'.json') if year==2026 else study.base.OLD/'cache2025'/(code+'_odds.json')
    assert sha(op)==prior['odds_sha256'];ss=json.loads(op.read_text())['snapshots'];assert all(v['status']=='final_postrace' for v in ss.values())
    odds=pd.DataFrame([x for v in ss.values() for x in v['rows']]);variants={};errors=[]
    for method in METHODS:
        h,c,events=study.probability_tables(race,stage_scores(race,year,method))
        merged=c.merge(odds,on=['race_code','bet_type','kumiban'],validate='one_to_one');assert len(merged)==len(c)
        scale=float((merged.ai_probability*merged.decimal_odds).max()*10000)
        eligible=int((merged.ai_probability*merged.decimal_odds>=1-1e-10).sum())
        if not eligible:
            # Existing optimization requires at least one ticket. Do not silently relax it.
            errors.append({'method':method,'stage':'eligibility','reason':'No nonnegative-EV ticket; min1 policy infeasible'})
            continue
        try:
            if method=='ai_market50':
                v=prior['variants']['D_filter_net'];ts=v['tickets'];audit=v['allocation_audit'];lookup={(x.bet_type,x.kumiban):x.ai_probability for x in c.itertuples()}
                for t in ts:assert abs(t['ai_probability']-lookup[(t['bet_type'],t['kumiban'])])<1e-10
                assert abs(scale-prior['expected_payout_scale_all_combinations'])<1e-7
                reused=True
            else:
                t,audit=allocate(merged,race['numbers'],events,expected_payout_scale=scale,time_limit=30.,mip_relative_gap=.01,net_profit=True,nonnegative_only=True)
                ts=t.to_dict('records');reused=False
            metrics=old.measure(ts,events,scale,True)
            assert metrics['below_one_ev_tickets']==0 and 1<=len(ts)<=30 and 0<metrics['stake_yen']<=10000
            assert abs(metrics['objective_value']-audit['objective_value'])<1e-9
            for t in ts:assert t['stake']==100*max(1,math.ceil(100/t['decimal_odds']-1e-12))
            variants[method]={'tickets':ts,'metrics':metrics,'allocation_audit':audit,'eligible_combinations':eligible,
                'scale_from_all_combinations':scale,'horse_probabilities':h.to_dict('records'),'reused_hash_verified':reused}
        except Exception as e:errors.append({'method':method,'stage':'allocation','reason':str(e)})
    save(dest,{'test_only':True,'year':year,'race_code':code,'date':race['date'],'variants':variants,'failures':errors,
       'horse_numbers':race['numbers'],'single_win_odds':race['odds'],'input_sha256':prior['input_sha256'],
       'odds_sha256':prior['odds_sha256'],'prior_prediction_sha256':prior_sha,'outcome_labels_passed_to_allocator':False})
    return {'year':year,'race_code':code,'sha256':sha(dest),'failures':errors}
def predict():
    assert (P/'protocol_commit.json').exists();rs,m=old.records();prior={(x['year'],x['race_code']):x for x in rs};hashes={(x['year'],x['race_code']):x['sha256'] for x in m['predictions']}
    tasks=[(y,r,prior[y,r['race_code']],hashes[y,r['race_code']]) for y in [2025,2026] for r in study.base.inputs(y)]
    done=[];bad=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
        fs={pool.submit(one,t):(t[0],t[1]['race_code']) for t in tasks}
        for f in concurrent.futures.as_completed(fs):
            try:done.append(f.result())
            except Exception as e:bad.append({'year':fs[f][0],'race_code':fs[f][1],'reason':str(e)})
            if (len(done)+len(bad))%10==0:print('PREDICT',len(done),'failed',len(bad),flush=True)
    save(P/'prediction_manifest.json',{'test_only':True,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'expected_races':222,'prepared_races':len(done),'expected_new_allocations':444,'reused_prior_allocations':222,
      'predictions':sorted(done,key=lambda x:(x['year'],x['race_code'])),'failures':bad,'outcomes_passed_to_allocator':False})
    print('SEALED',len(done),'errors',bad,flush=True)
def records():
    seal=json.loads((P/'prediction_seal_commit.json').read_text());assert sha(P/'prediction_manifest.json')==seal['manifest_sha256']
    m=json.loads((P/'prediction_manifest.json').read_text());rs=[]
    for x in m['predictions']:
        p=A/'predictions'/str(x['year'])/(x['race_code']+'.json');assert sha(p)==x['sha256'];rs.append(json.loads(p.read_text()))
    return rs,m
def settle():
    rs,m=records();rows=[];horses=[];errors=[];excluded=[]
    for r in rs:
        y=r['year'];code=r['race_code'];o=study.official(y,code)
        if o is None:excluded.append({'year':y,'race_code':code,'reason':'Same existing unresolved official result'});continue
        if r['failures']:errors.append({'year':y,'race_code':code,'failures':r['failures']});continue
        status={int(x['horse_number']):x['finish_status'] for x in o['finish_rows']}
        assert set(r['horse_numbers'])==set(status)-set(o.get('refunded_horse_numbers',[]))
        for method,v in r['variants'].items():
            pay=sum(int(o['payouts_per_100_yen'][t['bet_type']].get(t['kumiban'],0))*int(t['stake'])//100 for t in v['tickets'])
            rows.append(dict(v['metrics'],year=y,race_code=code,date=r['date'],variant=method,payout_yen=pay,any_hit=pay>0,
               solver_gap=v['allocation_audit']['actual_mip_gap']))
            for h in v['horse_probabilities']:
                n=int(h['umaban']);s=status[n]
                horses.append({'year':y,'race_code':code,'method':method,'win':h['win_probability'],'top3':h['top3_probability'],
                    'y_win':int(s=='1'),'y_top3':int(s in ['1','2','3'])})
    annual={str(y):{v:old.agg([x for x in rows if x['year']==y and x['variant']==v]) for v in METHODS} for y in [2025,2026]}
    reference=json.loads((old.P/'comparison.json').read_text())
    for y in ['2025','2026']:
        a=annual[y]['ai_market50'];b=reference['annual'][y]['D_filter_net']
        if not errors:
            for key in ['stake_yen','payout_yen','hit_races','races']:assert a[key]==b[key]
    metrics={}
    for y in [2025,2026]:
        metrics[str(y)]={}
        for method in METHODS:
            v=[x for x in horses if x['year']==y and x['method']==method];out={}
            for head in ['win','top3']:
                q=np.clip([x[head] for x in v],1e-12,1-1e-12);target=np.asarray([x['y_'+head] for x in v])
                out[head]={'brier':float(np.mean((q-target)**2)),'logloss':float(np.mean(-target*np.log(q)-(1-target)*np.log1p(-q)))}
            metrics[str(y)][method]=out
    report={'test_only':True,'annual':annual,'horse_probability_metrics':metrics,
      'methods':{'ai_only':'Same pretrained incumbent WIN/TOP3 with existing Platt calibrators, sqrt strength, no market correction',
         'market_only':'Normalize inverse WIN odds, sequential PL top3 without fitted parameters; no AI features',
         'ai_market50':'Same previous50% frozen strength correction mix'},
      'allocation':'Same EV>=1 filter, net_E50+H50, cap30, budget ceiling10000, minimum stake only',
      'new_allocations_expected':444,'reused_hash_verified_expected':222,'prediction_failures':m['failures'],
      'allocation_failures':errors,'official_exclusions':excluded,'no_production_or_tasks_changed':True,
      'halves':{str(y):{half:{v:old.agg([x for x in rows if x['year']==y and x['variant']==v and (x['date']<f'{y}-07-01')==early]) for v in METHODS} for half,early in [('H1',True),('H2',False)]} for y in [2025,2026]},
      'same_model_source_and_race_cohort':True,'model_specific_probability_scales_same_formula_not_same_numeric_value':True,
      'final_odds_and_final_starters_used':True,'periods_previously_inspected_not_independent_holdout':True,
      'feature_point_in_time_not_fully_certified':True,'prediction_seal_commit':json.loads((P/'prediction_seal_commit.json').read_text())['commit_sha']}
    save(P/'comparison.json',report);save(P/'race_results.json',rows);save(A/'horse_probability_rows.json',horses)
    print('RESULT',json.dumps({'annual':annual,'allocation_failures':errors,'exclusions':excluded}),flush=True)
if __name__=='__main__':{'predict':predict,'settle':settle}[sys.argv[1]]()
