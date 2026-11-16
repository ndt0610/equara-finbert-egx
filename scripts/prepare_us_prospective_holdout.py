"""Create a future, model-blind candidate holdout after its preregistered window."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from backend.evaluation.annotation_schema import BlindAnnotationTaskItem, file_sha256
from backend.services.event_clustering import _canonical_url, content_tokens
from backend.storage.pit_ledger import DEFAULT_PATH, PitLedger, canonical
from backend.universe.calendar_nyse import ET, is_session
from backend.universe.catalog import universe_by_ticker

TICKERS = ('AAPL', 'MSFT', 'NVDA', 'JPM', 'GS', 'XOM', 'CVX', 'UNH', 'LLY', 'CAT')
START, END = date(2026, 11, 16), date(2026, 12, 14)
READY = datetime.combine(END, time(20, 5), ET).astimezone(timezone.utc)
SEED = 'equara-holdout-prospective-2026-v1'
OLD_BATCHES = (Path('artifacts/evaluations/alpaca_first_us_batch.jsonl'),
               Path('artifacts/evaluations/us_eval_20261115_v2/batch.jsonl'))
PREREG = Path('artifacts/evaluations/us_holdout_prospective_2026_v1/preregistration.json')


def parse_time(value):
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return d.astimezone(timezone.utc) if d.tzinfo and d.utcoffset() is not None else None
    except (ValueError, TypeError, AttributeError):
        return None


def eligible(row):
    published, ingested = parse_time(row.get('published_at_utc')), parse_time(row.get('ingested_at_utc'))
    if not published or not ingested or ingested < published:
        return False
    pub, seen = published.astimezone(ET), ingested.astimezone(ET)
    day = pub.date()
    return (row['ticker'] in TICKERS and row['item_type'] != 'SEC_FILING'
            and row['provenance_tier'] == 'LIVE_CAPTURED_PIT'
            and START <= day <= END and is_session(day)
            and seen.date() == day and seen.time() <= time(20))


def overlaps(a, b, aliases):
    """Conservative links are exclusions, not proof of identical events."""
    if a['item_id'] == b['item_id'] or a['headline'].strip().casefold() == b['headline'].strip().casefold():
        return True
    ua, ub = _canonical_url(a.get('source_url')), _canonical_url(b.get('source_url'))
    if ua and ua == ub:
        return True
    if a.get('external_event_key') and a['external_event_key'] == b.get('external_event_key'):
        return True
    pa, pb = parse_time(a['published_at_utc']), parse_time(b['published_at_utc'])
    if a['ticker'] != b['ticker'] or not pa or not pb or abs((pa-pb).total_seconds()) > 7*86400:
        return False
    aa, bb = content_tokens(a['headline'], a['ticker'], aliases), content_tokens(b['headline'], b['ticker'], aliases)
    return bool(len(aa & bb) >= 2 and len(aa & bb) / len(aa | bb) >= .4)


def select(rows, prior, now):
    if now.astimezone(timezone.utc) < READY:
        raise ValueError('HOLDOUT_WINDOW_NOT_COMPLETE')
    catalog = universe_by_ticker()
    aliases = [s for t, v in catalog.items() for s in [t, v['company_name'], *v.get('aliases', [])]]
    # Earliest qualifying observation is fixed to avoid selecting later revisions.
    candidates = {}
    for row in rows:
        if not eligible(row):
            continue
        key = (row['ticker'], row['item_id'])
        old = candidates.get(key)
        if old is None or (row['ingested_at_utc'], row['observation_id']) < (old['ingested_at_utc'], old['observation_id']):
            candidates[key] = row
    groups = defaultdict(list)
    excluded = 0
    for row in candidates.values():
        if any(overlaps(row, item, aliases) for item in prior):
            excluded += 1
            continue
        groups[row['ticker']].append(row)
    selected = []
    for ticker in TICKERS:
        ordered = sorted(groups[ticker], key=lambda x: hashlib.sha256(f"{SEED}|{x['item_id']}|{x['observation_id']}".encode()).hexdigest())
        for row in ordered:
            if sum(x['ticker'] == ticker for x in selected) >= 6:
                break
            if not any(overlaps(row, x, aliases) for x in selected):
                selected.append(row)
    counts = {ticker: sum(x['ticker'] == ticker for x in selected) for ticker in TICKERS}
    return selected, counts, excluded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path, default=DEFAULT_PATH)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-incomplete', action='store_true', help='After the window, explicitly accept fewer than six items per ticker')
    args = parser.parse_args()
    if not args.ledger.is_file():
        parser.error('Ledger does not exist')
    prereg = json.loads(PREREG.read_text(encoding='utf-8'))
    if (prereg['script_sha256'] != file_sha256(Path(__file__)) or
        prereg['policy_sha256'] != file_sha256('docs/US_PROSPECTIVE_HOLDOUT_V1.md') or
        prereg['prior_batch_hashes'] != {p.as_posix():file_sha256(p) for p in OLD_BATCHES}):
        raise ValueError('PREREGISTERED_ARTIFACT_CHANGED')
    if args.output.exists() or args.output.with_suffix(args.output.suffix + '.manifest.json').exists():
        raise FileExistsError('OUTPUT_EXISTS')
    old_tasks = [json.loads(line) for path in OLD_BATCHES for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    ledger = PitLedger(args.ledger)
    try:
        raw = ledger.rows('raw_news_events')
    finally:
        ledger.close()
    by_obs = {x['observation_id']: x for x in raw}
    if any(t['observation_id'] not in by_obs for t in old_tasks):
        raise ValueError('PRIOR_TASK_NOT_IN_LEDGER')
    prior = [by_obs[t['observation_id']] for t in old_tasks]
    selected, counts, excluded = select(raw, prior, datetime.now(timezone.utc))
    if min(counts.values()) < 6 and not args.allow_incomplete:
        print(json.dumps({'status':'INSUFFICIENT_CANDIDATES', 'counts':counts, 'excluded_overlap':excluded}))
        raise SystemExit(2)
    if not selected:
        raise ValueError('NO_ELIGIBLE_ITEMS')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as f:
        for row in selected:
            pub = parse_time(row['published_at_utc']).astimezone(ET)
            year, week, _ = pub.isocalendar()
            window = f"{row['ticker']}:{year}-W{week:02d}"
            task = BlindAnnotationTaskItem(task_id=hashlib.sha256(f"{row['observation_id']}|{row['ticker']}|{window}".encode()).hexdigest()[:24],
                observation_id=row['observation_id'], item_id=row['item_id'], ticker=row['ticker'], session_window_id=window,
                headline=row['headline'], item_type=row['item_type'], source_name=row['source_name'], source_url=row['source_url'],
                published_at_utc=parse_time(row['published_at_utc']), ingested_at_utc=parse_time(row['ingested_at_utc']),
                publication_time_basis=row.get('publication_time_basis'), source_filing_date=row.get('source_filing_date'))
            f.write(canonical(task.model_dump(mode='json'))+'\n')
    manifest = {'status':'CANDIDATE_REQUIRES_INDEPENDENT_EVENT_REVIEW_AND_HUMAN_LABELS',
                'created_at_utc':datetime.now(timezone.utc).isoformat(), 'batch_sha256':file_sha256(args.output),
                'window_start':START.isoformat(), 'window_end':END.isoformat(), 'seed':SEED,
                'counts':counts, 'excluded_prior_overlap':excluded, 'allow_incomplete':args.allow_incomplete,
                'prior_batch_hashes':{p.as_posix():file_sha256(p) for p in OLD_BATCHES},
                'policy_sha256':file_sha256('docs/US_PROSPECTIVE_HOLDOUT_V1.md'),
                'script_sha256':file_sha256(Path(__file__)), 'timing':'LIVE_CAPTURED_PIT; first observation on publication session by 20:00 ET',
                'limitation':'Heuristic overlap exclusion does not prove independence or complete news coverage.'}
    args.output.with_suffix(args.output.suffix+'.manifest.json').write_text(canonical(manifest)+'\n',encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
