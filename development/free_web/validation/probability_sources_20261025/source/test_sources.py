"""Check that AI-only and market-only exclude the opposite information source."""
import importlib.util,numpy as np
spec=importlib.util.spec_from_file_location('source_study','probability_sources_20261025/replay.py')
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
r={'race_code':'2026010101010111','numbers':[1,2,3],'win':[.6,.3,.1],'top3':[.8,.7,.5],'odds':[2.,4.,5.]}
changed_market=dict(r,odds=[10.,3.,1.5]);changed_ai=dict(r,win=[.1,.2,.7],top3=[.3,.9,.8])
assert np.allclose(s.stage_scores(r,2026,'ai_only'),s.stage_scores(changed_market,2026,'ai_only'),atol=0,rtol=0)
assert np.allclose(s.stage_scores(r,2026,'market_only'),s.stage_scores(changed_ai,2026,'market_only'),atol=0,rtol=0)
h,c,events=s.study.probability_tables(r,s.stage_scores(r,2026,'market_only'));q=1/np.asarray(r['odds']);q/=q.sum()
assert np.allclose(h.win_probability,q)
p=q[0]*q[1]/(1-q[0])+q[1]*q[0]/(1-q[1]);actual=c.loc[(c.bet_type=='umaren')&(c.kumiban=='0102'),'ai_probability'].iloc[0]
assert abs(p-actual)<1e-12
assert abs(c.loc[c.bet_type=='sanrenpuku','ai_probability'].iloc[0]-1)<1e-12
print('PASS: source isolation, inverse-odds WIN, sequential pair probability, coherent triple mass')
