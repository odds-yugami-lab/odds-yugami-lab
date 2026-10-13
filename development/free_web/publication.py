"""Prepare append-only GitHub requests and confirm exact committed bytes.

An orchestrator calls create_file, fetch_file(ref=returned_commit), and
fetch_commit. No credentials are embedded and no API success is assumed.
"""
import datetime as dt
import hashlib
import json
import re
from pre_race_record import timestamp,x_draft

REPOSITORY='odds-yugami-lab/odds-yugami-lab'

def request(record,branch,now=None,test_only=False):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:raise ValueError('Timezone required')
    race=record['race_code']
    if not re.fullmatch(r'\d{16}',race):raise ValueError('Invalid race')
    if not test_only and timestamp(record['race_start_at'])-now<dt.timedelta(minutes=12):
        raise ValueError('Publication deadline passed')
    if record.get('status')!='prepared_not_published':raise ValueError('Not a prepared record')
    if record['total_stake_yen']!=10000 or sum(t['stake'] for t in record['tickets'])!=10000:
        raise ValueError('Invalid saved budget')
    payload=dict(record,is_pre_race_prediction=not test_only,
                 record_type='publication_test' if test_only else 'pre_race_prediction')
    prefix='development/free_web/publication_tests' if test_only else 'predictions/free52'
    path=f'{prefix}/{race}.json'
    content=json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n'
    return {'repository_full_name':REPOSITORY,'branch':branch,'path':path,'content':content,
            'message':('Test publication ' if test_only else 'Record pre-race prediction ')+race,
            'content_sha256':hashlib.sha256(content.encode()).hexdigest(),'test_only':test_only}

def confirm(write_request,commit_sha,committed_content,commit_recorded_at,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if not re.fullmatch(r'[0-9a-f]{40}',commit_sha):raise ValueError('Invalid commit receipt')
    if committed_content!=write_request['content']:raise ValueError('Committed bytes differ')
    saved=timestamp(commit_recorded_at)
    if now.tzinfo is None or saved>now:raise ValueError('Invalid commit time')
    record=json.loads(committed_content)
    if not write_request['test_only']:
        finalized=timestamp(record['prediction_finalized_at'])
        if not finalized<=saved<=timestamp(record['race_start_at'])-dt.timedelta(minutes=12):
            raise ValueError('Commit was not made before deadline')
        if now>timestamp(record['race_start_at'])-dt.timedelta(minutes=12):
            raise ValueError('Presentation deadline passed')
    url=f"https://github.com/{REPOSITORY}/blob/{commit_sha}/{write_request['path']}"
    receipt={'status':'test_saved' if write_request['test_only'] else 'published',
             'race_code':record['race_code'],'commit_sha':commit_sha,
             'recorded_at':saved.isoformat(),'record_url':url,
             'content_sha256':write_request['content_sha256'],'test_only':write_request['test_only']}
    lines=[f"{record['race_name']}：馬連・3連複 合計10,000円"]
    for t in record['tickets']:
        key=t['kumiban'];nums='－'.join(str(int(key[i:i+2])) for i in range(0,len(key),2))
        name={'umaren':'馬連','sanrenpuku':'3連複'}[t['bet_type']]
        lines.append(f"{name} {nums}：{t['stake']:,}円（取得時オッズ {t['decimal_odds']}倍）")
    lines.append(url)
    return receipt,'\n'.join(lines),None if write_request['test_only'] else x_draft(record,url,commit_sha)
