"""Frozen 2025-fitted correction vs 2026 final-odds baselines; no live outputs."""
import os
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import argparse, concurrent.futures, datetime as dt, hashlib, json, math, sys, time
from pathlib import Path
import numpy as np, pandas as pd
from strength_calibration import corrected_strength, probability_tables, ordered_nll
from balanced_A_v3_explicit import allocate_balanced, _ordered_outcomes

VARIANTS=('old','corrected','market')

def binary_metrics(prob,y):
    p=np.clip(np.asarray(prob,float),1e-12,1-1e-12);y=np.asarray(y,float)
    return {'brier':float(np.mean((p-y)**2)),'logloss':float(np.mean(-y*np.log(p)-(1-y)*np.log1p(-p)))}

def one(task):
    root_string,official,records,coef=task
    root=Path(root_string);code=official['race_code'];dest=root/'private_assets/evaluation'/code
    dest.mkdir(parents=True,exist_ok=True)
    h=pd.DataFrame(records).sort_values('umaban').reset_index(drop=True)
    market=json.loads((root/'cache/market'/(code+'.json')).read_text())
    mp={r['umaban']:r for r in market['runners']}
    if set(h.umaban.astype(int))!=set(mp):raise ValueError('2026 field mismatch '+code)
    identity_resolutions=[];popularity_ties=[]
    official_names={r['umaban']:r['name'] for r in official['runners']}
    by_official_pop={int(r.popularity):int(r.umaban) for r in h.itertuples()}
    for r in h.itertuples():
        source=mp[int(r.umaban)]
        if r.horse_id is None and r.source=='verified_52_model_retrospective_checkpoint_20261018':
            if source.get('horse_name')!=official_names[int(r.umaban)]:raise ValueError('Checkpoint official/source horse-name mismatch')
            identity_resolutions.append({'umaban':int(r.umaban),'horse_id':source['horse_id'],
                'method':'Checkpoint race and horse number joined to public horse ID, with exact public/official horse-name match'})
        elif str(r.horse_id)!=source['horse_id']:raise ValueError('2026 horse mismatch '+code)
        if int(r.popularity)!=source['popularity']:
            other=by_official_pop[source['popularity']]
            if source['decimal_win_odds']!=mp[other]['decimal_win_odds']:
                raise ValueError('Non-tied popularity mismatch '+code)
            popularity_ties.append({'umaban':int(r.umaban),'official_popularity':int(r.popularity),
                'source_popularity':source['popularity'],'equal_displayed_WIN_odds':source['decimal_win_odds'],
                'policy':'Use official popularity for diagnostics; displayed numeric odds for probability calculation'})
    prices=np.array([mp[int(x)]['decimal_win_odds'] for x in h.umaban])
    sources=json.loads((Path('bias_20261020/public_cache/odds')/(code+'.json')).read_text())['snapshots']
    odds=pd.DataFrame([r for source in sources.values() for r in source['rows']])
    # Exact marginal probabilities, union coverage and combination probabilities
    # all come from the same ordered-outcome mass for corrected/market variants.
    summaries=[]
    for variant in VARIANTS:
        path=dest/(variant+'.json')
        if path.exists():summaries.append(json.loads(path.read_text()));continue
        if variant=='old':
            strength=np.sqrt(h.win_probability.to_numpy()*h.top3_probability.to_numpy());strength/=strength.sum()
        elif variant=='corrected':strength=corrected_strength(h,prices,coef['alpha_ai'],coef['beta_market'])
        else:strength=corrected_strength(h,prices,0.,1.)
        marginals,combos=probability_tables(h,strength)
        if variant=='old':
            # Preserve original separately calibrated horse marginals in the
            # probability audit; combo and union use its original sqrt strength.
            forecast=h.copy()
            from corrected_v2_core import generate_combinations
            original=generate_combinations(h)
            check=original.merge(combos,on=['race_code','bet_type','kumiban'],validate='one_to_one',suffixes=('_old','_new'))
            assert np.max(np.abs(check.ai_probability_old-check.ai_probability_new))<1e-10
        else:forecast=marginals
        allocated_horses=marginals.copy() # explicit rank_strength consumed by adapter
        # Check allocator's independently enumerated outcome mass agrees exactly.
        scenario=_ordered_outcomes(allocated_horses)
        for kind in ['umaren','sanrenpuku']:
            slot=2 if kind=='umaren' else 4
            mass={}
            for row in scenario:mass[row[slot]]=mass.get(row[slot],0.)+row[0]
            for row in combos[combos.bet_type==kind].itertuples():assert abs(row.ai_probability-mass[row.kumiban])<1e-10
        combo=combos.merge(odds,on=['race_code','bet_type','kumiban'],how='outer',validate='one_to_one',indicator=True)
        assert combo._merge.eq('both').all();combo=combo.drop(columns='_merge')
        started=time.monotonic();tickets,audit=allocate_balanced(combo,allocated_horses)
        results=[]
        for row in tickets.to_dict('records'):
            stake=int(row['stake']);price=float(row['decimal_odds'])
            assert stake==100*max(1,math.ceil(10000/(100*price)-1e-12))
            payout=int(official['payouts_per_100_yen'][row['bet_type']].get(row['kumiban'],0))*stake//100
            results.append(dict(row,stake=stake,payout_yen=payout))
        assert sum(r['stake'] for r in results)==10000
        events={};unique_ranks=[r['finish_status'] for r in official['finish_rows'] if r['finish_status'].isdigit() and int(r['finish_status'])<=3]
        deadheat=len(unique_ranks)!=len(set(unique_ranks))
        if not deadheat:
            first=sorted([r for r in official['finish_rows'] if r['finish_status'] in ['1','2','3']],key=lambda r:int(r['finish_status']))
            order=[int(np.where(h.umaban.to_numpy()==r['horse_number'])[0][0]) for r in first]
            events['ordered_top3_logloss']=ordered_nll(np.log(strength),order)
            for kind in ['umaren','sanrenpuku']:
                part=combos[combos.bet_type==kind];winning=official['payouts_per_100_yen'][kind]
                assert len(winning)==1
                key=next(iter(winning));prob=float(part.loc[part.kumiban==key,'ai_probability'].iloc[0])
                events[kind+'_logloss']=-math.log(prob)
                events[kind+'_brier']=float(np.square(part.ai_probability).sum()-2*prob+1)
        horse_rows=[]
        for idx,row in forecast.iterrows():
            horse_rows.append({'umaban':int(row.umaban),'popularity':int(row.popularity),
                'win_probability':float(row.win_probability),'top3_probability':float(row.top3_probability),
                'target_win':bool(row.target_win),'target_top3':bool(row.target_top3)})
        result={'race_code':code,'date':official['date'],'race_name':official['name'],'variant':variant,
            'test_only':True,'final_odds_used':True,'is_live_performance':False,
            'stake_yen':10000,'payout_yen':sum(r['payout_yen'] for r in results),'any_hit':any(r['payout_yen']>0 for r in results),
            'model_hit_probability':float(audit['probability_any_win']),
            'model_expected_payout_yen':float(audit['model_expected_payout_yen_full_actual_odds']),
            'ticket_count':len(results),'stake_at_100x_or_more':sum(r['stake'] for r in results if r['decimal_odds']>=100),
            'metrics':events,'horse_probabilities':horse_rows,'tickets':results,'allocation_audit':audit,
            'allocation_seconds':time.monotonic()-started,'deadheat':deadheat,
            'checkpoint_identity_resolutions':identity_resolutions,'equal_displayed_odds_popularity_ties':popularity_ties}
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        print('EVALUATED',code,variant,len(results),result['payout_yen'],round(result['allocation_seconds'],2),flush=True)
        summaries.append(result)
    return summaries

