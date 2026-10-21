"""Actual archived feature reconstruction + saved inference + calibrated allocation."""
import argparse,datetime as dt,hashlib,json,sys
from pathlib import Path
import numpy as np,pandas as pd

def main(root_string,modules,model_dir,history_dir,bundle_dir):
    root=Path(root_string);sys.path.insert(0,modules)
    from official_entries import parse as official_parse
    from feature_pipeline import assemble
    from infer_free_model import predict
    from win_odds import parse as parse_win,verify_snapshot
    from strength_calibration import corrected_strength,probability_tables
    from probability_correction import PARAMETERS,MODEL_SHA256
    from balanced_A_v3_explicit import allocate_balanced
    from official_results import fetch_for_race
    race='2026101208040511';bundle=Path(bundle_dir);model=Path(model_dir)
    stamp=dt.datetime.now(dt.timezone.utc).isoformat()
    assert {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in model.glob('*.joblib')}==MODEL_SHA256
    official=official_parse((bundle/'fixtures/swan_official_entry.html').read_text(),race,
        'https://www.jra.go.jp/JRADB/accessD.html',stamp,historical_test=True)
    evidence=json.loads((bundle/'fixtures/swan_previous_evidence.json').read_text())
    assembly=assemble((bundle/'fixtures/swan_free_entry.html').read_text(),'2608040511','entries',
        Path(history_dir)/'history.parquet',json.loads((model/'feature_spec.json').read_text()),[],stamp,'2026-10-18',
        pedigree_paths=[bundle/'fixtures/pedigree_lookup.parquet'],participation_snapshot=official,test_only=True,previous_overrides=evidence)
    runners=assembly['runners'];assert len(runners)==18 and not any(r['unpublished_or_unresolved'] for r in runners)
    out=predict(model,runners)
    (root/'private_assets/rehearsal_horse_probabilities.json').write_text(json.dumps([
        {'umaban':int(r['umaban']),'win_probability':float(w),'top3_probability':float(t)}
        for r,w,t in zip(runners,out['win'],out['top3'])],indent=2)+'\n')
    horses=pd.DataFrame({'race_code':[race]*18,'umaban':[int(r['umaban']) for r in runners],
        'ketto_toroku_bango':[r['ketto_toroku_bango'] for r in runners],'win_probability':out['win'],'top3_probability':out['top3']})
    win=parse_win((root/'cache/win_odds_example.html').read_text(),race,list(horses.umaban))
    assert win['status']=='final_postrace'
    denma={r['umaban']:r for r in json.loads((root/'cache/market'/(race+'.json')).read_text())['runners']}
    assert all(row['decimal_odds']==denma[row['umaban']]['decimal_win_odds'] for row in win['rows'])
    try:verify_snapshot(win,{'race_code':race,'race_start_at':'2026-10-12T15:30:00+09:00'},runners,dt.datetime.now(dt.timezone.utc))
    except ValueError:historical_live_rejection=True
    else:raise AssertionError('Historical WIN odds accepted as live')
    price={r['umaban']:r['decimal_odds'] for r in win['rows']}
    strength=corrected_strength(horses,[price[n] for n in horses.umaban],PARAMETERS['alpha_ai'],PARAMETERS['beta_market'])
    prediction,combo=probability_tables(horses,strength)
    sources=json.loads(Path('bias_20261020/public_cache/odds',race+'.json').read_text())['snapshots']
    odds=pd.DataFrame([r for s in sources.values() for r in s['rows']])
    merged=combo.merge(odds,on=['race_code','bet_type','kumiban'],validate='one_to_one')
    tickets,audit=allocate_balanced(merged,prediction)
    comparison=json.loads((root/'private_assets/evaluation'/race/'corrected.json').read_text())
    matches_comparison={(r.bet_type,r.kumiban,int(r.stake)) for r in tickets.itertuples()}=={(r['bet_type'],r['kumiban'],r['stake']) for r in comparison['tickets']}
    payouts=fetch_for_race(race)
    record={'status':'prepared_not_published','race_code':race,'race_name':'スワンS・確率補正版の過去動作テスト',
        'test_only':True,'odds_status':'final_postrace','is_live_operation_ready':False,'total_stake_yen':10000,
        'model_package':json.loads((model/'manifest.json').read_text())['package'],'probability_method':PARAMETERS['version'],
        'model_file_sha256':MODEL_SHA256,'allocation_rule':'balanced_A_v3','allocation_audit':audit,
        'horse_probabilities':prediction.to_dict('records'),'tickets':tickets.to_dict('records'),
        'source_urls':[s['source_url'] for s in sources.values()]+[json.loads((root/'cache/market'/(race+'.json')).read_text())['source_url']]}
    (root/'candidate_record.json').write_text(json.dumps(record,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')
    (root/'candidate_payouts.json').write_text(json.dumps(payouts,ensure_ascii=False,indent=2)+'\n')
    report={'test_only':True,'race_code':race,'actual_saved_model_inference':True,'public_previous_for_all_18':True,
        'prior_30_recalculated':True,'all_combinations':len(combo),'ticket_count':len(tickets),'stake_yen':int(tickets.stake.sum()),
        'matches_103_race_comparison_exactly':matches_comparison,'live_WIN_rejects_final_odds':historical_live_rejection,
        'fresh_in_sale_WIN_odds_pipeline_checked':False,'github_roundtrip':False}
    (root/'public/runtime_rehearsal.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ['workdir','modules','model_dir','history_dir','bundle_dir']:p.add_argument(k)
    a=p.parse_args();main(a.workdir,a.modules,a.model_dir,a.history_dir,a.bundle_dir)
