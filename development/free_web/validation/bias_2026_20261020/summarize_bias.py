from runtime_paths import ROOT, MODULES, MODEL, HISTORY, HISTORY_DIR, BUNDLE, ASSETS
"""Summarize frozen-rule 2026 retrospective bias; no model/production changes."""
from pathlib import Path
import datetime as dt,hashlib,html,json,math,sys,zipfile
import numpy as np,pandas as pd
ROOT=ROOT;OUT=ROOT/'deliverables';OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(MODULES))
from corrected_v2_core import generate_combinations

def clean(value):
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(x) for x in value]
    if isinstance(value,np.generic):return clean(value.item())
    if isinstance(value,float) and not math.isfinite(value):return None
    return value

def wilson(w,n):
    z=1.95996398454;p=w/n;denom=1+z*z/n
    center=(p+z*z/(2*n))/denom
    error=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/denom
    return [center-error,center+error]

def horse_groups(frame):
    x=frame.copy()
    x['group']=pd.cut(x.popularity,[0,1,3,6,10,18],labels=['1番人気','2～3番人気','4～6番人気','7～10番人気','11番人気以下'])
    rows=[]
    for name,g in x.groupby('group',observed=True):
        rows.append({'popularity_group':str(name),'horses':len(g),
            'model_win_rate':float(g.win_probability.mean()),'actual_win_rate':float(g.target_win.mean()),
            'model_expected_wins':float(g.win_probability.sum()),'actual_wins':int(g.target_win.sum()),
            'model_top3_rate':float(g.top3_probability.mean()),'actual_top3_rate':float(g.target_top3.mean()),
            'model_expected_top3':float(g.top3_probability.sum()),'actual_top3':int(g.target_top3.sum())})
    return rows

def bins(frame,prob,target,edges):
    x=frame.copy();x['band']=pd.cut(x[prob],edges,include_lowest=True)
    return [{'predicted_probability_band':str(name),'horses':len(g),
        'mean_model_probability':float(g[prob].mean()),'observed_rate':float(g[target].mean()),
        'expected_events':float(g[prob].sum()),'actual_events':int(g[target].sum())}
        for name,g in x.groupby('band',observed=True)]

def price_band(x):
    for upper,label in [(10,'10倍未満'),(30,'10～30倍未満'),(100,'30～100倍未満'),
        (300,'100～300倍未満'),(1000,'300～1,000倍未満'),(10000,'1,000～10,000倍未満')]:
        if x<upper:return label
    return '10,000倍以上'

