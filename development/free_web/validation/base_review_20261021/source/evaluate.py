"""Frozen learner, same-input temporal comparison; final odds, not live performance."""
import datetime as dt,hashlib,json,sys
from pathlib import Path
import joblib,numpy as np,pandas as pd
from features import augment,matrix
sys.path.insert(0,'decomposition_20261021')
from evaluate import summarize,paired
from rankwise import scores,probability_tables,observed_losses
ROOT=Path('base_review_20261021');PRIVATE=ROOT/'private_assets';PUBLIC=ROOT/'public'
ORIGINAL=Path('repair_20261020/private_assets/JRA_free_model_52_20261013')

def infer(frame,model_dir,platt_paths=None):
    spec=json.loads((model_dir/'feature_spec.json').read_text())
    maps=spec['category_map'];x,_=matrix(frame,spec['features'],spec['categorical'],maps)
    result={}
    for label in ['win','top3']:
        model=joblib.load(model_dir/(label+'_model.joblib'))
        raw=np.clip(model.predict_proba(x)[:,1],1e-7,1-1e-7)
        cal=joblib.load(platt_paths[label] if platt_paths else model_dir/(label+'_platt.joblib'))
        result[label]=cal.predict_proba(np.log(raw/(1-raw)).reshape(-1,1))[:,1]
    return result

def main():
    selection=json.loads((PUBLIC/'selection.json').read_text());selected=selection['selected_family']
    assert (PUBLIC/'selection_commit.json').exists(),'Freeze and commit selection before 2026 inference'
    frame=augment(pd.read_pickle(PRIVATE/'features_2026.pkl'))
    old=json.loads(Path('correction_20261021/private_assets/correction_coefficients.json').read_text())
    models={'incumbent_same_input':(ORIGINAL,None,[old['alpha_ai'],old['beta_market']]),
        'candidate':(PRIVATE/(selected+'_through2025'),{label:PRIVATE/(selected+'_2025_'+label+'_platt.joblib') for label in ['win','top3']},
            selection['final_2025_fits'][selected]['parameters'])}
    official={r['race_code']:r for r in json.loads(Path('bias_20261020/official_results.json').read_text())['races']}
    archived=pd.DataFrame(json.loads(Path('bias_20261020/horse_predictions_all.json').read_text()))
    outputs={};rawoutputs={};privateraces={};differences=[]
    for name,(model,platt,parameters) in models.items():
        probability=infer(frame,model,platt);temp=frame.copy();temp['w']=probability['win'];temp['t']=probability['top3']
        outputs[name]=[];rawoutputs[name]=[];privateraces[name]=[]
        for code,g in temp.groupby('race_code',sort=True):
            g=g.assign(number=g.umaban.astype(int)).sort_values('number').reset_index(drop=True);obs=official[code]
            observed={r['umaban']:r for r in obs['runners']}
            market=json.loads((Path('correction_20261021/cache/market')/(code+'.json')).read_text())
            mp={r['umaban']:r for r in market['runners']};assert set(g.number)==set(mp)
            race={'race_code':code,'date':obs['date'],'numbers':g.number.tolist(),'win':g.w.tolist(),'top3':g.t.tolist(),
                'odds':[mp[n]['decimal_win_odds'] for n in g.number],
                'target_win':[int(observed[n]['finish_status']=='1') for n in g.number],
                'target_top3':[int(observed[n]['finish_status'].isdigit() and int(observed[n]['finish_status'])<=3) for n in g.number],
                'popularity':[observed[n]['popularity'] for n in g.number],
                'input_source':g.input_source.iloc[0]}
            first=sorted([r for r in obs['finish_rows'] if r['finish_status'].isdigit() and int(r['finish_status'])<=3],key=lambda r:int(r['finish_status']))
            deadheat=len(first)!=3 or len({r['finish_status'] for r in first})!=3
            race['order']=[] if deadheat else [race['numbers'].index(r['horse_number']) for r in first]
            privateraces[name].append(race)
            def horse_rows(w,t):
                return [{'umaban':n,'win_probability':float(a),'top3_probability':float(b),'target_win':race['target_win'][i],
                    'target_top3':race['target_top3'][i],'popularity':race['popularity'][i]} for i,(n,a,b) in enumerate(zip(race['numbers'],w,t))]
            rawoutputs[name].append({'race_code':code,'date':race['date'],'metrics':{},'horses':horse_rows(g.w,g.t),'archive':race['input_source']=='archive'})
            stage=scores(race,'shared_ai_market',parameters);pred,combo,_=probability_tables(race,stage)
            metrics={}
            if not deadheat:
                metrics['ordered_nll']=sum(observed_losses(stage,race['order']))
                for kind in ['umaren','sanrenpuku']:
                    subset=combo[combo.bet_type==kind];winners=obs['payouts_per_100_yen'][kind];assert len(winners)==1
                    key=next(iter(winners));p=float(subset.loc[subset.kumiban==key,'ai_probability'].iloc[0])
                    metrics[kind+'_nll']=-float(np.log(p));metrics[kind+'_brier']=float((subset.ai_probability**2).sum()-2*p+1)
            outputs[name].append({'race_code':code,'date':race['date'],'metrics':metrics,'horses':horse_rows(pred.win_probability,pred.top3_probability),'archive':race['input_source']=='archive'})
            if name=='incumbent_same_input':
                prior=archived[archived.race_code==code].sort_values('umaban')
                assert prior.umaban.tolist()==g.number.tolist()
                differences.append({'race_code':code,'archive':race['input_source']=='archive',
                    'max_WIN_difference':float(np.abs(g.w.to_numpy()-prior.win_probability.to_numpy()).max()),
                    'max_TOP3_difference':float(np.abs(g.t.to_numpy()-prior.top3_probability.to_numpy()).max())})
        print('INFERRED',name,len(outputs[name]),flush=True)
    result={'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'test_only':True,'selected_family':selected,
        'selection_sha256':hashlib.sha256((PUBLIC/'selection.json').read_bytes()).hexdigest(),
        'selection_commit':json.loads((PUBLIC/'selection_commit.json').read_text())['commit_sha'],
        'raw':{k:summarize(v) for k,v in rawoutputs.items()},'corrected':{k:summarize(v) for k,v in outputs.items()},
        'archive96_only':{'raw':{k:summarize([r for r in v if r['archive']]) for k,v in rawoutputs.items()},
            'corrected':{k:summarize([r for r in v if r['archive']]) for k,v in outputs.items()}},
        'paired_ordered_nll':paired(outputs['candidate'],outputs['incumbent_same_input'],'ordered_nll'),
        'incumbent_archive_reinference_differences':differences,'production_changed':False,
        '2026_is_untouched':False,'final_odds_used':True,'source_point_in_time_certified':False}
    (PUBLIC/'probability_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (PRIVATE/'races_2026.json').write_text(json.dumps(privateraces)+'\n')
    (PRIVATE/'evaluation.json').write_text(json.dumps(outputs)+'\n')
    print('COMPARISON',json.dumps({k:result[k] for k in ['selected_family','raw','corrected','paired_ordered_nll']}),flush=True)

if __name__=='__main__':main()
