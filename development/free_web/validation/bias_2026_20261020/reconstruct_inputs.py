from runtime_paths import ROOT, MODULES, MODEL, HISTORY, HISTORY_DIR, BUNDLE, ASSETS
"""Retrospective public-card/profile supplementation, not live certification.
Public result labels are never passed to predict. Prior dates must precede race.
"""
from pathlib import Path
import concurrent.futures,datetime as dt,json,re,sys,hashlib
import duckdb,pandas as pd
ROOT=ROOT;CACHE=ROOT/'public_cache/profiles';CACHE.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(MODULES))
from source_bundle import download
from entries import parse,attach_known_sires,TRACKS
from previous_features import calculate as previous
from prior_features import calculate as priors
from running_style import classify
from result_store import text
from infer_free_model import predict
HISTORY=HISTORY
MODEL=MODEL
def page(url,key):
    path=CACHE/(key+'.json')
    if path.exists():return json.loads(path.read_text())
    html,stamp,sha=download(url)
    obj={'url':url,'retrieved_at':stamp,'sha256':sha,'html':html}
    path.write_text(json.dumps(obj,ensure_ascii=False));return obj

def profile_previous(horse,target):
    source=page('https://sports.yahoo.co.jp/keiba/directory/horse/'+horse+'/','horse_'+horse)
    tables=[t for t in re.findall(r'<table\b[^>]*>(.*?)</table>',source['html'],re.S) if '通過順位' in t and '着順' in t]
    if len(tables)!=1:raise ValueError('Previous profile table missing')
    found=[]
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',tables[0],re.S):
        cells=re.findall(r'<td\b[^>]*>(.*?)</td>',row,re.S)
        if not cells:continue
        if len(cells)!=9:raise ValueError('Unsupported profile columns')
        day=text(cells[0]).replace('/','-')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day) or day>=target:continue
        status=text(cells[2])
        if status in {'取消','除外'}:continue
        link=re.findall(r'/keiba/race/index/(\d{10})',cells[1])
        if len(set(link))!=1:raise ValueError('Previous non-JRA/unlinked start: '+horse)
        race_id=link[0]
        course=re.search(r'(札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)\s+(芝|ダ|障)(\d+)m\s+(\d+)頭',text(cells[1]))
        if not course:raise ValueError('Previous profile course missing')
        if race_id[:2]!=day[2:4]:raise ValueError('Previous race identity mismatch')
        corners_text=text(re.sub(r'<p\b[^>]*>.*?</p>','',cells[8],flags=re.S))
        corners=list(map(int,corners_text.split('-'))) if re.fullmatch(r'\d+(?:-\d+)+',corners_text) else []
        count=int(course[4]);style=classify(corners,count,status)
        weight=re.fullmatch(r'(\d+)(?:\(([+-]?\d+)\))?',text(cells[6]).replace(' ',''))
        found.append({'horse_id':horse,'previous_race_date':day,'race_id':race_id,
            'previous_finish_position':int(status) if status.isdigit() else None,
            'previous_running_style_code':style,'previous_distance_m':int(course[3]),
            'previous_style_resolved':style is not None,
            'previous_keibajo_code':race_id[2:4],
            'previous_body_weight_kg':int(weight[1]) if weight else None,
            'previous_body_weight_change_kg':int(weight[2]) if weight and weight[2] is not None else None,
            'source_url':source['url'],'retrieved_at':source['retrieved_at'],'page_sha256':source['sha256']})
        break  # Profile rows are reverse chronological; keep latest eligible start.
    if not found:raise ValueError('No preceding start: '+horse)
    found.sort(key=lambda x:x['previous_race_date'],reverse=True)
    result=found[0]
    # Exact track orientation from actual linked preceding card, not a venue guess.
    prior_page=page('https://sports.yahoo.co.jp/keiba/race/denma/'+result['race_id'],'entry_'+result['race_id'])
    prior_date=re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日',text(prior_page['html']))
    if not prior_date or dt.date(*map(int,prior_date.groups())).isoformat()!=result['previous_race_date']:
        raise ValueError('Previous card date mismatch')
    meta=re.search(r'class="hr-predictRaceInfo__text"[^>]*>([^<]+?)(\d+)m</span>',prior_page['html'])
    if not meta or meta[1].strip() not in TRACKS or int(meta[2])!=result['previous_distance_m']:
        raise ValueError('Previous card course mismatch')
    result['previous_track_code']=TRACKS[meta[1].strip()]
    result['days_since_last_race']=(dt.date.fromisoformat(target)-dt.date.fromisoformat(result['previous_race_date'])).days
    result['days_since_previous_race']=result['days_since_last_race']
    return result

def rebuild(result):
    race=result['race_code'];target=result['date'];web=race[2:4]+race[8:]
    src=page('https://sports.yahoo.co.jp/keiba/race/denma/'+web,'entry_'+web)
    rows=parse(src['html'],web,'entries')
    expected={r['horse_number'] for r in result['finish_rows'] if r['finish_status'] not in {'取消','除外'}}
    rows=[r for r in rows if int(r['umaban']) in expected]
    if {int(r['umaban']) for r in rows}!=expected:raise ValueError('Current card/official starters differ')
    for row in rows:row['field_size']=len(expected)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        evidence=list(pool.map(lambda r:profile_previous(r['ketto_toroku_bango'],target),rows))
    by_id={e['horse_id']:e for e in evidence}
    with duckdb.connect() as con:
        rows=attach_known_sires(con,rows,[HISTORY,ROOT/'private_assets/jra_features_pilot_2025_2026.parquet'],target)
        rows=previous(con,HISTORY,rows,target,{})
        rows=priors(con,HISTORY,rows,target)
    for row in rows:
        e=by_id[row['ketto_toroku_bango']]
        for key,value in e.items():
            if key.startswith('previous_') or key.startswith('days_since_'):row[key]=value
    probs=predict(MODEL,pd.DataFrame(rows))
    output=[]
    for row,w,t in zip(rows,probs['win'],probs['top3']):
        num=int(row['umaban']);observed=next(r for r in result['runners'] if r['umaban']==num)
        status=observed['finish_status']
        output.append({'race_code':race,'umaban':num,'horse_id':row['ketto_toroku_bango'],
            'win_probability':float(w),'top3_probability':float(t),'finish_status':status,
            'target_win':status=='1','target_top3':status.isdigit() and int(status)<=3,
            'popularity':observed['popularity'],'grade':result['grade'],
            'source':'retrospective_public_entry_profile_history_reconstruction'})
    path=ROOT/'private_assets'/('reconstructed_'+race+'.json')
    path.write_text(json.dumps({'race_code':race,'probabilities':output,
        'public_previous_evidence':evidence,'current_entry_source':{k:v for k,v in src.items() if k!='html'},
        'not_immutable_pre_race_inputs':True},ensure_ascii=False,indent=2)+'\n')
    return output

if __name__=='__main__':
    codes=sys.argv[1:]
    results=json.loads((ROOT/'official_results.json').read_text())['races']
    for code in codes:
        try:
            output=rebuild(next(r for r in results if r.get('race_code')==code))
            print('RECONSTRUCTED',code,len(output),flush=True)
        except Exception as e:
            print('RECONSTRUCTION_FAILED',code,type(e).__name__,str(e),flush=True)
