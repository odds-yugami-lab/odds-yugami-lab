"""User-approved 2026-10-23 budget ceiling, max30, exact minimum stakes."""
from balanced_A_v3_explicit import _ordered_outcomes
from cap30_ceiling_allocator import allocate
VERSION='cap30_budget_ceiling_E50_v1_20261023'

def allocate_balanced(combo,horses):
    scale=float((combo.ai_probability*combo.decimal_odds).max()*10000)
    return allocate(combo,horses.umaban.tolist(),_ordered_outcomes(horses),
        expected_payout_scale=scale,time_limit=30.,mip_relative_gap=.01)

def validate_record_budget(record):
    tickets=record.get('tickets',[]);total=sum(t['stake'] for t in tickets)
    if record.get('allocation_rule')==VERSION:
        if record.get('schema_version',0)<7 or record.get('budget_limit_yen')!=10000:
            raise ValueError('Missing budget-ceiling policy metadata')
        if not 1<=len(tickets)<=30 or not 0<total<=10000 or record.get('total_stake_yen')!=total:
            raise ValueError('Invalid capped budget or ticket count')
        if record.get('unspent_yen')!=10000-total:raise ValueError('Unspent budget mismatch')
        for t in tickets:
            import math
            required=100*max(1,math.ceil(100/t['decimal_odds']-1e-12))
            if t['stake']!=required:raise ValueError('Extra stake above minimum is forbidden')
    elif total!=10000 or record.get('total_stake_yen',10000)!=10000:
        raise ValueError('Legacy saved budget mismatch')
    return total
