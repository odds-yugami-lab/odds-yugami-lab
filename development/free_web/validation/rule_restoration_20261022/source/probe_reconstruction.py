"""Final-odds operation probe, NOT an original live replay or ROI study."""
import argparse,datetime as dt,hashlib,json,sys
from pathlib import Path
import numpy as np,pandas as pd
from cap30_reconstruction import allocate
sys.path.insert(0,'decomposition_20261021')
from rankwise import probability_tables
ROOT=Path('rule_restoration_20261022')

def main(scale_mode):
    all_races=json.loads(Path('base_review_20261021/private_assets/races_2026.json').read_text())['incumbent_same_input']
    source=next(r for r in all_races if r['race_code']=='2026101808040711')
    # Never pass target labels, popularity, observed order, official payouts.
    race={k:source[k] for k in ['race_code','numbers','win','top3']}
    stage=np.repeat(((np.log(race['win'])+np.log(race['top3']))/2)[None,:],3,axis=0)
    _,combo,scenario=probability_tables(race,stage)
    odds=json.loads(Path('bias_20261020/public_cache/odds/2026101808040711.json').read_text())['snapshots']
    prices=pd.DataFrame([r for snapshot in odds.values() for r in snapshot['rows']])
    merged=combo.merge(prices,on=['race_code','bet_type','kumiban'],validate='one_to_one')
    assert len(merged)==816
    # The normalizer is deliberately an explicit experimental setting.
    # Never relabel it as the recovered original normalization.
    scale=10000. if scale_mode=='budget' else float((merged.ai_probability*merged.decimal_odds).max()*10000)
    tickets,audit=allocate(merged,race['numbers'],scenario,expected_payout_scale=scale,time_limit=30.,mip_relative_gap=.01)
    original=json.loads(Path('repair_20261020/repo/development/free_web/incidents/2026101808040711_recovered_settlement.json').read_text())['virtual_settlement']['lines']
    prior={(r['bet_type'],r['kumiban']):r['stake'] for r in original}
    current={(r.bet_type,r.kumiban):int(r.stake) for r in tickets.itertuples()}
    oldH=float(sum(p for p,t1,k1,t2,k2 in scenario if (t1,k1) in prior or (t2,k2) in prior))
    pmap={(r.bet_type,r.kumiban):r.ai_probability for r in combo.itertuples()}
    omap={(r.bet_type,r.kumiban):r.decimal_odds for r in merged.itertuples()}
    oldE=float(sum(pmap[key]*omap[key]*amount for key,amount in prior.items()))
    report={'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'test_only':True,
        'status':'reconstruction_candidate_operational_original_equivalence_unverified',
        'actual_integer_optimization_executed':True,'source_model':'original_saved52_probabilities_no_market_correction',
        'race_code':race['race_code'],'odds_status':'final_postrace','combination_count':len(merged),
        'allocation_audit':audit,'original_ticket_count':30,'original_total_stake_yen':10000,
        'candidate_matches_original_ticket_keys':set(current)==set(prior),
        'candidate_matches_original_keys_and_stakes':current==prior,
        'shared_ticket_keys':len(set(current)&set(prior)),
        'identical_key_and_stake_count':sum(current.get(k)==v for k,v in prior.items()),
        'fixed_original_tickets_recomputed_with_available_inputs':{'probability_any_hit':oldH,
            'expected_payout_with_final_odds':oldE,'reported_original_probability_any_hit':.4812,
            'reported_original_expected_payout_yen':10632,
            'original_probability_exactly_reproduced':False,'original_odds_snapshot_recovered':False},
        'verification_tests_passed':5,'historical_ROI_evaluation_started':False,
        'production_code_or_automations_changed':False,
        'normalizer_and_solver_settings_are_explicit_unverified_assumptions':True,
        'scale_mode':scale_mode,
        'scale_mode_sources':{'budget':'Dimensionless expected-payout ratio E/10000; not documented as original.',
            'theoretical_upper':'Older balanced A v1 source uses max(ticket_probability*odds)*budget; not verified as cap30 policy.'},
        'program_sha256':hashlib.sha256((ROOT/'cap30_reconstruction.py').read_bytes()).hexdigest(),
        'tickets':tickets.to_dict('records')}
    path=ROOT/('candidate_probe_'+scale_mode+'_20261022.json')
    if path.exists():raise FileExistsError('Preserve previous probe: '+str(path))
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['status','shared_ticket_keys','identical_key_and_stake_count','candidate_matches_original_keys_and_stakes','allocation_audit','fixed_original_tickets_recomputed_with_available_inputs']}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--scale-mode',required=True,choices=['budget','theoretical_upper'])
    main(p.parse_args().scale_mode)
