"""Connect probability inference to frozen corrected V2 allocation.

Numerical engine only. Publication/freshness checks belong to the live recorder.
This initial wrapper emits retrospective verification records exclusively.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from infer_free_model import predict
from corrected_v2_core import generate_combinations, allocate

def retrospective(model_dir,runners,odds_snapshots):
    races={r['race_code'] for r in runners}
    horses=[int(r['umaban']) for r in runners]
    if len(races)!=1 or len(horses)<3 or len(set(horses))!=len(horses) or not all(1<=h<=18 for h in horses):
        raise ValueError('Invalid single-race runners')
    if set(odds_snapshots)!={'umaren','sanrenpuku'}:
        raise ValueError('Both bet-type snapshots required')
    if any(v['status']!='final_postrace' for v in odds_snapshots.values()):
        raise ValueError('This wrapper is retrospective only')
    probabilities=predict(model_dir,runners)
    prediction=pd.DataFrame({'race_code':[next(iter(races))]*len(runners),'umaban':horses,
                              'win_probability':probabilities['win'],'top3_probability':probabilities['top3']})
    combos=generate_combinations(prediction)
    odds=pd.DataFrame([r for snapshot in odds_snapshots.values() for r in snapshot['rows']])
    combined=combos.merge(odds,on=['race_code','bet_type','kumiban'],how='outer',validate='one_to_one',indicator=True)
    if not combined['_merge'].eq('both').all():
        raise ValueError('Odds and probability combinations differ')
    combined=combined.drop(columns='_merge')
    if not np.allclose(combined.groupby('bet_type')['ai_probability'].sum().to_numpy(),1):
        raise ValueError('Invalid combination probability sums')
    selected=allocate(combined)
    if selected.empty or int(selected['stake'].sum())!=10000:
        raise ValueError('No complete 10000-yen allocation')
    if not ((selected['stake']>0)&(selected['stake']%100==0)).all():
        raise ValueError('Invalid 100-yen stake units')
    if not (selected['stake']*selected['decimal_odds']>=10000-1e-8).all():
        raise ValueError('Single-ticket payout constraint failed')
    model_manifest=json.loads((Path(model_dir)/'manifest.json').read_text())
    core_sha=hashlib.sha256(Path(__file__).with_name('corrected_v2_core.py').read_bytes()).hexdigest()
    return {'record_type':'retrospective_pipeline_verification','is_pre_race_prediction':False,
            'is_live_operation_ready':False,'race_code':next(iter(races)),
            'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'model_package':model_manifest['package'],'feature_count':52,
            'allocation_rule':'corrected_V2','allocation_core_sha256':core_sha,
            'budget_yen':10000,'odds_status':'final_postrace',
            'all_combination_count':len(combined),'selected_ticket_count':len(selected),
            'horse_probabilities':prediction.to_dict('records'),
            'selected_bets':selected.to_dict('records'),
            'odds_sources':{k:{'source_url':v['source_url'],'updated_at_text':v['source_updated_at_text']} for k,v in odds_snapshots.items()},
            'validation':{'complete_odds':True,'probability_sums':True,'stake_sum_yen':int(selected['stake'].sum()),
                          'stake_unit_yen':100,'single_ticket_payout_min_yen':float((selected['stake']*selected['decimal_odds']).min())}}
