"""Atomic two-policy publication, authenticated settlement, persisted X drafts."""
import argparse,copy,datetime as dt,json,re,sys
from pathlib import Path
from operation_runner import GitHub,ConnectorRPC,BRANCH,REPOSITORY,dumps
from pre_race_record import timestamp
from two_researchers import VERSION,validate,digest,prediction_draft,result_draft

def paths(race,test_only=False,run_id=None):
    if not re.fullmatch(r'\d{16}',race):raise ValueError('Invalid race')
    if test_only:
        if not run_id or not re.fullmatch('[A-Za-z0-9_-]+',run_id):raise ValueError('Test run ID required')
        root='development/free_web/publication_tests/'+run_id
        return {k:root+'/'+race+suffix for k,suffix in [('prediction','.json'),('receipt','_receipt.json'),('result','_result.json'),('prediction_x','_prediction_x.txt'),('result_x','_result_x.txt')]}
    return {'prediction':'predictions/researchers/'+race+'.json','receipt':'predictions/researchers_receipts/'+race+'.json',
       'result':'results/researchers/'+race+'.json','prediction_x':'publications/researchers/'+race+'_prediction_x.txt',
       'result_x':'publications/researchers/'+race+'_result_x.txt'}
def url(sha,path):return 'https://github.com/'+REPOSITORY+'/blob/'+sha+'/'+path
def timely(pair,stamp,test_only):
    if not test_only and not timestamp(pair['prediction_finalized_at'])<=timestamp(stamp)<=timestamp(pair['race_start_at'])-dt.timedelta(minutes=12):raise ValueError('Late/invalid pre-race commit')
def listing(pair):
    out=[]
    for key,r in pair['researchers'].items():
        out.append(r['researcher_name']+f"：{len(r['tickets'])}点、仮想{r['total_stake_yen']:,}円、残額{r['unspent_yen']:,}円")
        for t in r['tickets']:
            nums='-'.join(str(int(t['kumiban'][i:i+2])) for i in range(0,len(t['kumiban']),2))
            out.append(('馬連' if t['bet_type']=='umaren' else '3連複')+' '+nums+f" {t['stake']:,}円")
    return '\n'.join(out)
def publish_pair(pair,github,test_only=False,run_id=None,clock=None):
    clock=clock or (lambda:dt.datetime.now(dt.timezone.utc));validate(pair,now=clock(),test_only=test_only)
    record=copy.deepcopy(pair);record['test_only']=test_only
    p=paths(record['race_code'],test_only,run_id);content=dumps(record)
    commit,(_,_,saved_at)=github.save(p['prediction'],content,'Save both research predictions '+record['race_code'])
    timely(record,saved_at,test_only)
    receipt={'schema_version':1,'test_only':test_only,'race_code':record['race_code'],'policy_version':VERSION,
       'commit_sha':commit,'recorded_at':saved_at,'content_sha256':digest(content),'record_url':url(commit,p['prediction'])}
    receipt_sha,(_,_,receipt_time)=github.save(p['receipt'],dumps(receipt),'Confirm both research predictions '+record['race_code'])
    timely(record,receipt_time,test_only)
    # Revalidate the real wall clock after storage, not just the computation timestamp.
    validate(record,now=clock(),test_only=test_only)
    draft=prediction_draft(record,receipt['record_url'],test_only)
    draft_sha,(_,_,draft_time)=github.save(p['prediction_x'],draft+'\n','Save prediction X draft '+record['race_code'])
    timely(record,draft_time,test_only);validate(record,now=clock(),test_only=test_only)
    return {'status':'test_complete' if test_only else 'published','test_only':test_only,'race_code':record['race_code'],
       'prediction_commit_sha':commit,'receipt_commit_sha':receipt_sha,'record_url':receipt['record_url'],
       'x_draft':draft,'x_draft_url':url(draft_sha,p['prediction_x']),'chat_listing':listing(record)}
