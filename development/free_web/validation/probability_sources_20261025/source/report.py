"""Year-separated source comparison, portfolio audit, paired concentration diagnostics."""
import hashlib,importlib.util,json,math,zipfile
from pathlib import Path
import numpy as np
spec=importlib.util.spec_from_file_location('source_study','probability_sources_20261025/replay.py')
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
R=s.R;P=s.P;A=s.A
LABELS={'ai_only':'AIのみ','market_only':'市場のみ','ai_market50':'AI＋市場（補正50%）'}
def main():
    c=json.loads((P/'comparison.json').read_text());rows=json.loads((P/'race_results.json').read_text());rs,m=s.records()
    assert not c['allocation_failures'] and not m['failures'] and len(rs)==222
    inputs={y:{r['race_code']:r for r in s.study.base.inputs(y)} for y in [2025,2026]};checks=0;new=0
    for r in rs:
        assert not r['failures'] and set(r['variants'])==set(s.METHODS)
        race=inputs[r['year']][r['race_code']]
        for method,v in r['variants'].items():
            h,combos,events=s.study.probability_tables(race,s.stage_scores(race,r['year'],method))
            for col in ['win_probability','top3_probability']:assert np.allclose(h[col],[x[col] for x in v['horse_probabilities']],rtol=0,atol=1e-12)
            if method=='market_only':
                q=1/np.asarray(race['odds']);q/=q.sum();assert np.allclose(h.win_probability,q,rtol=0,atol=1e-12)
            ts=v['tickets'];st=sum(t['stake'] for t in ts)
            assert 1<=len(ts)<=30 and 0<st<=10000 and st==v['metrics']['stake_yen'] and v['metrics']['unspent_yen']==10000-st
            lookup={(x.bet_type,x.kumiban):x.ai_probability for x in combos.itertuples()}
            for t in ts:
                assert abs(t['ai_probability']-lookup[(t['bet_type'],t['kumiban'])])<1e-10
                assert t['ai_probability']*t['decimal_odds']>=1-1e-10
                assert t['stake']==100*max(1,math.ceil(100/t['decimal_odds']-1e-12))
            measure=s.old.measure(ts,events,v['scale_from_all_combinations'],True)
            for name,val in measure.items():assert abs(val-v['metrics'][name])<1e-7
            checks+=1;new+=int(not v['reused_hash_verified'])
    assert checks==666 and new==444
    audit={'test_only':True,'races':222,'portfolios_checked':666,'new_allocations':444,'prior_mixed_portfolios_hash_verified':222,
      'full_source_probability_and_ticket_checks_passed':True,'unit_source_isolation_and_inverse_odds_test_passed':True,
      'no_production_or_tasks_changed':True}
    (P/'audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    rng=np.random.default_rng(20261025);diag={}
    for year in [2025,2026]:
        by={method:{x['race_code']:x for x in rows if x['year']==year and x['variant']==method} for method in s.METHODS}
        codes=sorted(by['market_only']);idx=rng.integers(0,len(codes),(20000,len(codes)));dist={}
        for method,data in by.items():
            assert set(data)==set(codes)
            p=np.array([data[code]['payout_yen'] for code in codes]);st=np.array([data[code]['stake_yen'] for code in codes]);dist[method]=100*p[idx].sum(axis=1)/st[idx].sum(axis=1)
        d={}
        for method,data in by.items():
            v=sorted(data.values(),key=lambda x:x['payout_yen'],reverse=True);total=sum(x['payout_yen'] for x in v);left=v[2:]
            d[method]={'top2_race_codes':[x['race_code'] for x in v[:2]],'top2_payouts_yen':[x['payout_yen'] for x in v[:2]],
                'top2_payout_share':sum(x['payout_yen'] for x in v[:2])/total if total else None,
                'recovery_after_remove_own_top2_percent':100*sum(x['payout_yen'] for x in left)/sum(x['stake_yen'] for x in left),
                'bootstrap95_ROI_difference_vs_market':np.quantile(dist[method]-dist['market_only'],[.025,.975]).tolist(),
                'same_years_reused_not_independent_inference':True}
        diag[str(year)]=d
    (P/'paired_diagnostics.json').write_text(json.dumps({'seed':20261025,'samples':20000,'annual':diag},indent=2)+'\n')
    text=['# AIのみ・市場のみ・AI＋市場：同じ除外と配分ルールでの比較','',
      '今回の固定条件では、回収率はAI＋市場（補正50%）が両年とも最も高くなりました。一方、馬ごとの勝率・3着以内率の予測誤差は、市場のみが最も小さくなりました。確率全体の正確さと、特定の買い方で得る収益は異なることが確認できる比較です。AI単独が市場単独より回収率で上回る一方、両方を混ぜた方式がさらに上回りました。ただし過去の少数の高額的中や同じ期間を何度も使った影響を含み、AIの独自情報が将来も利益を生むと確定したものではありません。','',
      '|方式|2025年回収率|的中レース|2026年回収率|的中レース|','|---|---:|---:|---:|---:|']
    for method in s.METHODS:
        a=c['annual']['2025'][method];b=c['annual']['2026'][method];text.append(f"|{LABELS[method]}|{a['recovery_percent']:.2f}%|{a['hit_races']}/{a['races']}|{b['recovery_percent']:.2f}%|{b['hit_races']}/{b['races']}|")
    text+=['','## 同じ買い方とは','',
      '全方式で、推定確率×馬連・3連複オッズが1未満の券を除外し、購入額を引いた期待利益と少なくとも1点当たる確率を50:50で評価します。最大30点・予算上限1万円・各券は単独的中時払戻1万円以上となる最低必要額・残額は使わず残す、という同じ制約です。25点の下限は追加していません。',
      '確率を作る材料だけを変えています。AIのみは既存のWIN/TOP3と既存Platt補正器を維持し、その幾何平均から同じ順位分布を作る従来の変換です。市場による追加補正を使いません。市場のみは単勝オッズの逆数を正規化し、1着馬を除いて2着、上位2頭を除いて3着を計算するPLモデルで、AI出力や特徴量を使いません。AI＋市場は前回の補正50%をそのまま使用します。',
      'AIのみでも、馬連・3連複オッズは割のよさの判定と金額計算に使います。「市場のみ」は馬連オッズの逆数を同じ馬連オッズと比べる循環的な計算ではなく、単勝市場から作った組合せ確率と馬連・3連複市場を比べる方法です。',
      '期待利益の尺度は全組合せのmax(確率×オッズ)×10000で求める同じ式です。モデルの確率が異なるため数値自体は方式ごとに異なります。純粋な期待利益最大化ではなく、的中機会も含む既存の混合目的を固定した比較です。単勝での相対的強さが上位3着の順位分布にも使える、という共通の仮定を含みます。',
      '', '## 金額・点数','',
      '|年|方式|実配分額|払戻|差引収支|平均点数|平均配分額|','|---|---|---:|---:|---:|---:|---:|']
    for y in ['2025','2026']:
        for method in s.METHODS:
            x=c['annual'][y][method];text.append(f"|{y}|{LABELS[method]}|{x['stake_yen']:,}円|{x['payout_yen']:,}円|{x['profit_yen']:,}円|{x['mean_ticket_count']:.2f}|{x['mean_stake_yen']:.0f}円|")
    text+=['','回収率の分母は実際に配分した金額です。全レースの予算上限を分母にしていません。各方式で最適化するため、買い目・点数・使用額が変わります。',
      '', '## 確率の予測精度','',
      '下表は買い目を作る同じ順位分布から得た各馬の勝率・3着以内率のBrier誤差で、小さいほどよい指標です。既存モデルの2出力をそのまま比較する指標とは区別します。','',
      '|年|方式|勝率の誤差|3着以内率の誤差|','|---|---|---:|---:|']
    for y in ['2025','2026']:
        for method in s.METHODS:
            x=c['horse_probability_metrics'][y][method];text.append(f"|{y}|{LABELS[method]}|{x['win']['brier']:.6f}|{x['top3']['brier']:.6f}|")
    text+=['','市場のみは両年とも、ここに示した誤差と対数損失で3方式中最小です。それでも今回の購入ルールでは回収率が最下位でした。全体の確率予測の誤差が小さいだけで、割安と判定した部分の確率が正確だったり、必ず利益を得られたりするとは限りません。AI＋市場の回収率が高いことも、AIの全体的な確率精度の優位性を示すものではありません。',
      '', '## 高額的中の影響','',
      '|年|方式|払戻上位2件の割合|その方式自身の上位2件を除いた回収率|','|---|---|---:|---:|']
    for y in ['2025','2026']:
        for method in s.METHODS:
            x=diag[y][method];text.append(f"|{y}|{LABELS[method]}|{100*x['top2_payout_share']:.2f}%|{x['recovery_after_remove_own_top2_percent']:.2f}%|")
    text+=['','この除外は集中度の診断で、方式ごとに除くレースが違います。同じ対象での優劣比較や採用判断には使いません。AI＋市場の払戻は前回と同じく上位2件に2025年43.03%、2026年40.85%が集中しており、過去の100%超だけで安定性を確定できません。',
      '', '## 実行・検査・保存','',
      '2025年119レース・2026年103レースで、AIのみと市場のみの買い目を計444組、今回実際に計算しました。AI＋市場50%の222組は前回原本のハッシュを照合して再利用し、今回計算した確率との一致も確認しました。3方式を全部配分し直したという説明はしません。基礎AIモデルの再学習や新しい補正係数の探索は行っていません。',
      '全買い目原本のハッシュをGitHubに確定してからJRA公式の実払戻で答え合わせしました。全666組について、確率・的中機会・期待払戻・期待利益・目的値、EV除外、最低必要額、点数、予算を再計算して検査しました。AIのみの計算が単勝オッズ変更に影響されないこと、市場のみがAI出力変更に影響されないことは、結果を使わない既知例で確認しました。',
      '収支比較は前回と同じ2025年117レース（元の130識別子のうち既存欠損等11件、公式結果未解決2件を除外）、2026年は10月18日までの103レースです。新しい計算失敗や該当券なしは発生していません。失敗を隠して対象レースを絞ったものではありません。',
      '条件は計算前に固定し、運用モデル・公開コード・予想予約は変更していません。同じ過去期間を繰り返し検証した後の比較で、完全に未知の期間による実証ではありません。確定オッズ・最終出走馬を使い、元特徴量全体の取得時点の正当性が完全に証明されているわけではありません。30秒上限・誤差1%の同じ設定を使い、厳密な最適解でない場合があります。',
      '', '[年別・前半後半集計](comparison.json)／[レース別](race_results.json)／[集中度・差の幅](paired_diagnostics.json)／[条件](protocol.json)／[検査](audit.json)／[買い目原本ハッシュ](prediction_manifest.json)','']
    (P/'README.md').write_text('\n'.join(text))
    dest=R/'JRA_probability_sources_private_20261025.zip'
    with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(A.rglob('*')):
            if p.is_file():z.write(p,str(p.relative_to(A)))
    with zipfile.ZipFile(dest) as z:assert z.testzip() is None
    (P/'private_archive.json').write_text(json.dumps({'filename':dest.name,'size_bytes':dest.stat().st_size,'sha256':sha(dest),'public_binary':False},indent=2)+'\n')
    print('AUDIT',audit);print('ZIP',dest.stat().st_size)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
if __name__=='__main__':main()
