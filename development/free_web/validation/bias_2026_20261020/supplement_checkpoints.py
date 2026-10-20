from runtime_paths import ROOT, MODULES, MODEL, HISTORY, HISTORY_DIR, BUNDLE, ASSETS
from pathlib import Path
import json,sys,datetime as dt,ast
import pandas as pd
ROOT=ROOT
sys.path.insert(0,str(MODULES))
sys.path.insert(0,str(ROOT.resolve()))
checkpoint=ROOT/'replay_checkpoint.py'
if not checkpoint.exists():checkpoint=MODULES/'validation/replay_ireland_saudi_A_v3.py'
module=ast.parse(checkpoint.read_text())
node=next(n.value for n in module.body if isinstance(n,ast.Assign) and
          any(isinstance(t,ast.Name) and t.id=='CASES' for t in n.targets))
CASES=[{k.arg:ast.literal_eval(k.value) for k in call.keywords} for call in node.elts]
from official_entries import parse as official_parse
from feature_pipeline import assemble
from infer_free_model import predict
official={r['race_code']:r for r in json.loads((ROOT/'official_results.json').read_text())['races']}
preds=json.loads((ROOT/'horse_predictions.json').read_text())
def add(code,records,source):
    result=official[code]
    expected={r['horse_number'] for r in result['finish_rows'] if r['finish_status'] not in {'取消','除外'}}
    assert {int(r['umaban']) for r in records}==expected
    assert not any(p['race_code']==code for p in preds)
    for row in records:
        num=int(row['umaban']);ob=next(r for r in result['runners'] if r['umaban']==num);status=ob['finish_status']
        preds.append({'race_code':code,'umaban':num,'horse_id':row.get('ketto_toroku_bango'),
            'win_probability':float(row['win_probability']),'top3_probability':float(row['top3_probability']),
            'target_win':status=='1','target_top3':status.isdigit() and int(status)<=3,
            'finish_status':status,'popularity':ob['popularity'],'grade':result['grade'],'source':source})
for case in CASES:
    add(case['race'],[{'umaban':n,'win_probability':w,'top3_probability':t}
                     for n,w,t in case['horse_probabilities']],
        'verified_52_model_retrospective_checkpoint_20261018')
fuji_path=ROOT/'fuji_checkpoint.json'
if not fuji_path.exists():fuji_path=MODULES.parents[1]/'predictions/free52/2026101705040611.json'
fuji=json.loads(fuji_path.read_text())
add(fuji['race_code'],fuji['horse_probabilities'],'immutable_52_model_prediction_checkpoint_20261017')
assets=ASSETS;bundle=BUNDLE;model=MODEL
code='2026101208040511';stamp=dt.datetime.now(dt.timezone.utc).isoformat()
official_entry=official_parse((bundle/'fixtures/swan_official_entry.html').read_text(),code,
    'https://www.jra.go.jp/JRADB/accessD.html',stamp,historical_test=True)
evidence=json.loads((bundle/'fixtures/swan_previous_evidence.json').read_text())
a=assemble((bundle/'fixtures/swan_free_entry.html').read_text(),'2608040511','entries',
    HISTORY,json.loads((model/'feature_spec.json').read_text()),[],
    stamp,'2026-10-18',pedigree_paths=[bundle/'fixtures/pedigree_lookup.parquet'],
    participation_snapshot=official_entry,test_only=True,previous_overrides=evidence)
assert not any(r['unpublished_or_unresolved'] for r in a['runners'])
out=predict(model,a['runners'])
add(code,[dict(r,win_probability=w,top3_probability=t) for r,w,t in zip(a['runners'],out['win'],out['top3'])],
    'private_archived_public_entry_previous_evidence_reinference')
(ROOT/'horse_predictions.json').write_text(json.dumps(preds,ensure_ascii=False,indent=2)+'\n')
print('PREDICTION_CHECKPOINTS',len({r['race_code'] for r in preds}),'races',len(preds),'horses',flush=True)
