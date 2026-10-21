"""Evaluate frozen 2025-selected families; separate source probabilities and conversion."""
import argparse,datetime as dt,hashlib,json,sys
from pathlib import Path
import numpy as np,pandas as pd
from scipy.special import logit
from rankwise import METHODS,scores,observed_losses,distribution,probability_tables

def binary(prob,y):
    p=np.clip(np.asarray(prob,float),1e-12,1-1e-12);y=np.asarray(y,float)
    return {'brier':float(np.mean((p-y)**2)),'logloss':float(np.mean(-y*np.log(p)-(1-y)*np.log1p(-p))),
        'predicted_events':float(p.sum()),'actual_events':int(y.sum())}

def popgroups(rows):
    h=pd.DataFrame(rows);groups=pd.cut(h.popularity,[0,1,3,6,10,18],labels=['1','2-3','4-6','7-10','11+'])
    return [{'group':str(name),'horses':len(g),'pred_WIN':float(g.win_probability.mean()),'actual_WIN':float(g.target_win.mean()),
        'pred_TOP3':float(g.top3_probability.mean()),'actual_TOP3':float(g.target_top3.mean())} for name,g in h.groupby(groups,observed=True)]

def summarize(rows):
    horses=[h for r in rows for h in r['horses']];h=pd.DataFrame(horses)
    nonempty=[set(r['metrics']) for r in rows if r['metrics']]
    keys=set.intersection(*nonempty) if nonempty else set()
    return {'races':len(rows),'horses':len(h),'horse_WIN':binary(h.win_probability,h.target_win),
        'horse_TOP3':binary(h.top3_probability,h.target_top3),'popularity_groups':popgroups(horses),
        'joint_metrics':{k:float(np.mean([r['metrics'][k] for r in rows if k in r['metrics']])) for k in sorted(keys)}}

def paired(a,b,key,seed=20261021):
    av={r['race_code']:r['metrics'][key] for r in a if key in r['metrics']}
    bv={r['race_code']:r['metrics'][key] for r in b if key in r['metrics']}
    values=np.array([av[k]-bv[k] for k in sorted(set(av)&set(bv))]);rng=np.random.default_rng(seed)
    means=values[rng.integers(0,len(values),size=(10000,len(values)))].mean(axis=1)
    return {'paired_races':len(values),'difference':float(values.mean()),'bootstrap_95CI':np.quantile(means,[.025,.975]).tolist()}

