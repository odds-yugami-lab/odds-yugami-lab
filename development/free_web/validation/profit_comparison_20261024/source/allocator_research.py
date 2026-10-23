"""Research fork2026-10-24; not a production change. Based on2026-10-23 revision: budget ceiling, retain unused cash.

This is NOT certified as the original cap30_minimum_E50 implementation.
The caller must explicitly specify the un-recovered expected-payout scale.
No production caller may use this module until the original policy is verified.
Inputs deliberately exclude labels/results; a joint scenario distribution and
full pre-race probability/price table are the only model inputs.
"""
from itertools import combinations
from math import comb
import numpy as np
import pandas as pd
from scipy.optimize import Bounds,LinearConstraint,milp
from scipy.sparse import coo_matrix

BUDGET=10000
UNIT=100
MAX_TICKETS=30

def allocate(combo,horse_numbers,scenarios,*,expected_payout_scale,
             time_limit=10.,mip_relative_gap=0.,net_profit=False,nonnegative_only=False):
    """Maximize .5 E/explicit_scale + .5 H, max30, stake<=10000.

    A single binary switch per ticket and continuous covered-outcome switches.
    Scale, time limit and gap are explicit reconstruction settings, not recovered
    historical settings. Never manufacture a fallback if constraints conflict.
    """
    if not np.isfinite(expected_payout_scale) or expected_payout_scale<=0:
        raise ValueError('An explicit positive expected-payout scale is required')
    numbers=sorted(map(int,horse_numbers));n=len(numbers)
    if n<3 or n>18 or len(set(numbers))!=n:raise ValueError('Invalid horse numbers')
    if any(col.startswith('target_') or col in {'finish_status','payout_yen'} for col in combo.columns):
        raise ValueError('Race outcomes are forbidden in allocation inputs')
    required={'race_code','bet_type','kumiban','ai_probability','decimal_odds'}
    if not required<=set(combo):raise ValueError('Missing model/odds columns')
    if combo.race_code.nunique()!=1 or combo.duplicated(['bet_type','kumiban']).any():raise ValueError('Race or ticket identity error')
    if len(combo)!=comb(n,2)+comb(n,3):raise ValueError('Incomplete combination table')
    frame=combo[['race_code','bet_type','kumiban','ai_probability','decimal_odds']].copy()
    for kind,k in [('umaren',2),('sanrenpuku',3)]:
        keys={''.join(f'{v:02d}' for v in c) for c in combinations(numbers,k)}
        selected=frame[frame.bet_type==kind]
        if set(selected.kumiban)!=keys:raise ValueError('Wrong combination identities')
        if abs(float(selected.ai_probability.sum())-1)>1e-9:raise ValueError('Invalid combination probability mass')
    values=frame[['ai_probability','decimal_odds']].to_numpy(float)
    if not np.isfinite(values).all() or (values[:,0]<=0).any() or (values[:,1]<1).any():raise ValueError('Invalid model probability or price')
    outcomes=list(scenarios)
    if len(outcomes)!=n*(n-1)*(n-2):raise ValueError('Incomplete ordered outcome table')
    mass=np.asarray([r[0] for r in outcomes],float)
    if not np.isfinite(mass).all() or (mass<=0).any() or abs(mass.sum()-1)>1e-9:raise ValueError('Invalid joint mass')
    for kind,slot in [('umaren',2),('sanrenpuku',4)]:
        marginals={}
        for event in outcomes:
            if event[slot-1]!=kind:raise ValueError('Invalid scenario bet type')
            key=event[slot];marginals[key]=marginals.get(key,0.)+event[0]
        expected={r.kumiban:r.ai_probability for r in frame[frame.bet_type==kind].itertuples()}
        if set(marginals)!=set(expected) or any(abs(marginals[k]-expected[k])>1e-9 for k in expected):raise ValueError('Joint distribution and ticket probabilities differ')
    frame['min_units']=np.ceil(10000/(100*frame.decimal_odds)-1e-12).astype(int).clip(lower=1)
    if nonnegative_only:
        frame=frame[frame.ai_probability*frame.decimal_odds>=1-1e-10].copy()
    frame=frame[frame.min_units<=BUDGET//UNIT].sort_values(['bet_type','kumiban']).reset_index(drop=True)
    count=len(frame);m=len(outcomes)
    if not count:raise RuntimeError('No feasible minimum-stake ticket')
    stakes=frame.min_units.to_numpy(int)*UNIT
    lookup={(r.bet_type,r.kumiban):i for i,r in frame.iterrows()}
    row=[];col=[];value=[];lo=[];hi=[]
    def constraint(items,lower,upper):
        idx=len(lo);lo.append(lower);hi.append(upper)
        for j,v in items:row.append(idx);col.append(j);value.append(v)
    constraint(list(enumerate(stakes.astype(float))),0,BUDGET)
    constraint([(i,1.) for i in range(count)],1,MAX_TICKETS)
    for index,event in enumerate(outcomes):
        keys={(event[1],event[2]),(event[3],event[4])}
        constraint([(count+index,1.)]+[(lookup[k],-1.) for k in keys if k in lookup],-np.inf,0.)
    matrix=coo_matrix((value,(row,col)),shape=(len(lo),count+m)).tocsc()
    ev=frame.ai_probability.to_numpy(float)*frame.decimal_odds.to_numpy(float)*stakes
    economic=ev-stakes if net_profit else ev
    objective=-np.concatenate([.5*economic/expected_payout_scale,.5*mass])
    solved=milp(objective,integrality=np.r_[np.ones(count),np.zeros(m)],
        bounds=Bounds(np.zeros(count+m),np.ones(count+m)),
        constraints=LinearConstraint(matrix,np.asarray(lo),np.asarray(hi)),
        options={'time_limit':time_limit,'mip_rel_gap':mip_relative_gap})
    if solved.x is None:raise RuntimeError('No feasible cap30 minimum-only allocation: '+str(solved.message))
    raw=solved.x[:count]
    if np.max(np.abs(raw-np.rint(raw)))>1e-5:raise RuntimeError('Noninteger incumbent')
    chosen=np.rint(raw).astype(bool);tickets=frame[chosen].copy();tickets['stake']=stakes[chosen]
    if not 1<=len(tickets)<=30 or not 0<tickets.stake.sum()<=10000:raise RuntimeError('Budget/count invariant failed')
    if (tickets.stake*tickets.decimal_odds<10000-1e-8).any():raise RuntimeError('Single-win payout invariant failed')
    if not tickets.loc[tickets.decimal_odds>=100,'stake'].eq(100).all():raise RuntimeError('High-odds extra stake is forbidden')
    active={(r.bet_type,r.kumiban) for r in tickets.itertuples()}
    hit=float(sum(e[0] for e in outcomes if (e[1],e[2]) in active or (e[3],e[4]) in active))
    expected=float(ev[chosen].sum());score=.5*float(economic[chosen].sum())/expected_payout_scale+.5*hit
    audit={'rule':'cap30_budget_ceiling_E50_v1_20261023','original_implementation_verified':False,
        'ticket_count':len(tickets),'budget_yen':int(tickets.stake.sum()),'maximum_tickets':30,
        'budget_limit_yen':10000,'unspent_yen':int(10000-tickets.stake.sum()),
        'exact_minimum_stakes_only':True,'expected_payout_yen':expected,'probability_any_win':hit,
        'expected_payout_weight':.5,'hit_probability_weight':.5,
        'expected_payout_scale_explicit':float(expected_payout_scale),'objective_value':score,
        'expected_payout_scale_historically_verified':False,'solver_settings_historically_verified':False,
        'solver_status':int(solved.status),'solver_message':str(solved.message),
        'time_limit':time_limit,'mip_relative_gap_requested':mip_relative_gap,
        'actual_mip_gap':float(solved.mip_gap),'globally_optimal_for_this_explicit_objective':bool(solved.status==0 and solved.mip_gap<1e-9),
        'production_ready':False,'research_only':True,'net_profit_objective':net_profit,
        'nonnegative_ev_only':nonnegative_only,'expected_net_profit_yen':expected-int(tickets.stake.sum()),
        'economic_objective_yen':float(economic[chosen].sum())}
    return tickets,audit
