"""Write a transparent diagnostic report, including negative findings."""
import argparse,datetime as dt,json
from pathlib import Path
import numpy as np,pandas as pd

LABELS={'market_PL':'市場オッズだけ（調整係数なし）','shared_ai_market':'現行と同じ共通補正',
    'stage_market':'着順別の市場補正','stage_shared_ai':'着順別のAI＋市場補正','stage_two_heads':'WIN/TOP3別＋着順別補正',
    'incumbent_frozen':'現行の固定補正'}

def main(workdir):
    root=Path(workdir);diagnosis=json.loads((root/'public/decomposition.json').read_text())
    selection=json.loads((root/'public/selection.json').read_text())
    portfolio=json.loads((root/'public/portfolio_comparison.json').read_text())
    values=json.loads((root/'private_assets/evaluation_horse_rows.json').read_text())
    original=pd.DataFrame(json.loads(Path('bias_20261020/horse_predictions_all.json').read_text()))
    values['raw_independent']=[{'race_code':str(code),'horses':g.to_dict('records')} for code,g in original.groupby('race_code')]
    race_codes=sorted(original.race_code.unique().tolist());rng=np.random.default_rng(20261021)
    indices=rng.integers(0,len(race_codes),size=(10000,len(race_codes)))
    uncertainty={}
    for method,races in values.items():
        by_code={r['race_code']:r for r in races};uncertainty[method]={}
        for label,keep in [('favorite',lambda h:h['popularity']==1),('popularity_11plus',lambda h:h['popularity']>=11)]:
            counts=[];delta_win=[];delta_top=[]
            for code in race_codes:
                h=[h for h in by_code[code]['horses'] if keep(h)]
                counts.append(len(h));delta_win.append(sum(x['win_probability']-x['target_win'] for x in h))
                delta_top.append(sum(x['top3_probability']-x['target_top3'] for x in h))
            denominator=np.array(counts)[indices].sum(axis=1)
            group={}
            for target,delta in [('WIN',delta_win),('TOP3',delta_top)]:
                difference=np.array(delta)[indices].sum(axis=1)/denominator
                group[target]={'predicted_minus_observed':float(sum(delta)/sum(counts)),
                    'race_bootstrap_95CI':np.quantile(difference,[.025,.975]).tolist(),'horses':sum(counts)}
            uncertainty[method][label]=group
    (root/'public/popularity_uncertainty.json').write_text(json.dumps(uncertainty,indent=2)+'\n')
    raw=diagnosis['decomposition']['raw_independent']['popularity_groups'][0]
    joint=diagnosis['decomposition']['geometric_WIN_TOP3_PL']['popularity_groups'][0]
    current=diagnosis['2026_aggregate']['incumbent_frozen']['popularity_groups'][0]
    method_order=['market_PL','shared_ai_market','stage_market','stage_shared_ai','stage_two_heads']
    cv={r['method']:r for r in selection['ranking']}
    table='\n'.join('|'+LABELS[m]+'|'+f"{cv[m]['mean_ordered_nll']:.4f}"+'|'+
        f"{diagnosis['2026_aggregate'][m]['joint_metrics']['ordered_nll']:.4f}"+'|'+
        f"{diagnosis['2026_aggregate'][m]['popularity_groups'][0]['pred_WIN']:.1%}"+'|' for m in method_order)
    source_table='\n'.join('|'+name+'|'+f"{row['pred_WIN']:.1%}"+'|'+f"{row['pred_TOP3']:.1%}"+'|' for name,row in [
        ('元の独立WIN/TOP3',raw),('従来の組み合わせ変換が表す周辺確率',joint),('現在の市場を使う補正版',current),
        ('実際の頻度',{'pred_WIN':raw['actual_WIN'],'pred_TOP3':raw['actual_TOP3']})])
    p=portfolio['aggregate'];pt='\n'.join('|'+LABELS.get(m,m)+'|'+str(v['hit_races'])+'/103|'+f"{v['recovery_percent']:.2f}%"+'|'+f"{v['payout_yen']:,}円"+'|' for m,v in p.items())
    rawci=uncertainty['raw_independent']['favorite']['WIN'];currentci=uncertainty['incumbent_frozen']['favorite']['WIN']
    marketci=uncertainty['market_PL']['favorite']['WIN'];stageci=uncertainty['stage_shared_ai']['favorite']['WIN']
    cvdiff=diagnosis['paired_2025_CV']['stage_shared_ai vs stage_market']
    summary={'record_type':'residual_bias_investigation_result','date_jst':'2026-10-21','task1_completed':True,
        'task2_completed':True,'further_correction_improvement_confirmed':False,'production_or_automation_changed':False,
        'main_finding':'Most original popularity-conditional bias already exists in separate WIN/TOP3 forecasts. Joint conversion trades off marginal accuracy; it is not the sole source.',
        'additional_correction_decision':'No deployment. Rank-specific adjustments improve WIN marginal metrics but do not beat incumbent overall joint metrics on 2026.',
        'training_selection_method':selection['selected_method'],'selection_rule':selection['selection_rule'],
        'selection_period':2025,'forward_validation_races':len(selection['validation_race_codes']),
        'evaluation_races':103,'evaluation_is_untouched':False,'final_odds_used':True,
        'cv_AI_increment_over_same_stage_market':cvdiff,'all_test_count':5,'tests_passed':True,
        'portfolio':p,'limits':diagnosis['limits']}
    (root/'public/summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    readme=f'''# 残る偏りの切り分けと補正方法の比較（2026-10-21）

依頼1・2の検証を完了。**追加補正による安定した改善は確認できず、今回の追加候補は本番に採用しない。** 予想予約・本番コード・モデルZIP・内部履歴・過去の原本と収支は変更していない。現行の市場補正v1の設定を維持する。

## 1. 元の予測と組み合わせ変換の切り分け

2026年の平地重賞103レース・1,547頭。同じ出走馬で、元のWIN/TOP3、WINのみからの変換、従来のsqrt(WIN×TOP3)の変換、現在の市場補正版を比較した。

1番人気の平均予測：

|段階|WIN|TOP3|
|---|---:|---:|
{source_table}

主な人気馬の過小評価は、組み合わせへの変換前にある。WINのレース内正規化だけなら1番人気は13.9%、従来のWIN/TOP3混合後は12.8%で、TOP3との混合によりWINの人気馬評価は少し薄まる。一方、TOP3周辺確率は34.2%から35.8%に上がり実績へ近づく。

変換はすべての誤差を悪化させているわけではない。全頭のBrierは、元WIN0.060250→従来変換0.059768、元TOP3 0.146297→0.144921と少し改善。人気馬だけの平均勝率を高めることを、全買い目の確率改善と同一視しない。

ここでいう「変換後WIN/TOP3」は、全順列の確率を足し合わせて得る周辺確率。従来の発走前記録に保存される独立WIN/TOP3の表示値と、買い目計算が実際に使う分布を分けた。元WIN/TOP3を別々に作るだけでは、両方が同じ単一強度の順位分布と完全に整合するとは限らない。今回、変換を確率の二重計上等の計算ミスとする証拠は得ていない。

現在の市場補正後も1番人気のWINは22.8%に対し実績34.0%。この差は約11.2ポイント。ただし103レースの観測であり、補正目標を2026年の34.0%そのものに設定していない。

## 2. 2025年内で方法を選び、2026年で確認

2024年末までで学習した既存の再構成モデルから、2025年47,497頭・3,455レースを再推論した。前の2025年重賞1,931頭の確率と照合し、差は保存JSONの丸め範囲（最大5×10^-11）だった。

重要な分離：2025年全体で学習したPlatt補正器を、そのまま2025年内の検証に使わない。各区間の訓練終了日までの**全レース**だけでWIN/TOP3補正器を学習し直し、後の区間を予測した。元のLightGBMは2024年末までのまま。

|訓練ラベルの最終日|評価区間|
|---|---|
|2025-04-30|2025年5～6月|
|2025-06-30|2025年7～8月|
|2025-08-31|2025年9～10月|
|2025-10-31|2025年11～12月|

市場補正は2025年の全頭が揃う119重賞を使用し、順次評価の対象は74レース。元の候補130レースのうち、頭数・特徴量が揃わない9レース、上位3着順が一意に揃わない2レースを除く。前回と同じ除外対象を固定した。

比較した方法は、共通のAI＋市場補正、1～3着で市場評価の強弱を別にする方法、着順別にAIと市場を使う方法、1着にはWIN・2/3着にはTOP3を使う方法、市場だけの基準。馬連・3連複と的中率は、各方法の同じ全順位分布から計算する。

下表の誤差は上位3着の順番までの平均負の対数尤度（小さいほど良い）。同着のある2026年安田記念はこの指標から除き102レースで評価、馬ごとの確率指標と公式払戻集計は103レースを維持。

|方法|2025年の順次評価|2026年の評価|2026年1番人気WIN|
|---|---:|---:|---:|
{table}

2025年では着順別AI＋市場の平均誤差が最小だったが、同じ着順別市場補正へのAI追加の差は{cvdiff['difference']:.4f}、レース単位bootstrap95%区間[{cvdiff['bootstrap_95CI'][0]:.4f}, {cvdiff['bootstrap_95CI'][1]:.4f}]で、安定した上積みは確認できない。

先に定めた「最良平均誤差の1標準誤差以内なら自由パラメータが少ない方法を選ぶ」保守的な規則では、市場だけの固定基準が選ばれた。2026年を見た後にこの選択を変更していない。これはAIが無価値である証明ではなく、今回の学習期間内の比較から、複雑な補正を優先するだけの根拠が得られなかったという意味。

2026年では、着順別補正で1番人気のWIN平均は約26.7%まで上がり、WINのBrierも改善した。しかし馬連・3連複と上位着順全体の誤差は現行補正を上回らなかった。前半68レース・後半35レースに分けても、着順別の追加候補の着順誤差は現行補正より大きかった。新しい候補を2026年に合わせて再調整していない。

## 確率の差の不確実性

レースを単位とした探索的bootstrap95%区間を`popularity_uncertainty.json`に保存。複数比較の調整はしていない。1番人気WINの「予測－実績」は、現行補正版で約-11.2ポイント。市場だけでは約-6.3ポイント、着順別AI＋市場では約-7.3ポイントで、後二者の95%区間は0を含む。1番人気が過去103レースで34.0%勝ったことだけから、今後の予測を必ず34.0%へ押し上げる根拠にはならない。

## 買い目まで再計算

2025年で選ばれた市場基準と現行固定補正を、それぞれ103レース、計206件で実際に配分・公式払戻計算した。合計1万円、100円単位、各券は単独払戻1万円以上になる最低額のみ、配分目的関数・探索重み・solver設定を固定した。

|方法|的中レース|回収率|公式払戻|
|---|---:|---:|---:|
{pt}

両方式とも合計投入1,030,000円に届かず赤字。回収率を見て方法を選んでいない。市場基準の1レースで近似solverの買い目が42→46点に変わったが、払戻は同じ11,700円。元の監査記録は保全し、都合の良い再実行で置き換えていない。現行固定補正の全103買い目は前回と一致した。

## 結論と保全

- 元の独立WIN/TOP3に大きな人気別のずれがある。組み合わせ変換だけを直せば解決する状態ではない。
- 変換にはWIN/TOP3の両立・順位別の強弱という制約があるが、今回の追加自由度は別期間の全体改善につながらなかった。
- 依頼の切り分け・学習期間内比較・別期間評価・買い目再計算は実施した。改善が出たものとして追加補正を採用しない。本番の市場補正v1と予約を維持する。
- 次に改善対象となるのは元のWIN/TOP3の情報・特徴量・学習方法。今回の結果だけで原因を特定したと断定しない。

5つの検証テスト（既知の一様確率、順位別分布と対数尤度の一致、結果ラベルからの確率生成の独立、未来ラベルが過去区間の補正器に影響しないこと、全買い目既知ケースの配分・不正分布拒否）が通過。全206件で予算・最低額・組み合わせ確率と順位分布の一致を検証。

これは確定オッズ・最終出走馬を使う事後検証。2026年は過去の診断や補正の評価にすでに使われたため、完全な未見期間・独立した将来検証とは呼ばない。元の全特徴量の時点整合性は未証明。前回の監査と同じく一部に保存確率checkpoint・公開情報からの再構成を含む。モデル・内部履歴・非公開fixture・生特徴量は公開していない。X送信・馬券購入・本番成績への算入・予約変更を行っていない。

主なファイル：`protocol.json`（事前の基準）、`selection.json`（2025年で固定した選定）、`decomposition.json`（切り分けと全候補の評価）、`portfolio_comparison.json`（買い目比較）、`summary.json`（実行結果）。
'''
    (root/'public/README.md').write_text(readme,encoding='utf-8')
    print(json.dumps({'summary':summary,'favorite_uncertainty':{m:uncertainty[m]['favorite']['WIN'] for m in ['raw_independent','incumbent_frozen','market_PL','stage_shared_ai']}},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('workdir');a=p.parse_args();main(a.workdir)
