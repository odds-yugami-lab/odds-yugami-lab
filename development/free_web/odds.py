"""Read all listed public pair/triple odds; reject incomplete snapshots."""
import itertools
import re
from result_store import text

def parse(page,race_id,kind,horses):
    if kind not in {'umaren','sanrenpuku'}:
        raise ValueError('Unsupported bet type')
    size=2 if kind=='umaren' else 3
    rows=[]
    for table in re.findall(r'<table\b[^>]*>(.*?)</table>',page,re.S):
        head=re.search(r'<thead\b[^>]*>(.*?)</thead>',table,re.S)
        body=re.search(r'<tbody\b[^>]*>(.*?)</tbody>',table,re.S)
        if not head or not body:continue
        label=text(head.group(1))
        if not re.fullmatch(r'\d+(?:－\d+)?',label):continue
        prefix=tuple(map(int,label.split('－')))
        if len(prefix)!=size-1:continue
        for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>',body.group(1),re.S):
            th=re.search(r'<th\b[^>]*>(.*?)</th>',tr,re.S)
            td=re.search(r'<td\b[^>]*>(.*?)</td>',tr,re.S)
            if not th or not td or not text(th.group(1)).isdigit():continue
            numbers=prefix+(int(text(th.group(1))),)
            if not set(numbers)<=set(horses):continue
            value=text(td.group(1))
            if not re.fullmatch(r'\d+(?:\.\d+)?',value) or float(value)<1:
                raise ValueError('Missing or invalid active odds')
            rows.append({'race_code':race_id,'bet_type':kind,
                         'kumiban':''.join(f'{n:02d}' for n in numbers),
                         'decimal_odds':float(value)})
    expected={''.join(f'{n:02d}' for n in combo) for combo in itertools.combinations(sorted(horses),size)}
    actual=[r['kumiban'] for r in rows]
    if len(actual)!=len(set(actual)) or set(actual)!=expected:
        raise ValueError('Incomplete or duplicate odds snapshot')
    plain=text(page)
    update=re.search(r'(\d{4}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2})\s*更新',plain)
    if not update:
        raise ValueError('Source update time unavailable')
    return {'rows':rows,'source_updated_at_text':update.group(1),
            'status':'final_postrace' if '確定オッズ' in plain else 'unverified_live',
            'combination_count':len(rows)}
