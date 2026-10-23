"""Fixed incumbent ablation. No result labels in prediction/allocation inputs."""
import os
os.environ['OPENBLAS_NUM_THREADS']='1'
os.environ['OMP_NUM_THREADS']='1'
import concurrent.futures,datetime,hashlib,json,math,sys
from pathlib import Path
import numpy as np,pandas as pd
sys.path.insert(0,'cap30_ceiling_20261023')
from allocator import allocate
from replay2026 import aggregate,prediction_input,sha,save
sys.path.insert(0,'decomposition_20261021')
from rankwise import scores,probability_tables
ROOT=Path('correction_ablation_20261024'); P=ROOT/'public'; A=ROOT/'private_assets'
OLD=Path('cap30_ceiling_20261023')

def inputs(year):
    if year==2026:
        raw=json.loads(Path('base_review_20261021/private_assets/races_2026.json').read_text())['incumbent_same_input']
        return [prediction_input(r) for r in raw]
    return json.loads((OLD/'private_assets/forecast_inputs2025.json').read_text())['incumbent']

def corrected(year,code):
    folder='predictions' if year==2026 else 'predictions2025'
    manifest='prediction_manifest.json' if year==2026 else 'prediction_manifest2025.json'
    m=json.loads((OLD/'public'/manifest).read_text())
    x=next(x for x in m['predictions'] if x['method']=='incumbent' and x['race_code']==code)
    path=OLD/'private_assets'/folder/'incumbent'/(code+'.json')
    assert sha(path)==x['sha256']
    return json.loads(path.read_text())

def params(year):
    name='protocol.json' if year==2026 else 'fit2024_for2025.json'
    return json.loads((OLD/'public'/name).read_text())['parameters']['incumbent']

def one(task):
    year,r=task;code=r['race_code'];dest=A/'predictions'/str(year)/(code+'.json')
    if dest.exists():return {'year':year,'race_code':code,'sha256':sha(dest)}
    assert set(r)<=set(['race_code','date','numbers','win','top3','odds','input_source'])
    # Baseline is the original sqrt(WIN*TOP3) PL conversion, equivalently [1,0].
    # Only the frozen strength correction changes; allocator and conversion stay fixed.
    h0,c0,events=probability_tables(r,scores(r,'shared_ai_market',[1.,0.]))
    h1,c1,_=probability_tables(r,scores(r,'shared_ai_market',params(year)))
    op=Path('bias_20261020/public_cache/odds')/(code+'.json') if year==2026 else OLD/'cache2025'/(code+'_odds.json')
    source=json.loads(op.read_text())['snapshots'];assert all(s['status']=='final_postrace' for s in source.values())
    odds=pd.DataFrame([x for s in source.values() for x in s['rows']])
    merged=c0.merge(odds,on=['race_code','bet_type','kumiban'],validate='one_to_one');assert len(merged)==len(c0)
    scale=float((merged.ai_probability*merged.decimal_odds).max()*10000)
    tickets,audit=allocate(merged,r['numbers'],events,expected_payout_scale=scale,time_limit=30.,mip_relative_gap=.01)
    existing=corrected(year,code)
    # Validate reused corrected tickets against probabilities recomputed in this run.
    cp={(x.bet_type,x.kumiban):x.ai_probability for x in c1.itertuples()}
    for x in existing['tickets']:assert abs(x['ai_probability']-cp[(x['bet_type'],x['kumiban'])])<1e-10
    # Prove baseline is byte-algebraically equivalent to original combination engine.
    if year==2026:
        sys.path.insert(0,'cap30_ceiling_20261023/runtime')
        from corrected_v2_core import generate_combinations
        original=generate_combinations(pd.DataFrame({'race_code':code,'umaban':r['numbers'],'win_probability':r['win'],'top3_probability':r['top3']}))
        check=original.merge(c0,on=['race_code','bet_type','kumiban'],suffixes=('_old','_new'),validate='one_to_one')
        assert np.max(np.abs(check.ai_probability_old-check.ai_probability_new))<1e-10
    record={'year':year,'race_code':code,'date':r['date'],'test_only':True,'odds_status':'final_postrace',
      'input_sha256':hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest(),'odds_sha256':sha(op),
      'baseline':{'parameters':[1.,0.],'tickets':tickets.to_dict('records'),'allocation_audit':audit,
        'stake_yen':int(tickets.stake.sum()),'unspent_yen':10000-int(tickets.stake.sum()),'ticket_count':len(tickets)},
      'corrected':{'parameters':params(year),'tickets':existing['tickets'],'allocation_audit':existing['allocation_audit'],
        'stake_yen':existing['stake_yen'],'unspent_yen':existing['unspent_yen'],'ticket_count':existing['ticket_count']},
      'horse_probabilities':{'baseline':h0.to_dict('records'),'corrected':h1.to_dict('records')},
      'original_head_probabilities':{'win':r['win'],'top3':r['top3']},
      'win_odds':r['odds'],'horse_numbers':r['numbers'],'outcomes_loaded':False}
    save(dest,record)
    return {'year':year,'race_code':code,'sha256':sha(dest)}

