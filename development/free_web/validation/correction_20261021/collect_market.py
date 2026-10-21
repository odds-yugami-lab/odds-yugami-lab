"""Historical WIN odds only. A final-odds source is never a live snapshot."""
import argparse, concurrent.futures, datetime as dt, hashlib, json, re, sys, time
from pathlib import Path

def parse_market(page, race_code, text):
    web_id=race_code[2:4]+race_code[8:]
    if '/keiba/race/denma/'+web_id not in page:raise ValueError('Page race ID mismatch')
    date=re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日',text(page))
    if not date or dt.date(*map(int,date.groups())).strftime('%Y%m%d')!=race_code[:8]:
        raise ValueError('Page race date mismatch')
    tables=[t for t in re.findall(r'<table\b[^>]*>(.*?)</table>',page,re.S) if 'horsePedigree' in t]
    if len(tables)!=1:raise ValueError('Ambiguous entry table')
    body=re.search(r'<tbody\b[^>]*>(.*?)</tbody>',tables[0],re.S)
    if not body:raise ValueError('Missing table body')
    rows=[];withdrawn=[];unpriced=[]
    for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>',body.group(1),re.S):
        cells=re.findall(r'<td\b[^>]*>(.*?)</td>',tr,re.S)
        if len(cells)!=8:raise ValueError('Wrong entry column count')
        number=text(cells[1]);horse=re.findall(r'/directory/horse/(\d+)/',cells[2])
        if not number.isdigit() or not 1<=int(number)<=18 or len(set(horse))!=1:raise ValueError('Invalid horse identity')
        odds=re.sub(r'\s+','',text(cells[-1]))
        match=re.fullmatch(r'(\d+)\(([0-9]+(?:\.[0-9]+)?)\)',odds)
        if not match:
            if '取消' in text(tr) or '除外' in text(tr) or 'hr-tableTr--cancel' in tr:
                withdrawn.append(int(number));continue
            if re.fullmatch(r'\d+\(\*+\)',odds):
                # Asterisks alone do not prove withdrawal. The caller must
                # independently compare the official/eligible active field.
                unpriced.append({'umaban':int(number),'horse_id':horse[0],'source_text':odds});continue
            raise ValueError('Missing WIN odds: '+str((number,odds)))
        popularity,price=int(match[1]),float(match[2])
        if price<1 or popularity<1:raise ValueError('Invalid WIN odds')
        anchor=re.search(r'<a\b[^>]*href="/keiba/directory/horse/\d+/"[^>]*>(.*?)</a>',cells[2],re.S)
        if not anchor:raise ValueError('Horse name anchor missing')
        rows.append({'umaban':int(number),'horse_id':horse[0],'horse_name':text(anchor[1]),'popularity':popularity,'decimal_win_odds':price})
    if len(rows)<3 or len({r['umaban'] for r in rows})!=len(rows):raise ValueError('Invalid field')
    return {'race_code':race_code,'historical_final_odds':True,'usable_for_live':False,'runners':rows,'withdrawn':withdrawn,'unpriced':unpriced}

def main(workdir, modules, mode):
    root=Path(workdir);sys.path.insert(0,modules)
    from source_bundle import download
    from result_store import text
    if mode=='2025':
        targets=root/'private_assets/predictions_2025.json'
        if not targets.exists():targets=root/'private_assets/market_targets_2025.json'
        horses=json.loads(targets.read_text())
    else:
        horses=json.loads(Path('bias_20261020/horse_predictions_all.json').read_text())
    codes=sorted({r['race_code'] for r in horses})
    def collect(code):
        path=root/'cache/market'/(code+'.json');url='https://sports.yahoo.co.jp/keiba/race/denma/'+code[2:4]+code[8:]
        if path.exists():return {'race_code':code,'status':'cached'}
        try:
            error=None
            for attempt in range(3):
                try:
                    page,stamp,sha=download(url)
                    record=parse_market(page,code,text)
                    record.update(source_url=url,retrieved_at=stamp,page_sha256=sha)
                    path.write_text(json.dumps(record,ensure_ascii=False)+'\n')
                    error=None;break
                except Exception as e:error=e
            if error:raise error
            print('MARKET',code,len(record['runners']),flush=True)
            return {'race_code':code,'status':'ok'}
        except Exception as e:
            print('MARKET_FAILED',code,str(e),flush=True)
            return {'race_code':code,'status':'failed','error':str(e)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(collect,codes))
    (root/'public'/('market_collection_'+mode+'.json')).write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    print('MARKET_COMPLETE',mode,len(results),'FAILURES',sum(r['status']=='failed' for r in results),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('workdir');p.add_argument('modules');p.add_argument('mode',choices=['2025','2026']);a=p.parse_args()
    main(a.workdir,a.modules,a.mode)
