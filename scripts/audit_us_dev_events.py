"""Generate high-recall candidate event pairs within the frozen dev sample."""
import argparse
import collections
import csv
import json
import math
from datetime import datetime
from pathlib import Path

from backend.services.event_clustering import GENERIC_EVENT_WORDS, _canonical_url, _pair_reason, content_tokens
from backend.storage.pit_ledger import PitLedger
from backend.universe.catalog import universe_by_ticker

STOP = GENERIC_EVENT_WORDS | {'says','said','s','2026','2027','2028','1','2','3','inc','incorporated',
    'announces','announced','thursday','wednesday','tuesday','monday','friday','today','group','company','plc','new','year','q3'}
FIELDS = ['ticker','a_id','b_id','a_title','b_title','a_time','b_time','hours','cos','jaccard','common','rule','a_url','b_url']


def find_candidates(tasks, labels, raw, catalog):
    docs=[]
    for row in tasks:
        c=catalog[row['ticker']]
        aliases=[row['ticker'],c['company_name'],*c.get('aliases',[])]
        docs.append(content_tokens(row['headline'],row['ticker'],aliases)-STOP)
    df=collections.Counter(token for document in docs for token in document)
    weights={token:math.log((len(tasks)+1)/(count+1))+1 for token,count in df.items()}
    out=[]
    for i,x in enumerate(tasks):
        for j in range(i):
            y=tasks[j]
            if x['ticker']!=y['ticker'] or any(labels[t['task_id']]['target_relevance_ai']=='INCIDENTAL_OR_NOISE' for t in (x,y)):
                continue
            u,v=docs[i],docs[j]; common=u&v
            hours=abs((datetime.fromisoformat(x['published_at_utc'])-datetime.fromisoformat(y['published_at_utc'])).total_seconds())/3600
            jaccard=len(common)/len(u|v) if u and v else 0
            containment=len(common)/min(len(u),len(v)) if u and v else 0
            denominator=math.sqrt(sum(weights[z]**2 for z in u)*sum(weights[z]**2 for z in v))
            cosine=sum(weights[z]**2 for z in common)/denominator if denominator else 0
            xx={**x,'item_id':x['task_id'],'external_event_key':raw[x['observation_id']]['external_event_key']}
            yy={**y,'item_id':y['task_id'],'external_event_key':raw[y['observation_id']]['external_event_key']}
            c=catalog[x['ticker']];aliases=[x['ticker'],c['company_name'],*c.get('aliases',[])]
            reason=_pair_reason(xx,yy,aliases)
            same_url=_canonical_url(x.get('source_url')) and _canonical_url(x.get('source_url'))==_canonical_url(y.get('source_url'))
            if reason or (len(common)>=2 and (cosine>=.25 or containment>=.55)) or (same_url and '/quote/' not in (x.get('source_url') or '')):
                out.append({'ticker':x['ticker'],'a_id':x['task_id'],'b_id':y['task_id'],'a_title':x['headline'],'b_title':y['headline'],
                    'a_time':x['published_at_utc'],'b_time':y['published_at_utc'],'hours':round(hours,1),'cos':round(cosine,3),
                    'jaccard':round(jaccard,3),'common':' '.join(sorted(common)),'rule':reason or '',
                    'a_url':x.get('source_url') or '', 'b_url':y.get('source_url') or ''})
    return sorted(out,key=lambda row:(-row['cos'],row['hours']))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks',required=True);parser.add_argument('--labels',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    tasks=[json.loads(line) for line in Path(args.tasks).read_text(encoding='utf8').splitlines() if line.strip()]
    with Path(args.labels).open(encoding='utf-8-sig',newline='') as f:
        labels={row['task_id']:row for row in csv.DictReader(f)}
    if len(labels)!=len(tasks) or {x['task_id'] for x in tasks}!=set(labels):
        raise ValueError('TASK_BINDING_MISMATCH')
    ledger=PitLedger()
    try: raw={row['observation_id']:row for row in ledger.rows('raw_news_events')}
    finally: ledger.close()
    rows=find_candidates(tasks,labels,raw,universe_by_ticker())
    with Path(args.output).open('x',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)
    print(json.dumps({'candidate_pairs':len(rows),'output':args.output}))


if __name__=='__main__': main()
