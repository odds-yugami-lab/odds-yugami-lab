"""Settle immutable ticket amounts using actual per-100-yen payouts.

Web parsing is provisional until official results are independently verified.
No final-odds estimate is substituted for actual payouts.
"""
import datetime as dt
import hashlib
import json
import re
from result_store import text

def parse_payouts(page):
    result={'umaren':{},'sanrenpuku':{}}
    names={'馬連':'umaren','3連複':'sanrenpuku','三連複':'sanrenpuku'}
    for table in re.findall(r'<table\b[^>]*>(.*?)</table>',page,re.S):
        if '払戻金' not in table:continue
        current=None
        for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',table,re.S):
            head=re.search(r'<th\b[^>]*>(.*?)</th>',row,re.S)
            if head:current=names.get(text(head.group(1)))
            if current is None:continue
            cells=re.findall(r'<td\b[^>]*>(.*?)</td>',row,re.S)
            if len(cells)!=3:raise ValueError('Unexpected payout columns')
            numbers=text(cells[0]);amount=text(cells[1])
            size=2 if current=='umaren' else 3
            if not re.fullmatch(r'\d+(?:-\d+){'+str(size-1)+'}',numbers):
                raise ValueError('Invalid winning combination')
            nums=sorted(map(int,numbers.split('-')))
            if len(set(nums))!=size or not all(1<=n<=18 for n in nums):raise ValueError('Invalid payout horses')
            if not re.fullmatch(r'[\d,]+円',amount):raise ValueError('Invalid payout amount')
            key=''.join(f'{n:02d}' for n in nums)
            value=int(amount[:-1].replace(',',''))
            if value<=0 or key in result[current]:raise ValueError('Duplicate/invalid payout')
            result[current][key]=value
    if any(not values for values in result.values()):raise ValueError('Both payouts required')
    return result

def settle(record,payout_snapshot,publication=None,test_only=False):
    race=record['race_code']
    if payout_snapshot['race_code']!=race:raise ValueError('Result race mismatch')
    if payout_snapshot.get('official_verified') is not True:raise ValueError('Official payout verification required')
    if not payout_snapshot.get('source_url'):raise ValueError('Result source missing')
    if not test_only:
        if record.get('is_pre_race_prediction') is not True:raise ValueError('Not a pre-race record')
        if not publication or not re.fullmatch(r'[0-9a-f]{40}',publication.get('commit_sha','')):
            raise ValueError('Confirmed publication required')
        start=dt.datetime.fromisoformat(record['race_start_at'])
        saved=dt.datetime.fromisoformat(publication['recorded_at'])
        if start.tzinfo is None or saved.tzinfo is None or saved>start-dt.timedelta(minutes=12):
            raise ValueError('Record was not saved by deadline')
    payouts=payout_snapshot['payouts_per_100_yen']
    if set(payouts)!={'umaren','sanrenpuku'}:raise ValueError('Both payout types required')
    refunds=set(map(int,payout_snapshot.get('refunded_horse_numbers',[])))
    bets=record.get('selected_bets',record.get('tickets'))
    if not bets:raise ValueError('Saved tickets missing')
    seen=set();lines=[];investment=returned=refunded=0
    for bet in bets:
        kind=bet['bet_type'];key=bet['kumiban'];stake=bet['stake']
        size={'umaren':2,'sanrenpuku':3}.get(kind)
        if size is None or not isinstance(key,str) or not re.fullmatch(r'\d{'+str(size*2)+'}',key):
            raise ValueError('Invalid ticket')
        if not isinstance(stake,int) or isinstance(stake,bool) or stake<=0 or stake%100:
            raise ValueError('Invalid stake')
        if (kind,key) in seen:raise ValueError('Duplicate saved ticket')
        seen.add((kind,key));investment+=stake
        numbers=[int(key[i:i+2]) for i in range(0,len(key),2)]
        if len(set(numbers))!=size or numbers!=sorted(numbers) or not all(1<=n<=18 for n in numbers):raise ValueError('Invalid ticket horses')
        refund=stake if refunds.intersection(numbers) else 0
        payout=0 if refund else int(payouts[kind].get(key,0))*(stake//100)
        returned+=payout;refunded+=refund
        lines.append({'bet_type':kind,'kumiban':key,'stake':stake,'payout_yen':payout,'refund_yen':refund})
    if investment!=10000:raise ValueError('Saved budget mismatch')
    gross=returned+refunded
    return {'record_type':'settlement_test' if test_only else 'virtual_bet_settlement',
            'race_code':race,'is_live_performance_record':not test_only,
            'allocation_rule':record.get('allocation_rule'), 'model_package':record.get('model_package'),
            'prediction_commit_sha':publication['commit_sha'] if publication else None,
            'prediction_sha256':hashlib.sha256(json.dumps(record,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
            'investment_yen':investment,'payout_yen':returned,'refund_yen':refunded,
            'profit_yen':gross-investment,'recovery_percent':100*gross/investment,
            'ticket_results':lines,'result_source_url':payout_snapshot['source_url']}
