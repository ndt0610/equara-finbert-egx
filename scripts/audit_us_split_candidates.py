"""Flag possible cross-split story overlap without assigning human gold labels."""
import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from backend.services.event_clustering import content_tokens, _canonical_url
from backend.universe.catalog import universe_by_ticker
from backend.storage.pit_ledger import PitLedger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dev', required=True)
    parser.add_argument('--holdout', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    read = lambda p: [json.loads(x) for x in Path(p).read_text(encoding='utf-8').splitlines() if x.strip()]
    dev, hold = read(args.dev), read(args.holdout)
    db = PitLedger()
    try:
        raw = {r['observation_id']: r for r in db.rows('raw_news_events')}
    finally:
        db.close()
    catalog = universe_by_ticker()
    aliases = [s for ticker, x in catalog.items() for s in [ticker,x['company_name'],*x.get('aliases',[])]]
    results = []
    for a in dev:
        ta = content_tokens(a['headline'], a['ticker'], aliases)
        for b in hold:
            tb = content_tokens(b['headline'], b['ticker'], aliases)
            shared = ta & tb
            score = len(shared)/len(ta|tb) if ta and tb else 0
            hours = abs((datetime.fromisoformat(a['published_at_utc'])-datetime.fromisoformat(b['published_at_utc'])).total_seconds())/3600
            url_a, url_b = _canonical_url(a.get('source_url')), _canonical_url(b.get('source_url'))
            key_a, key_b = raw[a['observation_id']].get('external_event_key'), raw[b['observation_id']].get('external_event_key')
            exact = (a['headline'].casefold().strip() == b['headline'].casefold().strip() or
                     bool(url_a and url_a == url_b) or bool(key_a and key_a == key_b))
            if exact or (hours <= 168 and len(shared) >= 3 and score >= .30):
                results.append({'dev_id':a['task_id'],'holdout_id':b['task_id'], 'dev_ticker':a['ticker'],
                                'holdout_ticker':b['ticker'],'dev_headline':a['headline'],'holdout_headline':b['headline'],
                                'hours_apart':round(hours,1),'jaccard':round(score,3),'hard_link':exact,'review':'UNREVIEWED'})
    results.sort(key=lambda x:(not x['hard_link'], -x['jaccard'],x['hours_apart']))
    path=Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8-sig',newline='') as f:
        fields=['dev_id','holdout_id','dev_ticker','holdout_ticker','dev_headline','holdout_headline','hours_apart','jaccard','hard_link','review']
        writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader();writer.writerows(results)
    print(f'Candidate pairs: {len(results)}; hard links: {sum(x["hard_link"] for x in results)}; {path}')


if __name__ == '__main__': main()
