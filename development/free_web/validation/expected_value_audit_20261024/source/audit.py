"""Audit fixed50%-correction records. No forecast/model/live changes."""
import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
import importlib.util,json,math,sys,hashlib
from pathlib import Path
import numpy as np,pandas as pd
from scipy.optimize import milp,Bounds,LinearConstraint
spec=importlib.util.spec_from_file_location('strength_study','correction_strength_20261024/replay.py')
study=importlib.util.module_from_spec(spec);spec.loader.exec_module(study)
P=Path('expected_value_audit_20261024/public');TOL=1e-10
def diagnostic_e_only(combos):
    # Same budget, minimum stakes and maximum count; only gross expected-payout objective.
    f=combos.sort_values(['bet_type','kumiban']).reset_index(drop=True)
    s=100*np.maximum(1,np.ceil(100/f.decimal_odds.to_numpy()-1e-12)).astype(int)
    ev=f.ai_probability.to_numpy()*f.decimal_odds.to_numpy();gross=ev*s
    result=milp(-gross/float(gross.max()),integrality=np.ones(len(f)),bounds=Bounds(np.zeros(len(f)),np.ones(len(f))),
       constraints=LinearConstraint(np.vstack([s,np.ones(len(f))]),[0,1],[10000,30]),
       options={'time_limit':30.,'mip_rel_gap':.01})
    assert result.x is not None and abs(result.x-np.rint(result.x)).max()<1e-5
    chosen=np.rint(result.x).astype(bool);keys={(x.bet_type,x.kumiban) for x in f[chosen].itertuples()}
    return {'keys':keys,'ticket_count':int(chosen.sum()),'stake_yen':int(s[chosen].sum()),
       'bad_ticket_count':int((chosen&(ev<1-TOL)).sum()),'bad_stake_yen':int(s[chosen&(ev<1-TOL)].sum()),
       'expected_payout_yen':float(gross[chosen].sum()),'solver_gap':float(result.mip_gap)}
