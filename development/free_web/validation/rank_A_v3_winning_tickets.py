"""Historical A v3 ranking audit for three retrospective winning pair wagers.
Rank is DESCRIPTIVE, not the optimization's selection order: it sorts full
tickets by expected return multiple or by model hit probability. Uses FINAL odds.
Do not modify live race records, archived predictions, or settled tickets.
"""
from __future__ import annotations
import json,sys
from pathlib import Path
import pandas as pd
import requests
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from corrected_v2_core import generate_combinations
from odds import parse as parse_odds
import validate_recent_balanced_v3 as recent
import replay_ireland_saudi_A_v3 as saudi

CASES=[
    {"race":"2026092706040911","web":"2606040911","name":"スプリンターズS",
     "pair":"0616","size":16,"expected_bets":94,
     "record":"development/free_web/samples/retrospective_pipeline_20260927.json"},
    {"race":"2026101005040311","web":"2605040311","name":"サウジアラビアRC",
     "pair":"0304","size":11,"expected_bets":83,
     "record":None},
    {"race":"2026101705040611","web":"2605040611","name":"富士S",
     "pair":"1013","size":14,"expected_bets":80,
     "record":"predictions/free52/2026101705040611.json"}
]
def analyze(spec):
    if spec['record']:
        rec=json.loads(Path(spec['record']).read_text())
        horse_records=rec['horse_probabilities']
        case=next(c for c in recent.CASES if c['race']==spec['race'])
        old=recent.run(case)
        tickets=pd.DataFrame(old['tickets']).rename(columns={"type":"bet_type"})
    else:
        case=next(c for c in saudi.CASES if c['race']==spec['race'])
        horse_records=[{'umaban':num,'win_probability':w,'top3_probability':t}
                       for num,w,t in case['horse_probabilities']]
        old=saudi.run(case)
        tickets=pd.DataFrame(old['selected_bets'])
    if old['payout_yen']<=0 or len(tickets)!=spec['expected_bets']:
        raise ValueError("Historical simulation changed, do not treat as original: "+str(spec['race']))
    h=pd.DataFrame(horse_records)
    h['race_code']=spec['race']
    assert len(h)==spec['size']
    probs=generate_combinations(h)
    sess=requests.Session()
    sess.headers.update({"User-Agent":"Mozilla/5.0 (historical audit)"})
    rows=[]
    sources={}
    for kind,market in (("umaren","ur"),("sanrenpuku","sf")):
        url=f'https://sports.yahoo.co.jp/keiba/race/odds/{market}/{spec["web"]}?ninki=0'
        resp=sess.get(url,timeout=40);resp.raise_for_status()
        parsed=parse_odds(resp.text,spec['race'],kind,list(range(1,spec['size']+1)))
        if parsed['status']!='final_postrace':
            raise ValueError("Not confirmed final odds for "+kind)
        rows.extend(parsed['rows'])
        sources[kind]={"url":url,"count":len(parsed['rows']),"updated":parsed['source_updated_at_text']}
    universe=probs.merge(pd.DataFrame(rows),on=['race_code','bet_type','kumiban'],validate='one_to_one')
    assert len(universe)==len(probs)
    universe['ev']=universe['ai_probability']*universe['decimal_odds']
    if 'ev' not in tickets:
        tickets['ev']=tickets['ai_probability']*tickets['odds_used'] if 'odds_used' in tickets else tickets['ai_probability']*tickets['decimal_odds']
    key=spec['pair']
    target=universe.loc[(universe.bet_type=='umaren')&(universe.kumiban==key)]
    if len(target)!=1:raise ValueError("Winning pair missing")
    picked=tickets.loc[(tickets.bet_type=='umaren')&(tickets.kumiban==key)]
    if len(picked)!=1 or int(picked.iloc[0]['payout_yen'])<=0:raise ValueError("Winner not selected")
    def rank(df,column):
        order=df.sort_values([column,'bet_type','kumiban'],ascending=[False,True,True]).reset_index(drop=True)
        match=order.index[(order.bet_type=='umaren')&(order.kumiban==key)]
        if len(match)!=1:raise ValueError("Winner rank missing")
        return int(match[0])+1
    only_all=universe[universe.bet_type=='umaren']
    only_bought=tickets[tickets.bet_type=='umaren']
    t=target.iloc[0]
    return {
      'race':spec['race'],'name':spec['name'],'winner_pair':key,
      'payout_yen':int(old['payout_yen']),
      'stake_yen':int(picked.iloc[0]['stake_yen']),
      'all_bets_count':len(universe),'all_umaren_count':len(only_all),
      'purchased_bets_count':len(tickets),'purchased_umaren_count':len(only_bought),
      'winner_ai_probability':float(t.ai_probability),
      'winner_final_odds':float(t.decimal_odds),
      'winner_ev_gross_multiple':float(t.ev),
      'universe_ev_rank_all':rank(universe,'ev'),
      'universe_probability_rank_all':rank(universe,'ai_probability'),
      'universe_ev_rank_umaren':rank(only_all,'ev'),
      'universe_probability_rank_umaren':rank(only_all,'ai_probability'),
      'purchased_ev_rank_all':rank(tickets,'ev'),
      'purchased_probability_rank_all':rank(tickets,'ai_probability'),
      'purchased_ev_rank_umaren':rank(only_bought,'ev'),
      'purchased_probability_rank_umaren':rank(only_bought,'ai_probability'),
      'final_odds_sources':sources
    }
def main():
    cases=[]
    for spec in CASES: cases.append(analyze(spec))
    target=Path('development/free_web/validation/rank_A_v3_winning_tickets_result.json')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps({
       "record_type":"historical_final_odds_winning_pair_rank_analysis",
       "not_live_pre_race_performance":True,
       "note":"A v3 makes portfolio choice with E and H, not simple top-N. Rankings are descriptive among all or selected combinations.",
       "cases":cases},ensure_ascii=False,indent=2)+"\n")
    print('RANKED_A_V3_WINNING='+json.dumps(cases,ensure_ascii=False,separators=(',',':')))
if __name__=="__main__":main()
