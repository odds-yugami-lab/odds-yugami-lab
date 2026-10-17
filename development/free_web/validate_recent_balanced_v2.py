"""Read-only retrospective A-v1 test on actual odds; NEVER writes official/live stats.

Run only with complete, confirmed final odds. Failed downloads are reported as failures,
not silently replaced with invented estimates or intermediate odds.
"""
from __future__ import annotations
import json
import pathlib
import sys
import datetime as dt
import requests
import pandas as pd
from corrected_v2_core import generate_combinations
from balanced_A_v2 import allocate_balanced
from odds import parse

ROOT = pathlib.Path(__file__).resolve().parents[2]
CASES = (
  dict(race="2026101705040611", label="2026-10-17 Fuji Stakes G2",
       prefix="2605040611",
       predictions="predictions/free52/2026101705040611.json",
       horse_field="horse_probabilities",
       winners={"umaren":"1013","sanrenpuku":"101314"},
       payouts={"umaren":12340,"sanrenpuku":27050},
       official_url="https://www.jra.go.jp/datafile/seiseki/replay/2026/095.html"),
  dict(race="2026092706040911", label="2026-09-27 Sprinters Stakes G1",
       prefix="2606040911",
       predictions="development/free_web/samples/retrospective_pipeline_20260927.json",
       horse_field="horse_probabilities",
       winners={"umaren":"0616","sanrenpuku":"050616"},
       payouts={"umaren":13560,"sanrenpuku":73620},
       official_url="https://www.jra.go.jp/datafile/seiseki/g1/sprint/result/sprint2026.html"),
)
def run(case):
    record=json.loads((ROOT/case["predictions"]).read_text())
    horses=pd.DataFrame(record[case["horse_field"]])
    nums=sorted(horses.umaban.astype(int).tolist())
    pairs=generate_combinations(horses.assign(race_code=case["race"]))
    sess=requests.Session()
    sess.headers.update({"User-Agent":"Mozilla/5.0 (compatible; historical-analysis/1.0)","Accept-Language":"ja-JP,ja;q=0.9"})
    frames=[]
    meta={}
    for kind,part in (("umaren","ur"),("sanrenpuku","sf")):
        url=f'https://sports.yahoo.co.jp/keiba/race/odds/{part}/{case["prefix"]}?ninki=0'
        response=sess.get(url,timeout=35)
        response.raise_for_status()
        odds=parse(response.text,case["race"],kind,nums)
        if odds["status"]!="final_postrace":
            raise RuntimeError(f'Final odds NOT verified for {kind}; status={odds["status"]}; page={url}')
        meta[kind]={"url":url,"count":odds["combination_count"],"updated":odds["source_updated_at_text"]}
        frames += odds["rows"]
    odds_frame=pd.DataFrame(frames)
    full=pairs.merge(odds_frame,how="outer",on=["race_code","bet_type","kumiban"],validate="one_to_one",indicator=True)
    if not full._merge.eq('both').all():
        raise RuntimeError("Incomplete combination odds or probability rows")
    tickets,audit=allocate_balanced(full.drop(columns="_merge"),horses,
       weights=(.10,.30,.50,.70,.90),time_limit_per_solve=3.0)
    result=[]
    payout=0
    for _,t in tickets.iterrows():
        official=case["payouts"].get(t.bet_type,0) if case["winners"].get(t.bet_type)==t.kumiban else 0
        got=int(t.stake)//100*official
        payout+=got
        result.append({"type":t.bet_type,"kumiban":t.kumiban,
                       "stake_yen":int(t.stake),"odds_used":float(t.decimal_odds),
                       "payout_yen":got,"ai_probability":float(t.ai_probability)})
    return dict(label=case["label"],race=case["race"],prediction_source=case["predictions"],
       final_odds=meta,results_source=case["official_url"],official_payout_per_100=case["payouts"],
       investment_yen=10000,payout_yen=payout,profit_yen=payout-10000,
       recovery_percent=payout/100.,ticket_count=len(result),allocation_audit=audit,
       tickets=result,postrace_replay=True,is_pre_race_prediction=False)
def main():
    reports=[]
    for case in CASES:
        try:reports.append({"status":"ok",**run(case)})
        except Exception as exc:
            reports.append({"race":case["race"],"label":case["label"],"status":"not_reproducible",
                 "error":str(exc)[:600],"no_fabricated_odds":True})
    dest=ROOT/"development/free_web/validation/balanced_A_v2_recent_replay_result.json"
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps({"run_time_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
      "rule":"balanced_A_v2","cases":reports},ensure_ascii=False,indent=2)+"\n")
    print(dest.read_text()[:24000])
    return 0 if all(t["status"]=="ok" for t in reports) else 2
if __name__=="__main__":sys.exit(main())
