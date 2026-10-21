"""Five final-odds operation checks; no settlement or model adoption comparison."""
import datetime as dt,json,sys
from pathlib import Path
import numpy as np,pandas as pd
from cap30_reconstruction import allocate
sys.path.insert(0,'decomposition_20261021')
from rankwise import probability_tables

def main():
    codes=['2026092706040911','2026101005040311','2026101105040411','2026101208040511','2026101705040611']
    source=json.loads(Path('base_review_20261021/private_assets/races_2026.json').read_text())['incumbent_same_input']
    results=[]
    for code in codes:
        record=next(r for r in source if r['race_code']==code)
        race={k:record[k] for k in ['race_code','numbers','win','top3']}
        stage=np.repeat(((np.log(race['win'])+np.log(race['top3']))/2)[None,:],3,axis=0)
        _,combo,scenario=probability_tables(race,stage)
        prices=json.loads((Path('bias_20261020/public_cache/odds')/(code+'.json')).read_text())['snapshots']
        odds=pd.DataFrame([r for v in prices.values() for r in v['rows']])
        merged=combo.merge(odds,on=['race_code','bet_type','kumiban'],validate='one_to_one')
        scale=float((merged.ai_probability*merged.decimal_odds).max()*10000)
        try:
            tickets,audit=allocate(merged,race['numbers'],scenario,expected_payout_scale=scale,time_limit=30.,mip_relative_gap=.01)
            result={'race_code':code,'status':'operation_check_passed','ticket_count':len(tickets),
                'umaren_tickets':int(tickets.bet_type.eq('umaren').sum()),'sanrenpuku_tickets':int(tickets.bet_type.eq('sanrenpuku').sum()),
                'stake_yen':int(tickets.stake.sum()),'exact_minimum_stakes':True,
                'audit':audit,'tickets':tickets.to_dict('records')}
        except RuntimeError as e:
            result={'race_code':code,'status':'no_feasible_solution_or_solver_failure','error':str(e),'fallback_used':False}
        results.append(result);print(code,result['status'],result.get('ticket_count'),flush=True)
    report={'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'test_only':True,
        'purpose':'Constraint and runtime checks only; no retrospective ROI or selection using outcomes.',
        'original_equivalence_certified':False,'normalizer':'max(ticket_ai_probability*decimal_odds)*10000; supported by earlier A source, not recovered cap30 source.',
        'model_probability_method':'original52 geometric strength without market correction',
        'race_outcomes_passed_to_allocator':False,'settlement_performed':False,
        'production_or_automation_changed':False,'cases':results}
    path=Path('rule_restoration_20261022/operation_checks_20261022.json')
    if path.exists():raise FileExistsError('Preserve prior check')
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
