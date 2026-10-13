"""Assemble future-race inputs. Partial entries never become predictions.

The caller supplies history coverage and independently acquired style evidence.
Missing history coverage/current announcements are operational blockers.
"""
import datetime as dt
import hashlib
import duckdb
from entries import parse,attach_known_sires
from previous_features import calculate as previous
from prior_features import calculate as priors
from entry_changes import reconcile

CURRENT=['keibajo_code','track_code','distance_m','grade_code','field_size',
         'wakuban','umaban','sex_code','age','carried_weight_kg','sire_code',
         'body_weight_kg','body_weight_change_kg','jockey_code','trainer_code','start_time']

def assemble(page,race_id,stage,history_path,feature_spec,style_evidence,
             obtained_at,history_complete_through,pedigree_paths=(),participation_snapshot=None):
    obtained=dt.datetime.fromisoformat(obtained_at)
    if obtained.tzinfo is None:raise ValueError('Timezone required')
    known_date=obtained.astimezone(dt.timezone(dt.timedelta(hours=9))).date()
    rows=parse(page,race_id,stage)
    withdrawn=[]
    if participation_snapshot is not None:
        if stage!='entries':raise ValueError('Participation requires confirmed entries')
        participation_time=dt.datetime.fromisoformat(participation_snapshot['obtained_at'])
        if participation_time.tzinfo is None or participation_time>obtained:
            raise ValueError('Invalid participation time')
        if obtained-participation_time>dt.timedelta(seconds=90):
            raise ValueError('Stale participation information')
        rows,withdrawn=reconcile(rows,participation_snapshot)
    target=dt.date.fromisoformat(rows[0]['race_date'])
    if target<known_date:raise ValueError('Future/current race assembly only')
    coverage=dt.date.fromisoformat(history_complete_through)
    if coverage>known_date:raise ValueError('Future history coverage')
    styles={}
    for evidence in style_evidence:
        key=(evidence['horse_id'],evidence['race_date'])
        if dt.date.fromisoformat(key[1])>=target:raise ValueError('Future style evidence')
        if evidence.get('error') or evidence.get('style') is None:continue
        if not evidence.get('source_url'):raise ValueError('Style source missing')
        if key in styles and styles[key]!=evidence['style']:raise ValueError('Conflicting styles')
        styles[key]=evidence['style']
    with duckdb.connect() as con:
        rows=attach_known_sires(con,rows,[history_path,*pedigree_paths],known_date.isoformat())
        rows=previous(con,history_path,rows,target.isoformat(),styles)
        rows=priors(con,history_path,rows,target.isoformat())
    blockers=[]
    if coverage<known_date-dt.timedelta(days=1):blockers.append('history_coverage_not_current')
    if stage!='entries':blockers.append('confirmed_entries_not_available')
    if stage=='entries' and participation_snapshot is None:
        blockers.append('verified_participation_snapshot_missing')
    numbers=[r['umaban'] for r in rows if r['umaban'] is not None]
    if len(numbers)!=len(set(numbers)):raise ValueError('Duplicate horse numbers')
    for row in rows:
        unresolved=[f for f in CURRENT if row.get(f) is None]
        if row['previous_race_date'] and row['previous_running_style_code'] is None:
            unresolved.append('previous_running_style_code')
        # Zero-start historical rates are legitimately missing model values.
        absent=[f for f in feature_spec['features'] if f not in row]
        if absent:raise ValueError('Missing feature columns: '+str(absent))
        row['unpublished_or_unresolved']=unresolved
        row['prediction_ready']=not unresolved and not blockers
    return {'race_code':rows[0]['race_code'],'features_obtained_at':obtained.isoformat(),
            'entry_page_sha256':hashlib.sha256(page.encode()).hexdigest(),
            'history_complete_through':coverage.isoformat(),
            'feature_count':len(feature_spec['features']),'runners':rows,
            'blockers':blockers,'prediction_ready':all(r['prediction_ready'] for r in rows),
            'is_pre_race_prediction':False,
            'withdrawn_horse_ids':[r['ketto_toroku_bango'] for r in withdrawn],
            'cancellation_handling_verified':participation_snapshot is not None}