def aggregate(rows):
    h=pd.DataFrame([r for x in rows for r in x['horse_probabilities']])
    result={'races':len(rows),'horses':len(h),'horse_WIN':binary_metrics(h.win_probability,h.target_win),
        'horse_TOP3':binary_metrics(h.top3_probability,h.target_top3),
        'combo':{key:float(np.mean([r['metrics'][key] for r in rows if key in r['metrics']])) for key in rows[0]['metrics']},
        'portfolio':{'ticket_count':sum(r['ticket_count'] for r in rows),'stake_yen':10000*len(rows),
            'payout_yen':sum(r['payout_yen'] for r in rows),'recovery_percent':sum(r['payout_yen'] for r in rows)/len(rows)/100,
            'hit_races':sum(r['any_hit'] for r in rows),'actual_hit_rate':sum(r['any_hit'] for r in rows)/len(rows),
            'mean_model_hit_probability':float(np.mean([r['model_hit_probability'] for r in rows])),
            'absolute_hit_calibration_gap':abs(float(np.mean([r['model_hit_probability']-r['any_hit'] for r in rows]))),
            'model_expected_payout_yen':sum(r['model_expected_payout_yen'] for r in rows),
            'stake_share_at_100x_or_more':sum(r['stake_at_100x_or_more'] for r in rows)/(10000*len(rows)),
            'max_allocation_seconds':max(r['allocation_seconds'] for r in rows)}}
    groups=pd.cut(h.popularity,[0,1,3,6,10,18],labels=['1','2-3','4-6','7-10','11+'])
    result['popularity_groups']=[{'group':str(name),'horses':len(g),'pred_WIN':float(g.win_probability.mean()),
        'actual_WIN':float(g.target_win.mean()),'pred_TOP3':float(g.top3_probability.mean()),'actual_TOP3':float(g.target_top3.mean())}
        for name,g in h.groupby(groups,observed=True)]
    return result

