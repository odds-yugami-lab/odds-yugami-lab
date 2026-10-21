"""One explicit Plackett-Luce strength for horse, pair, triple and union probabilities."""
from itertools import permutations
import numpy as np
import pandas as pd
from scipy.special import softmax

def corrected_strength(horses, win_odds, alpha, beta):
    win=np.asarray(horses['win_probability'],float)
    top=np.asarray(horses['top3_probability'],float)
    price=np.asarray(win_odds,float)
    if len(win)!=len(price) or not np.isfinite(price).all() or (price<1).any():
        raise ValueError('Complete positive matching WIN odds required')
    if not (0<=alpha<=1 and 0<=beta<=2):raise ValueError('Coefficients outside frozen protocol')
    if not np.isfinite(win).all() or not np.isfinite(top).all() or (win<=0).any() or (top<=0).any():
        raise ValueError('Invalid AI probabilities')
    ai=np.sqrt(win*top);ai/=ai.sum()
    market=1/price;market/=market.sum()
    return softmax(alpha*np.log(ai)+beta*np.log(market))

def ordered_nll(log_strength, order):
    remaining=np.ones(len(log_strength),dtype=bool);loss=0.
    for idx in order:
        values=log_strength[remaining];maximum=values.max()
        loss+=maximum+np.log(np.exp(values-maximum).sum())-log_strength[idx]
        remaining[idx]=False
    return float(loss)

def probability_tables(horses, strength):
    h=horses.copy().reset_index(drop=True);s=np.asarray(strength,float).copy()
    if len(s)!=len(h) or len(h)<3 or h.umaban.duplicated().any():raise ValueError('Invalid identities')
    if not np.isfinite(s).all() or (s<=0).any():raise ValueError('Invalid rank strength')
    s/=s.sum();nums=h.umaban.astype(int).to_numpy();n=len(s)
    outcomes=np.array(list(permutations(range(n),3)),dtype=int)
    i,j,k=outcomes.T
    mass=s[i]*s[j]/(1-s[i])*s[k]/(1-s[i]-s[j])
    if not abs(mass.sum()-1)<1e-9:raise ValueError('Outcome mass does not sum to one')
    pairs=np.sort(nums[outcomes[:,:2]],axis=1)
    triples=np.sort(nums[outcomes],axis=1)
    data=[]
    for kind,keys in [('umaren',pairs),('sanrenpuku',triples)]:
        unique,indices=np.unique(keys,axis=0,return_inverse=True)
        probabilities=np.bincount(indices,weights=mass)
        if abs(probabilities.sum()-1)>1e-9:raise ValueError('Combination probability mismatch')
        data.extend({'race_code':str(h.race_code.iloc[0]),'bet_type':kind,
                     'kumiban':''.join(f'{x:02d}' for x in key),'ai_probability':float(p)}
                    for key,p in zip(unique,probabilities))
    win=np.bincount(i,weights=mass,minlength=n)
    top=np.bincount(outcomes.ravel(),weights=np.repeat(mass,3),minlength=n)
    assert np.allclose(win,s) and abs(top.sum()-3)<1e-9
    h['raw_saved_win_probability']=h['win_probability']
    h['raw_saved_top3_probability']=h['top3_probability']
    h['rank_strength']=s
    h['win_probability']=win;h['top3_probability']=top
    return h,pd.DataFrame(data)
