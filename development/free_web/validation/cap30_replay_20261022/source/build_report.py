"""Summarize all failures, matched cohorts and allocation sensitivity honestly."""
import csv,hashlib,json,math,zipfile
from pathlib import Path
ROOT=Path('cap30_replay_20261022');PUBLIC=ROOT/'public';PRIVATE=ROOT/'private_assets'

def main():
    report=json.loads((PUBLIC/'comparison.json').read_text())
    official={r['race_code']:r for r in json.loads(Path('bias_20261020/official_results.json').read_text())['races']}
    fail=[]
    for code in sorted({r['race_code'] for r in report['failures']}):
        sources=json.loads((Path('bias_20261020/public_cache/odds')/(code+'.json')).read_text())['snapshots']
        minimums=sorted([100*max(1,math.ceil(100/r['decimal_odds']-1e-12)) for s in sources.values() for r in s['rows']],reverse=True)
        maximum30=sum(minimums[:30]);assert maximum30<10000
        fail.append({'race_code':code,'date':official[code]['date'],'name':official[code]['name'],
            'top30_largest_required_stakes_yen':maximum30,'shortfall_to_10000_yen':10000-maximum30,
            'failure_kind':'mathematically_infeasible_under_fixed_rule','both_models_affected':True})
    previous=json.loads(Path('base_review_20261021/public/portfolio_races.json').read_text())
    codes={r['race_code'] for r in report['payout_difference_contributors']}
    before={}
    for method,old in [('incumbent','incumbent_same_input'),('candidate','candidate')]:
        rows=[r for r in previous if r['method']==old and r['race_code'] in codes]
        assert len(rows)==100
        before[method]={'races':len(rows),'payout_yen':sum(r['payout_yen'] for r in rows),
            'recovery_percent':sum(r['payout_yen'] for r in rows)/10000,
            'hit_races':sum(r['any_hit'] for r in rows)}
    verification={'new_cases_attempted':206,'new_predictions_prepared':200,'settled_cases':200,
        'matched_races':100,'failures_unique_races':3,'failure_proof':fail,
        'original_reconstruction_tests_previously_passed':5,'new_prediction_isolation_tests_passed':2,
        'prediction_manifest_commit':report['prediction_manifest_commit'],
        'all_sealed_prediction_bytes_reverified_before_settlement':True,
        'all_ticket_count_at_most30':True,'all_stakes_exact_minimum':True,
        'original_policy_equivalence_certified':False,'normalizer_and_solver_are_unverified_reconstruction_settings':True,
        'same100_prior_no_cap_comparison':before,'no_cap_ROI103_not_directly_comparable_to_cap30_ROI100':True,
        'production_or_automations_changed':False}
    (PUBLIC/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n')
    # Private full prediction bytes preserve the exact sealed artifacts, without
    # duplicating repository-backed code/reports in Library.
    archive=ROOT/'cap30_prediction_records_20261022.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted((PRIVATE/'predictions').rglob('*.json')):z.write(p,str(p.relative_to(PRIVATE)))
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None and len(z.namelist())==200
    package={'filename':archive.name,'size_bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'sealed_prediction_files':200,
        'contains_models_or_history':False,'contains_result_labels':False,'test_only':True,
        'prediction_manifest_commit':report['prediction_manifest_commit']}
    (PUBLIC/'prediction_archive.json').write_text(json.dumps(package,indent=2)+'\n')
    a=report['aggregate_common_cases']['incumbent'];b=report['aggregate_common_cases']['candidate']
    failure_table='\n'.join(f"| {r['name']} | {r['top30_largest_required_stakes_yen']:,}円 | {r['shortfall_to_10000_yen']:,}円 |" for r in fail)
    half=report['halves_common_cases']
    md=f'''# 最大30点・50:50復元候補の2026年回収率再検証

**両モデルとも同じ100レースで計算でき、回収率は現行モデル71.58%、新しい候補71.54%、的中61レースでした。候補の優位性は確認できません。**

103レース×2モデルの全206件を試行しましたが、3レースは両モデルとも購入条件を両立できず、200件の買い目を確定しました。103レースすべてで完走した検証ではありません。

## 同じ100レースでの結果

| 項目 | 現行モデル | 新しい候補 |
|---|---:|---:|
| 対象 | 100レース | 100レース |
| 仮の購入総額 | {a['stake_yen']:,}円 | {b['stake_yen']:,}円 |
| 払戻総額 | {a['payout_yen']:,}円 | {b['payout_yen']:,}円 |
| 回収率 | {a['recovery_percent']:.2f}% | {b['recovery_percent']:.2f}% |
| 的中レース | {a['hit_races']} | {b['hit_races']} |
| 損失 | {-a['profit_yen']:,}円 | {-b['profit_yen']:,}円 |
| 平均買い目点数 | {a['ticket_count_mean']:.2f}点 | {b['ticket_count_mean']:.2f}点 |
| 最小～最大点数 | {a['ticket_count_min']}～{a['ticket_count_max']}点 | {b['ticket_count_min']}～{b['ticket_count_max']}点 |
| 25～30点のレース | {a['races_with_25_to_30_tickets']} | {b['races_with_25_to_30_tickets']} |

候補の払戻は現行より410円少ない結果です。候補が多かった9レース、少なかった6レース、同額85レースでした。レース単位で見た払戻差の推定幅も改善・悪化の双方を含みます。[詳細](comparison.json)

| 期間 | 現行回収率 | 候補回収率 |
|---|---:|---:|
| 1～6月・65レース | {half['H1']['incumbent']['recovery_percent']:.2f}% | {half['H1']['candidate']['recovery_percent']:.2f}% |
| 7～10月18日・35レース | {half['H2']['incumbent']['recovery_percent']:.2f}% | {half['H2']['candidate']['recovery_percent']:.2f}% |

## 3レースで条件が両立しなかった理由

各買い目を単独払戻1万円以上になる最低必要額に固定すると、次のレースでは必要額が大きい順に30点選んでも合計1万円に届きません。別の組合せを選んだり計算時間を延長しても、この上限の不足は解消できません。

| レース | 最低必要額の大きい30点の合計 | 1万円との差 |
|---|---:|---:|
{failure_table}

この3レースは正式な「見送り」と決めたのではなく、ルールの両立不能として記録したものです。1万円を使い切るための増額や31点以上への変更はしていません。3レースを隠して103レースの成績として集計することもしていません。

## 以前の79.21%・88.28%との関係

以前の数字は点数制限なし・103レースでした。今回計算できた**同じ100レース**に限定すると、点数制限なしの成績は現行77.22%・候補86.56%でした。

| 同じ100レースの購入方式 | 現行モデル | 候補 |
|---|---:|---:|
| 点数制限なし（前回計算済み） | {before['incumbent']['recovery_percent']:.2f}% | {before['candidate']['recovery_percent']:.2f}% |
| 最大30点・50:50復元候補（今回新規計算） | {a['recovery_percent']:.2f}% | {b['recovery_percent']:.2f}% |

確率予測には、以前の79.21%・88.28%比較と同じ元モデル／recent52候補の計算済み予測と、各モデルで2025年に固定した市場補正係数を使っています。今回変えたのは買い目の算定方法で、人気馬への追加1.2倍補正はありません。秋華賞の原本再現で使った市場補正なしの元確率とは、今回の比較対象を区別しています。

## 買い目の確定と答え合わせ

購入ルール・尺度・計算設定は[事前に固定](protocol.json)。予想処理には結果ラベル・着順・公式払戻を渡さず、200件の買い目と金額を先に保存しました。その全件のハッシュと6件の失敗（3レース×2モデル）を[GitHubへ確定](https://github.com/odds-yugami-lab/odds-yugami-lab/commit/{report['prediction_manifest_commit']})した後、保存内容が変わっていないことを全200件で照合し、公式結果で払戻を計算しました。

予想から結果ラベルを除く検査と、確定後の買い目改変を拒否する検査は2件とも通過しています。各券の最低必要額、合計1万円、最大30点も実際の出力で全200件確認しました。

## 復元と検証の限界

このコードは最大30点・最低必要額・50:50の復元候補です。期待払戻の尺度は旧Aコードにある `max(AI確率×オッズ)×10000` とし、目的を `0.5×E/尺度＋0.5×H` に固定しました。当時のcap30元コードとの完全一致は未確認です。尺度や計算設定を2026年の回収率を見て変更していません。

計算時間上限30秒、許容誤差1%を両モデルに同じように設定しています。全てで唯一・厳密な最適解を保証するものではなく、解ごとの誤差を記録しています。

確定オッズ・最終出走馬による過去テストで、2026年は既に何度も確認した期間です。元の特徴量全体の取得時点が完全に証明されたわけでもありません。今後の利益や本番の期限内動作を保証しません。

今回の結果は候補モデルへの切替根拠にはなりません。また、3レースの両立不能と、25点未満になった5レースの扱いは、運用条件として残っています。2025年の検証、本番コード・予約の変更、X送信・馬券購入は行っていません。過去原本も変更していません。

[レース別結果](race_results.json)／[照合・失敗の詳細](verification.json)／[計算コード](source/run.py)
'''
    (PUBLIC/'README.md').write_text(md)
    print('REPORT_READY',len(fail),'infeasible; archive bytes',archive.stat().st_size,flush=True)

if __name__=='__main__':main()
