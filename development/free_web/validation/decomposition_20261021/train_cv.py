"""Select correction families in 2025 forward validation only. Never read 2026 labels."""
import argparse,datetime as dt,hashlib,json
from pathlib import Path
import joblib,numpy as np,pandas as pd
from sklearn.linear_model import LogisticRegression
from rankwise import METHODS,fit,scores,observed_losses,distribution

def calibrate(data,training_mask):
    result={};calibrators={}
    for label in ['win','top3']:
        raw=np.clip(data['raw_'+label].to_numpy(),1e-7,1-1e-7);logits=np.log(raw/(1-raw)).reshape(-1,1)
        model=LogisticRegression(C=1e6,solver='lbfgs',max_iter=2000)
        model.fit(logits[training_mask],data.loc[training_mask,'target_'+label].to_numpy(dtype=int))
        result[label]=model.predict_proba(logits)[:,1];calibrators[label]=model
    return result,calibrators

def make_races(data,probability,codes):
    frame=data.copy();frame['win']=probability['win'];frame['top3']=probability['top3'];races=[]
    for code,g in frame[frame.race_code.isin(codes)].groupby('race_code',sort=True):
        g=g.assign(number=g.umaban.astype(int)).sort_values('number').reset_index(drop=True)
        market=json.loads((Path('correction_20261021/cache/market')/(code+'.json')).read_text())
        mp={r['umaban']:r for r in market['runners']}
        assert set(g.number)==set(mp) and len(g)==int(g.field_size.max())
        assert all(str(row.ketto_toroku_bango)==mp[row.number]['horse_id'] for row in g.itertuples())
        order=g[g.target_finish_position.between(1,3)].sort_values('target_finish_position')
        assert order.target_finish_position.tolist()==[1,2,3]
        races.append({'race_code':code,'date':g.race_date.iloc[0].strftime('%Y-%m-%d'),
            'numbers':g.number.tolist(),'win':g.win.tolist(),'top3':g.top3.tolist(),
            'order':order.index.tolist(),'odds':[mp[n]['decimal_win_odds'] for n in g.number],
            'target_win':g.target_win.astype(int).tolist(),'target_top3':g.target_top3.astype(int).tolist()})
    return races

def main(workdir):
    root=Path(workdir);data=pd.read_pickle(root/'private_assets/raw_predictions_2025.pkl')
    assert data.race_date.max()<=pd.Timestamp('2025-12-31')
    protocol=json.loads((root/'public/protocol.json').read_text())
    fixed=json.loads(Path('correction_20261021/private_assets/correction_coefficients.json').read_text())
    codes=set(fixed['fit_race_codes']);assert len(codes)==119
    validation_rows=[];fold_reports=[]
    for fold_number,fold in enumerate(protocol['folds'],1):
        training_mask=(data.race_date<=fold['train_end']).to_numpy()
        probabilities,_=calibrate(data,training_mask)
        all_races=make_races(data,probabilities,codes)
        train=[r for r in all_races if r['date']<=fold['train_end']]
        validation=[r for r in all_races if fold['validate_start']<=r['date']<=fold['validate_end']]
        assert train and validation and max(r['date'] for r in train)<min(r['date'] for r in validation)
        report={'fold':fold_number,**fold,'calibrator_training_rows':int(training_mask.sum()),
            'calibrator_latest_label_date':data.loc[training_mask,'race_date'].max().strftime('%Y-%m-%d'),
            'rank_training_races':len(train),'validation_races':len(validation),'fits':{}}
        for method in METHODS:
            fitted=fit(train,method);report['fits'][method]=fitted
            for race in validation:
                stage=scores(race,method,fitted['parameters']);rank_losses=observed_losses(stage,race['order'])
                _,_,win,top=distribution(stage)
                validation_rows.append({'fold':fold_number,'race_code':race['race_code'],'date':race['date'],'method':method,
                    'ordered_nll':sum(rank_losses),'rank_nll':rank_losses,
                    'WIN_brier':float(np.mean((win-np.asarray(race['target_win']))**2)),
                    'TOP3_brier':float(np.mean((top-np.asarray(race['target_top3']))**2))})
            print('CV',fold_number,method,'TRAIN',len(train),'VALIDATE',len(validation),flush=True)
        fold_reports.append(report)
    table=pd.DataFrame(validation_rows);ranking=[]
    for method,g in table.groupby('method',sort=False):
        ranking.append({'method':method,'free_parameters':METHODS[method],'validation_races':len(g),
            'mean_ordered_nll':float(g.ordered_nll.mean()),'standard_error':float(g.ordered_nll.std(ddof=1)/np.sqrt(len(g))),
            'mean_WIN_brier':float(g.WIN_brier.mean()),'mean_TOP3_brier':float(g.TOP3_brier.mean())})
    best=min(ranking,key=lambda r:r['mean_ordered_nll']);threshold=best['mean_ordered_nll']+best['standard_error']
    eligible=[r for r in ranking if r['mean_ordered_nll']<=threshold]
    selected=min(eligible,key=lambda r:(r['free_parameters'],r['mean_ordered_nll'],r['method']))
    probability,calibrators=calibrate(data,np.ones(len(data),bool))
    races=make_races(data,probability,codes);models={name:fit(races,name) for name in METHODS}
    for label,model in calibrators.items():joblib.dump(model,root/('private_assets/full2025_'+label+'_platt.joblib'),compress=3)
    # This coefficient snapshot is written before any 2026 evaluation in this experiment.
    report={'record_type':'2025_forward_validation_selection','created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'selection_year':2025,'2026_labels_used':False,'fold_specific_base_calibrators':True,
        'selection_rule':protocol['selection'],'best_mean_method':best['method'],'one_SE_threshold':threshold,
        'selected_method':selected['method'],'selected_by_one_SE':True,'ranking':sorted(ranking,key=lambda r:r['mean_ordered_nll']),
        'folds':fold_reports,'final_full2025_fits':models,'fit_races':len(races),
        'validation_race_codes':sorted(table.race_code.unique().tolist()),'protocol_sha256':hashlib.sha256((root/'public/protocol.json').read_bytes()).hexdigest(),
        'no_production_model_or_automation_changes':True,'all_families_to_be_reported_in_2026_without_reselection':True}
    (root/'private_assets/full2025_races.json').write_text(json.dumps(races)+'\n')
    (root/'public/cv_validation_races.json').write_text(json.dumps(validation_rows,indent=2)+'\n')
    (root/'public/selection.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('SELECTION',json.dumps({'selected':selected,'ranking':ranking,'fits':models}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('workdir');a=p.parse_args();main(a.workdir)
