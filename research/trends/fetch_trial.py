"""One-off metadata trial. No daily state updates or publication."""
import argparse,json,time,urllib.request,urllib.parse,urllib.error,xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime,timezone
N={'a':'http://www.w3.org/2005/Atom','o':'http://a9.com/-/spec/opensearch/1.1/','x':'http://arxiv.org/schemas/atom'}
OUT=Path('research/trends/raw'); OUT.mkdir(parents=True,exist_ok=True)
from datetime import timedelta,date
from analyze_trial import shift_months
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--until-exclusive', default=(datetime.now(timezone.utc).date()-timedelta(days=2)).isoformat())
parser.add_argument('--category', default='cond-mat.str-el')
parser.add_argument('--framework', type=Path, default=Path('research/trends/framework.json'))
args=parser.parse_args()
config=json.loads(args.framework.read_text())
window_end=date.fromisoformat(args.until_exclusive)
bounds=[shift_months(window_end,i).strftime('%Y%m%d') for i in range(-12*config['history_years'],1)]
papers={}; queries=[]
for lo,hi in zip(bounds,bounds[1:]):
 end=(datetime.strptime(hi,'%Y%m%d')-timedelta(days=1)).strftime('%Y%m%d')
 q=f'cat:{args.category} AND submittedDate:[{lo}0000 TO {end}2359]'
 offset=0; expected=None; batch=set()
 while True:
  params={'search_query':q,'start':offset,'max_results':1000,'sortBy':'submittedDate','sortOrder':'ascending'}
  url='https://export.arxiv.org/api/query?'+urllib.parse.urlencode(params)
  req=urllib.request.Request(url,headers={'User-Agent':'arxiv-trend-trial/0.1 (https://github.com/RintaroMasaoka/daily-arxiv)','Accept':'application/atom+xml'})
  for attempt in range(4):
   try:
    with urllib.request.urlopen(req,timeout=90) as r: body=r.read()
    root=ET.fromstring(body)
    if root.tag!='{'+N['a']+'}feed': raise ValueError('Not an Atom feed')
    total=int(root.find('o:totalResults',N).text)
    break
   except (urllib.error.URLError,ET.ParseError,ValueError) as e:
    print(f'ERROR {lo} attempt {attempt+1}: {e}',flush=True)
    if attempt==3: raise
    time.sleep([15,45,120][attempt])
  (OUT/f'{lo}-{offset}.xml').write_bytes(body)
  if expected is None: expected=total
  if expected!=total: raise ValueError('Result count changed during pagination')
  entries=root.findall('a:entry',N)
  for e in entries:
   def t(tag): return ' '.join((e.findtext(tag,'',N) or '').split())
   rid=t('a:id')
   if '/abs/' not in rid: raise ValueError('Unexpected entry: '+rid)
   aid=rid.split('/abs/')[-1].rsplit('v',1)[0]
   pub=t('a:published'); primary=e.find('x:primary_category',N)
   p={'arxiv_id':aid,'title':t('a:title'),'abstract':t('a:summary'),'published':pub,'updated':t('a:updated'),'primary_category':primary.get('term') if primary is not None else None,'categories':[c.get('term') for c in e.findall('a:category',N)],'authors':[a.findtext('a:name','',N) for a in e.findall('a:author',N)]}
   if not pub: raise ValueError('Missing first-submission date')
   batch.add(aid); papers[aid]=p
  print(f'{lo} offset={offset} total={total} entries={len(entries)} unique={len(batch)}',flush=True)
  offset+=len(entries)
  time.sleep(3.2)
  if offset>=total: break
  if not entries: raise ValueError('Incomplete pagination')
 if len(batch)!=expected: raise ValueError(f'Incomplete slice: {len(batch)} != {expected}')
 queries.append({'from':lo,'until_exclusive':hi,'query':q,'total_results':expected,'unique_fetched':len(batch)})
result={'fetched_at':datetime.now(timezone.utc).isoformat(),'target_from':shift_months(window_end,-config['recent_months']).isoformat(),'target_until_exclusive':window_end.isoformat(),'context_from':shift_months(window_end,-12*config['history_years']).isoformat(),'category':args.category,'queries':queries,'papers':sorted(papers.values(),key=lambda p:p['published'])}
Path('research/trends/corpus.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(f'COMPLETE {len(papers)} unique papers',flush=True)
