"""Historical full-final-odds replay, A v3. Not an immutable pre-race prediction.

Inputs: output of unchanged private trained no-workout 52-feature WIN/TOP3
model, using October 9 or 10 as-of history cutoff, current public entries,
and source-verified public previous running positions.
NO private model/feature/history bytes stored in this public source.
Saudi race 2 missing pre-race history records (Demian/Satono Hakumai) were
supplemented in-memory from earlier independently verifiable public results,
without modifying historical source archive or trained model.

This run uses FINAL odds; post-race-only and not a live performance claim.
"""
from __future__ import annotations
from pathlib import Path
from itertools import permutations
import json,datetime as dt,traceback,sys
import pandas as pd
import requests
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from corrected_v2_core import generate_combinations
from balanced_A_v3 import allocate_balanced
from odds import parse as parse_odds

CASES=[
 dict(date='2026-10-10',race='2026101005040311',name='サウジアラビアロイヤルカップ G3',
  web='2605040311',winner={'umaren':'0304','sanrenpuku':'030405'},
  payout_per_100={'umaren':5180,'sanrenpuku':3400},
  source_url='https://www.jra.go.jp/datafile/seiseki/replay/2026/092.html',
  extra_private_history_correction=True,
  horse_probabilities=[[1,0.045400775078366554,0.2498302938342448],[2,0.06745257759488965,0.21263235991716342],[3,0.06898242852957377,0.3115328621155174],[4,0.06126356210168347,0.19525624514515005],[5,0.16495309653951062,0.5212370399460882],[6,0.0752085401939314,0.22909249592740594],[7,0.06541256521866501,0.1631938131404554],[8,0.05033062587456865,0.19188028852122901],[9,0.04641778969225521,0.15934292394463165],[10,0.03706491459175072,0.1637913149216393],[11,0.03583034848854842,0.16968596917316478]]),
 dict(date='2026-10-11',race='2026101105040411',name='アイルランドトロフィー G2',
  web='2605040411',winner={'umaren':'1516','sanrenpuku':'111516'},
  payout_per_100={'umaren':1110,'sanrenpuku':2100},
  source_url='https://www.jra.go.jp/datafile/seiseki/replay/2026/093.html',
  extra_private_history_correction=False,
  horse_probabilities=[[1,0.03717650725880181,0.14212678247211644],[2,0.04600403491838309,0.17940636933484383],[3,0.05446065223320228,0.2596021847348523],[4,0.024149861441751644,0.09903909354607712],[5,0.0599749369798831,0.19882127505639277],[6,0.017211776313431428,0.06627824473394753],[7,0.08194840076359358,0.27469250091507574],[8,0.07853909665711811,0.22151252689434348],[9,0.12453380032824751,0.2930379976112827],[10,0.05463880040779088,0.21367004847551205],[11,0.04961113278134657,0.2176407626693963],[12,0.046072512343048676,0.15885515162757496],[13,0.05943481327656261,0.10521874558072843],[14,0.05638315360806084,0.22515295501827826],[15,0.07549317128256272,0.2839390671926742],[16,0.15699341913364542,0.4042672974086356]])
]
DEST=Path('development/free_web/validation/ireland_saudi_A_v3_full_result.json')
def run(case):
    h=pd.DataFrame([{'race_code':case['race'],'umaban':num,'win_probability':win,
            'top3_probability':top3} for num,win,top3 in case['horse_probabilities']])
    assert sorted(h.umaban)==list(range(1,len(h)+1)) and len(h) in (11,16)
    combos=generate_combinations(h)
    sess=requests.Session()
    sess.headers.update({'User-Agent':'Mozilla/5.0 (historical audit)','Accept-Language':'ja-JP,ja;q=0.9'})
    odds=[];sources={}
    for typ,market in [('umaren','ur'),('sanrenpuku','sf')]:
        url=f'https://sports.yahoo.co.jp/keiba/race/odds/{market}/{case["web"]}?ninki=0'
        res=sess.get(url,timeout=40);res.raise_for_status()
        parsed=parse_odds(res.text,case['race'],typ,list(h.umaban))
        if parsed['status']!='final_postrace':
            raise RuntimeError('Not final odds: '+typ)
        sources[typ]={'url':url,'count':len(parsed['rows']),'updated_at':parsed['source_updated_at_text'],'status':parsed['status']}
        odds.extend(parsed['rows'])
    combined=combos.merge(pd.DataFrame(odds),on=['race_code','bet_type','kumiban'],how='outer',indicator=True,validate='one_to_one')
    if not combined._merge.eq('both').all():raise ValueError('Missing/extra historical final odds')
    selected,audit=allocate_balanced(combined.drop(columns='_merge'),h)
    if selected.empty or selected.stake.sum()!=10000 or any(selected.stake!=selected.min_units*100):
        raise RuntimeError('Failed fixed-minimum total stake condition')
    bets=[]
    for r in selected.itertuples():
        matched=(r.kumiban==case['winner'][r.bet_type])
        payout=(int(r.stake)//100)*case['payout_per_100'][r.bet_type] if matched else 0
        bets.append({'bet_type':r.bet_type,'kumiban':r.kumiban,'stake_yen':int(r.stake),
            'decimal_odds':float(r.decimal_odds),'ai_probability':float(r.ai_probability),
            'ev_gross_multiplier':float(r.ev),'payout_yen':payout})
    gross=sum(t['payout_yen'] for t in bets)
    # Equal weighting of all possible ordered 1st-2nd-3rd outcomes;
    # conditional on at least one selected ticket being a winner.
    wagers={(t['bet_type'],t['kumiban']):t['stake_yen']*t['decimal_odds'] for t in bets}
    if_hit=[]
    for first,second,third in permutations(h.umaban,3):
        pair=''.join(f'{a:02d}' for a in sorted((first,second)))
        tri=''.join(f'{a:02d}' for a in sorted((first,second,third)))
        p=wagers.get(('umaren',pair),0)+wagers.get(('sanrenpuku',tri),0)
        if p>0:if_hit.append(p)
    if_hit.sort()
    return {
        'status':'ok','race_code':case['race'],'race_name':case['name'],'race_date':case['date'],
        'is_live_prediction':False,'test_kind':'retrospective_final_odds_52_model_A_v3',
        'trained_model_unchanged':True,'used_result_labels_as_features':False,
        'supplemented_old_historical_records_in_memory':case['extra_private_history_correction'],
        'horse_count':len(h),'all_probabilities':h.to_dict('records'),
        'winning_combination':case['winner'],'payout_per_100':case['payout_per_100'],
        'result_source_url':case['source_url'],'odds_sources':sources,
        'investment_yen':10000,'payout_yen':gross,'profit_yen':gross-10000,
        'recovery_percent':gross/100,'any_bet_hit':gross>0,
        'bet_count':len(bets),
        'umaren_count':sum(x['bet_type']=='umaren' for x in bets),
        'sanrenpuku_count':sum(x['bet_type']=='sanrenpuku' for x in bets),
        'winning_bets':[x for x in bets if x['payout_yen']],
        'winning_umaren_selected':any(x['kumiban']==case['winner']['umaren'] and x['bet_type']=='umaren' for x in bets),
        'winning_sanrenpuku_selected':any(x['kumiban']==case['winner']['sanrenpuku'] and x['bet_type']=='sanrenpuku' for x in bets),
        'minimum_only_invariant':all(x['stake_yen']==100*int(r.min_units) for x,r in zip(bets,selected.itertuples())),
        'max_ticket_stake_yen':max(x['stake_yen'] for x in bets),
        'conditional_unweighted_mean_payout_yen':sum(if_hit)/len(if_hit),
        'conditional_unweighted_median_payout_yen':if_hit[len(if_hit)//2],
        'num_hit_scenarios':len(if_hit),
        'model_prob_any_hit':audit['probability_any_win'],
        'allocation_audit':audit,'selected_bets':bets
    }
def main():
    reports=[]
    for c in CASES:
        try: reports.append(run(c))
        except Exception as e:reports.append({'race_code':c['race'],'race_name':c['name'],'status':'error',
                'error':str(e),'traceback':traceback.format_exc()[-700:]})
    DEST.parent.mkdir(parents=True,exist_ok=True)
    DEST.write_text(json.dumps({'record_type':'retrospective_52_model_A_v3_two_races',
        'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'live_performance':False,'cases':reports},ensure_ascii=False,indent=2)+'\n')
    keys=['race_code','race_name','status','error','horse_count','bet_count','umaren_count','sanrenpuku_count','investment_yen','payout_yen','profit_yen','recovery_percent','any_bet_hit','winning_bets','winning_umaren_selected','winning_sanrenpuku_selected','minimum_only_invariant','max_ticket_stake_yen','conditional_unweighted_mean_payout_yen','conditional_unweighted_median_payout_yen','model_prob_any_hit','num_hit_scenarios','supplemented_old_historical_records_in_memory']
    print('A_V3_IRELAND_SAUDI_RESULT='+json.dumps([{k:v[k] for k in keys if k in v} for v in reports],ensure_ascii=False,separators=(',',':')))
    return 0 if all(x['status']=='ok' for x in reports) else 2
if __name__=='__main__':sys.exit(main())
