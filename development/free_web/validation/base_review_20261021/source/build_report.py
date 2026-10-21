"""Decision fixed by preregistered gates, never by 2026 payout alone."""
import datetime as dt,hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path('base_review_20261021');PUBLIC=ROOT/'public';PRIVATE=ROOT/'private_assets'

def main():
    selection=json.loads((PUBLIC/'selection.json').read_text());family=selection['selected_family']
    probability=json.loads((PUBLIC/'probability_comparison.json').read_text())
    portfolio=json.loads((PUBLIC/'portfolio_comparison.json').read_text())
    rankings={r['family']:r for r in selection['ranking']};a=rankings[family];b=rankings['incumbent']
    corrected=probability['corrected'];raw=probability['raw']
    gates={'2025_joint_improved':a['ordered_nll']<b['ordered_nll'],
        '2025_unassisted_WIN_not_worse':a['raw_WIN_brier']<=b['raw_WIN_brier'],
        '2025_unassisted_TOP3_not_worse':a['raw_TOP3_brier']<=b['raw_TOP3_brier'],
        '2026_joint_improved':corrected['candidate']['joint_metrics']['ordered_nll']<corrected['incumbent_same_input']['joint_metrics']['ordered_nll'],
        '2026_corrected_WIN_not_worse':corrected['candidate']['horse_WIN']['brier']<=corrected['incumbent_same_input']['horse_WIN']['brier'],
        '2026_corrected_TOP3_not_worse':corrected['candidate']['horse_TOP3']['brier']<=corrected['incumbent_same_input']['horse_TOP3']['brier'],
        '2026_unassisted_WIN_not_worse':raw['candidate']['horse_WIN']['brier']<=raw['incumbent_same_input']['horse_WIN']['brier'],
        '2026_unassisted_TOP3_not_worse':raw['candidate']['horse_TOP3']['brier']<=raw['incumbent_same_input']['horse_TOP3']['brier'],
        'live_candidate_connected_and_validated':False}
    def paired_ci(values):
        values=np.asarray(values,float);rng=np.random.default_rng(20261021)
        boot=values[rng.integers(0,len(values),size=(10000,len(values)))].mean(axis=1)
        return {'races':len(values),'mean_difference':float(values.mean()),'bootstrap_95CI':np.quantile(boot,[.025,.975]).tolist()}
    rows=json.loads((PUBLIC/'portfolio_races.json').read_text());by={m:{r['race_code']:r for r in rows if r['method']==m} for m in ['candidate','incumbent_same_input']}
    changes=[]
    for code in by['candidate']:
        candidate=by['candidate'][code];original=by['incumbent_same_input'][code]
        changes.append(candidate['payout_yen']-original['payout_yen'])
    payout_ci=paired_ci(changes)
    variations=[]
    for file in (PRIVATE/'portfolios/incumbent_frozen').glob('*.json'):
        new=json.loads(file.read_text());old=json.loads((Path('correction_20261021/private_assets/evaluation')/file.name[:-5]/'corrected.json').read_text())
        key=lambda record:{(r['bet_type'],r['kumiban'],int(r['stake'])) for r in record['tickets']}
        if key(new)!=key(old):variations.append({'race_code':new['race_code'],'old_tickets':old.get('ticket_count',len(old['tickets'])),
            'new_tickets':len(new['tickets']),'old_payout_yen':old['payout_yen'],'new_payout_yen':new['payout_yen']})
    cv=json.loads((PUBLIC/'cv_races.json').read_text());cvby={m:{r['race_code']:r for r in cv if r['family']==m} for m in [family,'incumbent']}
    cv_ci=paired_ci([cvby[family][code]['ordered_nll']-cvby['incumbent'][code]['ordered_nll'] for code in cvby[family]])
    orig=Path('repair_20261020/private_assets/JRA_free_model_52_20261013')
    sys.path.insert(0,'correction_20261021/runtime');from probability_correction import MODEL_SHA256
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in orig.glob('*.joblib')};assert hashes==MODEL_SHA256
    summary={'record_type':'base_learner_review','created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'selected_candidate':family,'research_only':True,'adopted':False,'reason':'Prespecified gates fail. Higher retrospective payout alone is not sufficient.',
        'gates':gates,'2025_CV_paired_joint':cv_ci,'2026_paired_payout_yen_per_race':payout_ci,
        'candidate_and_incumbent_portfolios':portfolio['aggregate'],
        'changes_vs_previous_original_comparison':variations,
        'difference_attribution':'Saudi RC input reconstruction changed; solver contribution not isolated. No other incumbent portfolio changed.',
        'original_model_hashes_verified_unchanged':True,'automations_or_operating_code_changed':False,
        'tests_passed':3,'new_2026_model_inferences':{'candidate_horses':1547,'original_horses':1547},
        'new_portfolio_calculations':206,'all103_feature_inputs_recreated':True,
        'inherited_source_point_in_time_certified':False,'final_odds_and_final_starters_used':True,
        'independent_prospective_proof':False,'live_candidate_ready':False}
    (PUBLIC/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    old,new=portfolio['aggregate']['incumbent_same_input'],portfolio['aggregate']['candidate']
    fav=lambda k,group:probability[group][k]['popularity_groups'][0]
    text=f'''# 馬の強さを判断するモデルの見直し（2026年10月21日）

**学習方法を3通り変えて実際に作り直し、候補を2026年の103レースで再計算しました。今回の候補は本番に採用しません。**

## 何を試したか

1. 元のモデルと同じ52項目を使い、学習対象を直近5年の平地レースに限定。
2. さらに、同じレースの他馬と比べた過去成績を26項目追加。
3. 2の学習を少し細かくする方法。

まず2020～2024年のデータで3通りを学習し、2025年の前半までの結果で調整→それ以降で確認する比較を4回実行しました。比較した重賞は74レースです。新しい3候補の中では1が最も良く、2026年の予想を計算する前に候補・補正係数を[固定](selection.json)しました。その後、2021～2025年で1を学習し直しました。2026年の結果を使って候補を選び直していません。

## 2026年の過去比較

2026年1月4日～10月18日の103レース。両方で同じ入力、確定オッズ、最終出走馬、同じ1レース1万円の購入ルールを使いました。モデルを実際に読み込み、各1547頭を新たに予測し、合計206レース分の買い目を計算しています。

| 項目 | 現行方式を再計算 | 新しい候補 |
|---|---:|---:|
| 仮の購入総額 | {old['stake_yen']:,}円 | {new['stake_yen']:,}円 |
| 払戻総額 | {old['payout_yen']:,}円 | {new['payout_yen']:,}円 |
| 回収率 | {old['recovery_percent']:.2f}% | {new['recovery_percent']:.2f}% |
| 何か当たったレース | {old['hit_races']}/103 | {new['hit_races']}/103 |
| 損益 | {old['payout_yen']-old['stake_yen']:,}円 | {new['payout_yen']-new['stake_yen']:,}円 |

**候補の回収率は上がりましたが、100%未満です。人気馬を低く評価する問題も残っています。**

| 1番人気の平均予測 | 現行方式 | 新しい候補 | 実際 |
|---|---:|---:|---:|
| オッズ補正前：勝つ確率 | {100*fav('incumbent_same_input','raw')['pred_WIN']:.2f}% | {100*fav('candidate','raw')['pred_WIN']:.2f}% | {100*fav('candidate','raw')['actual_WIN']:.2f}% |
| オッズ補正後：勝つ確率 | {100*fav('incumbent_same_input','corrected')['pred_WIN']:.2f}% | {100*fav('candidate','corrected')['pred_WIN']:.2f}% | {100*fav('candidate','corrected')['actual_WIN']:.2f}% |

## 採用しない理由

2025年では、買い目の組合せ全体の予測は少し良くなった一方、馬ごとの勝ち・3着以内の確率には両方とも悪化した指標がありました。2026年でも、補正後の勝つ確率の誤差はわずかに悪化しています。事前に決めた採用条件を満たしていません。

回収率の上昇は主に1～6月で、7～10月は現行方式94.38%に対し候補91.32%でした。レース単位で差を取り直す統計的な幅も[summary.json](summary.json)に保存しています。小さな予測精度の差を安定した改善とは断定できません。

## 入力と検証の限界

保存済み特徴量を使った96レースでは、元のモデルの予測が前回と完全一致しました。残る7レースは公開出馬表・過去成績などから入力を作成し直しました。このうちサウジアラビアRCは前回の確率チェックポイントと差があるため、両モデルを今回の同一入力で比較しています。保存済み96レースだけでも回収率は現行77.30%→候補87.05%でした。

前回の現行方式79.19%と今回79.21%で差が出たのは、入力を再作成したサウジアラビアRCの1レースです（払戻10200円→10360円）。他の102レースの現行方式の買い目・払戻は前回と一致しました。違いは[summary.json](summary.json)に保存しています。買い目計算には時間制限があり、同じ確率でも別の組合せを選ぶ可能性がありますが、今回その影響を入力変更の影響から分離したわけではありません。最も良い再計算を選んだものではありません。

元の学習725030行について、前走日が対象レース以降の行、過去勝ち数などの大小関係・率計算の矛盾は今回の検査で0件でした。ただし、元データ全体の保存時刻や各集計値の取得時点を完全に証明したものではありません。体重の確認範囲外は1件で、誤りと断定して削除していません。

確定オッズを使った過去テストです。2026年は以前にも結果を確認した期間なので、新しい独立した実戦検証とは扱いません。発売中オッズ、当日取消、締切内の本番完走はこのテストでは検証していません。

## 保存したもの

新しい候補モデルは研究用として非公開で保管しました。元の運用モデル4ファイルのハッシュが変わっていないことを確認しています。本番コード・予約・過去の予想と成績は変更していません。公開したのは検証コードと集計結果だけです。追加の有料サービスは使用していません。

特徴量が他レースや結果ラベルから影響を受けないこと、行順変更で変わらないこと、学習時にない分類値を適切に扱うことの3テストは通過しました。

詳細：[比較条件](protocol.json)・[2025年選定](selection.json)・[入力確認](input_audit_2026.json)・[予測精度](probability_comparison.json)・[買い目の成績](portfolio_comparison.json)・[レース別一覧](portfolio_races.json)・[元データ検査](source_audit.json)
'''
    (PUBLIC/'README.md').write_text(text)
    print(json.dumps({'gates':gates,'payout_ci':payout_ci,'solver_variations':len(variations),'ROI':{k:v['recovery_percent'] for k,v in portfolio['aggregate'].items()}},indent=2),flush=True)

if __name__=='__main__':main()