def main(workdir):
    root=Path(workdir);selection=json.loads((root/'public/selection.json').read_text())
    fits=selection['final_full2025_fits'];selected=selection['selected_method']
    old_parameters=json.loads(Path('correction_20261021/private_assets/correction_coefficients.json').read_text())
    fits['incumbent_frozen']={'parameters':[old_parameters['alpha_ai'],old_parameters['beta_market']]}
    frozen_sha=hashlib.sha256((root/'public/selection.json').read_bytes()).hexdigest()
    horses=pd.DataFrame(json.loads(Path('bias_20261020/horse_predictions_all.json').read_text()))
    officials={r['race_code']:r for r in json.loads(Path('bias_20261020/official_results.json').read_text())['races']}
    methods=list(METHODS)+['incumbent_frozen'];outputs={k:[] for k in methods}
    diagnosis={k:[] for k in ['raw_independent','normalized_WIN_PL','geometric_WIN_TOP3_PL']}
    private_races=[]
    for code,g in horses.groupby('race_code',sort=True):
        g=g.sort_values('umaban').reset_index(drop=True);official=officials[code]
        market=json.loads((Path('correction_20261021/cache/market')/(code+'.json')).read_text());mp={r['umaban']:r for r in market['runners']}
        assert set(g.umaban)==set(mp)
        record={'race_code':code,'date':official['date'],'numbers':g.umaban.astype(int).tolist(),
            'win':g.win_probability.tolist(),'top3':g.top3_probability.tolist(),'odds':[mp[int(n)]['decimal_win_odds'] for n in g.umaban],
            'target_win':g.target_win.astype(int).tolist(),'target_top3':g.target_top3.astype(int).tolist(),
            'popularity':g.popularity.astype(int).tolist(),'sources':sorted(g.source.unique().tolist())}
        first=sorted([r for r in official['finish_rows'] if r['finish_status'].isdigit() and int(r['finish_status'])<=3],key=lambda r:int(r['finish_status']))
        deadheat=len(first)!=3 or len({r['finish_status'] for r in first})!=3
        record['order']=[] if deadheat else [record['numbers'].index(r['horse_number']) for r in first]
        private_races.append(record)
        observed={int(r.umaban):(int(r.target_win),int(r.target_top3),int(r.popularity)) for r in g.itertuples()}
        def horse_rows(w,t):
            return [{'umaban':n,'win_probability':float(a),'top3_probability':float(b),'target_win':observed[n][0],
                'target_top3':observed[n][1],'popularity':observed[n][2]} for n,a,b in zip(record['numbers'],w,t)]
        diagnosis['raw_independent'].append({'race_code':code,'date':record['date'],'metrics':{},'horses':horse_rows(g.win_probability,g.top3_probability)})
        for name,strength in [('normalized_WIN_PL',g.win_probability.to_numpy()),
            ('geometric_WIN_TOP3_PL',np.sqrt(g.win_probability.to_numpy()*g.top3_probability.to_numpy()))]:
            stage=np.repeat(np.log(strength)[None,:],3,axis=0);_,_,w,t=distribution(stage)
            loss={} if deadheat else {'ordered_nll':sum(observed_losses(stage,record['order']))}
            diagnosis[name].append({'race_code':code,'date':record['date'],'metrics':loss,'horses':horse_rows(w,t)})
        odds=json.loads((Path('bias_20261020/public_cache/odds')/(code+'.json')).read_text())['snapshots']
        odds_frame=pd.DataFrame([r for s in odds.values() for r in s['rows']])
        for method in methods:
            family='shared_ai_market' if method=='incumbent_frozen' else method
            stage=scores(record,family,fits[method]['parameters'])
            prediction,combo,scenarios=probability_tables(record,stage)
            joint={}
            if not deadheat:
                losses=observed_losses(stage,record['order']);joint.update(ordered_nll=sum(losses),**{f'rank{i+1}_nll':x for i,x in enumerate(losses)})
                for kind in ['umaren','sanrenpuku']:
                    subset=combo[combo.bet_type==kind];winners=official['payouts_per_100_yen'][kind];assert len(winners)==1
                    key=next(iter(winners));p=float(subset.loc[subset.kumiban==key,'ai_probability'].iloc[0])
                    joint[kind+'_nll']=-float(np.log(p));joint[kind+'_brier']=float((subset.ai_probability**2).sum()-2*p+1)
            outputs[method].append({'race_code':code,'date':record['date'],'method':method,'metrics':joint,
                'horses':horse_rows(prediction.win_probability,prediction.top3_probability),'deadheat':deadheat})
    assert all(len(x)==103 for x in outputs.values())
    aggregate={m:summarize(v) for m,v in outputs.items()}
    decomp={m:summarize(v) for m,v in diagnosis.items()}
    halves={half:{m:summarize([r for r in values if (r['date']<'2026-07-01')==early]) for m,values in outputs.items()}
        for half,early in [('H1',True),('H2',False)]}
    comparisons={m:{base:paired(v,outputs[base],'ordered_nll') for base in ['incumbent_frozen','market_PL'] if base!=m}
        for m,v in outputs.items()}
    # Verify incumbent probability metrics match the previous authoritative audit.
    prior=json.loads(Path('correction_20261021/public/comparison.json').read_text())['aggregate']['corrected']
    assert abs(aggregate['incumbent_frozen']['horse_WIN']['brier']-prior['horse_WIN']['brier'])<1e-12
    assert abs(aggregate['incumbent_frozen']['joint_metrics']['ordered_nll']-prior['combo']['ordered_top3_logloss'])<1e-12
    raw_h=pd.DataFrame([dict(h,race_code=r['race_code']) for r in diagnosis['raw_independent'] for h in r['horses']])
    converted=pd.DataFrame([dict(h,race_code=r['race_code']) for r in diagnosis['geometric_WIN_TOP3_PL'] for h in r['horses']])
    shift=raw_h.merge(converted,on=['race_code','umaban'],suffixes=('_raw','_joint'),validate='one_to_one')
    conversion={'mean_absolute_WIN_shift':float(np.abs(shift.win_probability_joint-shift.win_probability_raw).mean()),
        'mean_absolute_TOP3_shift':float(np.abs(shift.top3_probability_joint-shift.top3_probability_raw).mean()),
        'source_WIN_Brier':decomp['raw_independent']['horse_WIN']['brier'],
        'converted_WIN_Brier':decomp['geometric_WIN_TOP3_PL']['horse_WIN']['brier'],
        'source_TOP3_Brier':decomp['raw_independent']['horse_TOP3']['brier'],
        'converted_TOP3_Brier':decomp['geometric_WIN_TOP3_PL']['horse_TOP3']['brier']}
    # Independent paired confidence intervals within 2025 CV are diagnostics,
    # not a replacement for the already-frozen one-standard-error selection.
    cv=json.loads((root/'public/cv_validation_races.json').read_text());cv_comp={}
    for method in METHODS:
        a=[dict(x,metrics={'ordered_nll':x['ordered_nll']}) for x in cv if x['method']==method]
        for baseline in ['market_PL','stage_market','shared_ai_market']:
            if baseline==method:continue
            b=[dict(x,metrics={'ordered_nll':x['ordered_nll']}) for x in cv if x['method']==baseline]
            cv_comp[method+' vs '+baseline]=paired(a,b,'ordered_nll')
    report={'record_type':'prediction_vs_joint_conversion_decomposition','created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'selected_in_2025':selected,'selection_repeated_after_2026':False,'selection_sha256':frozen_sha,
        '2026_is_untouched':False,'final_odds_used':True,'test_only':True,'production_or_automation_changed':False,
        'decomposition':decomp,'conversion_shift':conversion,'2026_aggregate':aggregate,'2026_halves':halves,
        'paired_2026':comparisons,'paired_2025_CV':cv_comp,
        'evaluation_rule':'All prespecified families reported. The method chosen by 2025 one-SE rule remains market_PL even if another family looks better in 2026.',
        'limits':json.loads((root/'public/protocol.json').read_text())['limits']}
    (root/'public/decomposition.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (root/'private_assets/races_2026.json').write_text(json.dumps(private_races)+'\n')
    (root/'private_assets/evaluation_horse_rows.json').write_text(json.dumps(outputs)+'\n')
    compact=[{k:r[k] for k in ['race_code','date','method','metrics']} for rows in outputs.values() for r in rows]
    (root/'public/probability_results_2026.json').write_text(json.dumps(compact,indent=2)+'\n')
    print('DECOMPOSITION',json.dumps({'selected':selected,'conversion':conversion,'methods':{m:v['joint_metrics'] for m,v in aggregate.items()},
        'WIN_brier':{m:v['horse_WIN']['brier'] for m,v in aggregate.items()},'TOP3_brier':{m:v['horse_TOP3']['brier'] for m,v in aggregate.items()}}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('workdir');a=p.parse_args();main(a.workdir)