def main(workdir,modules):
    root=Path(workdir);sys.path.insert(0,modules)
    coefficient=json.loads((root/'private_assets/correction_coefficients.json').read_text())
    official=json.loads(Path('bias_20261020/official_results.json').read_text())['races']
    horses=json.loads(Path('bias_20261020/horse_predictions_all.json').read_text())
    tasks=[(str(root),o,[h for h in horses if h['race_code']==o['race_code']],coefficient) for o in official]
    completed=[];failures=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=2) as pool:
        pending={pool.submit(one,t):t[1]['race_code'] for t in tasks}
        for future in concurrent.futures.as_completed(pending):
            try:completed.extend(future.result())
            except Exception as e:
                failures.append({'race_code':pending[future],'error':str(e)})
                print('EVALUATION_FAILED',pending[future],str(e),flush=True)
    (root/'public/evaluation_status.json').write_text(json.dumps({'completed_variants':len(completed),'failures':failures},indent=2)+'\n')
    if failures or len(completed)!=309:raise RuntimeError('Incomplete evaluation')
    results={v:sorted([r for r in completed if r['variant']==v],key=lambda r:r['race_code']) for v in VARIANTS}
    full={v:aggregate(r) for v,r in results.items()}
    halves={half:{v:aggregate([r for r in rows if (r['date']<'2026-07-01')==early]) for v,rows in results.items()}
        for half,early in [('H1',True),('H2',False)]}
    # Equal race-weight paired bootstrap. Negative loss difference is improvement.
    rng=np.random.default_rng(20261021);comparisons={}
    for baseline in ['old','market']:
        paired=[]
        for a,b in zip(results['corrected'],results[baseline]):
            assert a['race_code']==b['race_code']
            if 'ordered_top3_logloss' in a['metrics']:
                paired.append(a['metrics']['ordered_top3_logloss']-b['metrics']['ordered_top3_logloss'])
        values=np.array(paired);means=values[rng.integers(0,len(values),size=(10000,len(values)))].mean(axis=1)
        comparisons[baseline]={'paired_races':len(values),'mean_ordered_top3_logloss_difference':float(values.mean()),
            'paired_race_bootstrap95CI':np.quantile(means,[.025,.975]).tolist()}
    old,corrected,market=(full[x] for x in VARIANTS)
    gates={
        'complete_103_races_309_variant_runs':True,
        'ordered_top3_logloss_improves':corrected['combo']['ordered_top3_logloss']<old['combo']['ordered_top3_logloss'],
        'both_combination_logloss_improve':all(corrected['combo'][k+'_logloss']<old['combo'][k+'_logloss'] for k in ['umaren','sanrenpuku']),
        'both_horse_brier_do_not_worsen':all(corrected[k]['brier']<=old[k]['brier'] for k in ['horse_WIN','horse_TOP3']),
        'both_halves_ordered_logloss_improve':all(halves[t]['corrected']['combo']['ordered_top3_logloss']<halves[t]['old']['combo']['ordered_top3_logloss'] for t in halves),
        'hit_calibration_gap_narrows':corrected['portfolio']['absolute_hit_calibration_gap']<old['portfolio']['absolute_hit_calibration_gap'],
        'historical_ROI_not_worse':corrected['portfolio']['recovery_percent']>=old['portfolio']['recovery_percent'],
        'competitive_with_market_baseline':corrected['combo']['ordered_top3_logloss']<=market['combo']['ordered_top3_logloss'],
        'retains_AI_contribution':coefficient['alpha_ai']>1e-8,
        'fresh_in_sale_WIN_odds_pipeline_checked':False,
        'full_candidate_publication_roundtrip_checked':False,
    }
    summary={'record_type':'time_separated_probability_correction_comparison','created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'fit_year':2025,'evaluation_year':2026,'evaluation_is_untouched':False,'test_only':True,'final_odds_used':True,
        'model_or_original_records_overwritten':False,'production_activated':False,
        'coefficient':{k:coefficient[k] for k in ['alpha_ai','beta_market','fitted_races','2026_labels_used_for_fitting']},
        'aggregate':full,'halves':halves,'paired_comparisons':comparisons,'deployment_gates':gates,
        'statistical_gates_pass':all(v for k,v in gates.items() if k not in ['fresh_in_sale_WIN_odds_pipeline_checked','full_candidate_publication_roundtrip_checked']),
        'limitations':json.loads((root/'public/protocol.json').read_text())['limitations']}
    (root/'public/comparison.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print('FINAL_COMPARISON',json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('workdir');p.add_argument('modules');a=p.parse_args();main(a.workdir,a.modules)
