"""Audit fixed-grid sweep and write a plain-Japanese report, no production edits."""
import hashlib,json,math,sys,zipfile,importlib.util
from pathlib import Path
import numpy as np
spec=importlib.util.spec_from_file_location('strength_study','correction_strength_20261024/replay.py')
study=importlib.util.module_from_spec(spec);spec.loader.exec_module(study)
R=study.R;P=study.P;A=study.A
def main():
    c=json.loads((P/'comparison.json').read_text());sel=json.loads((P/'selection2025.json').read_text());rows=json.loads((P/'race_results.json').read_text())
    records,manifest=study.records();portfolios=0;new=0;reused=0
    for rec in records:
        race=next(x for x in study.base.inputs(rec['year']) if x['race_code']==rec['race_code'])
        before=study.scores(race,'shared_ai_market',[1,0]);after=study.scores(race,'shared_ai_market',study.base.params(rec['year']))
        for k,v in rec['variants'].items():
            s=v['strength'];assert k==study.key(s);assert np.allclose(v['parameters'],study.coefficients(rec['year'],s),rtol=0,atol=1e-14)
            score=study.scores(race,'shared_ai_market',v['parameters'])
            assert np.allclose(score,(1-s)*before+s*after,rtol=0,atol=1e-13)
            h,_,_=study.probability_tables(race,score)
            for col in ['win_probability','top3_probability']:
                assert np.allclose(h[col].to_numpy(),[x[col] for x in v['horse_probabilities']],rtol=0,atol=1e-12)
            ts=v['tickets'];assert 1<=len(ts)<=30
            total=sum(int(x['stake']) for x in ts);assert 0<total<=10000 and total==v['stake_yen'] and v['unspent_yen']==10000-total
            for t in ts:assert t['stake']==100*max(1,math.ceil(100/t['decimal_odds']-1e-12))
            portfolios+=1;reused+=int(v['reused_hash_verified']);new+=int(not v['reused_hash_verified'])
    assert new==666 and reused==444 and portfolios==1110 and not manifest['failures']
    audit={'test_only':True,'races':len(records),'portfolios':portfolios,'newly_allocated':new,'reused_hash_verified':reused,
       'all_ticket_and_budget_invariants_passed':True,'interpolated_scores_and_horse_probabilities_verified':True,
       'endpoint_annual_results_reproduce_previous_comparison':True,'no_production_or_tasks_changed':True}
    (P/'audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    rng=np.random.default_rng(20261024);diag={}
    for year in [2025,2026]:
        by={k:{x['race_code']:x for x in rows if x['year']==year and x['method']==k} for k in ['000','025','050','075','100']}
        codes=sorted(by['100']);idx=rng.integers(0,len(codes),(20000,len(codes)));dist={}
        for k,rs in by.items():
            assert set(rs)==set(codes)
            p=np.array([rs[code]['payout_yen'] for code in codes]);s=np.array([rs[code]['stake_yen'] for code in codes]);dist[k]=100*p[idx].sum(axis=1)/s[idx].sum(axis=1)
        diag[str(year)]={k:{'roi_difference_vs_current_percentage_points':c['annual'][str(year)][k]['recovery_percent']-c['annual'][str(year)]['100']['recovery_percent'],
          'descriptive_paired_bootstrap95_interval':np.quantile(dist[k]-dist['100'],[.025,.975]).tolist()} for k in ['000','025','050','075']}
    (P/'paired_diagnostics.json').write_text(json.dumps({'seed':20261024,'samples':20000,'not_independent_inference':True,'years':diag},indent=2)+'\n')
    chosen=sel['selected_key'];lines=['# 人気補正の強さ：事前固定した5通りの比較','',
      '現行モデル、各年の入力・オッズ、馬連と3連複、最大30点、上限1万円、各券は単独的中時1万円以上となる最低必要額、余りを残すルールを固定しました。運用設定・モデル・予約は変更していません。','',
      '|補正の強さ|2025年 回収率|2025年 的中|2026年 回収率|2026年 的中|','|---|---:|---:|---:|---:|']
    for k,label in [('000','なし'),('025','現行の25%'),('050','現行の50%'),('075','現行の75%'),('100','現行100%')]:
        a=c['annual']['2025'][k];b=c['annual']['2026'][k];lines.append(f"|{label}|{a['recovery_percent']:.2f}%|{a['hit_races']}/{a['races']}|{b['recovery_percent']:.2f}%|{b['hit_races']}/{b['races']}|")
    a=c['annual']['2025'][chosen];b=c['annual']['2026'][chosen];cur=c['annual']['2026']['100']
    lines+=['',f"2025年の実配分額を分母とした回収率で選ぶ、同率なら強い補正を残す、という基準を計算前に固定しました。この基準で選ばれたのは現行の{int(chosen)}%です。2025年は{a['recovery_percent']:.2f}%、次に照合した2026年は{b['recovery_percent']:.2f}%（現行100%は{cur['recovery_percent']:.2f}%）でした。2025年の選択記録は2026年の今回の採点処理より先にGitHubへ固定しています。",'',
      '2026年は既に結果を見ており、弱める案を出したきっかけも以前の検証です。したがって、2026年を完全に未知の独立した検証期間と説明しません。2025年も研究全体で既に使っている年です。数字を見てから候補や採用基準を増やしていません。','',
      '2025年で事前の選択基準に従って選ばれた現行100%は、2026年では最良ではありませんでした。2026年だけを見て50%を最適と断定することもできません。一方で、補正を弱めた25～75%が2026年の現行100%をすべて上回ったため、弱める案は今後の比較候補として残ります。2026年の回収率は50%が最高ですが、差引損失額は25%が最小であり、指標の違いも区別します。今回、採用や運用切替は行っていません。','','## 金額も含めた比較','',
      '|年|強さ|実配分額|未使用額|払戻|差引収支|平均点数|','|---|---|---:|---:|---:|---:|---:|']
    for y in ['2025','2026']:
        for k in ['000','025','050','075','100']:
            x=c['annual'][y][k];lines.append(f"|{y}|{int(k)}%|{x['stake_yen']:,}円|{x['unspent_yen']:,}円|{x['payout_yen']:,}円|{x['profit_yen']:,}円|{x['ticket_count_mean']:.2f}|")
    lines+=['','## 補正を弱める意味','',
      '補正前のAI評価と、既存の補正後の評価を、強さの割合で対数評価の段階で混ぜます。たとえば50%は、現在の補正による変更の半分です。確率を単純に足して2で割る方法ではありません。計算上はAI係数を1−s＋s×現行AI係数、市場係数をs×現行市場係数とします。元から付属するWIN/TOP3のPlatt補正器は両条件で同じものを維持しています。','',
      '係数自体を今回学習し直していません。2025年には2024年で固定した係数、2026年には2025年で固定した係数を使用しています。強さの選択に2025年の成績は使いますが、2025年の各レースの買い目作成や基礎モデル・係数の学習にそのレースの結果を渡していません。',
      '確率の精度と人気別の偏りも各強さで保存しました。2025年分はselection2025.json、2026年分はcomparison.jsonを参照。市場人気順は確定単勝オッズ順、同率なら馬番順です。回収率・的中率と確率の正確さは別の指標として扱います。',
      '', '## 検査と比較の範囲','',
      '2025年119レース、2026年103レースについて、25%・50%・75%の買い目を今回新規に666組計算しました。0%と100%は前回計算済みの444組をハッシュ照合して利用し、今回計算した確率との一致も確認しました。1110組すべての点数・金額・残額・最低必要額を検査し、補正の混合式と馬ごとの確率も再計算して照合しました。全件の買い目ハッシュをGitHubに確定してから今回の答え合わせをしています。',
      '2025年は元の130識別子から既存の欠損等11件を除いた119件で買い目を作り、公式結果を一意に対応できなかった2件を全方式から同じように除いて共通117レースで比較しています。2026年は10月18日までの103レースです。全重賞の完全網羅ではありません。',
      '確定オッズと最終出走馬による過去テストです。基礎データ全体の予測時点の正当性は完全には証明していません。配分は同じ30秒上限・誤差1%設定で、時間切れの実行可能解を含みます。期待払戻の尺度を決める式は全方式同じですが、入力確率が変わるので尺度の数値は変化します。',
      '', '[集計](comparison.json)／[2025年での選択](selection2025.json)／[レース別](race_results.json)／[差の幅](paired_diagnostics.json)／[条件](protocol.json)／[検査](audit.json)','']
    (P/'README.md').write_text('\n'.join(lines))
    dest=R/'JRA_correction_strength_private_20261024.zip'
    with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(A.rglob('*')):
            if p.is_file():z.write(p,str(p.relative_to(A)))
    with zipfile.ZipFile(dest) as z:assert z.testzip() is None
    (P/'private_archive.json').write_text(json.dumps({'filename':dest.name,'size_bytes':dest.stat().st_size,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'public_binary':False},indent=2)+'\n')
    print('AUDIT',audit,flush=True);print('SELECTED',chosen,'2026',b['recovery_percent'],'current',cur['recovery_percent'],flush=True);print('ZIP',dest.stat().st_size,flush=True)
if __name__=='__main__':main()