def settle_pair(race,github,payout_snapshot=None,test_only=False,run_id=None):
    from settlement import settle
    p=paths(race,test_only,run_id);receipt_bytes=github.optional(p['receipt'])
    if receipt_bytes is None:raise ValueError('Pair receipt missing; no retrospective pre-race fabrication')
    receipt=json.loads(receipt_bytes)
    if receipt['race_code']!=race or receipt['test_only'] is not test_only or receipt.get('policy_version')!=VERSION:raise ValueError('Receipt identity mismatch')
    content=github.content(p['prediction'],receipt['commit_sha']);github.verify(p['prediction'],content,receipt['commit_sha'])
    if digest(content)!=receipt['content_sha256']:raise ValueError('Pair hash mismatch')
    if timestamp(github.commit_time(receipt['commit_sha']))!=timestamp(receipt['recorded_at']):raise ValueError('Server/receipt time mismatch')
    _,(_,_,receipt_time)=github.save(p['receipt'],receipt_bytes,'Confirm both research predictions '+race)
    pair=json.loads(content)
    # For settlement validate model/policy/source consistency; computation/publication
    # happened in the past, so the current-clock pre-race check is inapplicable.
    validate(pair,test_only=True)
    if pair['test_only'] is not test_only:raise ValueError('Prediction test flag mismatch')
    timely(pair,receipt['recorded_at'],test_only);timely(pair,receipt_time,test_only)
    if payout_snapshot is None:
        from official_results import fetch_for_race
        payout_snapshot=fetch_for_race(race)
    result={'schema_version':1,'policy_version':VERSION,'race_code':race,'race_name':pair['race_name'],
       'test_only':test_only,'is_live_performance_record':not test_only,'prediction_commit_sha':receipt['commit_sha'],
       'prediction_content_sha256':receipt['content_sha256'],
       'researchers':{key:settle(r,payout_snapshot,publication=receipt,test_only=test_only) for key,r in pair['researchers'].items()}}
    commit,_=github.save(p['result'],dumps(result),'Settle both research predictions '+race)
    draft=result_draft(result,url(commit,p['result']))
    draft_commit,_=github.save(p['result_x'],draft+'\n','Save results X draft '+race)
    return {'status':'settled','test_only':test_only,'result':result,'record_url':url(commit,p['result']),
       'commit_sha':commit,'x_draft':draft,'x_draft_url':url(draft_commit,p['result_x'])}
def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['live','publish','settle'])
    for arg in ['race','model-dir','history-dir','window','record','payout','run-id','output']:parser.add_argument('--'+arg,required=arg in ['race','output'])
    parser.add_argument('--pedigree',action='append',default=[]);parser.add_argument('--test-only',action='store_true');args=parser.parse_args()
    github=GitHub(ConnectorRPC());stage=args.action
    try:
        if args.action=='settle':
            if args.payout and not args.test_only:raise ValueError('Live settlement must fetch official result')
            payout=json.loads(Path(args.payout).read_text()) if args.payout else None
            outcome=settle_pair(args.race,github,payout,args.test_only,args.run_id)
        else:
            if args.action=='live':
                if args.test_only:raise ValueError('Live acquisition cannot be test-only')
                p=paths(args.race);existing=github.optional(p['prediction'])
                if existing is not None:record=json.loads(existing)
                else:
                    from calibrated_live_pipeline import prepare_live
                    from two_researchers import prepare
                    record=prepare_live(args.race,args.model_dir,args.history_dir,args.pedigree,args.window,record_prepare=prepare)
                if args.window:
                    from calibrated_live_pipeline import check_window
                    check_window(record['race_start_at'],args.window)
            else:
                if not args.test_only:raise ValueError('Direct record publication is test-only; live must acquire sources')
                record=json.loads(Path(args.record).read_text())
            stage='publish_both_receipts_prediction_x_draft'
            outcome=publish_pair(record,github,args.test_only,args.run_id)
        Path(args.output).write_text(dumps(outcome));print('JRA_DONE '+json.dumps({'status':outcome['status'],'output':args.output}),flush=True)
    except Exception as exc:
        failure={'status':'failed','stage':github.stage or stage,'race_code':args.race,'error_type':type(exc).__name__,
          'error':str(exc)[:500],'completed':False,'x_draft':None}
        try:
            stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d/%H%M%S%f')
            path='development/free_web/incidents/two_researchers/'+stamp+'_'+args.race+'.json'
            commit,_=github.save(path,dumps(failure),'Record interrupted dual operation');failure['incident_url']=url(commit,path)
        except Exception:failure['incident_saved']=False
        Path(args.output).write_text(dumps(failure));print('JRA_FAILED '+json.dumps(failure),flush=True);raise SystemExit(1)
if __name__=='__main__':main()