def main():
    records,manifest=study.records();inputs={y:{r['race_code']:r for r in study.base.inputs(y)} for y in [2025,2026]}
    rows=[];allchecked=0
    # Cohort membership is inherited from the prior comparison, not chosen from results here.
    cohort={(x['year'],x['race_code']) for x in json.loads((study.P/'race_results.json').read_text())}
    for r in records:
        y=r['year'];code=r['race_code'];x=r['variants']['050'];race=inputs[y][code]
        h,combos,events=study.probability_tables(race,study.scores(race,'shared_ai_market',study.coefficients(y,.5)))
        oddsfile=Path('bias_20261020/public_cache/odds')/(code+'.json') if y==2026 else study.base.OLD/'cache2025'/(code+'_odds.json')
        assert study.sha(oddsfile)==r['odds_sha256']
        ss=json.loads(oddsfile.read_text())['snapshots'];odds=pd.DataFrame([z for v in ss.values() for z in v['rows']])
        merged=combos.merge(odds,on=['race_code','bet_type','kumiban'],validate='one_to_one');assert len(merged)==len(combos)
        tickets=x['tickets'];selected={(t['bet_type'],t['kumiban']) for t in tickets};lookup={(z.bet_type,z.kumiban):z.ai_probability for z in combos.itertuples()}
        assert len(tickets)<=30 and sum(t['stake'] for t in tickets)==x['stake_yen']<=10000
        for t in tickets:
            assert abs(t['ai_probability']-lookup[(t['bet_type'],t['kumiban'])])<1e-10
            assert t['stake']==100*max(1,math.ceil(100/t['decimal_odds']-1e-12))
        bad=[t for t in tickets if t['ai_probability']*t['decimal_odds']<1-TOL]
        good=[t for t in tickets if t['ai_probability']*t['decimal_odds']>1+TOL]
        neutral=[t for t in tickets if abs(t['ai_probability']*t['decimal_odds']-1)<=TOL]
        badkeys={(t['bet_type'],t['kumiban']) for t in bad};goodkeys=selected-badkeys
        hit=lambda keys:float(sum(e[0] for e in events if (e[1],e[2]) in keys or (e[3],e[4]) in keys))
        H=hit(selected);Hgood=hit(goodkeys);assert abs(H-x['allocation_audit']['probability_any_win'])<1e-10
        E=lambda ts:sum(t['stake']*t['ai_probability']*t['decimal_odds'] for t in ts)
        gross=E(tickets);assert abs(gross-x['allocation_audit']['expected_payout_yen'])<1e-7
        scale=x['allocation_audit']['expected_payout_scale_explicit'];con=diagnostic_e_only(merged)
        extra=badkeys-con['keys'];unique_bad=float(sum(e[0] for e in events if int((e[1],e[2]) in selected)+int((e[3],e[4]) in selected)==1 and ((e[1],e[2]) in badkeys or (e[3],e[4]) in badkeys)))
        row={'year':y,'race_code':code,'included_in_prior_settled_cohort':(y,code) in cohort,'ticket_count':len(tickets),
          'stake_yen':x['stake_yen'],'bad_ticket_count':len(bad),'bad_stake_yen':sum(t['stake'] for t in bad),
          'good_ticket_count':len(good),'neutral_ticket_count':len(neutral),
          'expected_payout_yen':gross,'expected_profit_yen':gross-x['stake_yen'],
          'bad_expected_payout_yen':E(bad),'bad_expected_profit_yen':E(bad)-sum(t['stake'] for t in bad),
          'good_expected_payout_yen':E(good),'good_stake_yen':sum(t['stake'] for t in good),
          'probability_any_hit':H,'probability_any_hit_after_delete_bad_no_reallocation':Hgood,
          'bad_collective_marginal_hit_probability':H-Hgood,'sum_bad_individual_unique_hit_probability':unique_bad,
          'objective_gross_E_component':.5*gross/scale,'objective_H_component':.5*H,
          'bad_collective_gross_E_objective_contribution':.5*E(bad)/scale,'bad_collective_H_objective_contribution':.5*(H-Hgood),
          'bad_tickets_not_selected_by_E_only_gross_diagnostic':len(extra),
          'E_only_gross_diagnostic':{k:v for k,v in con.items() if k!='keys'},
          'original_allocation_solver_gap':x['allocation_audit']['actual_mip_gap']}
        rows.append(row);allchecked+=1
    # Only now inspect official payouts, for the already-frozen selected tickets.
    for row in rows:
        if not row['included_in_prior_settled_cohort']:continue
        y=row['year'];code=row['race_code'];official=study.official(y,code)
        original=next(r for r in records if r['year']==y and r['race_code']==code)['variants']['050']['tickets']
        def payout(ts):return sum(int(official['payouts_per_100_yen'][t['bet_type']].get(t['kumiban'],0))*int(t['stake'])//100 for t in ts)
        bad=[t for t in original if t['ai_probability']*t['decimal_odds']<1-TOL]
        row['actual_payout_yen']=payout(original);row['bad_actual_payout_yen']=payout(bad)
        row['good_and_neutral_actual_payout_yen']=payout([t for t in original if t not in bad])
    annual={}
    for y in [2025,2026]:
        v=[x for x in rows if x['year']==y and x['included_in_prior_settled_cohort']];s=lambda k:sum(x[k] for x in v)
        stake=s('stake_yen');badstake=s('bad_stake_yen');goodstake=stake-badstake;badpay=s('bad_actual_payout_yen');goodpay=s('good_and_neutral_actual_payout_yen')
        annual[str(y)]={'races':len(v),'tickets':s('ticket_count'),'stake_yen':stake,'actual_payout_yen':s('actual_payout_yen'),
         'actual_recovery_percent':100*s('actual_payout_yen')/stake,'bad_ticket_count':s('bad_ticket_count'),
         'bad_ticket_percent':100*s('bad_ticket_count')/s('ticket_count'),'bad_stake_yen':badstake,'bad_stake_percent':100*badstake/stake,
         'races_containing_bad_tickets':sum(x['bad_ticket_count']>0 for x in v),'bad_expected_payout_yen':s('bad_expected_payout_yen'),
         'bad_expected_profit_yen':s('bad_expected_profit_yen'),'bad_actual_payout_yen':badpay,
         'bad_actual_recovery_percent':100*badpay/badstake if badstake else None,
         'retained_stake_yen_if_delete_bad_no_reallocation':goodstake,'retained_actual_payout_yen_if_delete_bad_no_reallocation':goodpay,
         'retained_actual_recovery_percent_if_delete_bad_no_reallocation':100*goodpay/goodstake if goodstake else None,
         'model_mean_hit_probability':float(np.mean([x['probability_any_hit'] for x in v])),
         'model_mean_hit_probability_after_delete_bad_no_reallocation':float(np.mean([x['probability_any_hit_after_delete_bad_no_reallocation'] for x in v])),
         'mean_bad_collective_marginal_hit_probability':float(np.mean([x['bad_collective_marginal_hit_probability'] for x in v])),
         'bad_tickets_also_chosen_by_E_only_gross_diagnostic':s('bad_ticket_count')-s('bad_tickets_not_selected_by_E_only_gross_diagnostic'),
         'bad_tickets_not_selected_by_E_only_gross_diagnostic':s('bad_tickets_not_selected_by_E_only_gross_diagnostic'),
         'E_only_gross_diagnostic_bad_tickets':sum(x['E_only_gross_diagnostic']['bad_ticket_count'] for x in v),
         'E_only_gross_diagnostic_tickets':sum(x['E_only_gross_diagnostic']['ticket_count'] for x in v),
         'mean_objective_gross_E_component':float(np.mean([x['objective_gross_E_component'] for x in v])),
         'mean_objective_H_component':float(np.mean([x['objective_H_component'] for x in v]))}
        prior=json.loads((study.P/'comparison.json').read_text())['annual'][str(y)]['050']
        for f,pf in [('stake_yen','stake_yen'),('actual_payout_yen','payout_yen')]:assert annual[str(y)][f]==prior[pf]
    report={'test_only':True,'correction_strength':.5,'annual':annual,'records_hash_checked':allchecked,
      'bad_definition':'probability*decimal_odds <1-1e-10; probabilities are model estimates, not known true probabilities',
      'critical_finding':'E component maximizes gross expected payout, not expected profit. A negative-EV ticket can add positive gross E as well as positive H.',
      'objective_formula':'.5*sum(stake*p*odds)/scale+.5*probability_any_hit; purchase cost not subtracted in E',
      'E_only_diagnostic':'Same full combination table, budget ceiling,max30,min stakes,solver30s/1%; maximize gross E only; no outcome labels. Not a deployed alternative, no alternate realized ROI computed.',
      'causal_limit':'Different selected tickets under E-only indicate a selection tradeoff, not uniquely proven H-only causation; limited solver precision and objective normalization also apply.',
      'no_reallocation_deletion_is_retrospective_diagnostic_not_strategy_approval':True,
      'no_production_or_automations_changed':True,'no_model_training_or_coefficient_changes':True,
      'final_odds_used':True,'forecast_feature_point_in_time_not_fully_certified':True,
      '2025_prior_exclusions':13,'2025_official_unresolved_same_two_races':True,
      'source_manifest_sha256':study.sha(study.P/'prediction_manifest.json')}
    (P/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');(P/'race_diagnostics.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
