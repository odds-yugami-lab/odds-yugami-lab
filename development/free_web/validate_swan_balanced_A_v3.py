"""Swan Stakes 2026-10-12: actual final-odds post-race A v3 replay, not live.
No private JRA model, runner features, training data or history files here.
Horse probabilities reconstructed from private 52-feature frozen model using
2026-10-11-cutoff history, captured 18-runner entry + independently matched
previous-race source evidence. Existing corrected V2 pair ranks are cross-checked.
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
import requests
import pandas as pd
from corrected_v2_core import generate_combinations
from balanced_A_v3 import allocate_balanced
from odds import parse as parse_odds

RACE='2026101208040511'
WEB='2608040511'
# umaban, win_probability, top3_probability (non-sensitive inference output)
PROBABILITIES=[[1,0.087614051454,0.17737589074],[2,0.04214106399,0.133256849953],[3,0.037965322286,0.107009246489],[4,0.014194004367,0.058429574396],[5,0.035718738863,0.1379405084],[6,0.042929633106,0.062148064962],[7,0.020334804231,0.034614842136],[8,0.063019933928,0.173807664674],[9,0.033181874015,0.140450687247],[10,0.050063182604,0.164618260961],[11,0.014680660045,0.052776578501],[12,0.031274305992,0.118379372293],[13,0.029531207199,0.17697069593],[14,0.041837698409,0.083119904535],[15,0.067223422874,0.191657298749],[16,0.024866825822,0.094083745433],[17,0.052417115751,0.204456723104],[18,0.054464618481,0.162058474617]]
WINNERS={'umaren':'0104','sanrenpuku':'010409'}
OFFICIAL_PAYOUT_PER_100={'umaren':8550,'sanrenpuku':9380}
OFFICIAL_URL='https://www.jra.go.jp/datafile/seiseki/replay/2026/094.html'
RESULT_FILE=Path('development/free_web/validation/balanced_A_v3_swan_20261012_result.json')

def run():
    horses=pd.DataFrame([{'race_code':RACE,'umaban':n,
        'win_probability':win,'top3_probability':top3}
        for n,win,top3 in PROBABILITIES])
    assert len(horses)==18 and sorted(horses.umaban)==list(range(1,19))
    combos=generate_combinations(horses)
    assert len(combos)==969
    def p(pair):
        key=''.join(f'{x:02d}' for x in pair)
        return float(combos.loc[(combos.bet_type=='umaren')&(combos.kumiban==key),'ai_probability'].iloc[0])
    # Cross-check against original frozen 52-model historical numerical test.
    assert abs(p((1,15))-0.018935828805235026)<1e-9
    assert abs(p((1,8))-0.01739440410445735)<1e-9
    assert abs(p((1,17))-0.017197535833637555)<1e-9

    sess=requests.Session()
    sess.headers.update({'User-Agent':'Mozilla/5.0 (historical graded race verification)',
                         'Accept-Language':'ja-JP,ja;q=0.9'})
    parsed=[]
    sources={}
    for kind,market,expected in [('umaren','ur',153),('sanrenpuku','sf',816)]:
        url=f'https://sports.yahoo.co.jp/keiba/race/odds/{market}/{WEB}?ninki=0'
        resp=sess.get(url,timeout=40)
        resp.raise_for_status()
        market_data=parse_odds(resp.text,RACE,kind,list(range(1,19)))
        if market_data['status']!='final_postrace' or len(market_data['rows'])!=expected:
            raise RuntimeError(f'Not complete verified final odds for {kind}')
        sources[kind]={'url':url,'updated_at':market_data['source_updated_at_text'],
                       'complete_combination_count':len(market_data['rows']),
                       'status':'final_postrace'}
        parsed.extend(market_data['rows'])

    merged=combos.merge(pd.DataFrame(parsed),how='outer',
        on=['race_code','bet_type','kumiban'],indicator=True,validate='one_to_one')
    if not merged._merge.eq('both').all():raise ValueError('Incomplete odds + probability join')
    tickets,audit=allocate_balanced(merged.drop(columns='_merge'),horses)
    if sum(tickets.stake)!=10000:raise AssertionError('Failed budget')
    if (tickets.stake!=tickets.min_units*100).any():raise AssertionError('Extra stake above minimum')
    if (tickets.stake*tickets.decimal_odds<10000-1e-7).any():raise AssertionError('Below target payout')
    # Distinct actual payout only, never mark a post-race replay as a live bet.
    bets=[];gross=0
    for _,t in tickets.iterrows():
        payout=(int(t.stake)//100)*OFFICIAL_PAYOUT_PER_100[t.bet_type] if t.kumiban==WINNERS[t.bet_type] else 0
        gross+=payout
        bets.append({'bet_type':t.bet_type,'kumiban':t.kumiban,
                     'stake_yen':int(t.stake),'decimal_odds':float(t.decimal_odds),
                     'ai_probability':float(t.ai_probability),
                     'expected_return_multiple':float(t.ev),'payout_yen':payout})
    # Arithmetic mean of payouts across ordered first/second/third combinations
    # where at least one purchased bet hits. No AI probability weighting.
    from itertools import permutations
    position_payout=[]
    stakes={(t['bet_type'],t['kumiban']):t['stake_yen']*t['decimal_odds'] for t in bets}
    for x,y,z in permutations(range(1,19),3):
        keypair=''.join(f'{a:02d}' for a in sorted((x,y)))
        keytriple=''.join(f'{a:02d}' for a in sorted((x,y,z)))
        amount=stakes.get(('umaren',keypair),0)+stakes.get(('sanrenpuku',keytriple),0)
        if amount>0:position_payout.append(amount)
    position_payout.sort()
    report={'record_type':'retrospective_full_final_odds_swan_A_v3',
      'is_pre_race_prediction':False,'counts_toward_live_performance':False,
      'race_code':RACE,'race_date':'2026-10-12','race_name':'MBS賞スワンステークス G2',
      'horse_prediction_model':'JRA_FREE_NO_WORKOUT_52_20261013',
      'horse_probabilities_reconstructed_from_historical_features':True,
      'used_2026_10_12_result_in_inference':False,
      'history_cutoff':'2026-10-11','allocation_rule':'balanced_A_v3',
      'odds_sources':sources,
      'jra_official_result_url':OFFICIAL_URL,
      'winning_combinations':WINNERS,'official_payouts_per_100':OFFICIAL_PAYOUT_PER_100,
      'total_stake_yen':int(tickets.stake.sum()),'payout_yen':gross,
      'profit_yen':gross-10000,'recovery_percent':gross/100,
      'hit':gross>0,'ticket_count':len(bets),
      'num_umaren':sum(t.bet_type=='umaren' for t in tickets.itertuples()),
      'num_sanrenpuku':sum(t.bet_type=='sanrenpuku' for t in tickets.itertuples()),
      'winning_bets':[b for b in bets if b['payout_yen']>0],
      'conditional_unweighted_mean_payout_yen':sum(position_payout)/len(position_payout),
      'conditional_unweighted_median_payout_yen':position_payout[len(position_payout)//2],
      'num_hit_outcomes':len(position_payout),
      'possible_ordered_first_three':18*17*16,
      'model_probability_any_hit':audit['probability_any_win'],
      'model_expected_payout_yen':audit['model_expected_payout_yen_full_actual_odds'],
      'max_ticket_stake_yen':max(b['stake_yen'] for b in bets),
      'minimum_only_invariant':all(b['stake_yen']==100*int(t.min_units) for b,t in zip(bets,tickets.itertuples())),
      'audit':audit,'tickets':bets}
    RESULT_FILE.parent.mkdir(parents=True,exist_ok=True)
    RESULT_FILE.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    summary={k:report[k] for k in (
        'race_code','total_stake_yen','payout_yen','profit_yen','recovery_percent',
        'hit','ticket_count','num_umaren','num_sanrenpuku','winning_bets',
        'conditional_unweighted_mean_payout_yen','conditional_unweighted_median_payout_yen',
        'num_hit_outcomes','model_probability_any_hit','model_expected_payout_yen',
        'max_ticket_stake_yen','minimum_only_invariant')}
    print('SWAN_A_V3_SUMMARY='+json.dumps(summary,ensure_ascii=False,sort_keys=True))
    print('SWAN_A_V3_ODDS_SOURCES='+json.dumps(sources,ensure_ascii=False))
    return report

if __name__=='__main__':run()
