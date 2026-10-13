"""Precompute registration-stage previous and prior features, no prediction.

Confirmed runners, draw, jockeys and current weights remain unannounced.
Past individual styles are fetched from free public result pages.
"""
import concurrent.futures
import datetime as dt
import hashlib
from pathlib import Path
import duckdb
from entries import parse
from feature_pipeline import assemble
from running_style import parse_styles
from source_bundle import download

def prepare(registrations,history_path,feature_spec,history_complete_through,cache_dir,pedigree_paths=()):
    cache=Path(cache_dir);cache.mkdir(parents=True,exist_ok=True)
    all_rows={key:parse(value['page'],value['race_id'],'registration') for key,value in registrations.items()}
    identities=sorted({r['ketto_toroku_bango'] for rows in all_rows.values() for r in rows})
    with duckdb.connect() as con:
        con.execute('CREATE TEMP TABLE history AS SELECT * FROM read_parquet(?)',[str(history_path)])
        latest=con.execute('''SELECT ketto_toroku_bango,race_code,race_date,keibajo_code
          FROM history WHERE ketto_toroku_bango IN (SELECT unnest(?))
          AND race_date<=? AND NOT is_cancelled_or_excluded
          AND race_code IN (SELECT race_code FROM history GROUP BY race_code HAVING count(target_finish_position)>0)
          QUALIFY row_number() OVER(PARTITION BY ketto_toroku_bango ORDER BY race_date DESC,race_code DESC)=1''',
          [identities,dt.date.fromisoformat(history_complete_through)]).fetchall()
    races={r[1] for r in latest if r[3] in {f'{n:02d}' for n in range(1,11)}}
    def past(race):
        web=race[2:4]+race[8:];url=f'https://sports.yahoo.co.jp/keiba/race/result/{web}'
        local=cache/(web+'.html')
        if local.exists():
            page=local.read_text();stamp=dt.datetime.fromtimestamp(local.stat().st_mtime,dt.timezone.utc).isoformat()
            digest=hashlib.sha256(page.encode()).hexdigest()
        else:
            page,stamp,digest=download(url);local.write_text(page)
        return race,{'styles':parse_styles(page,web),'source_url':url,'retrieved_at':stamp,'page_sha256':digest}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:sources=dict(pool.map(past,sorted(races)))
    style_evidence=[];unresolved=[]
    for horse,race,date,venue in latest:
        if race not in sources:
            unresolved.append({'horse_id':horse,'reason':'previous_start_outside_JRA_history_source'});continue
        source=sources[race];style=source['styles'].get(horse,{}).get('running_style_code')
        if style is None:unresolved.append({'horse_id':horse,'reason':'individual_previous_style_unavailable'})
        style_evidence.append({'horse_id':horse,'race_date':date.isoformat(),'style':style,
                              'source_url':source['source_url'],'error':None if style is not None else 'unresolved'})
    result={}
    for name,registration in registrations.items():
        prepared=assemble(registration['page'],registration['race_id'],'registration',history_path,
              feature_spec,style_evidence,registration['obtained_at'],history_complete_through,pedigree_paths=pedigree_paths)
        for row in prepared['runners']:
            if row['jockey_code'] is None:
                for field in feature_spec['features']:
                    if field.startswith('jockey_prior_'):row[field]=None
        prepared.update(source_url=registration['source_url'],previous_source_count=len(sources),
                        previous_style_evidence=[e for e in style_evidence if e['horse_id'] in {r['ketto_toroku_bango'] for r in prepared['runners']}],
                        unresolved_previous=[e for e in unresolved if e['horse_id'] in {r['ketto_toroku_bango'] for r in prepared['runners']}],
                        registration_not_confirmed_entries=True)
        result[name]=prepared
    return result
