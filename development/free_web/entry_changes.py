"""Reconcile entries with separately verified participation information.

No cancellation is inferred from missing weight/odds alone. The caller must
obtain the complete per-horse status snapshot from an authoritative source.
"""
import datetime as dt

def reconcile(rows,snapshot):
    if snapshot.get('verified') is not True or not snapshot.get('source_url'):
        raise ValueError('Verified participation source required')
    stamp=dt.datetime.fromisoformat(snapshot['obtained_at'])
    if stamp.tzinfo is None:raise ValueError('Timezone required')
    if not rows or snapshot['race_code']!=rows[0]['race_code']:
        raise ValueError('Participation race mismatch')
    statuses=snapshot['horse_statuses']
    if set(statuses)!={r['ketto_toroku_bango'] for r in rows}:
        raise ValueError('Incomplete participation snapshot')
    if not set(statuses.values())<={'active','cancelled','excluded'}:
        raise ValueError('Unknown participation status')
    active=[];withdrawn=[]
    for original in rows:
        row=dict(original);status=statuses[row['ketto_toroku_bango']]
        row['participation_status']=status
        (active if status=='active' else withdrawn).append(row)
    if len(active)<3:raise ValueError('Too few active horses')
    for row in active:row['field_size']=len(active)
    return active,withdrawn

def changes(old_rows,new_rows):
    old={r['ketto_toroku_bango']:r for r in old_rows}
    output=[]
    for new in new_rows:
        prior=old.get(new['ketto_toroku_bango'])
        if prior is None:continue
        for field in ['jockey_code','carried_weight_kg','wakuban','umaban',
                      'body_weight_kg','body_weight_change_kg','participation_status']:
            if prior.get(field)!=new.get(field):
                output.append({'horse_id':new['ketto_toroku_bango'],'field':field,
                               'before':prior.get(field),'after':new.get(field)})
    return output
