"""Balanced A v2 concentration-aware allocation. Caller must verify full in-sale odds.

Inputs: complete combo frame [race_code,bet_type,kumiban,ai_probability,decimal_odds]
        and horse prediction frame [umaban,win_probability,top3_probability].
Output: allocation and audit. No hard-coded bet count; no fixed bet-type split.

Use exact ordered top-3 outcomes for union hit chance. Modelled scenario
probabilities are Plackett-Luce from the same geometric-mean strength used by
corrected_v2_core.py, ensuring consistency with combination probabilities.
"""
from __future__ import annotations
from itertools import permutations
import math
import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

BUDGET = 10_000
UNIT = 100
TARGET_RETURN = 10_000
# Prevent residual-budget concentration in one astronomical-odds ticket.
# Where qualifying minimum stake exceeds 10% of budget, only that minimum
# is permitted, preserving the user's single-ticket break-even condition.
DISCRETIONARY_STAKE_CAP_YEN = 1000
# This is a conservative ranking proxy, not a payout/settlement cap.
VALUE_ODDS_CEILING = 50.0


def _ordered_outcomes(horses: pd.DataFrame):
    horses = horses.sort_values('umaban').reset_index(drop=True)
    nums = horses['umaban'].astype(int).to_numpy()
    strength = np.sqrt(horses['win_probability'].astype(float).to_numpy() *
                       horses['top3_probability'].astype(float).to_numpy())
    strength = np.clip(strength, 1e-12, None)
    strength /= strength.sum()
    result = []
    for i, j, k in permutations(range(len(nums)), 3):
        total = 1 - strength[i]
        second = total - strength[j]
        p = strength[i] * strength[j] / total * strength[k] / second
        a,b,c = int(nums[i]),int(nums[j]),int(nums[k])
        result.append((p, 'umaren', f'{min(a,b):02d}{max(a,b):02d}',
                       'sanrenpuku', ''.join(f'{t:02d}' for t in sorted((a,b,c)))))
    probabilities = np.array([r[0] for r in result],dtype=float)
    if not abs(float(probabilities.sum())-1.0) < 1e-7:
        raise ValueError('Outcome scenario probabilities do not sum to one')
    return result


