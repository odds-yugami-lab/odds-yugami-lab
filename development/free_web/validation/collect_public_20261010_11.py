"""Collect ONLY public JRA/Yahoo entry and prior-result facts for October 10-11 replay.
No trained model, history parquet, private pedigree or nonpublic files.
Race results and winning outcomes are deliberately not read here.
"""
import datetime as dt,json,traceback,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from official_entries import fetch as official_fetch,match_free_entries
from source_bundle import download
from entries import parse as free_parse
from public_previous import acquire as previous_acquire

CASES=[
 {'race_code':'2026101005040311','date':'2026-10-10','web':'2605040311',
  'official_url':'https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde1005202604031120261010%2F7D'},
 {'race_code':'2026101105040411','date':'2026-10-11','web':'2605040411',
  'official_url':'https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde1005202604041120261011%2FAD'}
]
def run(case):
    entry_url='https://sports.yahoo.co.jp/keiba/race/denma/'+case['web']
    html,time,sha=download(entry_url)
    runners=free_parse(html,case['web'],'entries')
    page,official_time,official_sha=download(case['official_url'])
    official_diagnostic={'bytes':len(page),'contains_past_p1':'class="past p1"' in page,
        'table_count':page.count('<table'),'looks_like_entry':'出馬表' in page,
        'has_horse_ids':'pw01dud00' in page, 'race_marker':case['web'] in page}
    official_parse_ok=False
    official_exception=None
    try:
        official=official_fetch(case['official_url'],case['race_code'],historical_test=True,include_page=False)
        match_free_entries(runners,official)
        official_parse_ok=True
    except Exception as e:
        official_exception=str(e)
    accepted=[]
    for r in runners:
        r.pop('unpublished_or_unresolved',None)
        r.pop('prediction_ready',None)
        accepted.append(r)
    try:
        previous,unresolved=previous_acquire(page,case['official_url'],case['date'])
    except Exception as e:
        previous=[]
        unresolved=[{'reason':'Previous acquisition fatal: '+str(e)}]
    return {'status':'ok','race_code':case['race_code'],
     'race_date':case['date'],'source_url':entry_url,'source_sha256':sha,
     'official_source_url':case['official_url'],
     'official_parser_ok':official_parse_ok,'official_exception':official_exception,
     'official_diagnostic':official_diagnostic,
     'full_runners':accepted,
     'prior_public_evidence':previous,'prior_unresolved':unresolved,
     'prior_coverage':len(previous),'runner_count':len(runners)}

def main():
    cases=[]
    for c in CASES:
        try: cases.append(run(c))
        except Exception as e: cases.append({'status':'failed','race_code':c['race_code'],
            'error':str(e),'traceback':traceback.format_exc()[-1500:]})
    result={'record_type':'historical_public_entries_and_previous_only',
        'no_private_model_or_history':True,'cases':cases}
    dest=Path('development/free_web/validation/public_oct10_11_collection.json')
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('PUBLIC_CASE_OVERVIEW='+json.dumps([{
         'race_code':c['race_code'],'status':c['status'],
         'runner_count':c.get('runner_count'),'prior_coverage':c.get('prior_coverage'),
         'unresolved':c.get('prior_unresolved'),'official_diagnostic':c.get('official_diagnostic'),
         'official_exception':c.get('official_exception'),'error':c.get('error'),
         'horse_entries':[{'number':r['umaban'],'horse_id':r['ketto_toroku_bango']}
             for r in c.get('full_runners',[])],
     } for c in cases],ensure_ascii=False))
    return 0 if all(c['status']=='ok' for c in cases) else 2
if __name__=='__main__':sys.exit(main())
