"""Exploratory popularity boost, fixed 1.2 multiplier, no 2026 tuning/adoption."""
import os
os.environ.setdefault('OMP_NUM_THREADS','1');os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import concurrent.futures,datetime as dt,hashlib,json,math,sys,time
from pathlib import Path
import numpy as np,pandas as pd
sys.path.insert(0,'decomposition_20261021')
from rankwise import scores,probability_tables,observed_losses
from allocation_scenarios import allocate_balanced
from portfolio import aggregate
ROOT=Path('popularity_boost_20261022');PRIVATE=ROOT/'private_assets';PUBLIC=ROOT/'public'

def boosted_stage(race,parameters,method):
    stage=scores(race,'shared_ai_market',parameters)
    popularity=np.asarray(race['popularity'],int)
    if method=='favorite_only':mask=popularity==1
    elif method=='top3_favorites':mask=popularity<=3
    elif method=='no_extra_boost':mask=np.zeros(len(popularity),bool)
    else:raise ValueError('Unknown method')
    # Multiply shared, market-corrected strength, then derive a coherent joint
    # distribution; do not multiply final probabilities without renormalizing.
    return stage+np.log(np.where(mask,1.2,1.))[None,:]

def one(task):
    race,parameters,method,official=task;dest=PRIVATE/method;dest.mkdir(parents=True,exist_ok=True)
    path=dest/(race['race_code']+'.json')
    if path.exists():return json.loads(path.read_text())
    stage=boosted_stage(race,parameters,method);horses,combo,scenario=probability_tables(race,stage)
    assert abs(horses.win_probability.sum()-1)<1e-9 and abs(horses.top3_probability.sum()-3)<1e-9
    source=json.loads((Path('bias_20261020/public_cache/odds')/(race['race_code']+'.json')).read_text())['snapshots']
    odds=pd.DataFrame([r for s in source.values() for r in s['rows']])
    merged=combo.merge(odds,on=['race_code','bet_type','kumiban'],how='outer',validate='one_to_one',indicator=True)
    assert merged._merge.eq('both').all();merged=merged.drop(columns='_merge')
    start=time.monotonic();tickets,audit=allocate_balanced(merged,horses,outcome_scenarios=scenario)
    rows=[]
    for ticket in tickets.to_dict('records'):
        stake=int(ticket['stake']);price=float(ticket['decimal_odds'])
        assert stake==100*max(1,math.ceil(10000/(100*price)-1e-12))
        payout=int(official['payouts_per_100_yen'][ticket['bet_type']].get(ticket['kumiban'],0))*stake//100
        rows.append(dict(ticket,stake=stake,payout_yen=payout))
    assert sum(r['stake'] for r in rows)==10000
    favorite=np.asarray(race['popularity'])==1
    result={'race_code':race['race_code'],'date':race['date'],'race_name':official['name'],'method':method,
        'test_only':True,'is_live_prediction':False,'final_odds_used':True,'stake_yen':10000,
        'ticket_count':len(rows),'payout_yen':sum(r['payout_yen'] for r in rows),'any_hit':any(r['payout_yen'] for r in rows),
        'predicted_hit_probability':audit['probability_any_win'],
        'stake_at_100x_or_more':sum(r['stake'] for r in rows if r['decimal_odds']>=100),
        'seconds':time.monotonic()-start,'allocation_audit':audit,'tickets':rows,
        'favorite_WIN_prediction':float(horses.win_probability.to_numpy()[favorite][0]),
        'favorite_WIN_observed':int(np.asarray(race['target_win'])[favorite][0]),
        'ordered_nll':sum(observed_losses(stage,race['order'])) if len(race['order'])==3 else None}
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('CALCULATED',method,race['race_code'],len(rows),result['payout_yen'],flush=True)
    return result