def allocate_balanced(combo:pd.DataFrame,horses:pd.DataFrame, *,
                      time_limit_per_solve:float=2.5,
                      weights=(0.10,.30,.50,.70,.90)):
    """Returns (tickets, audit), or raises if even one valid allocation is not found.
    Weighted-sum MILPs search a Pareto subset; selecting max normalized E*H is
    approximate, not a proof of globally best nonlinear product.
    """
    if combo.empty or combo['race_code'].nunique()!=1:
        raise ValueError('Exactly one race required')
    horses=horses.copy()
    if len(horses)<3 or horses['umaban'].duplicated().any():
        raise ValueError('Invalid horse identities')
    n_h=len(horses)
    if n_h>18: raise ValueError('Maximum supported runners: 18')
    from math import comb
    expected=comb(n_h,2)+comb(n_h,3)
    if len(combo)!=expected or combo.duplicated(['bet_type','kumiban']).any():
        raise ValueError('Incomplete/duplicate combo frame')
    if set(combo['bet_type'])!={'umaren','sanrenpuku'}:
        raise ValueError('Both bet types required')
    if not np.isfinite(combo[['ai_probability','decimal_odds']].to_numpy(dtype=float)).all():
        raise ValueError('Nonfinite inputs')
    if (combo[['ai_probability','decimal_odds']]<=0).any().any():
        raise ValueError('Nonpositive probabilities/odds')
    for k in ('umaren','sanrenpuku'):
        if abs(combo.loc[combo.bet_type==k,'ai_probability'].sum()-1)>1e-5:
            raise ValueError('Invalid combo probabilities')
    combo=combo.copy().reset_index(drop=True)
    from itertools import combinations
    for kind,k in [('umaren',2),('sanrenpuku',3)]:
        expect={''.join(f'{h:02d}' for h in hs) for hs in combinations(sorted(horses.umaban.astype(int)),k)}
        if set(combo.loc[combo.bet_type==kind,'kumiban'])!=expect:
            raise ValueError('Wrong or missing combination IDs: '+kind)
    combo['min_units']=np.ceil(TARGET_RETURN / (UNIT*combo.decimal_odds) - 1e-12).astype(int).clip(lower=1)
    combo=combo[combo.min_units<=BUDGET//UNIT].reset_index(drop=True)
    if combo.empty:
        raise ValueError('No feasible odds to meet single-win return')
    n=len(combo)
    cap_units=np.maximum(combo.min_units.to_numpy(dtype=int),
                         DISCRETIONARY_STAKE_CAP_YEN//UNIT)
    scenario=_ordered_outcomes(horses)
    m=len(scenario)
    lookup={(r.bet_type,r.kumiban):i for i,r in combo.iterrows()}
    # decision variables: binary ticket switch, integer stake units, continuous coverage per outcome
    lower=np.zeros(2*n+m)
    upper=np.concatenate([np.ones(n), cap_units.astype(float), np.ones(m)])
    integrality=np.concatenate([np.ones(2*n),np.zeros(m)]).astype(int)
    rows=[];cols=[];vals=[];lo=[];hi=[]
    def add_constraint(items,lb,ub):
        q=len(lo);lo.append(lb);hi.append(ub)
        for c,v in items:
            rows.append(q);cols.append(c);vals.append(v)
    add_constraint([(n+i,1.) for i in range(n)],BUDGET//UNIT,BUDGET//UNIT)
    for i,r in combo.iterrows():
        add_constraint([(i,float(r.min_units)),(n+i,-1.)],-np.inf,0)
        add_constraint([(i,-float(cap_units[i])),(n+i,1.)],-np.inf,0)
    scenario_probs=[]
    for si,(pr,t1,k1,t2,k2) in enumerate(scenario):
        scenario_probs.append(pr)
        inds=[lookup[key] for key in ((t1,k1),(t2,k2)) if key in lookup]
        add_constraint([(2*n+si,1.)]+[(index,-1.) for index in inds],-np.inf,0)
    mat=coo_matrix((vals,(rows,cols)),shape=(len(lo),2*n+m)).tocsc()
    constraints=LinearConstraint(mat,np.array(lo),np.array(hi))
    # Winsorized *ranking* proxy prevents astronomical parimutuel prices
    # from dominating optimization under poorly calibrated tail probabilities.
    # Real odds remain unchanged on saved tickets and in settlement.
    ev_ticket=(combo.ai_probability*np.minimum(combo.decimal_odds, VALUE_ODDS_CEILING)).to_numpy(dtype=float)
    raw_ev_ticket=(combo.ai_probability*combo.decimal_odds).to_numpy(dtype=float)
    e_ref=max(ev_ticket)*BUDGET
    scen_p=np.array(scenario_probs)
    solutions=[]
    for w in weights:
        objective=np.zeros(2*n+m)
        objective[n:2*n]=-(w * UNIT * ev_ticket / e_ref)
        objective[2*n:]= -((1-w) * scen_p)
        res=milp(objective, integrality=integrality, bounds=Bounds(lower,upper),
                 constraints=constraints,options={'time_limit':time_limit_per_solve,'mip_rel_gap':0.06})
        if res.x is None:
            continue
        x=np.rint(res.x[:n]).astype(int)
        units=np.rint(res.x[n:2*n]).astype(int)
        if (units.sum()!=BUDGET//UNIT or
            np.any(units < x*combo.min_units.to_numpy()) or
            np.any(units > x*cap_units) or
            not np.array_equal((units>0).astype(int),x)):
            continue
        active={(row.bet_type,row.kumiban) for j,row in combo.iterrows() if x[j]}
        h=float(sum(pr for pr,t1,k1,t2,k2 in scenario if (t1,k1) in active or (t2,k2) in active))
        e=float(UNIT * np.dot(units,ev_ticket))
        raw_e=float(UNIT * np.dot(units,raw_ev_ticket))
        solutions.append((e,h,raw_e,units,res.status,res.message,w))
    if not solutions:raise RuntimeError('Optimizer found no verified feasible solution')
    # E_ref is exact upper bound for expected payouts.
    # H_ref is best incumbent hit chance; report approximate status when search non-optimal.
    h_ref=max(q[1] for q in solutions)
    attainable_e=max(q[0] for q in solutions)
    chosen=max(solutions,key=lambda z:(z[0]/attainable_e)*(z[1]/max(h_ref,1e-12)))
    e,h,raw_e,units,status,message,w=chosen
    chosen_df=combo[units>0].copy()
    chosen_df['stake']=(units[units>0]*UNIT).astype(int)
    chosen_df['ev']=chosen_df.ai_probability*chosen_df.decimal_odds
    stake=chosen_df.stake.to_numpy(dtype=int)
    max_legal=np.maximum(chosen_df.min_units.to_numpy(dtype=int)*UNIT,DISCRETIONARY_STAKE_CAP_YEN)
    if stake.sum()!=BUDGET or np.any(stake>max_legal) or np.any(stake%UNIT):
        raise RuntimeError('V2 concentration or budget invariant failed')
    single_payout=stake*chosen_df.decimal_odds.to_numpy(dtype=float)
    if (single_payout<TARGET_RETURN-1e-7).any():
        raise RuntimeError('Ticket return floor failed')
    audit={'record_type':'allocation_audit','rule':'balanced_A_v2',
           'ticket_count':len(chosen_df),'budget_yen':int(stake.sum()),
           'umaren_count':int((chosen_df.bet_type=='umaren').sum()),
           'sanrenpuku_count':int((chosen_df.bet_type=='sanrenpuku').sum()),
           'largest_ticket_stake_yen':int(stake.max()),
           'largest_ticket_stake_share_percent':float(stake.max()/BUDGET*100),
           'maximum_potential_single_ticket_payout_yen':float(single_payout.max()),
           'minimum_ticket_return_yen':float(single_payout.min()),
           'robust_expected_payout_proxy_yen':e,
           'raw_model_expected_payout_yen_NOT_for_decision':raw_e,
           'probability_any_win':h,
           'value_odds_ceiling_for_rank_only':VALUE_ODDS_CEILING,
           'discretionary_stake_cap_yen':DISCRETIONARY_STAKE_CAP_YEN,
           'E_ref_proxy_upper_bound':e_ref,'H_ref_incumbent':h_ref,
           'weights_attempted':list(weights),
           'solutions_found':len(solutions),'selected_weight':w,
           'solver_status':int(status),'solver_message':message,
           'global_optimality_proven':False}
    return chosen_df,audit
