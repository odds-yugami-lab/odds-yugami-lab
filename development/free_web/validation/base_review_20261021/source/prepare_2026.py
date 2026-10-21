"""Recreate real feature rows; old probability checkpoints cannot feed a new model."""
import concurrent.futures,datetime as dt,json,sys
from pathlib import Path
import duckdb,pandas as pd
sys.path.insert(0,'bias_20261020')
import reconstruct_inputs as source
ROOT=Path('base_review_20261021');PRIVATE=ROOT/'private_assets'

def rebuild(result):
    code=result['race_code'];target=result['date'];web=code[2:4]+code[8:]
    src=source.page('https://sports.yahoo.co.jp/keiba/race/denma/'+web,'entry_'+web)
    rows=source.parse(src['html'],web,'entries')
    expected={r['horse_number'] for r in result['finish_rows'] if r['finish_status'] not in {'取消','除外'}}
    rows=[r for r in rows if int(r['umaban']) in expected]
    assert {int(r['umaban']) for r in rows}==expected
    for row in rows:row['field_size']=len(expected)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        evidence=list(pool.map(lambda r:source.profile_previous(r['ketto_toroku_bango'],target),rows))
    by_id={e['horse_id']:e for e in evidence}
    with duckdb.connect() as con:
        rows=source.attach_known_sires(con,rows,[source.HISTORY,source.ROOT/'private_assets/jra_features_pilot_2025_2026.parquet'],target)
        rows=source.previous(con,source.HISTORY,rows,target,{})
        rows=source.priors(con,source.HISTORY,rows,target)
    for row in rows:
        e=by_id[row['ketto_toroku_bango']]
        assert e['previous_race_date']<target
        for key,value in e.items():
            if key.startswith('previous_') or key.startswith('days_since_'):row[key]=value
    return pd.DataFrame(rows),{'public_previous_starts':len(evidence),'unresolved_previous_style':sum(not e['previous_style_resolved'] for e in evidence),
        'source':'public_card_profile_history','immutable_pre_race_snapshot':False}

def swan():
    from official_entries import parse
    from feature_pipeline import assemble
    bundle=source.BUNDLE;code='2026101208040511';stamp=dt.datetime.now(dt.timezone.utc).isoformat()
    official=parse((bundle/'fixtures/swan_official_entry.html').read_text(),code,
        'https://www.jra.go.jp/JRADB/accessD.html',stamp,historical_test=True)
    evidence=json.loads((bundle/'fixtures/swan_previous_evidence.json').read_text())
    assembly=assemble((bundle/'fixtures/swan_free_entry.html').read_text(),'2608040511','entries',
        source.HISTORY,json.loads((source.MODEL/'feature_spec.json').read_text()),[],stamp,'2026-10-18',
        pedigree_paths=[bundle/'fixtures/pedigree_lookup.parquet'],participation_snapshot=official,test_only=True,previous_overrides=evidence)
    rows=assembly['runners'];assert len(rows)==18 and not any(r['unpublished_or_unresolved'] for r in rows)
    return pd.DataFrame(rows),{'public_previous_starts':18,'source':'official_fixture_public_previous_JRA17_NAR1','immutable_pre_race_snapshot':False}

def main():
    officials=json.loads(Path('bias_20261020/official_results.json').read_text())['races'];codes={r['race_code'] for r in officials}
    con=duckdb.connect();parts=[]
    for name in ['race_features.parquet','jra_features_pilot_2025_2026.parquet']:
        frame=con.execute("""SELECT *,date_diff('day',previous_race_date,race_date) AS days_since_previous_race
          FROM read_parquet(?) WHERE race_date BETWEEN '2026-01-01' AND '2026-10-18'
          AND keibajo_code BETWEEN '01' AND '10' AND grade_code IN ('A','B','C')""",
          [str(Path('bias_20261020/private_assets')/name)]).fetchdf()
        frame=frame[frame.race_code.isin(codes)]
        frame=frame[frame.umaban.astype('string').str.fullmatch(r'0?[1-9]|1[0-8]',na=False)]
        frame=frame[~frame.is_cancelled_or_excluded.fillna(False)]
        frame=frame[(frame.field_size>=3)&frame.body_weight_kg.notna()&frame.jockey_code.notna()&frame.wakuban.notna()]
        frame['_source']=name;parts.append(frame)
    joined=pd.concat(parts,ignore_index=True).drop_duplicates(['race_code','ketto_toroku_bango'],keep='first')
    spec=json.loads((source.MODEL/'feature_spec.json').read_text());features=spec['features'];good=[];audit=[]
    for official in officials:
        code=official['race_code'];rows=joined[joined.race_code==code].copy()
        expected={r['horse_number'] for r in official['finish_rows'] if r['finish_status'] not in {'取消','除外'}}
        complete=set(pd.to_numeric(rows.umaban).astype(int))==expected and not rows.umaban.duplicated().any()
        if complete:info={'source':'private_archive','immutable_pre_race_snapshot':False}
        else:
            saved=PRIVATE/('features_'+code+'.pkl');meta=PRIVATE/('features_'+code+'_audit.json')
            if saved.exists():rows=pd.read_pickle(saved);info=json.loads(meta.read_text())
            else:
                print('REBUILD',code,official['name'],flush=True)
                rows,info=swan() if code=='2026101208040511' else rebuild(official)
                rows.to_pickle(saved);meta.write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n')
        rows=rows.copy();rows['race_code']=code
        assert set(pd.to_numeric(rows.umaban).astype(int))==expected and len(rows)==len(expected)
        assert set(features)<=set(rows),sorted(set(features)-set(rows))
        assert rows.field_size.eq(len(expected)).all()
        rows['input_source']='archive' if complete else 'reconstructed'
        good.append(rows[['race_code','ketto_toroku_bango','input_source']+features])
        audit.append({'race_code':code,'runners':len(rows),'archive':complete,**info})
        print('FEATURES',code,len(rows),'archive' if complete else 'reconstructed',flush=True)
    frame=pd.concat(good,ignore_index=True);assert frame.race_code.nunique()==103 and len(frame)==1547
    assert not frame.duplicated(['race_code','ketto_toroku_bango']).any()
    frame.to_pickle(PRIVATE/'features_2026.pkl')
    report={'races':103,'horses':1547,'archive_races':sum(r['archive'] for r in audit),
        'reconstructed_races':sum(not r['archive'] for r in audit),'source_point_in_time_certified':False,'races_detail':audit}
    (ROOT/'public/input_audit_2026.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('INPUTS_READY',len(frame),flush=True)

if __name__=='__main__':main()
