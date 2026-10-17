"""Public previous-race running styles only; no restricted model/history used."""
import concurrent.futures,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from source_bundle import download
from running_style import parse_styles
from result_store import parse_result
TARGETS={
  "2026101005040311": [
    [
      "2024105852",
      "2026092609040804"
    ],
    [
      "2024108228",
      "2026061305030306"
    ],
    [
      "2024102281",
      "2026091206040305"
    ],
    [
      "2024105444",
      "2026081501010709"
    ],
    [
      "2024106538",
      "2026060605030105"
    ],
    [
      "2024101333",
      "2026061405030405"
    ],
    [
      "2024102993",
      "2026080204020403"
    ],
    [
      "2024101344",
      "2026080804020501"
    ],
    [
      "2024105893",
      "2026082204030103"
    ],
    [
      "2024105215",
      "2026082204030103"
    ],
    [
      "2024104872",
      "2026092606040802"
    ]
  ],
  "2026101105040411": [
    [
      "2021100244",
      "2026062105030611"
    ],
    [
      "2022105778",
      "2026081607020807"
    ],
    [
      "2021105414",
      "2026051705020811"
    ],
    [
      "2021100139",
      "2026090506040111"
    ],
    [
      "2022104839",
      "2026081607020807"
    ],
    [
      "2022102408",
      "2026090509040111"
    ],
    [
      "2021105105",
      "2026071803020711"
    ],
    [
      "2022105157",
      "2026080201010411"
    ],
    [
      "2022106232",
      "2026062105030611"
    ],
    [
      "2021103975",
      "2026062105030611"
    ],
    [
      "2021107098",
      "2026081607020807"
    ],
    [
      "2021105801",
      "2026080804020507"
    ],
    [
      "2022101412",
      "2026083001020411"
    ],
    [
      "2021105255",
      "2026080107020307"
    ],
    [
      "2022104767",
      "2026051705020811"
    ],
    [
      "2022105402",
      "2026051705020811"
    ]
  ]
}
def fetch_race(race):
    url='https://sports.yahoo.co.jp/keiba/race/result/'+race[2:4]+race[8:]
    page,when,digest=download(url)
    parsed=parse_styles(page,race[2:4]+race[8:])
    details=parse_result(page,race[2:4]+race[8:])
    return {'status':'ok','url':url,'page_sha256':digest,'runners':parsed,
       'detail_by_horse':{row['horse_id']:{'finish_text':row['finish_text'],
         'horse_number':row['horse_number'],'horse_detail':row['horse_detail'],
         'jockey_id':row.get('jockey_id'),'trainer_id':row.get('trainer_id')}
         for row in details}}
def main():
    unique=sorted({race for grp in TARGETS.values() for hid,race in grp})
    def work(race):
        try:return race,fetch_race(race)
        except Exception as ex:return race,{'status':'error','error':str(ex)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        race_data=dict(pool.map(work,unique))
    out={}
    for case,rows in TARGETS.items():
        horse_rows=[]
        for hid,prior in rows:
            d=race_data[prior]
            style=d.get('runners',{}).get(hid,{})
            detail=d.get('detail_by_horse',{}).get(hid,{})
            horse_rows.append({'horse_id':hid,'prior_race':prior,
               'prior_url':d.get('url'),'prior_page_sha256':d.get('page_sha256'),
               'running_style_code':style.get('running_style_code'),
               'corners':style.get('corners'),
               'previous_result_detail':detail,
               'error':d.get('error') or ('horse missing' if not style else None)})
        out[case]=horse_rows
    dest=Path('development/free_web/validation/public_previous_styles_oct10_11.json')
    dest.write_text(json.dumps({'record_type':'public_historical_previous_only',
        'previous_sources':race_data,'target_mapping':out},ensure_ascii=False,indent=2)+'\n')
    print('PREVIOUS_STYLE_COMPACT='+json.dumps(out,ensure_ascii=False,separators=(',',':')))
    print('PREVIOUS_STYLE_SUMMARY='+json.dumps({
       r:{'race_count':len(unique),'resolved':sum(x['running_style_code'] is not None for x in d),
          'total':len(d),'issues':[x for x in d if x['running_style_code'] is None]}
       for r,d in out.items()},ensure_ascii=False,separators=(',',':')))
    return 0 if all(x['running_style_code'] is not None for d in out.values() for x in d) else 2
if __name__=='__main__':sys.exit(main())