def main():
    PUBLIC.mkdir(parents=True,exist_ok=True);PRIVATE.mkdir(exist_ok=True)
    assert (PUBLIC/'protocol_commit.json').exists(),'Record protocol before calculation'
    protocol=json.loads((PUBLIC/'protocol.json').read_text())
    source=Path('base_review_20261021/private_assets/races_2026.json')
    assert hashlib.sha256(source.read_bytes()).hexdigest()==protocol['input_sha256']
    races=json.loads(source.read_text())['candidate'];assert len(races)==103
    selection=json.loads(Path('base_review_20261021/public/selection.json').read_text())
    parameters=selection['final_2025_fits'][selection['selected_family']]['parameters']
    official={r['race_code']:r for r in json.loads(Path('bias_20261020/official_results.json').read_text())['races']}
    prior=Path('base_review_20261021/private_assets/portfolios/shared_ai_market')
    baseline=[]
    for race in races:
        row=json.loads((prior/(race['race_code']+'.json')).read_text());row['method']='no_extra_boost'
        stage=boosted_stage(race,parameters,'no_extra_boost');horses,_,_=probability_tables(race,stage)
        favorite=np.asarray(race['popularity'])==1
        row['favorite_WIN_prediction']=float(horses.win_probability.to_numpy()[favorite][0]);row['favorite_WIN_observed']=int(np.asarray(race['target_win'])[favorite][0])
        row['ordered_nll']=sum(observed_losses(stage,race['order'])) if len(race['order'])==3 else None
        baseline.append(row)
    old=aggregate(baseline);assert old['payout_yen']==909270 and old['hit_races']==66
    rows=list(baseline);errors=[]
    tasks=[(r,parameters,m,official[r['race_code']]) for m in ['favorite_only','top3_favorites'] for r in races]
    with concurrent.futures.ProcessPoolExecutor(max_workers=2) as pool:
        future={pool.submit(one,t):(t[0]['race_code'],t[2]) for t in tasks}
        for f in concurrent.futures.as_completed(future):
            try:rows.append(f.result())
            except Exception as e:errors.append({'case':future[f],'error':str(e)})
    if errors:
        (PUBLIC/'errors.json').write_text(json.dumps(errors,indent=2)+'\n');raise RuntimeError(str(errors))
    assert len(rows)==309
    by={m:sorted([r for r in rows if r['method']==m],key=lambda r:r['race_code']) for m in ['no_extra_boost','favorite_only','top3_favorites']}
    summary={m:{**aggregate(v),'mean_favorite_WIN_prediction':float(np.mean([r['favorite_WIN_prediction'] for r in v])),
        'actual_favorite_WIN_rate':float(np.mean([r['favorite_WIN_observed'] for r in v])),
        'mean_ordered_nll':float(np.mean([r['ordered_nll'] for r in v if r['ordered_nll'] is not None]))} for m,v in by.items()}
    paired={};rng=np.random.default_rng(20261022)
    for method in ['favorite_only','top3_favorites']:
        differences=np.array([a['payout_yen']-b['payout_yen'] for a,b in zip(by[method],by['no_extra_boost'])])
        boot=differences[rng.integers(0,103,size=(10000,103))].mean(axis=1)
        paired[method]={'total_payout_difference_yen':int(differences.sum()),'mean_difference_yen_per_race':float(differences.mean()),
            'bootstrap95CI_yen_per_race':np.quantile(boot,[.025,.975]).tolist()}
    report={'record_type':'exploratory_popularity_strength_boost','created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'test_only':True,'baseline':'recent52 candidate, no additional boost;88.27864077669904% from prior actual replay',
        'baseline_reused_not_recomputed':True,'new_portfolio_calculations':206,'aggregate':summary,
        'halves':{half:{m:aggregate([r for r in v if (r['date']<'2026-07-01')==early]) for m,v in by.items()} for half,early in [('H1',True),('H2',False)]},
        'archive96_only':{m:aggregate([r for r in v if next(x for x in races if x['race_code']==r['race_code'])['input_source']=='archive']) for m,v in by.items()},
        'paired_vs_no_extra_boost':paired,'exploratory_2026_previously_inspected':True,
        '2025_selection_performed':False,'model_retrained':False,'production_or_automations_changed':False,
        'source_point_in_time_certified':False,'final_odds_and_final_starters':True,
        'one_fixed_multiplier_only':1.2,'independent_future_validation_needed_for_adoption':True,
        'original_model_or_history_published':False}
    (PUBLIC/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    compact=[{k:r[k] for k in ['race_code','date','race_name','method','ticket_count','stake_yen','payout_yen','any_hit','predicted_hit_probability','favorite_WIN_prediction','favorite_WIN_observed','ordered_nll']} for r in rows]
    (PUBLIC/'race_comparison.json').write_text(json.dumps(compact,ensure_ascii=False,indent=2)+'\n')
    labels={'no_extra_boost':'追加なし（既存結果）','favorite_only':'1番人気だけ1.2倍','top3_favorites':'3番人気以内を1.2倍'}
    table='\n'.join(f"| {labels[m]} | {v['recovery_percent']:.2f}% | {v['hit_races']}/103 | {v['payout_yen']:,}円 | {100*v['mean_favorite_WIN_prediction']:.2f}% |" for m,v in summary.items())
    readme=f'''# 人気馬への下駄：3通り比較（2026年10月22日）

2026年1月4日～10月18日の103レースを比較しました。基準は直前に作った研究用recent52候補（回収率88.28%）です。従来方式79.21%とは区別します。

| 条件 | 回収率 | 的中レース | 払戻総額 | 1番人気の平均勝つ予測 |
|---|---:|---:|---:|---:|
{table}

仮の購入総額は各103万円。既存の補正なし103件を再利用し、新しく計算したのは2条件×103レースの206件です。学習モデル・入力・補正係数・購入ルールは固定しました。上乗せ対象の馬の最終評価を1.2倍にし、全体の確率を計算し直して馬連・3連複を作成しました。勝つ確率そのものを単純に1.2倍しているわけではありません。

人気順はJRA公式の確定人気を使用。購入は1レース1万円、100円単位、各買い目は単独払戻が1万円以上になる最小金額、100倍以上は100円です。balanced_A_v3の目的・制約・時間制限は変えていません。時間制限付き計算なので、厳密な唯一の最適解を保証しません。

これは確定オッズ・最終出走馬による過去テストです。2026年は既に何度も確認した期間で、今回2025年で条件を選ぶ検証は行っていません。対象2条件と倍率1.2は計算前に固定し、他の倍率は試していません。結果にかかわらず本番には切り替えません。保存特徴量96レースと公開情報からの再作成7レースを含み、元の入力すべての取得時点を完全に証明したものではありません。

1番人気の実際の勝率は33.98%。人気馬の予測の近さと、買い目の回収率は別々に確認します。前半・後半・保存済み96レースのみの比較、払戻差の不確かさは[comparison.json](comparison.json)に、全レースの一覧は[race_comparison.json](race_comparison.json)に保存しています。X送信・購入・運用モデルや予約の変更は行っていません。
'''
    (PUBLIC/'README.md').write_text(readme)
    print('RESULT',json.dumps(summary),flush=True)

if __name__=='__main__':main()
