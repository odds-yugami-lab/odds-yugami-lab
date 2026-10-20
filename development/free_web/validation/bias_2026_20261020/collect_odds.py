from runtime_paths import ROOT, MODULES, MODEL, HISTORY, HISTORY_DIR, BUNDLE, ASSETS
from pathlib import Path
import concurrent.futures,json,sys,time
ROOT=ROOT;DEST=ROOT/'public_cache/odds';DEST.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(MODULES))
from source_bundle import download
from odds import parse
def collect(race):
    code=race['race_code'];path=DEST/(code+'.json')
    if path.exists():return {'race_code':code,'status':'cached'}
    nums=sorted(r['horse_number'] for r in race['finish_rows'] if r['finish_status'] not in {'取消','除外'})
    snapshots={};web=code[2:4]+code[8:]
    try:
        for kind,part in [('umaren','ur'),('sanrenpuku','sf')]:
            url=f'https://sports.yahoo.co.jp/keiba/race/odds/{part}/{web}?ninki=0'
            error=None
            for attempt in range(2):
                try:
                    page,stamp,sha=download(url)
                    parsed=parse(page,code,kind,nums)
                    if parsed['status']!='final_postrace':raise ValueError('Not final historical odds')
                    snapshots[kind]=dict(parsed,source_url=url,retrieved_at=stamp,page_sha256=sha)
                    error=None;break
                except Exception as e:error=e
            if error:raise error
        path.write_text(json.dumps({'race_code':code,'snapshots':snapshots},ensure_ascii=False)+'\n')
        print('ODDS',code,sum(len(s['rows']) for s in snapshots.values()),flush=True)
        return {'race_code':code,'status':'ok'}
    except Exception as e:
        print('ODDS_FAILED',code,str(e),flush=True)
        return {'race_code':code,'status':'failed','error':str(e)}
races=json.loads((ROOT/'official_results.json').read_text())['races']
assert not any('error' in r for r in races)
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:reports=list(pool.map(collect,races))
(ROOT/'odds_collection.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2)+'\n')
print('ODDS_DONE',sum(r['status']!='failed' for r in reports),len(reports),flush=True)
