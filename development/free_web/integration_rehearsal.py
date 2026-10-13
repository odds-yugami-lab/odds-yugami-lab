"""Historical integration rehearsal; never invokes live-odds verification.

Uses captured official/free entry HTML, saved prior-style seed values and
downloaded final odds. Its output is restricted to publication_tests.
"""
import concurrent.futures
import datetime as dt
import json
from pathlib import Path
import duckdb
from official_entries import parse as official_parse,match_free_entries
from feature_pipeline import assemble
from source_bundle import download
from odds import parse as odds_parse
from bet_pipeline import retrospective
from publication import request

def run(model_dir,history_path,pilot_path,official_page,free_page):
    race='2026101208040511';web='2608040511'
    stamp=dt.datetime.now(dt.timezone.utc).isoformat()
    official=official_parse(official_page,race,
      'https://jra.jp/JRADB/accessD.html?CNAME=pw01dde1008202604051120261012%2FBB',stamp,historical_test=True)
    with duckdb.connect() as con:
        values=con.execute('''SELECT DISTINCT ketto_toroku_bango,previous_race_date,previous_running_style_code
          FROM read_parquet(?) WHERE race_code=?''',[str(pilot_path),race]).fetchall()
    styles=[{'horse_id':horse,'race_date':date.isoformat(),'style':style,
             'source_url':'private_historical_feature_seed','error':None}
            for horse,date,style in values if date is not None]
    assembly=assemble(free_page,web,'entries',history_path,
       json.loads((Path(model_dir)/'feature_spec.json').read_text()),styles,stamp,'2026-10-12',
       pedigree_paths=[pilot_path],participation_snapshot=official,test_only=True)
    assert not assembly['prediction_ready']
    runners=assembly['runners'];assert len(runners)==18
    # One local runner has a newer local start absent from the JRA result
    # history. Preserve its saved historical input for this rehearsal only.
    previous_fields=['previous_race_date','days_since_last_race','previous_finish_position',
                     'previous_running_style_code','previous_distance_m','previous_keibajo_code',
                     'previous_track_code','previous_body_weight_kg','previous_body_weight_change_kg']
    fallback_horses=[]
    with duckdb.connect() as con:
        for row in runners:
            if row['unpublished_or_unresolved']==['previous_running_style_code']:
                query='SELECT DISTINCT '+','.join(previous_fields)+' FROM read_parquet(?) WHERE race_code=? AND ketto_toroku_bango=?'
                seeds=con.execute(query,[str(pilot_path),race,row['ketto_toroku_bango']]).fetchall()
                if len(seeds)!=1:raise ValueError('Ambiguous previous-race seed')
                values=list(seeds[0]);values[0]=values[0].isoformat()
                row.update(zip(previous_fields,values));row['days_since_previous_race']=row['days_since_last_race']
                row['unpublished_or_unresolved']=[];fallback_horses.append(row['ketto_toroku_bango'])
    unresolved={r['ketto_toroku_bango']:r['unpublished_or_unresolved'] for r in runners if r['unpublished_or_unresolved']}
    if unresolved:raise ValueError('Historical input unresolved: '+str(unresolved))
    assert match_free_entries(runners,official)
    def get_odds(kind):
        part={'umaren':'ur','sanrenpuku':'sf'}[kind]
        url=f'https://sports.yahoo.co.jp/keiba/race/odds/{part}/{web}?ninki=0'
        page,time,sha=download(url)
        parsed=odds_parse(page,race,kind,[int(r['umaban']) for r in runners])
        assert parsed['status']=='final_postrace'
        parsed.update(source_url=url,retrieved_at=time,page_sha256=sha)
        return kind,parsed
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        snapshots=dict(pool.map(get_odds,['umaren','sanrenpuku']))
    result=retrospective(model_dir,runners,snapshots)
    record={'status':'prepared_not_published','race_code':race,
            'race_name':'スワンS・一括動作テスト','total_stake_yen':result['budget_yen'],
            'tickets':result['selected_bets'],'model_package':result['model_package'],
            'odds_status':'final_postrace','is_live_operation_ready':False,
            'historical_feature_seed_used_for_previous_styles':True,
            'source_urls':[official['source_url'],'https://sports.yahoo.co.jp/keiba/race/denma/'+web],
            'validation':result['validation']}
    write=request(record,'dev/free-windows-probe-20261011',test_only=True)
    report={'record_type':'integration_rehearsal','is_pre_race_prediction':False,
            'race_code':race,'runners':18,'feature_count':52,
            'prior_30_features_recalculated':True,'previous_information_assembled':True,
            'previous_styles_from_saved_seed_not_web':True,'official_free_entries_reconciled':True,
            'previous_record_seed_fallback_count':len(fallback_horses),
            'future_local_runner_previous_start_update_unresolved':bool(fallback_horses),
            'model_inference_executed':True,'all_odds_count':result['all_combination_count'],
            'selected_ticket_count':result['selected_ticket_count'],'budget_yen':10000,
            'live_source_bundle_acquire_executed':False,
            'live_pre_race_prepare_executed':False,
            'github_saved':False,'chat_generated':False,'settlement_checked':False}
    return write,report
