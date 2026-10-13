"""JRA-VAN corner-based running style; unresolved data stays None.

Definition: https://jra-van.jp/dlb/sdv/sdk/JV-Data4901.pdf pp.11,32.
Straight-course timing rule is not implemented and must be handled separately.
"""
import re
from result_store import parse_result, text

def classify(corners, starters, status):
    if status in {"取消","除外","中止"}:
        return "0"
    if len(corners)<2:
        return None
    if any(x==1 for x in corners[:-1]):
        return "1"
    if corners[-1]<=4:
        return "2"
    if starters>=8 and corners[-1]*3<=starters*2:
        return "3"
    return "4"

def parse_styles(page,race_id):
    results=parse_result(page,race_id)
    starters=sum(r['finish_text'] not in {"取消","除外"} for r in results)
    table=[t for t in re.findall(r'<table\b[^>]*>(.*?)</table>',page,re.S) if '着順' in t and '調教師' in t][0]
    body=re.search(r'<tbody\b[^>]*>(.*?)</tbody>',table,re.S).group(1)
    order={}
    for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>',body,re.S):
        cells=re.findall(r'<td\b[^>]*>(.*?)</td>',tr,re.S)
        horse=re.search(r'/keiba/directory/horse/(\d+)/',cells[3]).group(1)
        prefix=text(re.sub(r'<p\b[^>]*>.*?</p>','',cells[5],flags=re.S))
        corners=list(map(int,prefix.split('-'))) if re.fullmatch(r'\d{1,2}(?:-\d{1,2})+',prefix) else []
        if any(x<1 or x>starters for x in corners):
            raise ValueError('Invalid corner positions')
        order[horse]=corners
    return {r['horse_id']:{'corners':order[r['horse_id']],
            'running_style_code':classify(order[r['horse_id']],starters,r['finish_text'])}
            for r in results}
