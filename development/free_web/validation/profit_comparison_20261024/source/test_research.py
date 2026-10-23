"""Known-cost example distinguishes gross payout from net profit."""
import sys
import numpy as np,pandas as pd
sys.path.insert(0,'decomposition_20261021')
from rankwise import probability_tables
from allocator_research import allocate
def main():
    r={'race_code':'2026010101010111','numbers':[1,2,3]}
    _,c,events=probability_tables(r,np.zeros((3,3)))
    c['decimal_odds']=np.where(c.bet_type.eq('umaren'),2.,100.)
    outputs={}
    for name,net,flt in [('gross',False,False),('net',True,False),('filtered',False,True),('both',True,True)]:
        t,a=allocate(c,r['numbers'],events,expected_payout_scale=10000.,time_limit=10,mip_relative_gap=0,net_profit=net,nonnegative_only=flt)
        outputs[name]=(t,a)
        assert t.stake.sum()<=10000 and (t.stake*t.decimal_odds>=10000-1e-8).all()
        assert abs(a['probability_any_win']-1)<1e-10
        if flt:assert (t.ai_probability*t.decimal_odds>=1-1e-10).all()
    # Triple covers every scenario. Gross E still buys a losing pair; net E does not.
    assert len(outputs['gross'][0])==2
    for name in ['net','filtered','both']:
        t,a=outputs[name];assert len(t)==1 and t.iloc[0].bet_type=='sanrenpuku' and t.stake.sum()==100
        assert abs(a['expected_net_profit_yen']-9900)<1e-8
    print('PASS: gross/net cost distinction,EV filter,joint coverage,budget,min-stake invariants')
if __name__=='__main__':main()
