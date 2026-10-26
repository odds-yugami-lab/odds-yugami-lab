"""Retrospective correction50 replay on authenticated original in-sale Kikka odds."""
import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
import json,hashlib,math,sys,shutil,datetime
from pathlib import Path
import numpy as np,pandas as pd
sys.path.insert(0,'decomposition_20261021')
from rankwise import scores,probability_tables
sys.path.insert(0,'profit_comparison_20261024')
from allocator_research import allocate
R=Path('kikka_50_20261026');P=R/'public';A=R/'private'
PARAM=[.10902943648255348,.7586398739642098]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,d):
 with p.open('x') as f:json.dump(d,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
def predict():
 path=Path('/workspace/scratch/5546614e7bb6/work/kikka_production_shadow_input.json')
 assert sha(path)=='bd12064585844212ce323bcb6555852c13e9888eab5a539be5f0708ed526e96c'
 d=json.loads(path.read_text());prod=json.loads((A/'production.json').read_text());shadow=json.loads((A/'shadow.json').read_text())
 captured=d['record']
 # Live runner appends these provenance fields after calibrated.prepare returns.
 assert set(prod)-set(captured)=={'is_pre_race_prediction','history_coverage_check','record_type','entry_sources'}
 assert all(prod[k]==v for k,v in captured.items()) and sha(path)==shadow['source_snapshot_sha256']
 shutil.copy2(path,A/'authenticated_snapshot.json')
 horses=sorted(prod['horse_probabilities'],key=lambda x:int(x['umaban']));nums=[int(x['umaban']) for x in horses]
 win={int(x['umaban']):x['decimal_odds'] for x in d['win_snapshot']['rows']};assert set(nums)==set(win)
 race={'race_code':prod['race_code'],'numbers':nums,'win':[h['raw_saved_win_probability'] for h in horses],
 'top3':[h['raw_saved_top3_probability'] for h in horses],'odds':[win[n] for n in nums]}
 h100,c100,events100=probability_tables(race,scores(race,'shared_ai_market',PARAM))
 assert np.allclose(h100.win_probability,[x['rank_strength'] for x in horses],rtol=0,atol=1e-12)
 lookup={(x.bet_type,x.kumiban):x.ai_probability for x in c100.itertuples()}
 for record in [prod,shadow]:
  for t in record['tickets']:assert abs(t['ai_probability']-lookup[(t['bet_type'],t['kumiban'])])<1e-10
 odds=pd.DataFrame([x for k,v in d['odds_snapshots'].items() for x in v['rows']])
 assert len(odds)==969 and odds.groupby('bet_type').size().to_dict()=={'sanrenpuku':816,'umaren':153}
 for k,v in d['odds_snapshots'].items():assert v['page_sha256']==prod['odds_sources'][k]['page_sha256']
 pars=[.5+.5*PARAM[0],.5*PARAM[1]];h,c,events=probability_tables(race,scores(race,'shared_ai_market',pars))
 combined=c.merge(odds,on=['race_code','bet_type','kumiban'],how='outer',indicator=True,validate='one_to_one');assert combined._merge.eq('both').all();combined=combined.drop(columns='_merge')
 scale=float((combined.ai_probability*combined.decimal_odds).max()*10000);records={}
 for name,net,flt in [('ichiro',False,False),('matsui',True,True)]:
  t,a=allocate(combined,nums,events,expected_payout_scale=scale,time_limit=30.,mip_relative_gap=.01,net_profit=net,nonnegative_only=flt)
  tickets=t.to_dict('records');total=sum(int(x['stake']) for x in tickets);assert 1<=len(tickets)<=30 and 0<total<=10000
  for x in tickets:assert x['stake']==100*max(1,math.ceil(100/x['decimal_odds']-1e-12))
  if flt:assert all(x['ai_probability']*x['decimal_odds']>=1-1e-10 for x in tickets)
  records[name]={'test_only':True,'is_pre_race_prediction':False,'record_type':'retrospective_same_in_sale_snapshot_replay',
   'researcher_name':'一郎研究員' if name=='ichiro' else 'マツイ研究員','race_code':prod['race_code'],'race_name':'菊花賞',
   'correction_strength':.5,'parameters':pars,'original_full_parameters':PARAM,'tickets':tickets,'allocation_audit':a,
   'total_stake_yen':total,'unspent_yen':10000-total,'ticket_count':len(tickets),'horse_probabilities':h.to_dict('records'),
   'authenticated_snapshot_sha256':sha(path),'original_production_commit':'edee7b3bbf02ac2429dd600b8384f8ff37426104',
   'recomputed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'original_odds_sources':prod['odds_sources'],
   'original_win_odds_source':prod['win_odds_source'],'outcomes_passed_to_allocator':False,'not_live_performance':True}
  save(P/(name+'_prediction.json'),records[name])
 save(P/'prediction_manifest.json',{'test_only':True,'same_original_input_authenticated':True,'full_correction_probability_reproduced':True,
   'odds_combinations':969,'raw_saved_heads_reused_not_model_reinference':True,
   'files':{name:sha(P/(name+'_prediction.json')) for name in records},'allocator_sha256':sha('profit_comparison_20261024/allocator_research.py')})
 print({n:{'tickets':r['ticket_count'],'stake':r['total_stake_yen'],'H':r['allocation_audit']['probability_any_win']} for n,r in records.items()})
def settle():
 assert (P/'prediction_seal.json').exists()
 m=json.loads((P/'prediction_manifest.json').read_text())
 for name,h in m['files'].items():assert sha(P/(name+'_prediction.json'))==h
 official=json.loads(Path('/workspace/scratch/1e48a2387f57/official_result_2026102508040911.json').read_text())
 if not (A/'official_result.json').exists():save(A/'official_result.json',official)
 assert official['race_code']=='2026102508040911' and official['official_verified'] and not official['refunded_horse_numbers']
 prior_settlement=json.loads((A/'prior_settlement.json').read_text());assert prior_settlement['result_source_url']==official['source_url']
 rows=[];settlements={}
 for name,prior_file in [('ichiro','production.json'),('matsui','shadow.json')]:
  new=json.loads((P/(name+'_prediction.json')).read_text());previous=json.loads((A/prior_file).read_text())
  for label,r in [('100_percent_original',previous),('50_percent_replay',new)]:
   tickets=r['tickets'];pay=sum(official['payouts_per_100_yen'][t['bet_type']].get(t['kumiban'],0)*int(t['stake'])//100 for t in tickets)
   total=sum(t['stake'] for t in tickets)
   row={'researcher':name,'setting':label,'tickets':len(tickets),'stake_yen':total,'payout_yen':pay,'profit_yen':pay-total,
    'recovery_percent':100*pay/total,'estimated_any_hit_probability':r['allocation_audit']['probability_any_win']}
   rows.append(row)
  settlements[name]={'test_only':True,'not_live_performance':True,'race_code':official['race_code'],'researcher_name':new['researcher_name'],
   'prediction_commit':json.loads((P/'prediction_seal.json').read_text())['commit_sha'],
   'prediction_sha256':sha(P/(name+'_prediction.json')),'official_verified':True,'source_url':official['source_url'],
   'official_page_sha256':official['page_sha256'],'official_obtained_at':official['obtained_at'],
   'winning_payouts_per100yen':official['payouts_per_100_yen'],'stake_yen':new['total_stake_yen'],'payout_yen':pay,
   'profit_yen':pay-new['total_stake_yen'],'recovery_percent':100*pay/new['total_stake_yen']}
  save(P/(name+'_settlement.json'),settlements[name])
  oldkeys={(t['bet_type'],t['kumiban']) for t in previous['tickets']};newkeys={(t['bet_type'],t['kumiban']) for t in new['tickets']}
  settlements[name]['unchanged_combinations']=len(oldkeys&newkeys)
 report={'test_only':True,'not_live_performance':True,'race_code':official['race_code'],'comparison':rows,
 'source_snapshot_authenticated':True,'full_correction_probability_reproduced':True,'same969_original_live_odds':True,
 'raw_saved_heads_reused_not_new_model_inference':True,'all30point_budget_minimum_stake_checks_passed':True,
 'matsui_nonnegative_ev_verified':True,'prediction_seal_readback_verified':True,
 'official_result_verified_from_existing_authenticated_result':True,'fresh_official_refetch_performed':False,
 'original_records_and_receipts_unchanged':True,'production_code_and_automations_unchanged':True,
 'original_production_was_formal_shadow_was_test':True,'replay_cannot_be_counted_as_pre_race_prediction':True,
 'comparison_combination_overlap':{n:s['unchanged_combinations'] for n,s in settlements.items()}}
 save(P/'report.json',report)
 text=['# 菊花賞：人気補正50%での一郎・マツイ再計算','',
 '2026年10月26日に実計算した事後検証。発走前予想・本番実績には加えません。従来の菊花賞原本・receipt・成績と運用コード・予約は変更していません。','',
 '発走前に保存された補正前WIN/TOP3と、単勝・馬連153組・3連複816組の当日オッズを使用。全captureのSHA256は発走前シャドー記録と一致。公開原本にはcapture後に4項目の出典メタデータが追加されていますが、capture内の全項目は原本と一致しました。','',
 '従来補正のAI係数0.10902943648255348、市場係数0.7586398739642098から、50%ではAI係数0.5545147182412767、市場係数0.3793199369821049へ変更。市場による補正前後の対数評価を半分ずつ混ぜる既存定義です。変更前の全馬の確率と購入券確率も再現して照合しました。基礎モデルの推論を再実行したものではなく、原本の保存済みWIN/TOP3を再利用しています。','',
 '一郎研究員は期待総払戻と的中機会、マツイ研究員は推定EV>=1の候補だけから期待純利益と的中機会を50:50で評価。同じ全組合せから得る尺度、最大30点、上限1万円、最低必要額、余りを残す規則を適用しました。両方30秒・誤差1%の研究用実装を使い、元のマツイ裏検証の10秒とは異なります。','',
 '|研究員|補正|点数|配分額|推定的中確率|実払戻|','|---|---|---:|---:|---:|---:|']
 for row in rows:text.append(f"|{'一郎' if row['researcher']=='ichiro' else 'マツイ'}|{'従来100%' if row['setting'].startswith('100') else '今回50%'}|{row['tickets']}|{row['stake_yen']:,}円|{100*row['estimated_any_hit_probability']:.2f}%|{row['payout_yen']:,}円|")
 text+=['','公式結果は馬連6-9が100円あたり11,530円、3連複6-9-10が8,580円。今回は両方式とも該当券がなく不的中でした。既存のJRA公式結果取得記録と、本番収支原本の出典URLを照合して使用し、新規に公式ページを取得し直してはいません。','',
 '買い目は公式結果を配分処理へ渡さず先に計算し、predictions.jsonをGitHubに確定・読戻ししてから収支を集計しました。現在の再計算時刻を記録し、発走前に作った予想と偽っていません。人気補正50%による同一当日入力での計算・保存・精算は実施しましたが、本番の発走前2人運用や予約更新の完了を意味しません。','',
 '[買い目2人分](predictions.json)／[比較・検査](report.json)／[一郎の収支](ichiro_settlement.json)／[マツイの収支](matsui_settlement.json)','']
 with (P/'README.md').open('x') as f:f.write('\n'.join(text))
 print(json.dumps(rows,ensure_ascii=False))
def main():{'predict':predict,'settle':settle}[sys.argv[1]]()
if __name__=='__main__':main()