def predict():
    assert (P/'protocol_commit.json').exists()
    tasks=[(year,r) for year in [2025,2026] for r in inputs(year)];done=[];bad=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
        fs={pool.submit(one,t):(t[0],t[1]['race_code']) for t in tasks}
        for f in concurrent.futures.as_completed(fs):
            try:done.append(f.result())
            except Exception as e:bad.append({'year':fs[f][0],'race_code':fs[f][1],'error':str(e)})
            if (len(done)+len(bad))%10==0:print('PREDICT',len(done),'failed',len(bad),flush=True)
    save(P/'prediction_manifest.json',{'test_only':True,'prepared_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'expected_races':222,'prepared_races':len(done),'outcomes_loaded':False,'predictions':sorted(done,key=lambda x:(x['year'],x['race_code'])),'failures':bad})
    print('SEALED',len(done),bad,flush=True)

def metrics(rows):
    result={}
    for variant in ['baseline','corrected','original_heads']:
        v=[x for x in rows if x['variant']==variant];d={}
        for head in ['win','top3']:
            q=np.clip([x[head] for x in v],1e-12,1-1e-12);y=np.array([x['y_'+head] for x in v])
            d[head]={'brier':float(np.mean((q-y)**2)),'logloss':float(np.mean(-y*np.log(q)-(1-y)*np.log1p(-q)))}
        d['popularity_groups']={}
        for lo,hi in [(1,1),(2,3),(4,6),(7,18)]:
            s=[x for x in v if lo<=x['popularity']<=hi];count=len(s)
            d['popularity_groups'][f'{lo}-{hi}']={'horses':count,**{head:{'predicted_mean':float(np.mean([x[head] for x in s])),
               'observed_rate':float(np.mean([x['y_'+head] for x in s])),
               'predicted_minus_observed':float(np.mean([x[head]-x['y_'+head] for x in s]))} for head in ['win','top3']}}
        result[variant]=d
    return result

def settle():
    seal=json.loads((P/'prediction_seal_commit.json').read_text());assert sha(P/'prediction_manifest.json')==seal['manifest_sha256']
    manifest=json.loads((P/'prediction_manifest.json').read_text());records=[]
    for x in manifest['predictions']:
        path=A/'predictions'/str(x['year'])/(x['race_code']+'.json');assert sha(path)==x['sha256'];records.append(json.loads(path.read_text()))
    off26={x['race_code']:x for x in json.loads(Path('bias_20261020/official_results.json').read_text())['races']}
    rows=[];horses=[];excluded=[]
    for r in records:
        code=r['race_code'];year=r['year']
        if year==2025:
            path=OLD/'cache2025'/(code+'_official.json')
            if not path.exists():excluded.append({'year':year,'race_code':code,'reason':'No unambiguously matched official result; same previous exclusion'});continue
            official=json.loads(path.read_text());assert official['official_verified']
        else:official=off26[code]
        status={int(x['horse_number']):x['finish_status'] for x in official['finish_rows']}
        assert set(r['horse_numbers'])==set(status)-set(official.get('refunded_horse_numbers',[]))
        rank={num:i+1 for i,num in enumerate(sorted(r['horse_numbers'],key=lambda n:(r['win_odds'][r['horse_numbers'].index(n)],n)))}
        for variant in ['baseline','corrected']:
            x=r[variant];pay=sum(int(official['payouts_per_100_yen'][t['bet_type']].get(t['kumiban'],0))*int(t['stake'])//100 for t in x['tickets'])
            rows.append({'year':year,'method':variant,'race_code':code,'date':r['date'],'stake_yen':x['stake_yen'],
              'unspent_yen':x['unspent_yen'],'payout_yen':pay,'any_hit':pay>0,'ticket_count':x['ticket_count'],
              'predicted_hit_probability':x['allocation_audit']['probability_any_win'],'solver_gap':x['allocation_audit']['actual_mip_gap']})
            for h in r['horse_probabilities'][variant]:
                num=int(h['umaban']);s=status[num]
                horses.append({'year':year,'race_code':code,'variant':variant,'popularity':rank[num],
                  'win':h['win_probability'],'top3':h['top3_probability'],'y_win':int(s=='1'),'y_top3':int(s in ['1','2','3'])})
        for i,num in enumerate(r['horse_numbers']):
            s=status[num];horses.append({'year':year,'race_code':code,'variant':'original_heads','popularity':rank[num],
              'win':r['original_head_probabilities']['win'][i],'top3':r['original_head_probabilities']['top3'][i],
              'y_win':int(s=='1'),'y_top3':int(s in ['1','2','3'])})
    report={'test_only':True,'model':'incumbent_only','allocation_rule':'cap30_budget_ceiling_E50_v1_20261023',
       'baseline':'Original sqrt(WIN*TOP3) PL, parameters [1,0], independently Platt-calibrated heads retained; no market strength correction',
       'corrected':'Frozen shared strength alpha*log(sqrt(WIN*TOP3))+beta*log(normalized inverse win odds)',
       'annual':{str(y):{'portfolio':{v:aggregate([x for x in rows if x['year']==y and x['method']==v]) for v in ['baseline','corrected']},
          'horse_metrics':metrics([x for x in horses if x['year']==y]),
          'halves':{half:{v:aggregate([x for x in rows if x['year']==y and x['method']==v and (x['date']<f'{y}-07-01')==early]) for v in ['baseline','corrected']} for half,early in [('H1',True),('H2',False)]}} for y in [2025,2026]},
       'exclusions':excluded,'prediction_failures':manifest['failures'],'prediction_seal_commit':seal['commit_sha'],
       'production_or_tasks_changed':False,'final_odds_used':True,'prior_inspection_and_model_selection_not_fully_independent':True,
       'market_correction_changes_ai_temperature_and_market_weight_together':True,
       'popularity_ties':'ascending displayed WIN odds then horse number; grouped diagnostics use deterministic rank',
       'original_feature_point_in_time_not_certified':True}
    save(P/'comparison.json',report);save(P/'race_results.json',rows);save(A/'horse_metrics_rows.json',horses)
    print('RESULT',json.dumps({y:r['portfolio'] for y,r in report['annual'].items()}),flush=True)

if __name__=='__main__':{'predict':predict,'settle':settle}[sys.argv[1]]()
