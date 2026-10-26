"""Shared inference and in-sale odds, two fixed policies, no external writes."""
import copy,datetime as dt,hashlib,json,math,re
from pathlib import Path
from probability_correction import PARAMETERS,MODEL_SHA256
from cap30_budget_ceiling import validate_record_budget
from pre_race_record import timestamp
from balanced_A_v3_explicit import _ordered_outcomes
from two_researcher_allocator import allocate

VERSION='two_researchers_half_v1_20261026'
POLICIES={'ichiro':'ichiro_half_gross_E50_H50_v1_20261026','matsui':'matsui_half_EV1_net_E50_H50_v1_20261026'}
NAMES={'ichiro':'一郎研究員','matsui':'マツイ研究員'}
HALF=dict(PARAMETERS,version='market_strength_half_v1_20261026',alpha_ai=.5+.5*PARAMETERS['alpha_ai'],
          beta_market=.5*PARAMETERS['beta_market'],correction_strength=.5,base_version=PARAMETERS['version'])
PARAM_HASH=hashlib.sha256(json.dumps(HALF,sort_keys=True).encode()).hexdigest()
def dumps(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n'
def digest(text):return hashlib.sha256(text.encode()).hexdigest()

def allocate_two(combo,horses):
    scale=float((combo.ai_probability*combo.decimal_odds).max()*10000)
    scenarios=_ordered_outcomes(horses);out={}
    for key,net,flt in [('ichiro',False,False),('matsui',True,True)]:
        tickets,audit=allocate(combo,horses.umaban.tolist(),scenarios,expected_payout_scale=scale,
           time_limit=30.,mip_relative_gap=.01,net_profit=net,nonnegative_only=flt)
        audit.update(rule=POLICIES[key],research_only=False)
        out[key]=(tickets,audit)
    return out

def prepare(model_dir,runners,snapshots,metadata,win_snapshot,now=None,clock=None):
    import calibrated_pre_race
    allocations={}
    def select(combo,horses):
        allocations.update(allocate_two(combo,horses));return allocations['ichiro']
    # Exactly one model inference. The legacy routine performs all freshness/model/entry gates
    # and checks the actual clock AFTER both optimizations have completed.
    base,_,_=calibrated_pre_race.prepare(model_dir,runners,snapshots,metadata,win_snapshot,
        now=now,clock=clock,correction_parameters=HALF,allocation_function=select)
    base.update(schema_version=8,correction_strength=.5,correction_parameters=HALF)
    researchers={}
    for key,(tickets,audit) in allocations.items():
        record=copy.deepcopy(base);total=int(tickets.stake.sum())
        record.update(researcher_id=key,researcher_name=NAMES[key],allocation_rule=POLICIES[key],
            tickets=tickets.to_dict('records'),total_stake_yen=total,unspent_yen=10000-total,
            allocation_audit=audit,allocation_core_sha256=hashlib.sha256(Path(__file__).with_name('two_researcher_allocator.py').read_bytes()).hexdigest(),
            is_pre_race_prediction=True)
        researchers[key]=record
    pair={'schema_version':1,'record_type':'two_researcher_prediction','policy_version':VERSION,'test_only':False,
        'race_code':base['race_code'],'race_name':base['race_name'],'race_start_at':base['race_start_at'],
        'prediction_finalized_at':base['prediction_finalized_at'],'researchers':researchers}
    validate(pair,now=timestamp(pair['prediction_finalized_at']))
    return pair,dumps(pair),digest(dumps(pair))

def validate(pair,now=None,test_only=False):
    if pair.get('policy_version')!=VERSION or set(pair.get('researchers',{}))!=set(POLICIES):raise ValueError('Both fixed research policies required')
    if not re.fullmatch(r'\d{16}',pair.get('race_code','')):raise ValueError('Invalid race')
    finalized=timestamp(pair['prediction_finalized_at']);start=timestamp(pair['race_start_at'])
    if not test_only:
        now=now or dt.datetime.now(dt.timezone.utc)
        if pair.get('test_only') or not finalized<=now<=start-dt.timedelta(minutes=12):raise ValueError('Pair publication deadline/test identity invalid')
    common=['horse_probabilities','model_file_sha256','input_snapshot_sha256','odds_sources','win_odds_source',
            'probability_correction_parameters_sha256','prediction_finalized_at','features_obtained_at']
    records=pair['researchers'];a=records['ichiro'];b=records['matsui']
    if any(a[k]!=b[k] for k in common):raise ValueError('Researchers do not share identical inference and odds')
    for key,r in records.items():
        if r['race_code']!=pair['race_code'] or r['race_start_at']!=pair['race_start_at'] or r['prediction_finalized_at']!=pair['prediction_finalized_at']:raise ValueError('Pair identity/time mismatch')
        if r['allocation_rule']!=POLICIES[key] or r.get('correction_strength')!=.5 or r.get('correction_parameters')!=HALF or r['probability_correction_parameters_sha256']!=PARAM_HASH:raise ValueError('Wrong correction/policy')
        if r['model_file_sha256']!=MODEL_SHA256:raise ValueError('Wrong saved model')
        validate_record_budget(r)
        if r['allocation_core_sha256']!=hashlib.sha256(Path(__file__).with_name('two_researcher_allocator.py').read_bytes()).hexdigest():raise ValueError('Allocator hash mismatch')
        if len({(t['bet_type'],t['kumiban']) for t in r['tickets']})!=len(r['tickets']):raise ValueError('Duplicate tickets')
        import pandas as pd
        from strength_calibration import probability_tables
        horses=pd.DataFrame(r['horse_probabilities'])
        if set(horses.umaban.astype(int))!=set(r['active_horse_numbers']):raise ValueError('Active field mismatch')
        _,combos=probability_tables(horses,horses.rank_strength.to_numpy(float))
        lookup={(x.bet_type,x.kumiban):x.ai_probability for x in combos.itertuples()}
        if any(abs(t['ai_probability']-lookup.get((t['bet_type'],t['kumiban']),-1))>1e-10 for t in r['tickets']):raise ValueError('Ticket probability mismatch')
        audit=r['allocation_audit'];expected=sum(t['stake']*t['ai_probability']*t['decimal_odds'] for t in r['tickets'])
        if abs(expected-audit['expected_payout_yen'])>1e-7:raise ValueError('Expected payout mismatch')
        if key=='matsui' and any(t['ai_probability']*t['decimal_odds']<1-1e-10 for t in r['tickets']):raise ValueError('NegativeEV Matsui ticket')
        for src in [*r['odds_sources'].values(),r['win_odds_source']]:
            updated=timestamp(src['source_updated_at']);obtained=timestamp(src['retrieved_at'])
            if not updated<=obtained<=finalized or finalized-updated>dt.timedelta(seconds=90) or finalized-obtained>dt.timedelta(seconds=90):raise ValueError('Pair stale/future source at calculation')
    return pair

def prediction_draft(pair,url,test_only=False):
    lines=[('【テスト・実戦成績外】' if test_only else '')+'オッズの歪みラボ｜'+pair['race_name'],
      '的中派・一郎研究員 vs 収益派・マツイ研究員']
    for key,r in pair['researchers'].items():lines.append(f"{NAMES[key]}：{len(r['tickets'])}点・仮想{r['total_stake_yen']:,}円")
    lines+=['全買い目・金額・確定時刻はこちら',url,'#競馬予想']
    return '\n'.join(lines)

def result_draft(result,url):
    lines=[('【テスト・実戦成績外】' if result['test_only'] else '')+'オッズの歪みラボ｜'+result['race_name']+' 結果']
    for key,r in result['researchers'].items():
        label='的中' if r['payout_yen'] else ('返還あり' if r['refund_yen'] else '不的中')
        lines.append(f"{NAMES[key]}：{label}／回収率{r['recovery_percent']:.1f}%／損益{r['profit_yen']:+,}円")
    lines += ['仮想配分に基づく記録。全買い目・払戻はこちら',url,'#競馬予想']
    return '\n'.join(lines)
