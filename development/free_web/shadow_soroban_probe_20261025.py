"""Optional shadow allocation. Production output/parameters are never changed.

capture: wrap the unchanged calibrated prepare function, retaining its verified
public odds/probability outputs locally; execute operation_runner normally.
compute: local background allocation during production GitHub saves.
shadow: only after production publication, authenticate the background inputs
against published bytes and append test-only files/readbacks.
"""
import os
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import subprocess
import pandas as pd

ROOT=Path(__file__).resolve().parent
UTC=dt.timezone.utc
RESEARCH_SHA='375e3b3c78352f634d7f74089bebda9497d85622d8aa9a0bc0fdff2ea070ed62'

def dumps(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n'
def digest(x):return hashlib.sha256(x.encode()).hexdigest()
def stamp(x):
    t=dt.datetime.fromisoformat(x)
    if t.tzinfo is None:raise ValueError('Timezone required')
    return t

def retain(path,record,snapshots,win_snapshot):
    # No feature rows, model binaries, history, or result labels are retained.
    payload={'record':record,'odds_snapshots':snapshots,'win_snapshot':win_snapshot,
             'captured_at':dt.datetime.now(UTC).isoformat()}
    content=dumps(payload)
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.read_text()!=content:raise ValueError('Shadow input already exists; do not replace')
    path.write_text(content)
    os.chmod(path,0o600)
    return digest(content)

def allocate_shadow(record,snapshots):
    from strength_calibration import probability_tables
    from balanced_A_v3_explicit import _ordered_outcomes
    h=pd.DataFrame(record['horse_probabilities'])
    numbers=sorted(int(n) for n in record['active_horse_numbers'])
    if sorted(h.umaban.astype(int))!=numbers:raise ValueError('Horse identities differ')
    if any(c.startswith('target_') or c in {'payout_yen','finish_status'} for c in h):
        raise ValueError('Outcome fields forbidden')
    _,combo=probability_tables(h,h.rank_strength.to_numpy(float))
    odds=pd.DataFrame([r for s in snapshots.values() for r in s['rows']])
    merged=combo.merge(odds,on=['race_code','bet_type','kumiban'],how='outer',validate='one_to_one',indicator=True)
    if not merged['_merge'].eq('both').all():raise ValueError('Incomplete/extra combination odds')
    merged=merged.drop(columns='_merge')
    path=ROOT/'validation/profit_comparison_20261024/source/allocator_research.py'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=RESEARCH_SHA:raise ValueError('Shadow allocator changed')
    spec=importlib.util.spec_from_file_location('soroban_shadow_allocator',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    scale=float((merged.ai_probability*merged.decimal_odds).max()*10000)
    tickets,audit=module.allocate(merged,numbers,_ordered_outcomes(h),
        expected_payout_scale=scale,time_limit=10.,mip_relative_gap=.01,
        net_profit=True,nonnegative_only=True)
    if not 0<int(tickets.stake.sum())<=10000 or not 1<=len(tickets)<=30:raise ValueError('Budget/count invalid')
    for t in tickets.itertuples():
        if t.ai_probability*t.decimal_odds<1-1e-10:raise ValueError('Negative-EV ticket')
        if t.stake!=100*max(1,math.ceil(100/t.decimal_odds-1e-12)):raise ValueError('Nonminimum stake')
    return tickets.to_dict('records'),audit

def freshness(data,now):
    record=data['record'];start=stamp(record['race_start_at'])
    if start-now<dt.timedelta(minutes=12):raise ValueError('Shadow deadline passed')
    if stamp(record['prediction_finalized_at'])>now:raise ValueError('Future production finalization')
    if set(data['odds_snapshots'])!={'umaren','sanrenpuku'}:raise ValueError('Both odds types required')
    for s in [*data['odds_snapshots'].values(),data['win_snapshot']]:
        if s['status']!='verified_live':raise ValueError('Shadow requires verified live odds')
        updated,obtained=stamp(s['source_updated_at']),stamp(s['retrieved_at'])
        if not updated<=obtained<=now or now-updated>dt.timedelta(seconds=90) or now-obtained>dt.timedelta(seconds=90):
            raise ValueError('Shadow inputs stale/future; do not relabel or refresh separately')

def capture():
    # All original arguments and returned production bytes remain unchanged.
    original_argv=sys.argv[:]
    args=original_argv[2:]
    if not args or args[0]!='live':raise ValueError('Capture supports live only')
    out=Path(args[args.index('--output')+1])
    capture_path=out.with_name(out.stem+'_shadow_input.json')
    import calibrated_pre_race
    original=calibrated_pre_race.prepare
    def wrapped(*a,**kw):
        result=original(*a,**kw)
        try:
            retain(capture_path,result[0],a[2],a[4])
            calculation_path=out.with_name(out.stem+'_shadow_calculation.json')
            subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'compute',
                              '--input',str(capture_path),'--output',str(calculation_path)],
                             stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                             start_new_session=True,close_fds=True)
        except Exception as exc:
            # Optional retention can never fail the production prediction.
            print('SHADOW_CAPTURE_FAILED '+type(exc).__name__,flush=True)
        return result
    calibrated_pre_race.prepare=wrapped
    sys.argv=[original_argv[0],*args]
    import operation_runner
    operation_runner.main()

def compute():
    """Pure local background work, concurrently with production GitHub saves."""
    parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args(sys.argv[2:])
    try:
        content=Path(args.input).read_text();data=json.loads(content)
        freshness(data,dt.datetime.now(UTC))
        tickets,audit=allocate_shadow(data['record'],data['odds_snapshots'])
        finalized=dt.datetime.now(UTC);freshness(data,finalized)
        result={'status':'shadow_calculated','test_only':True,'source_snapshot_sha256':digest(content),
                'prediction_finalized_at':finalized.isoformat(),'tickets':tickets,'allocation_audit':audit}
    except Exception as exc:
        result={'status':'shadow_compute_failed','test_only':True,'error_type':type(exc).__name__,'error':str(exc)[:500]}
    Path(args.output).write_text(dumps(result))

