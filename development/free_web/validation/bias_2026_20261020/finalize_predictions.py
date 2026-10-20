from runtime_paths import ROOT
from pathlib import Path
import json
ROOT=ROOT
rows=json.loads((ROOT/'horse_predictions.json').read_text())
for code in ['2026061302010111','2026091209040311','2026101808040711']:
    source=ROOT/'private_assets'/('reconstructed_'+code+'.json')
    data=json.loads(source.read_text())
    if any(r['race_code']==code for r in rows):raise ValueError('Duplicate reconstruction')
    rows.extend(data['probabilities'])
if len({r['race_code'] for r in rows})!=103:raise ValueError('Not all official 103 races are covered')
(ROOT/'horse_predictions_all.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
print('All 103 target races have probabilities; outcomes remain separate from model input')