def main():
    horses=pd.DataFrame(json.loads((ROOT/'horse_predictions_all.json').read_text()))
    official={r['race_code']:r for r in json.loads((ROOT/'official_results.json').read_text())['races']}
    portfolios=[json.loads(p.read_text()) for p in sorted((ROOT/'portfolio_results').glob('*.json'))]
    assert len(portfolios)==len(official)==horses.race_code.nunique()==103
    assert horses[['race_code','umaban']].duplicated().sum()==0
    assert all(r['stake_yen']==10000 and r['audit']['additional_stake_above_minimum_yen']==0 for r in portfolios)
    reconstructed={r['race_code'] for r in portfolios if
        'retrospective_public_entry_profile_history_reconstruction' in r['input_sources']}
    tickets=pd.DataFrame([dict(t,race_code=r['race_code']) for r in portfolios for t in r['tickets']])
    assert tickets.stake.sum()==1030000 and (tickets.stake%100==0).all()
    assert (tickets.stake*tickets.decimal_odds>=10000-1e-8).all()
    for t in tickets.itertuples():
        assert int(t.stake)==100*max(1,math.ceil(10000/(100*t.decimal_odds)-1e-12))
        assert t.payout_yen==official[t.race_code]['payouts_per_100_yen'][t.bet_type].get(t.kumiban,0)*(t.stake//100)
    tickets['odds_band']=tickets.decimal_odds.map(price_band)
    tickets['model_expected_payout_yen']=tickets.ai_probability*tickets.decimal_odds*tickets.stake
    price_rows=[]
    for label,g in tickets.groupby('odds_band',sort=False):
        price_rows.append({'odds_band':label,'tickets':len(g),'stake_yen':int(g.stake.sum()),
            'stake_share':float(g.stake.sum()/tickets.stake.sum()),
            'actual_winning_tickets':int((g.payout_yen>0).sum()),'payout_yen':int(g.payout_yen.sum()),
            'recovery_percent':float(100*g.payout_yen.sum()/g.stake.sum()),
            'model_expected_payout_yen':float(g.model_expected_payout_yen.sum())})
    combo_bands=[];deadheat=[]
    for code,result in official.items():
        ranks=[r['finish_status'] for r in result['finish_rows'] if r['finish_status'].isdigit() and int(r['finish_status'])<=3]
        if len(ranks)!=len(set(ranks)):deadheat.append(code);continue
        h=horses[horses.race_code==code].rename(columns={'horse_id':'ketto_toroku_bango'})
        odds=json.loads((ROOT/'public_cache/odds'/(code+'.json')).read_text())['snapshots']
        rows=[r for s in odds.values() for r in s['rows']]
        combo=generate_combinations(h).merge(pd.DataFrame(rows),on=['race_code','bet_type','kumiban'],validate='one_to_one')
        combo['band']=combo.decimal_odds.map(price_band)
        combo['inverse_odds']=1/combo.decimal_odds
        combo['normalized_market_probability']=combo.inverse_odds/combo.groupby('bet_type').inverse_odds.transform('sum')
        combo['actual_event']=[int(k in result['payouts_per_100_yen'][b]) for b,k in zip(combo.bet_type,combo.kumiban)]
        for (kind,band),g in combo.groupby(['bet_type','band'],sort=False):
            combo_bands.append({'race_code':code,'bet_type':kind,'odds_band':band,
                'combinations':len(g),'model_expected_wins':float(g.ai_probability.sum()),
                'normalized_market_expected_wins':float(g.normalized_market_probability.sum()),
                'actual_wins':int(g.actual_event.sum())})
    combo_df=pd.DataFrame(combo_bands)
    combo_summary=combo_df.groupby(['bet_type','odds_band'],sort=False).sum(numeric_only=True).reset_index().to_dict('records')
    hits=sum(r['any_hit'] for r in portfolios);stake=sum(r['stake_yen'] for r in portfolios);payout=sum(r['payout_yen'] for r in portfolios)
    def cohort_summary(codes):
        p=[r for r in portfolios if r['race_code'] in codes]
        h=horses[horses.race_code.isin(codes)]
        return {'races':len(p),'horse_popularity_bias':horse_groups(h),
            'actual_hit_races':sum(r['any_hit'] for r in p),
            'model_expected_hit_races':sum(r['predicted_hit_probability'] for r in p),
            'payout_yen':sum(r['payout_yen'] for r in p),
            'recovery_percent':100*sum(r['payout_yen'] for r in p)/(10000*len(p))}
    manifest=json.loads((MODEL/'manifest.json').read_text())
    summary={'record_type':'2026_retrospective_prediction_and_selection_bias_audit','created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'period':['2026-01-04','2026-10-18'],'official_flat_graded_races':103,'completed_races':len(portfolios),
        'horses':len(horses),'model_package':manifest['package'],'training_end':manifest['training_end'],
        'calibration_year':manifest['calibration_year'],'training_or_calibration_used_2026':False,
        'feature_count':52,'allocation_rule':'balanced_A_v3','production_model_or_rule_changed':False,
        'is_live_pre_race_performance':False,'final_odds_used':True,
        'horse_win_expected_events':float(horses.win_probability.sum()),'horse_win_actual_events':int(horses.target_win.sum()),
        'horse_top3_expected_events':float(horses.top3_probability.sum()),'horse_top3_actual_events':int(horses.target_top3.sum()),
        'horse_popularity_bias':horse_groups(horses),
        'win_probability_bins':bins(horses,'win_probability','target_win',[0,.01,.03,.05,.1,.2,.4,.6,1]),
        'top3_probability_bins':bins(horses,'top3_probability','target_top3',[0,.05,.1,.2,.4,.6,.8,1]),
        'portfolio':{'races':len(portfolios),'tickets':len(tickets),'investment_yen':stake,'payout_yen':payout,
            'profit_yen':payout-stake,'recovery_percent':100*payout/stake,
            'actual_hit_races':hits,'actual_hit_rate':hits/len(portfolios),'actual_hit_rate_wilson_95':wilson(hits,len(portfolios)),
            'model_expected_hit_races':sum(r['predicted_hit_probability'] for r in portfolios),
            'mean_model_hit_rate':sum(r['predicted_hit_probability'] for r in portfolios)/len(portfolios),
            'model_expected_payout_yen':sum(r['predicted_expected_payout_yen'] for r in portfolios),
            'at_or_above_100x_ticket_share':float((tickets.decimal_odds>=100).mean()),
            'at_or_above_100x_stake_share':float(tickets.loc[tickets.decimal_odds>=100,'stake'].sum()/stake),
            'at_or_above_10000x_stake_yen':int(tickets.loc[tickets.decimal_odds>=10000,'stake'].sum()),
            'at_or_above_10000x_payout_yen':int(tickets.loc[tickets.decimal_odds>=10000,'payout_yen'].sum())},
        'ticket_odds_bands':price_rows,'combination_probability_calibration_by_odds':combo_summary,
        'sensitivity_excluding_3_public_reconstructions':cohort_summary(set(official)-reconstructed),
        'sensitivity_archive_96_only':cohort_summary(set(horses.loc[horses.source.isin(['race_features.parquet','jra_features_pilot_2025_2026.parquet']),'race_code'])),
        'reconstructed_races':sorted(reconstructed),'deadheat_excluded_from_combination_calibration':deadheat,
        'actual_payout_always_from_official':True,
        'final_odds_and_official_payout_differences':[{'race_code':r['race_code'],'differences':r['official_final_odds_payout_mismatches']}
            for r in portfolios if r['official_final_odds_payout_mismatches']],
        'limits':['Final market popularity and final odds are retrospective diagnostic groups, not the odds available at the original publication time.',
            'Current allocation was designed after some tested races; this is not a strictly preregistered strategy backtest or live performance.',
            'The original full exported features have not been certified point-in-time; current outcome labels were excluded from inference.',
            '96 races were re-inferred from stored complete features; Saudi/Ireland/Fuji use previously verified same-model probability checkpoints; Swan was re-inferred from private archived public snapshots; 3 races were publicly reconstructed.',
            'One Hakodate previous straight-course running style was unresolved and kept missing, not guessed. Sensitivity excludes all 3 reconstructions.',
            'The original October 18 Shuka cap30 forecast and recovered 112% result are preserved separately; the A_v3 replay is not a replacement.',
            'Yasuda Kinen had a second-place dead heat. Official payout, not odds times stake, determines settlement; one selected winner returned less than 10000 yen.',
            'Extreme payouts are rare; a 103-race sample alone does not establish each tail-price category true expectation.']}
    summary=clean(summary)
    (OUT/'bias_2026_summary_20261020.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    race_rows=[{k:r[k] for k in ['race_code','race_name','date','grade','runners','all_combinations','ticket_count',
        'stake_yen','payout_yen','any_hit','predicted_hit_probability','predicted_expected_payout_yen','input_sources','result_source_url']}
        for r in portfolios]
    (OUT/'race_results_103.json').write_text(json.dumps(race_rows,ensure_ascii=False,indent=2)+'\n')
    (OUT/'horse_probability_results.json').write_text(json.dumps(clean(horses.to_dict('records')),ensure_ascii=False,indent=2)+'\n')
    def table(headers,rows):
        return '<table><thead><tr>'+''.join('<th>'+html.escape(str(v))+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table>'
    pop_table=table(['最終人気','出走頭数','AI平均勝率','実際の勝率','AI平均TOP3率','実際のTOP3率'],[
        [r['popularity_group'],r['horses'],f"{r['model_win_rate']:.1%}",f"{r['actual_win_rate']:.1%}",f"{r['model_top3_rate']:.1%}",f"{r['actual_top3_rate']:.1%}"] for r in summary['horse_popularity_bias']])
    bands_table=table(['取得オッズ帯','買い目数','仮想投入額','投入割合','公式払戻','回収率'],[
        [r['odds_band'],r['tickets'],f"{r['stake_yen']:,}円",f"{r['stake_share']:.1%}",f"{r['payout_yen']:,}円",f"{r['recovery_percent']:.1f}%"] for r in price_rows])
    race_table=table(['日付','レース','点数','仮想投入','公式払戻','AI的中率','的中'],[
        [r['date'],r['race_name'],r['ticket_count'],'10,000円',f"{r['payout_yen']:,}円",f"{r['predicted_hit_probability']:.1%}",'○' if r['any_hit'] else '－'] for r in portfolios])
    report=f'''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>2026年・予想の偏り検証</title><style>body{{font-family:system-ui,sans-serif;line-height:1.8;max-width:1100px;margin:32px auto;padding:0 20px;color:#142832;background:#f8fafb}}h1,h2{{line-height:1.4}}table{{border-collapse:collapse;background:white;margin:20px 0;width:100%;font-size:14px}}th,td{{padding:10px;border-bottom:1px solid #d5e0e5;text-align:right}}th:first-child,td:first-child{{text-align:left}}th{{background:#143b49;color:white}}.note{{border-left:4px solid #b06c23;background:#fff8eb;padding:16px}}.scroll{{overflow:auto}}.key{{font-size:22px;color:#87351c;font-weight:700}}a{{color:#135e84}}</style><h1>オッズの歪みラボ<br>2026年の予想・購入先の偏り検証</h1><p>対象：2026年1月4日～10月18日、JRA平地重賞103レース・1,547頭。保存済み52項目WIN/TOP3モデルと現行balanced_A_v3を固定して検証。</p><p class="key">人気馬を低く、人気薄を高く評価する偏りを確認しました。</p><p>AIの勝ち数の総予測は実際の勝ち数に近いものの、最終人気で分けると大きくずれます。確率の全体平均が合っていても、オッズと組み合わせた期待値評価が正しいとは限りません。</p><h2>人気別の確率と実際の成績</h2><div class="scroll">{pop_table}</div><p>モデル入力52項目にはオッズ・人気は含まれず、オッズは買い目の期待値計算と配分に使われます。この検証では最終人気を診断用に使っており、最終人気で予想を作り直してはいません。</p><h2>買い目への影響</h2><p>AIの合計予測的中数は {summary['portfolio']['model_expected_hit_races']:.1f}レース、実際は {hits}レース（{hits/103:.1%}）。仮想投入 {stake:,}円、公式払戻 {payout:,}円、回収率 {100*payout/stake:.2f}%でした。100倍以上の買い目に投入額の {summary['portfolio']['at_or_above_100x_stake_share']:.1%}が向かいました。</p><div class="scroll">{bands_table}</div><p>モデルの理論期待払戻合計 {summary['portfolio']['model_expected_payout_yen']:,.0f}円を、そのまま実現可能な利益と説明することはできません。特に高配当帯の確率評価が購入先を穴側へ寄せています。</p><h2>データを補ったレースを除いた確認</h2><p>公開情報で再構成した函館スプリントS・チャレンジC・秋華賞を除く100レースでも、1番人気のAI平均勝率 {summary['sensitivity_excluding_3_public_reconstructions']['horse_popularity_bias'][0]['model_win_rate']:.1%}に対し実際 {summary['sensitivity_excluding_3_public_reconstructions']['horse_popularity_bias'][0]['actual_win_rate']:.1%}。11番人気以下はAI {summary['sensitivity_excluding_3_public_reconstructions']['horse_popularity_bias'][-1]['model_win_rate']:.1%}に対し実際 {summary['sensitivity_excluding_3_public_reconstructions']['horse_popularity_bias'][-1]['actual_win_rate']:.1%}で、主要な傾向は変わりません。</p><div class="note"><strong>検証の扱い</strong><ul><li>確定オッズを使った過去検証で、本番の発走前予想・公開成績ではありません。</li><li>モデル・補正器・現行購入ルールは変更していません。秋華賞の元の30点・仮想112%の記録も、この再計算では置き換えません。</li><li>元の特徴量全体の時点整合性は未証明です。対象レースの着順・勝敗ラベルはモデル入力から除外しました。</li><li>函館スプリントSの1頭の前走脚質は未解決の欠損値を保持しました。補完3レースを除いた結果も別集計しています。</li><li>安田記念は2着同着のため、通常のオッズ計算と公式払戻が異なります。公式払戻を採用し、1点の払戻が1万円未満となった事例を隠していません。</li><li>この103レースだけで高配当帯の真の期待値を確定することはできません。</li></ul></div><h2>103レースの一覧</h2><div class="scroll">{race_table}</div><p>公式対象一覧：<a href="https://www.jra.go.jp/datafile/seiseki/replay/2026/jyusyo.html">JRA 2026年重賞レース結果</a>。レース別の公式出典と確定オッズ出典は同梱JSONに保持しています。</p></html>'''
    (OUT/'bias_2026_report_20261020.html').write_text(report,encoding='utf-8')
    archive=ROOT/'bias_2026_report_20261020.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in OUT.iterdir():z.write(p,p.name)
        for p in sorted((ROOT/'portfolio_results').glob('*.json')):z.write(p,'race_tickets/'+p.name)
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None
    print(json.dumps({'races':103,'horse_popularity_bias':summary['horse_popularity_bias'],
        'portfolio':summary['portfolio'],'sensitivity_100':{k:v for k,v in summary['sensitivity_excluding_3_public_reconstructions'].items() if k!='horse_popularity_bias'},
        'summary':str(OUT/'bias_2026_summary_20261020.json'),'zip':str(archive),'zip_size':archive.stat().st_size},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