def shadow():
    parser=argparse.ArgumentParser()
    parser.add_argument('--production-output',required=True)
    parser.add_argument('--output',required=True)
    a=parser.parse_args(sys.argv[2:])
    output=Path(a.output)
    from operation_runner import GitHub,ConnectorRPC
    github=GitHub(ConnectorRPC())
    try:
        prod=Path(a.production_output);published=json.loads(prod.read_text())
        if published.get('status')!='published' or published.get('test_only') is not False:
            raise ValueError('Production must be published and read back first')
        capture_path=prod.with_name(prod.stem+'_shadow_input.json')
        content=capture_path.read_text();data=json.loads(content);record=data['record'];race=record['race_code']
        now=dt.datetime.now(UTC)
        # Leave at least 3 minutes before the unchanged 12-minute deadline.
        if stamp(record['race_start_at'])-dt.timedelta(minutes=12)-now<dt.timedelta(minutes=3):
            raise ValueError('Insufficient time; production takes priority')
        if published['race_code']!=race:raise ValueError('Published race differs')
        saved_bytes=github.content('predictions/free52/'+race+'.json',published['prediction_commit_sha'])
        saved=json.loads(saved_bytes)
        for key in ['horse_probabilities','tickets','model_file_sha256','input_snapshot_sha256','odds_sources','win_odds_source','allocation_rule','probability_method']:
            if saved[key]!=record[key]:raise ValueError('Capture differs from published production: '+key)
        from probability_correction import MODEL_SHA256,PARAMETERS
        if record['model_file_sha256']!=MODEL_SHA256 or record['probability_method']!=PARAMETERS['version']:
            raise ValueError('Production model/probability method changed')
        calculation_path=prod.with_name(prod.stem+'_shadow_calculation.json')
        calculation=json.loads(calculation_path.read_text())
        if calculation.get('status')!='shadow_calculated':raise ValueError('Background calculation failed: '+str(calculation.get('error')))
        if calculation['source_snapshot_sha256']!=digest(content):raise ValueError('Background input hash mismatch')
        finalized=stamp(calculation['prediction_finalized_at'])
        if finalized>dt.datetime.now(UTC) or finalized<stamp(data['captured_at']):raise ValueError('Invalid background calculation time')
        freshness(data,finalized)
        tickets=calculation['tickets'];audit=calculation['allocation_audit']
        total=sum(int(t['stake']) for t in tickets)
        shadow_record={'record_type':'soroban_shadow_test','test_only':True,'is_pre_race_prediction':False,
            'race_code':race,'race_name':record['race_name'],'race_start_at':record['race_start_at'],
            'prediction_finalized_at':finalized.isoformat(),'production_prediction_commit_sha':published['prediction_commit_sha'],
            'production_receipt_commit_sha':published['receipt_commit_sha'],'production_record_sha256':digest(saved_bytes),
            'same_probabilities_and_full_odds_as_production':True,'probability_method':record['probability_method'],
            'source_snapshot_sha256':digest(content),'odds_sources':record['odds_sources'],'win_odds_source':record['win_odds_source'],
            'allocation_rule':'soroban_EV_ge_1_net_E50_H50_shadow_v1','allocation_core_sha256':RESEARCH_SHA,
            'tickets':tickets,'allocation_audit':audit,'total_stake_yen':total,'budget_limit_yen':10000,'unspent_yen':10000-total,
            'no_production_change':True,'x_posted':False,'real_tickets_purchased':False}
        path='development/free_web/publication_tests/soroban_shadow_20261025/'+race+'.json'
        sha,(_,_,server_time)=github.save(path,dumps(shadow_record),'Save separate Soroban shadow test '+race)
        deadline=stamp(record['race_start_at'])-dt.timedelta(minutes=12)
        if stamp(server_time)>deadline:raise ValueError('Shadow saved late; never count as timely pre-race test')
        receipt={'test_only':True,'race_code':race,'shadow_commit_sha':sha,'content_sha256':digest(dumps(shadow_record)),
            'recorded_at':server_time,'production_prediction_commit_sha':published['prediction_commit_sha'],
            'readback_commit_and_branch_verified':True,'not_production_performance':True}
        receipt_sha,(_,_,receipt_time)=github.save(path.replace('.json','_receipt.json'),dumps(receipt),'Confirm Soroban shadow test '+race)
        if stamp(receipt_time)>deadline or dt.datetime.now(UTC)>deadline:raise ValueError('Shadow receipt/readback late')
        result={'status':'shadow_saved','test_only':True,'race_code':race,'commit_sha':sha,'receipt_commit_sha':receipt_sha,
                'ticket_count':len(tickets),'total_stake_yen':total,'record_url':'https://github.com/odds-yugami-lab/odds-yugami-lab/blob/'+sha+'/'+path}
    except Exception as exc:
        result={'status':'shadow_failed_or_skipped','test_only':True,'error_type':type(exc).__name__,'error':str(exc)[:500],
                'production_unchanged':True,'completed':False,'checked_at':dt.datetime.now(UTC).isoformat()}
    output.write_text(dumps(result));print('JRA_DONE '+json.dumps({'status':result['status'],'output':str(output)}),flush=True)

if __name__=='__main__':
    {'capture':capture,'compute':compute,'shadow':shadow}[sys.argv[1]]()
