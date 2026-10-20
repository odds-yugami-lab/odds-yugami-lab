from runtime_paths import ROOT, MODULES, MODEL, HISTORY, HISTORY_DIR, BUNDLE, ASSETS
from pathlib import Path
import concurrent.futures,datetime as dt,json,re,sys,urllib.parse,time
sys.path.insert(0,str(MODULES))
from source_bundle import download
import urllib.request,hashlib
from official_results import parse,VENUES
from result_store import text
ROOT=ROOT
DEST=ROOT/'public_cache/official'
DEST.mkdir(parents=True,exist_ok=True)
def collect(spec):
    path=DEST/(spec['result_links'][0].split('/')[-1].replace('.html','')+'_'+spec['date']+'.json')
    if path.exists():return json.loads(path.read_text())
    url=urllib.parse.urljoin('https://www.jra.go.jp',spec['result_links'][0])
    for attempt in range(2):
        try:
            try:
                page,stamp,sha=download(url)
            except UnicodeDecodeError:
                req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
                with urllib.request.urlopen(req,timeout=25) as response:raw=response.read()
                page=raw.decode('cp932')
                stamp=dt.datetime.now(dt.timezone.utc).isoformat();sha=hashlib.sha256(raw).hexdigest()
            tables=[t for t in re.findall(r'<table\b[^>]*>(.*?)</table>',page,re.S) if '着順' in t and '馬名' in t]
            if len(tables)!=1:raise ValueError('Missing official result table')
            table=tables[0]
            venue=next(code for code,name in VENUES.items() if name==spec['venue'])
            meeting=re.search(r'(\d+)回'+spec['venue']+r'(\d+)日',text(table))
            number=re.findall(r'alt="(\d+)レース"',table)
            if not meeting or len(set(number))!=1:raise ValueError('Official identity unavailable')
            race=spec['date'].replace('-','')+venue+f'{int(meeting[1]):02d}{int(meeting[2]):02d}{int(number[0]):02d}'
            result=parse(page,race,url,stamp)
            body=re.search(r'<tbody[^>]*>(.*?)</tbody>',table,re.S).group(1)
            runners=[]
            for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',body,re.S):
                cells=dict(re.findall(r'<td\b[^>]*class="([^"]+)"[^>]*>(.*?)</td>',row,re.S))
                if 'num' not in cells:continue
                pop=text(cells.get('pop',''))
                runners.append({'umaban':int(text(cells['num'])),'name':text(cells['horse']),
                    'finish_status':text(cells['place']),'popularity':int(pop) if pop.isdigit() else None})
            result.update(name=spec['name'],date=spec['date'],grade=spec['grade'],runners=runners)
            path.with_suffix('.html').write_text(page)
            path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print('official',race,flush=True)
            return result
        except Exception as e:
            if attempt: return {'date':spec['date'],'name':spec['name'],'error':str(e),'source_url':url}
specs=json.loads((ROOT/'official_races.json').read_text())['flat_races']
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(collect,specs))
(ROOT/'official_results.json').write_text(json.dumps({'races':results},ensure_ascii=False,indent=2)+'\n')
print('OFFICIAL_DONE',len(results),'errors',sum('error' in r for r in results),flush=True)
