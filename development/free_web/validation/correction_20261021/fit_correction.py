"""Fit two strength coefficients using 2025 only. Do not read 2026 outcomes."""
import argparse, datetime as dt, hashlib, json
from pathlib import Path
import numpy as np, pandas as pd
from scipy.optimize import minimize
from strength_calibration import ordered_nll

def main(workdir):
    root=Path(workdir);df=pd.read_json(root/'private_assets/predictions_2025.json',dtype={'race_code':str,'ketto_toroku_bango':str})
    fit_data=[];exclusions=[];sources=[]
    for code,g in df.groupby('race_code',sort=True):
        g=g.sort_values('umaban').reset_index(drop=True)
        path=root/'cache/market'/(code+'.json')
        if not path.exists():exclusions.append({'race_code':code,'reason':'market unavailable'});continue
        market=json.loads(path.read_text());mp={r['umaban']:r for r in market['runners']}
        if set(g.umaban.astype(int))!=set(mp) or len(g)!=int(g.field_size.max()):
            exclusions.append({'race_code':code,'reason':'incomplete archive or starter mismatch'});continue
        if any(str(r.ketto_toroku_bango)!=mp[int(r.umaban)]['horse_id'] for r in g.itertuples()):
            raise ValueError('Horse identity mismatch: '+code)
        first=g[g.target_finish_position.between(1,3)].sort_values('target_finish_position')
        if first.target_finish_position.tolist()!=[1,2,3]:
            exclusions.append({'race_code':code,'reason':'missing/nonunique top3 ranking (including dead heat)'});continue
        ai=np.sqrt(g.win_probability.to_numpy()*g.top3_probability.to_numpy());ai/=ai.sum()
        odds=np.array([mp[int(x)]['decimal_win_odds'] for x in g.umaban]);q=1/odds;q/=q.sum()
        order=first.index.to_numpy()
        fit_data.append((code,np.log(ai),np.log(q),order))
        sources.append({k:market[k] for k in ['race_code','source_url','retrieved_at','page_sha256']})
    if len(fit_data)<100:raise ValueError('Insufficient complete 2025 calibration races')
    def objective(params):
        a,b=params
        return np.mean([ordered_nll(a*ai+b*market,order) for _,ai,market,order in fit_data])
    result=minimize(objective,np.array([.5,.5]),method='L-BFGS-B',bounds=[(0.,1.),(0.,2.)],
        options={'ftol':1e-12,'gtol':1e-7,'maxiter':1000})
    if not result.success:raise RuntimeError(str(result.message))
    a,b=map(float,result.x)
    coefficient={'version':'market_strength_calibration_v1_20261021','alpha_ai':a,'beta_market':b,
        'fitted_on_year':2025,'fitted_races':len(fit_data),'2026_labels_used_for_fitting':False,
        'fit_ordered_top3_nll':float(result.fun),'old_strength_nll':objective([1.,0.]),
        'market_only_nll':objective([0.,1.]),'optimizer_success':bool(result.success),
        'gradient':result.jac.tolist(),'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'fit_race_codes':[r[0] for r in fit_data],'exclusions':exclusions,'market_sources':sources,
        'protocol_sha256':hashlib.sha256((root/'public/protocol.json').read_bytes()).hexdigest(),
        'production_activated':False,'test_only':True}
    (root/'private_assets/correction_coefficients.json').write_text(json.dumps(coefficient,ensure_ascii=False,indent=2)+'\n')
    public={k:v for k,v in coefficient.items() if k not in ['market_sources','fit_race_codes']}
    (root/'public/fit_report.json').write_text(json.dumps(public,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(public,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('workdir');a=p.parse_args();main(a.workdir)
