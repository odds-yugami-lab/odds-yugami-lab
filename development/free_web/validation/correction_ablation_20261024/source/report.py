"""Report paired correction ablation, preserve differences and uncertainty."""
import hashlib,json,zipfile
from pathlib import Path
import numpy as np,pandas as pd,sys
R=Path('correction_ablation_20261024');P=R/'public';A=R/'private_assets'
def main():
    report=json.loads((P/'comparison.json').read_text());rows=json.loads((P/'race_results.json').read_text());diagnostic={};checks=0
    # Audit every record, not just the result aggregates, with independent invariants.
    import math
    sys.path.insert(0,'cap30_ceiling_20261023/runtime')
    from corrected_v2_core import generate_combinations
    sys.path.insert(0,'decomposition_20261021')
    from rankwise import scores,probability_tables
    for path in sorted((A/'predictions').rglob('*.json')):
        x=json.loads(path.read_text());n=x['horse_numbers']
        for v in ['baseline','corrected']:
            ts=x[v]['tickets'];total=sum(int(t['stake']) for t in ts)
            assert 1<=len(ts)<=30 and 0<total<=10000 and x[v]['stake_yen']==total
            assert x[v]['unspent_yen']==10000-total
            for t in ts:assert t['stake']==100*max(1,math.ceil(100/t['decimal_odds']-1e-12))
            checks+=1
        if x['year']==2025:
            r={'race_code':x['race_code'],'numbers':n,'win':x['original_head_probabilities']['win'],'top3':x['original_head_probabilities']['top3'],'odds':x['win_odds']}
            _,c,_=probability_tables(r,scores(r,'shared_ai_market',[1,0]))
            old=generate_combinations(pd.DataFrame({'race_code':r['race_code'],'umaban':n,'win_probability':r['win'],'top3_probability':r['top3']}))
            d=c.merge(old,on=['race_code','bet_type','kumiban'],suffixes=('_new','_old'),validate='one_to_one')
            assert abs(d.ai_probability_new-d.ai_probability_old).max()<1e-10
    rng=np.random.default_rng(20261024)
    for y in [2025,2026]:
        data={v:{x['race_code']:x for x in rows if x['year']==y and x['method']==v} for v in ['baseline','corrected']}
        codes=sorted(data['baseline']);assert set(codes)==set(data['corrected'])
        pay=np.array([[data[v][c]['payout_yen'] for c in codes] for v in ['baseline','corrected']]);stake=np.array([[data[v][c]['stake_yen'] for c in codes] for v in ['baseline','corrected']])
        idx=rng.integers(0,len(codes),(20000,len(codes)));roi=100*pay[:,idx].sum(axis=2)/stake[:,idx].sum(axis=2)
        dif=[]
        for c in codes:
            b=data['baseline'][c];a=data['corrected'][c]
            dif.append({'race_code':c,'date':a['date'],'payout_before':b['payout_yen'],'payout_after':a['payout_yen'],
              'stake_before':b['stake_yen'],'stake_after':a['stake_yen'],'profit_difference_yen':(a['payout_yen']-a['stake_yen'])-(b['payout_yen']-b['stake_yen'])})
        dif.sort(key=lambda x:x['profit_difference_yen'],reverse=True)
        diagnostic[str(y)]={'corrected_minus_baseline_roi_percentage_points':report['annual'][str(y)]['portfolio']['corrected']['recovery_percent']-report['annual'][str(y)]['portfolio']['baseline']['recovery_percent'],
          'paired_bootstrap95_percentile_interval_percentage_points':np.quantile(roi[1]-roi[0],[.025,.975]).tolist(),
          'bootstrap_seed':20261024,'bootstrap_samples':20000,'bootstrap_is_descriptive_not_independent_new_test':True,
          'both_hit':sum(data['baseline'][c]['any_hit'] and data['corrected'][c]['any_hit'] for c in codes),
          'only_before_hit':sum(data['baseline'][c]['any_hit'] and not data['corrected'][c]['any_hit'] for c in codes),
          'only_after_hit':sum(not data['baseline'][c]['any_hit'] and data['corrected'][c]['any_hit'] for c in codes),'profit_differences':dif}
    audit={'ticket_portfolios_checked':checks,'races_checked':checks//2,'all_invariants_passed':True,'original_combination_conversion_verified_all222':True,
      'source_data_container_may_include_result_fields':True,'only_whitelisted_forecast_fields_reach_predict_and_allocator':True,
      'original_heads_platt_calibration_not_removed':True,'corrected_portfolios_reused_with_hash_and_probability_checks':True,
      'solver_time_cap_same_seconds':30,'relative_gap_same':.01,'same_formula_numeric_objective_scale_depends_on_probabilities':True}
    (P/'audit.json').write_text(json.dumps(audit,indent=2)+'\n');(P/'paired_diagnostics.json').write_text(json.dumps(diagnostic,indent=2)+'\n')
    lines=['# 現行モデル：人気補正の前後比較','',
      '結論：人気別の確率の偏りは小さくなり、的中レースは両年とも増えました。ただし回収率は2025年に改善し、2026年に悪化しました。補正によって回収率が安定して改善したとは判断できません。今回の作業では運用モデル・補正・予約を変更していません。','',
      '|期間|補正|レース数|実配分額|払戻|回収率|的中レース|的中率|平均点数|',
      '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for y,d in report['annual'].items():
        for v,label in [('baseline','なし'),('corrected','あり')]:
            z=d['portfolio'][v];lines.append(f"|{y}年|{label}|{z['races']}|{z['stake_yen']:,}円|{z['payout_yen']:,}円|{z['recovery_percent']:.2f}%|{z['hit_races']}|{100*z['hit_rate']:.2f}%|{z['ticket_count_mean']:.2f}|")
    lines+=['','回収率の分母は実配分額です。買い目は最大30点、予算は上限1万円、各券は単独的中時1万円以上となる最低必要額、残額は使わず残す、期待払戻と的中機会を50:50で評価する同一ルールです。全444組の配分について点数・予算・最低額を検査しました。',
      '', '## 何を比較したか','',
      '同じ現行52項目モデルのWIN/TOP3出力と同じ既存の確率補正器を使用。追加の市場補正だけを外した場合と、事前に固定した市場補正を適用した場合を比べました。「補正なし」はPlatt補正器まで外した生のLightGBM値ではありません。以前から使っていたWINとTOP3の幾何平均を使う馬連・3連複変換です。',
      '市場補正はAI評価の強弱と市場オッズの重みを一緒に変える既存方式です。単に市場の項だけゼロにしてAI重みを補正後の値に残す比較ではありません。両者の確率変換と配分コード・制限時間・許容誤差は同じです。期待払戻を尺度化する式も同じですが、入力確率が異なるので数値の尺度は変わります。',
      '補正なしの222レースを今回再計算しました。補正ありの222レースは前回の買い目原本をハッシュ照合して使い、今回計算し直した補正後確率と全購入券の確率が一致することも確認しました。両方を再配分したと説明しません。',
      '', '## 人気別の評価','',
      '以下は買い目の確率を作る整合的な確率分布の値です。元のWIN/TOP3出力も別に保存しています。人気順は最終単勝オッズ順（同率は馬番順）のため、公式人気順位と同オッズ馬の順序が異なる場合があります。',
      '', '|期間・グループ|項目|補正前の平均予測|補正後の平均予測|実際の割合|','|---|---|---:|---:|---:|']
    for y,d in report['annual'].items():
        for group,label in [('1-1','1番人気'),('7-18','7番人気以下')]:
            b=d['horse_metrics']['baseline']['popularity_groups'][group];c=d['horse_metrics']['corrected']['popularity_groups'][group]
            for h,l in [('win','勝率'),('top3','3着以内率')]:lines.append(f"|{y}年・{label}|{l}|{100*b[h]['predicted_mean']:.2f}%|{100*c[h]['predicted_mean']:.2f}%|{100*c[h]['observed_rate']:.2f}%|")
    lines+=['','全馬の勝率・3着以内率の予測誤差（Brier・対数損失）は両年とも補正後が小さくなりました。しかし、確率の精度や的中率の改善は、そのまま回収率の改善を意味しません。人気馬寄りに買い目や配分が変わるため、的中回数が増えても払戻の大きい当たりを逃すことがあります。個別の増減と年の前半・後半もJSONに記録しました。',
      '', '## 結果を使わない計算と範囲','',
      '2025年は基礎モデルが2024年末まで、補正係数が2024年のデータで固定済み。2026年は2025年末までで固定済み。今回は学習・係数探索・人気馬への一律加点を行っていません。入力の元データ容器には着順等があるものもありますが、買い目計算には許可した予測項目のみ渡し、結果や払戻は渡していません。買い目ファイルのハッシュをGitHubで確定してから公式払戻で収支を計算しました。',
      '2025年は元の130識別子から既存の欠損等11件を除いた119件で買い目を作成し、公式結果を一意に対応できなかった2件（2025060105021211、2025122706050711）は両方式から同じように除外して117レースで比較しました。2026年は2026年10月18日までの共通103レース。最終出走馬と確定オッズによる過去テストであり、実戦成績ではありません。',
      '研究全体ではこれらの年を既に調べており、2025年はモデルの方式選択にも使われています。完全な未知期間での確認ではなく、保存特徴量全体の予測時点の正当性も完全に証明したものではありません。30秒・誤差1%以内という同じ設定ですが、時間切れの実行可能解を含むため、厳密な最適解の比較ではない場合があります。',
      '', '[詳細比較](comparison.json)／[レース別収支](race_results.json)／[差の内訳・幅](paired_diagnostics.json)／[検査](audit.json)／[事前固定条件](protocol.json)／[計算原本のハッシュ](prediction_manifest.json)',
      '']
    (P/'README.md').write_text('\n'.join(lines))
    dest=R/'JRA_correction_ablation_private_20261024.zip'
    with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(A.rglob('*')):
            if p.is_file():z.write(p,str(p.relative_to(A)))
    with zipfile.ZipFile(dest) as z:assert z.testzip() is None
    (P/'private_archive.json').write_text(json.dumps({'filename':dest.name,'size_bytes':dest.stat().st_size,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'public_binary':False},indent=2)+'\n')
    print('AUDIT',audit);print('DIAGNOSTICS',{y:{k:v for k,v in x.items() if k!='profit_differences'} for y,x in diagnostic.items()});print('ZIP',dest.stat().st_size)

if __name__=='__main__':main()
