"""Create a year-separated report and audit all historical portfolios."""
import hashlib,importlib.util,json,math,zipfile
from pathlib import Path
import numpy as np
spec=importlib.util.spec_from_file_location('profit_study','profit_comparison_20261024/replay.py')
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
R=s.R;P=s.P;A=s.A
LABELS={'A_current':'現状（期待払戻＋的中）','B_filter_gross':'不利な券を除いて再配分','C_net_all':'期待利益＋的中へ変更','D_filter_net':'不利な券を除き、期待利益＋的中','E_delete_only':'参考：元の買い目から単純削除'}
def main():
    c=json.loads((P/'comparison.json').read_text());rows=json.loads((P/'race_results.json').read_text());records,m=s.records()
    assert not m['failures'] and not c['allocation_failures'] and len(records)==222
    count=0;new=0
    for r in records:
        assert not r['failures'] and set(r['variants'])==set(s.VARIANTS)
        for name,v in r['variants'].items():
            ts=v['tickets'];st=sum(t['stake'] for t in ts);metric=v['metrics']
            assert (0 if name=='E_delete_only' else 1)<=len(ts)<=30 and 0<=st<=10000 and st==metric['stake_yen']
            assert metric['unspent_yen']==10000-st and metric['ticket_count']==len(ts)
            for t in ts:assert t['stake']==100*max(1,math.ceil(100/t['decimal_odds']-1e-12))
            e=sum(t['stake']*t['ai_probability']*t['decimal_odds'] for t in ts)
            assert abs(metric['expected_payout_yen']-e)<1e-7 and abs(metric['expected_net_profit_yen']-(e-st))<1e-7
            if name in ['B_filter_gross','D_filter_net','E_delete_only']:assert all(t['ai_probability']*t['decimal_odds']>=1-1e-10 for t in ts)
            net=name in ['C_net_all','D_filter_net'];objective=.5*(e-st if net else e)/r['expected_payout_scale_all_combinations']+.5*metric['probability_any_hit']
            assert abs(objective-metric['objective_value'])<1e-9
            count+=1;new+=int(not v['reused_hash_verified'])
    assert count==1110 and new==666
    audit={'test_only':True,'race_records':222,'portfolio_records':count,'new_optimized_portfolios':new,
      'prior_current_portfolios_hash_verified':222,'deletion_reference_portfolios':222,
      'all_ticket_cost_threshold_objective_checks_passed':True,'baseline_and_deletion_settlement_reproduced':True,
      'known3horse_unit_case_passed':True,'no_production_or_automations_changed':True}
    (P/'audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    diagnostics={};rng=np.random.default_rng(20261024)
    for year in [2025,2026]:
        by={v:{r['race_code']:r for r in rows if r['year']==year and r['variant']==v} for v in s.VARIANTS};codes=sorted(by['A_current']);idx=rng.integers(0,len(codes),(20000,len(codes)))
        def boot(v):
            rs=by[v];p=np.array([rs[code]['payout_yen'] for code in codes]);st=np.array([rs[code]['stake_yen'] for code in codes]);return 100*p[idx].sum(axis=1)/st[idx].sum(axis=1)
        b=boot('A_current');out={}
        for variant,rs in by.items():
            assert set(rs)==set(codes)
            sorted_rows=sorted(rs.values(),key=lambda r:r['payout_yen'],reverse=True);pay=sum(x['payout_yen'] for x in sorted_rows)
            t=sorted_rows[2:];stake=sum(x['stake_yen'] for x in t);remaining_pay=sum(x['payout_yen'] for x in t)
            out[variant]={'top2_payouts_yen':[x['payout_yen'] for x in sorted_rows[:2]],'top2_race_codes':[x['race_code'] for x in sorted_rows[:2]],
               'top2_share_of_payout':sum(x['payout_yen'] for x in sorted_rows[:2])/pay if pay else None,
               'recovery_after_remove_own_top2_percent':100*remaining_pay/stake if stake else None,
               'own_top2_removal_is_concentration_diagnostic_not_a_common_cohort_comparison':True,
               'paired_descriptive_bootstrap95_ROI_difference_vs_A':np.quantile(boot(variant)-b,[.025,.975]).tolist(),
               'mean_payout_per_hit_race_yen':pay/sum(x['any_hit'] for x in sorted_rows) if pay else None}
        diagnostics[str(year)]=out
    (P/'concentration_diagnostics.json').write_text(json.dumps({'seed':20261024,'bootstrap_samples':20000,'periods_previously_inspected':True,'annual':diagnostics},indent=2)+'\n')
    lines=['# 不利な券の除外と期待利益：補正50%での固定条件比較','',
      '同じ現行モデル・人気補正50%・確定オッズ・全組合せを使い、「推定上不利な券を除くか」と「購入額を差し引くか」の2×2で比較しました。元の買い目からの単純削除は参考として別に残します。','',
      '最大30点、予算上限1万円、各券は単独的中時に1万円以上となる最低必要額、100円単位、余りを残す、という制約は共通です。25点の下限は追加していません。運用設定・予約は変更していません。',
      '', '|方式|2025年 回収率|2025年 的中|2026年 回収率|2026年 的中|','|---|---:|---:|---:|---:|']
    for v in s.VARIANTS:
        a=c['annual']['2025'][v];b=c['annual']['2026'][v];lines.append(f"|{LABELS[v]}|{a['recovery_percent']:.2f}%|{a['hit_races']}/{a['races']}|{b['recovery_percent']:.2f}%|{b['hit_races']}/{b['races']}|")
    lines+=['','推定上不利な券の除外は、期待払戻を使ったままでも両年で大きく改善しました。期待利益への変更だけでは改善が小さく、2026年は悪化しました。両方を適用したDはBと払戻総額・的中数が同じで、配分額が少ない分だけ回収率が上がっています。今回、大きく効いたのは除外条件の方です。',
      'ただしDでは、払戻上位2レースが2025年43.03%、2026年40.85%を占めます。その方式自身の上位2件を除くと回収率は83.08%、70.20%です。少数の高額払戻の影響が大きく、過去の100%超だけで安定性が確認できたとは判断しません。','',
      '単純削除Eから再最適化B・Dへ変えると、2025年は的中数と回収率が増えますが、2026年は的中数が増える一方で回収率は下がっています。再配分すれば必ずよくなるという結果でもありません。','',
      '## 資金・点数と損益','',
      '|年|方式|実配分額|未使用予算|払戻|差引収支|平均点数|平均配分額|','|---|---|---:|---:|---:|---:|---:|---:|']
    for y in ['2025','2026']:
        for v in s.VARIANTS:
            x=c['annual'][y][v];lines.append(f"|{y}|{LABELS[v]}|{x['stake_yen']:,}円|{x['unspent_yen']:,}円|{x['payout_yen']:,}円|{x['profit_yen']:,}円|{x['mean_ticket_count']:.2f}|{x['mean_stake_yen']:.0f}円|")
    lines+=['','回収率は実配分額を分母にしています。予算上限を分母にした指標ではありません。単純削除と新しい最適化では、購入券・配分総額・的中機会が変わります。元の結果が新しい配分でも再現するとは扱いません。',
      '', '## 方式の違い','',
      '- A：現在の期待払戻＋的中機会の評価。以前のハッシュ固定済み原本を再利用し、今回計算した確率・尺度と照合。',
      '- B：全候補から確率×オッズが1以上の券だけを選べるようにして、期待払戻＋的中機会で新たに最適化。',
      '- C：券を事前に制限せず、期待払戻から購入額を引いた期待利益＋的中機会で新たに最適化。的中機会の項があるため、推定上不利な券が残る可能性があります。',
      '- D：推定上不利な券の除外と期待利益への変更を両方適用して新たに最適化。',
      '- E：Aの既存買い目から推定上不利な券を外すだけ。余りを別の券に配分し直していません。',
      '', 'B・Dの閾値は確率×小数オッズ≧1（数値誤差1e-10を許容）に事前固定し、結果で閾値を探していません。モデルの推定であり、真の確率が分かるという意味ではありません。',
      '経済評価と的中機会の重みは50:50のままです。経済評価の尺度は、各レースの全組合せから決まるmax(確率×オッズ)×10000に固定して全方式で共有しています。除外後に尺度を計算し直したり、期待利益に変えた時に尺度を別物へ変えたりしていません。したがって、今回のC・Dは純粋な期待利益最大化ではなく、期待利益と的中機会の混合目的です。',
      '', '## 少数の大きな払戻への依存','',
      '|年|方式|払戻上位2レースの合計が全払戻に占める割合|その方式自身の上位2件を除いた回収率|','|---|---|---:|---:|']
    for y in ['2025','2026']:
        for v in s.VARIANTS:
            d=diagnostics[y][v];lines.append(f"|{y}|{LABELS[v]}|{100*d['top2_share_of_payout']:.2f}%|{d['recovery_after_remove_own_top2_percent']:.2f}%|")
    lines+=['','上位2件の除外は偏りの大きさを見るための診断です。方式ごとに除くレースが異なるため、同じ対象での優劣比較ではありません。採用判断のために都合の悪いレースを除いた数字として使いません。',
      '', '## 計算・検査・限界','',
      'B・C・Dの119＋103レース、666組を実際に新規計算し、全買い目ファイルのハッシュをGitHubへ確定してから公式払戻で答え合わせしました。Aの222組は原本のハッシュを照合し、Eの222組も同じ原本から作成。全1110組の予算・点数・最低必要額・除外条件・期待払戻・期待利益・目的値を検査しました。購入額を一定としない場合に期待払戻と期待利益が異なることは、結果を必要としない3頭の既知例でも検査しています。',
      '2025年は以前と同じ共通117レース（既存欠損等11件＋公式結果未解決2件を除外）、2026年は10月18日までの103レース。新たな実行失敗を隠して対象から除外していません。基礎モデル・補正係数・特徴量は変更していません。結果を配分入力に渡していません。',
      '同じ過去期間を既に何度も調べた後の比較で、独立した未知期間の検証ではありません。確定オッズ・最終出走馬によるテストで、元特徴量全体の取得時点の正当性も完全に証明されていません。最大30秒・誤差1%の同一最適化設定を使い、厳密な最適解でないケースもあります。',
      '', '[年別・前半後半集計](comparison.json)／[レース別](race_results.json)／[集中度・差の幅](concentration_diagnostics.json)／[条件](protocol.json)／[検査](audit.json)／[買い目原本のハッシュ](prediction_manifest.json)','']
    (P/'README.md').write_text('\n'.join(lines))
    archive=R/'JRA_profit_comparison_private_20261024.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(A.rglob('*')):
            if p.is_file():z.write(p,str(p.relative_to(A)))
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None
    (P/'private_archive.json').write_text(json.dumps({'filename':archive.name,'size_bytes':archive.stat().st_size,'sha256':sha(archive),'public_binary':False},indent=2)+'\n')
    print('AUDIT',audit);print('ZIP',archive.stat().st_size)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
if __name__=='__main__':main()
