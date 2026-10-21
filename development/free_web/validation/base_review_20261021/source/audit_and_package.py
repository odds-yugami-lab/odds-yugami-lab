"""Save private research model separately; do not replace the operating package."""
import datetime as dt,hashlib,json,platform,shutil,zipfile
from pathlib import Path
import duckdb,joblib,lightgbm,numpy,pandas,sklearn
ROOT=Path('base_review_20261021');PUBLIC=ROOT/'public';PRIVATE=ROOT/'private_assets'

def main():
    con=duckdb.connect()
    con.execute("""CREATE VIEW checked AS SELECT * FROM read_parquet('bias_20261020/private_assets/race_features.parquet')
        WHERE analysis_eligible AND keibajo_code BETWEEN '01' AND '10' AND race_date<='2025-12-31'
        AND target_win IS NOT NULL AND target_top3 IS NOT NULL""")
    rate_checks={}
    for prefix in ['horse_prior','horse_distance_prior','horse_course_track_prior','jockey_prior','trainer_prior','sire_prior']:
        query=f"""SELECT count(*) FILTER(WHERE {prefix}_wins<0 OR {prefix}_top3<0 OR {prefix}_starts<0
            OR {prefix}_wins>{prefix}_top3 OR {prefix}_top3>{prefix}_starts),
            count(*) FILTER(WHERE {prefix}_starts>0 AND abs({prefix}_win_rate-{prefix}_wins/{prefix}_starts)>1e-6),
            count(*) FILTER(WHERE {prefix}_starts>0 AND abs({prefix}_top3_rate-{prefix}_top3/{prefix}_starts)>1e-6)
            FROM checked"""
        a,b,c=con.execute(query).fetchone();rate_checks[prefix]={'invalid_counts':a,'win_rate_mismatches':b,'top3_rate_mismatches':c}
    body=con.execute('SELECT count(*),count(*) FILTER(WHERE previous_race_date>=race_date),count(*) FILTER(WHERE body_weight_kg IS NOT NULL AND body_weight_kg NOT BETWEEN 300 AND 650) FROM checked').fetchone()
    audit={'original_training_rows':body[0],'previous_date_at_or_after_target':body[1],
        'bodyweight_outside_screening_range':body[2],'outside_range_not_automatically_error':True,
        'aggregate_internal_checks':rate_checks,
        'counts_consistent_do_not_prove_point_in_time':'Historical source snapshot timing and full recomputation of source aggregates remain uncertified.',
        'public_previous_2026_reconstruction':'Strictly preceding starts; source archives96 and public reconstruction7 separately reported.',
        'original_model_modified':False}
    (PUBLIC/'source_audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    selection=json.loads((PUBLIC/'selection.json').read_text());family=selection['selected_family']
    package=PRIVATE/'JRA_recent52_research_20261021';package.mkdir(exist_ok=True)
    for file in ['win_model.joblib','top3_model.joblib','feature_spec.json']:
        shutil.copy2(PRIVATE/(family+'_through2025')/file,package/file)
    for label in ['win','top3']:shutil.copy2(PRIVATE/(family+'_2025_'+label+'_platt.joblib'),package/(label+'_platt.joblib'))
    manifest={'package':package.name,'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'research_candidate_only':True,'adopted':False,'live_operation_ready':False,
        'training_period':['2021-01-01','2025-12-31'],'training_rows':219047,
        'training_source_sha256':hashlib.sha256(Path('bias_20261020/private_assets/race_features.parquet').read_bytes()).hexdigest(),
        'feature_count':52,'training_filter':'Complete unique flat10..29 fields, one winner, three top3 labels; five recent complete years.',
        'base_parameters':dict(objective='binary',n_estimators=368,learning_rate=.025,num_leaves=24,max_depth=8,
            min_child_samples=200,subsample=.85,colsample_bytree=.8,reg_alpha=.5,reg_lambda=2.,random_state=20261002,n_jobs=2,verbosity=-1),
        'calibration_predictions':'2025 from model trained2020..2024; full2025 Platt fits, chronological2025 CV used separate earlier-only fits.',
        'market_correction':selection['final_2025_fits'][family],
        'selection_commit':json.loads((PUBLIC/'selection_commit.json').read_text())['commit_sha'],
        'source_feature_point_in_time_certified':False,'2026_used_for_training_or_selection':False,
        '2026_previously_inspected':True,'original_package_replaced':False,
        'versions':{'python':platform.python_version(),'lightgbm':lightgbm.__version__,'pandas':pandas.__version__,
            'numpy':numpy.__version__,'scikit_learn':sklearn.__version__,'joblib':joblib.__version__}}
    manifest['file_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in package.iterdir() if p.is_file()}
    (package/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (package/'README.txt').write_text('研究用候補です。本番には不採用。元の運用モデルは変更していません。\n2011年以降すべてから学習した元モデルに対し、2021～2025年の平地に限定して再学習。\n2026年比較の最終報告を参照してください。確定オッズによる過去テストです。\n')
    dest=ROOT/'JRA_recent52_research_20261021.zip'
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(package.iterdir()):z.write(p,package.name+'/'+p.name)
    with zipfile.ZipFile(dest) as z:assert z.testzip() is None
    (PUBLIC/'candidate_package.json').write_text(json.dumps({'filename':dest.name,'size_bytes':dest.stat().st_size,
        'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'binary_public':False,'research_only':True,
        'original_package_modified':False,'model_hashes':manifest['file_sha256']},indent=2)+'\n')
    print('AUDIT',json.dumps(audit),'PACKAGE_BYTES',dest.stat().st_size,flush=True)

if __name__=='__main__':main()
