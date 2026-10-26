"""Prepare a 52-feature pre-race record; does not publish or fetch live odds.

Requires live snapshots already verified by the source acquisition layer.
That layer has not yet been demonstrated on an in-sale race.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import pandas as pd
from infer_free_model import predict
from strength_calibration import probability_tables, corrected_strength
from probability_correction import PARAMETERS, MODEL_SHA256
from win_odds import verify_snapshot
from cap30_budget_ceiling import allocate_balanced,VERSION

def timestamp(value):
    stamp=dt.datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError('Timezone required')
    return stamp.astimezone(dt.timezone.utc)

def prepare(model_dir,runners,snapshots,metadata,win_snapshot,now=None,clock=None,correction_parameters=None,allocation_function=None):
    now_was_supplied=now is not None
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:raise ValueError('Timezone required')
    now=now.astimezone(dt.timezone.utc)
    start=timestamp(metadata['race_start_at'])
    if start-now<dt.timedelta(minutes=12):
        raise ValueError('Publication deadline passed')
    if timestamp(metadata['features_obtained_at'])>now:
        raise ValueError('Future feature timestamp')
    race=metadata['race_code']
    if not re.fullmatch(r'\d{16}',race):raise ValueError('Invalid race code')
    if set(snapshots)!={'umaren','sanrenpuku'}:raise ValueError('Both odds snapshots required')
    for kind,snapshot in snapshots.items():
        if snapshot['status']!='verified_live':
            raise ValueError('Source has not verified live odds: '+kind)
        acquired=timestamp(snapshot['retrieved_at']);updated=timestamp(snapshot['source_updated_at'])
        if not updated<=acquired<=now or now-acquired>dt.timedelta(seconds=90) or now-updated>dt.timedelta(seconds=90):
            raise ValueError('Stale or future odds timestamps')
        if not snapshot.get('source_url') or not re.fullmatch(r'[a-f0-9]{64}',snapshot.get('page_sha256','')):
            raise ValueError('Odds source evidence missing')
    active=sorted(map(int,metadata['active_horse_numbers']))
    if len(active)!=len(set(active)) or len(active)<3:raise ValueError('Invalid active horse set')
    if sorted(int(r['umaban']) for r in runners)!=active:raise ValueError('Active horse set differs')
    if len({r['ketto_toroku_bango'] for r in runners})!=len(runners):raise ValueError('Duplicate horse identity')
    required=['race_code','keibajo_code','track_code','distance_m','grade_code','field_size',
              'wakuban','umaban','sex_code','age','carried_weight_kg','sire_code',
              'body_weight_kg','body_weight_change_kg','jockey_code','trainer_code']
    for row in runners:
        if any(k in row for k in ['target_finish_position','target_win','target_top3']):
            raise ValueError('Race result labels are forbidden in pre-race inputs')
        if row['race_code']!=race or row.get('stage')!='entries':raise ValueError('Not a confirmed entry row')
        if any(row.get(k) is None for k in required):raise ValueError('Unresolved current entry information')
    current_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(model_dir).glob('*.joblib')}
    if current_hashes!=MODEL_SHA256:raise ValueError('Calibrator incompatible with saved model hashes')
    verify_snapshot(win_snapshot, metadata, runners, now)
    probabilities=predict(model_dir,runners)
    pred=pd.DataFrame({'race_code':[race]*len(runners),'umaban':active if [int(r['umaban']) for r in runners]==active else [int(r['umaban']) for r in runners],
                       'ketto_toroku_bango':[r['ketto_toroku_bango'] for r in runners],
                       'win_probability':probabilities['win'],'top3_probability':probabilities['top3']})
    price_by_number={int(r['umaban']):r['decimal_odds'] for r in win_snapshot['rows']}
    prices=[price_by_number[int(n)] for n in pred.umaban]
    parameters=correction_parameters or PARAMETERS
    strength=corrected_strength(pred,prices,parameters['alpha_ai'],parameters['beta_market'])
    pred,combos=probability_tables(pred,strength)
    odds=pd.DataFrame([r for s in snapshots.values() for r in s['rows']])
    merged=combos.merge(odds,on=['race_code','bet_type','kumiban'],how='outer',validate='one_to_one',indicator=True)
    if not merged['_merge'].eq('both').all():raise ValueError('Incomplete or extra odds')
    if not merged['decimal_odds'].map(lambda x:pd.notna(x) and 1<=x<float('inf')).all():raise ValueError('Invalid odds')
    tickets, allocation_audit=(allocation_function or allocate_balanced)(merged.drop(columns='_merge'),pred)
    if tickets.empty or not 0<tickets['stake'].sum()<=10000 or len(tickets)>30 or not ((tickets['stake']>0)&(tickets['stake']%100==0)).all():raise ValueError('Invalid budget allocation')
    if not (tickets['stake']*tickets['decimal_odds']>=10000-1e-8).all():raise ValueError('Single-ticket payout condition failed')
    model_manifest=json.loads((Path(model_dir)/'manifest.json').read_text())
    input_json=json.dumps(runners,ensure_ascii=False,sort_keys=True,allow_nan=False,default=str)
    model_files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(model_dir).glob('*.joblib'))}
    # Finalization is AFTER inference/optimization, using the actual wall clock.
    # A supplied now remains a deterministic test clock unless clock is supplied.
    finalized=clock() if clock else (now if now_was_supplied else dt.datetime.now(dt.timezone.utc))
    if finalized.tzinfo is None or finalized<now or start-finalized<dt.timedelta(minutes=12):
        raise ValueError('Calculation finished outside publication deadline')
    if any(finalized-timestamp(s['retrieved_at'])>dt.timedelta(seconds=90) or
           finalized-timestamp(s['source_updated_at'])>dt.timedelta(seconds=90) for s in snapshots.values()):
        raise ValueError('Odds became stale during calculation; acquire again')
    if metadata.get('participation_obtained_at') and not dt.timedelta(0)<=finalized-timestamp(metadata['participation_obtained_at'])<=dt.timedelta(seconds=90):
        raise ValueError('Participation became stale during calculation; acquire again')
    verify_snapshot(win_snapshot, metadata, runners, finalized)
    record={'schema_version':7,'status':'prepared_not_published','race_code':race,'race_name':metadata['race_name'],
            'race_start_at':metadata['race_start_at'],'prediction_finalized_at':finalized.isoformat(),
            'features_obtained_at':metadata['features_obtained_at'],'active_horse_numbers':active,
            'model_package':model_manifest['package'],'model_file_sha256':model_files,
            'feature_spec_sha256':hashlib.sha256((Path(model_dir)/'feature_spec.json').read_bytes()).hexdigest(),
            'input_snapshot_sha256':hashlib.sha256(input_json.encode()).hexdigest(),
            'allocation_rule':VERSION,'total_stake_yen':int(tickets.stake.sum()),
            'budget_limit_yen':10000,'unspent_yen':int(10000-tickets.stake.sum()),
            'allocation_core_sha256':hashlib.sha256(Path(__file__).with_name('cap30_ceiling_allocator.py').read_bytes()).hexdigest(),
            'probability_method':parameters['version'],
            'probability_correction_parameters_sha256':hashlib.sha256(json.dumps(parameters,sort_keys=True).encode()).hexdigest(),
            'probability_correction_core_sha256':hashlib.sha256(Path(__file__).with_name('strength_calibration.py').read_bytes()).hexdigest(),
            'win_odds_source':{k:win_snapshot[k] for k in ['source_url','retrieved_at','source_updated_at','page_sha256']},
            'allocation_audit':allocation_audit,
            'horse_probabilities':pred.to_dict('records'),'tickets':tickets.to_dict('records'),
            'odds_sources':{k:{n:v[n] for n in ['source_url','retrieved_at','source_updated_at','page_sha256']} for k,v in snapshots.items()}}
    content=json.dumps(record,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n'
    return record,content,hashlib.sha256(content.encode()).hexdigest()

def x_draft(record,url,commit_sha):
    prefix='https://github.com/odds-yugami-lab/odds-yugami-lab/blob/'+commit_sha+'/'
    if not re.fullmatch(r'[a-f0-9]{40}',commit_sha) or not url.startswith(prefix):
        raise ValueError('Confirmed immutable GitHub URL required')
    return f"【オッズの歪みラボ】{record['race_name']}\n馬連・3連複 計{len(record['tickets'])}点／{record['total_stake_yen']:,}円\n全買い目・金額・取得時オッズ：\n{url}"

