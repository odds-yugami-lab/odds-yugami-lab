"""Exact rank-dependent sequential probabilities; all marginals share one mass."""
from functools import lru_cache
from itertools import permutations
import numpy as np,pandas as pd
from scipy.optimize import minimize
from scipy.special import logsumexp,softmax

METHODS={'market_PL':0,'shared_ai_market':2,'stage_market':3,'stage_shared_ai':4,'stage_two_heads':5}

def design(race,method):
    w=np.log(np.clip(race['win'],1e-12,1));t=np.log(np.clip(race['top3'],1e-12,1))
    q=1/np.asarray(race['odds'],float);q/=q.sum();market=np.log(q);g=(w+t)/2
    n=len(w);p=METHODS[method];x=np.zeros((3,n,p))
    if method=='shared_ai_market':x[:,:,0]=g;x[:,:,1]=market
    elif method=='stage_market':
        for stage in range(3):x[stage,:,stage]=market
    elif method=='stage_shared_ai':
        x[:,:,0]=g
        for stage in range(3):x[stage,:,stage+1]=market
    elif method=='stage_two_heads':
        x[0,:,0]=w;x[1:,:,1]=t
        for stage in range(3):x[stage,:,stage+2]=market
    return x

def scores(race,method,parameters):
    if method=='market_PL':
        q=1/np.asarray(race['odds'],float);q/=q.sum()
        return np.repeat(np.log(q)[None,:],3,axis=0)
    return np.einsum('tnp,p->tn',design(race,method),np.asarray(parameters))

def observed_losses(stage_scores,order):
    available=np.ones(stage_scores.shape[1],bool);losses=[]
    for stage,chosen in enumerate(order):
        losses.append(float(logsumexp(stage_scores[stage,available])-stage_scores[stage,chosen]))
        available[chosen]=False
    return losses

def fit(races,method):
    if method=='market_PL':return {'method':method,'parameters':[],'success':True,'free_parameters':0}
    p=METHODS[method];count=len(races);n=max(len(r['win']) for r in races)
    features=np.zeros((count,3,n,p));mask=np.zeros((count,3,n),bool);orders=[]
    for ri,r in enumerate(races):
        size=len(r['win']);features[ri,:,:size,:]=design(r,method)
        mask[ri,:,:size]=True;order=list(r['order']);orders.append(order)
        mask[ri,1,order[0]]=False;mask[ri,2,order[:2]]=False
    orders=np.asarray(orders,int)
    picked=features[np.arange(count)[:,None],np.arange(3)[None,:],orders]
    def objective(theta):
        value=np.einsum('rtnp,p->rtn',features,theta);value=np.where(mask,value,-np.inf)
        normalizer=logsumexp(value,axis=2)
        prob=np.exp(value-normalizer[:,:,None])
        loss=np.sum(normalizer-np.einsum('rtp,p->rt',picked,theta))/count
        gradient=(np.sum(prob[:,:,:,None]*features,axis=(0,1,2))-np.sum(picked,axis=(0,1)))/count
        return float(loss),gradient
    bounds={
        'shared_ai_market':[(0,1),(0,2)],'stage_market':[(0,2)]*3,
        'stage_shared_ai':[(0,1)]+[(0,2)]*3,
        'stage_two_heads':[(0,1)]*2+[(0,2)]*3}[method]
    start={'shared_ai_market':[.5,.8],'stage_market':[1.,.8,.7],
        'stage_shared_ai':[.5,1.,.8,.7],'stage_two_heads':[.5,.5,1.,.8,.7]}[method]
    result=minimize(objective,start,jac=True,method='L-BFGS-B',bounds=bounds,
        options={'ftol':1e-12,'gtol':1e-7,'maxiter':2000})
    gradient=result.jac.copy()
    for j,(lo,hi) in enumerate(bounds):
        if result.x[j]<=lo+1e-7 and gradient[j]>0:gradient[j]=0
        if result.x[j]>=hi-1e-7 and gradient[j]<0:gradient[j]=0
    if not result.success and np.max(np.abs(gradient))>1e-5:raise RuntimeError(str(result.message))
    return {'method':method,'parameters':result.x.tolist(),'success':bool(result.success),
        'projected_gradient_max':float(np.max(np.abs(gradient))),'fit_nll':float(result.fun),'free_parameters':p}

@lru_cache(maxsize=20)
def outcome_indices(n):return np.array(list(permutations(range(n),3)),dtype=int)

def distribution(stage_scores):
    stage_scores=np.asarray(stage_scores,float);n=stage_scores.shape[1]
    if stage_scores.shape!=(3,n) or n<3 or not np.isfinite(stage_scores).all():raise ValueError('Invalid rank scores')
    order=outcome_indices(n);i,j,k=order.T
    weights=np.exp(stage_scores-stage_scores.max(axis=1,keepdims=True))
    sums=weights.sum(axis=1)
    mass=weights[0,i]/sums[0]*weights[1,j]/(sums[1]-weights[1,i])*weights[2,k]/(sums[2]-weights[2,i]-weights[2,j])
    if not np.isfinite(mass).all() or (mass<=0).any() or abs(mass.sum()-1)>1e-9:raise ValueError('Invalid ordered outcome probability')
    win=np.bincount(i,weights=mass,minlength=n)
    top=np.bincount(order.ravel(),weights=np.repeat(mass,3),minlength=n)
    assert np.allclose(win,softmax(stage_scores[0])) and abs(top.sum()-3)<1e-9
    return order,mass,win,top

def probability_tables(race,stage_scores):
    order,mass,win,top=distribution(stage_scores);nums=np.asarray(race['numbers'],int)
    if len(set(nums))!=len(nums):raise ValueError('Duplicate horse number')
    pair_keys=np.sort(nums[order[:,:2]],axis=1);triple_keys=np.sort(nums[order],axis=1)
    rows=[]
    for kind,keys in [('umaren',pair_keys),('sanrenpuku',triple_keys)]:
        unique,index=np.unique(keys,axis=0,return_inverse=True)
        probabilities=np.bincount(index,weights=mass)
        assert abs(probabilities.sum()-1)<1e-9
        rows.extend({'race_code':race['race_code'],'bet_type':kind,'kumiban':''.join(f'{v:02d}' for v in key),
            'ai_probability':float(p)} for key,p in zip(unique,probabilities))
    scenarios=[(float(p),'umaren',''.join(f'{v:02d}' for v in pair),'sanrenpuku',''.join(f'{v:02d}' for v in triple))
        for p,pair,triple in zip(mass,pair_keys,triple_keys)]
    horses=pd.DataFrame({'race_code':race['race_code'],'umaban':nums,'win_probability':win,'top3_probability':top})
    return horses,pd.DataFrame(rows),scenarios
