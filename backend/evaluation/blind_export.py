"""Deterministic stratified sampling from the raw ledger; no scores are read."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.evaluation.annotation_schema import BlindAnnotationTaskItem, file_sha256, read_jsonl
from backend.storage.pit_ledger import PitLedger, canonical
from backend.universe.calendar_nyse import ET
from backend.universe.catalog import universe_by_ticker
from backend.services.event_clustering import cluster_events_v2, content_tokens


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def export_blind_annotation_batch(ledger: PitLedger, output_path: str | Path, cutoff_utc: str,
                                  limit: int = 200, tickers: list[str] | None = None,
                                  include_structural: bool = False, lookback_days: int = 30,
                                  seed: str = "us-annotation-v1", exclude_item_ids: set[str] | None = None,
                                  exclude_headlines: set[str] | None = None) -> dict:
    if not 1 <= limit <= 1000 or not 1 <= lookback_days <= 365:
        raise ValueError("INVALID_SAMPLE_CONFIGURATION")
    cutoff = _aware(cutoff_utc)
    chosen = {}
    for row in ledger.rows("raw_news_events"):
        if exclude_item_ids and row['item_id'] in exclude_item_ids:
            continue
        if exclude_headlines and row['headline'].strip().casefold() in exclude_headlines:
            continue
        if tickers and row["ticker"] not in tickers:
            continue
        if row["item_type"] == "SEC_FILING" and not include_structural:
            continue
        try:
            ingested, published = _aware(row["ingested_at_utc"]), _aware(row["published_at_utc"])
        except (TypeError, ValueError):
            continue
        if ingested > cutoff or published > cutoff or published < cutoff - timedelta(days=lookback_days):
            continue
        source_day = row.get("source_filing_date")
        if source_day and not ((cutoff.astimezone(ET).date() - timedelta(days=lookback_days)).isoformat()
                               <= source_day <= cutoff.astimezone(ET).date().isoformat()):
            continue
        key = row["ticker"], row["item_id"]
        old = chosen.get(key)
        if old is None or (ingested, row["observation_id"]) > (_aware(old["ingested_at_utc"]), old["observation_id"]):
            chosen[key] = row
    strata = defaultdict(list)
    for row in chosen.values():
        source_day = row.get("source_filing_date")
        published = _aware(row["published_at_utc"]).astimezone(ET)
        year, week, _ = published.isocalendar()
        window = f"{row['ticker']}:{year}-W{week:02d}"
        task_id = hashlib.sha256(f"{row['observation_id']}|{row['ticker']}|{window}".encode()).hexdigest()[:24]
        task = BlindAnnotationTaskItem(
            task_id=task_id, observation_id=row["observation_id"], item_id=row["item_id"],
            ticker=row["ticker"], session_window_id=window, headline=row["headline"],
            item_type=row["item_type"], source_name=row["source_name"], source_url=row["source_url"],
            published_at_utc=_aware(row["published_at_utc"]), ingested_at_utc=_aware(row["ingested_at_utc"]),
            publication_time_basis=row.get("publication_time_basis"), source_filing_date=source_day)
        strata[(task.ticker, task.item_type)].append(task)
    queues = {}
    for key, tasks in strata.items():
        queues[key] = deque(sorted(tasks, key=lambda task: hashlib.sha256(f"{seed}|{task.task_id}".encode()).hexdigest()))
    sampled = []
    while len(sampled) < limit and any(queues.values()):
        for key in sorted(queues):
            if queues[key] and len(sampled) < limit:
                sampled.append(queues[key].popleft())
    if not sampled:
        raise ValueError("NO_ELIGIBLE_ANNOTATION_ITEMS")
    target = Path(output_path)
    manifest_path = target.with_suffix(target.suffix + ".manifest.json")
    if target.exists() or manifest_path.exists():
        raise FileExistsError("ANNOTATION_BATCH_ALREADY_EXISTS")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        for task in sampled:
            handle.write(canonical(task.model_dump(mode="json")) + "\n")
    manifest = {"batch_sha256": file_sha256(target), "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "cutoff_utc": cutoff.isoformat(), "limit": limit, "selected_count": len(sampled),
                "lookback_days": lookback_days, "include_structural": include_structural,
                "tickers": sorted(tickers or []), "seed": seed,
                "excluded_item_count": len(exclude_item_ids or ()),
                "excluded_headline_count": len(exclude_headlines or ()),
                "selection": "round_robin_ticker_item_type; hash_rank_within_stratum"}
    with manifest_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical(manifest) + "\n")
    return {"tasks_path": str(target), "manifest_path": str(manifest_path), **manifest}


def split_blind_batch(batch_path: str | Path, dev_path: str | Path, holdout_path: str | Path,
                      holdout_fraction: float = .25, seed: str = "us-group-split-v1", ledger: PitLedger | None = None,
                      event_groups_path: str | Path | None = None) -> dict:
    """Keep verified story and event groups intact across development and holdout."""
    if not .1 <= holdout_fraction <= .5:
        raise ValueError("INVALID_HOLDOUT_FRACTION")
    tasks = read_jsonl(batch_path, BlindAnnotationTaskItem)
    raw = {r['observation_id']: r for r in ledger.rows('raw_news_events')} if ledger else {}
    if ledger:
        for task in tasks:
            record = raw.get(task.observation_id)
            if record is None or (record['item_id'], record['ticker'], record['headline']) != (task.item_id, task.ticker, task.headline):
                raise ValueError('TASK_LEDGER_BINDING_MISMATCH')
    parent = list(range(len(tasks)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def union(i, j):
        a, b = root(i), root(j)
        if a != b:
            parent[b] = a
    catalog = universe_by_ticker()
    aliases = [name for ticker, row in catalog.items() for name in [ticker, row['company_name'], *row.get('aliases', [])]]
    def tokens(task):
        return content_tokens(task.headline, task.ticker, aliases)
    token_sets = [tokens(task) for task in tasks]
    for i, a in enumerate(tasks):
        for j in range(i):
            b = tasks[j]
            linked = a.item_id == b.item_id or a.observation_id == b.observation_id
            if a.item_type == b.item_type == 'SEC_FILING' and a.ticker == b.ticker and a.source_filing_date:
                linked |= a.source_filing_date == b.source_filing_date and a.headline == b.headline
            if a.item_type != 'SEC_FILING' and b.item_type != 'SEC_FILING':
                x, y = raw.get(a.observation_id, {}).get('external_event_key'), raw.get(b.observation_id, {}).get('external_event_key')
                ta, tb = token_sets[i], token_sets[j]
                linked |= bool(x and x == y) or bool(a.source_url and a.source_url == b.source_url)
                linked |= a.headline.strip().casefold() == b.headline.strip().casefold()
                linked |= bool(ta and tb and ta == tb)
            if linked:
                union(i, j)
    payload = [{**t.model_dump(mode='json'), 'item_id': t.task_id, 'external_event_key': raw.get(t.observation_id, {}).get('external_event_key')} for t in tasks]
    ticker_aliases = {k: [k, v['company_name'], *v.get('aliases', [])] for k,v in catalog.items()}
    by_id = {t.task_id: i for i,t in enumerate(tasks)}
    for cluster in cluster_events_v2(payload, ticker_aliases):
        members = cluster['item_ids']
        for member in members[1:]:
            union(by_id[members[0]], by_id[member])
    if event_groups_path is not None:
        groups_data = json.loads(Path(event_groups_path).read_text(encoding='utf-8'))
        if not isinstance(groups_data, list) or any(not isinstance(group, list) or len(group) < 2 for group in groups_data):
            raise ValueError('INVALID_EVENT_GROUPS')
        for group in groups_data:
            if len(set(group)) != len(group) or any(task_id not in by_id for task_id in group):
                raise ValueError('INVALID_EVENT_GROUPS')
            for task_id in group[1:]:
                union(by_id[group[0]], by_id[task_id])
    groups = defaultdict(list)
    for i, task in enumerate(tasks):
        groups[root(i)].append(task)
    if len(groups) < 2:
        raise ValueError("NEED_TWO_OR_MORE_SESSION_WINDOWS")
    ordered = sorted(groups, key=lambda group: hashlib.sha256((seed + '|' + '|'.join(sorted(t.task_id for t in groups[group]))).encode()).hexdigest())
    target_size = max(1, round(len(tasks) * holdout_fraction))
    holdout_windows = set()
    held_count = 0
    for window in ordered[:-1]:
        if held_count >= target_size:
            break
        holdout_windows.add(window)
        held_count += len(groups[window])
    assignments = {"CALIBRATION_DEV": [task for group in groups if group not in holdout_windows for task in groups[group]],
                   "LOCKED_HOLDOUT": [task for group in groups if group in holdout_windows for task in groups[group]]}
    if not .20 <= len(assignments["LOCKED_HOLDOUT"]) / len(tasks) <= .30:
        raise ValueError("INSUFFICIENT_HOLDOUT_COMPONENTS")
    dev, hold = assignments['CALIBRATION_DEV'], assignments['LOCKED_HOLDOUT']
    nonsec = lambda group: [t for t in group if t.item_type != 'SEC_FILING']
    for key in ('item_id', 'observation_id'):
        if {getattr(t, key) for t in dev} & {getattr(t, key) for t in hold}:
            raise ValueError('SPLIT_LEAKAGE_DETECTED')
    for key in (lambda t: t.headline.strip().casefold(), lambda t: t.source_url,
                lambda t: raw.get(t.observation_id, {}).get('external_event_key'),
                lambda t: frozenset(tokens(t))):
        if ({key(t) for t in nonsec(dev)} & {key(t) for t in nonsec(hold)}) - {None, '', frozenset()}:
            raise ValueError('SPLIT_LEAKAGE_DETECTED')
    if nonsec(tasks) and not .20 <= len(nonsec(hold)) / len(nonsec(tasks)) <= .30:
        raise ValueError('INSUFFICIENT_HOLDOUT_NEWS')
    if event_groups_path is not None:
        dev_ids = {task.task_id for task in dev}
        for group in groups_data:
            if 0 < len(dev_ids.intersection(group)) < len(group):
                raise ValueError('SPLIT_LEAKAGE_DETECTED')
    parent_hash = file_sha256(batch_path)
    for path in (dev_path, holdout_path):
        candidate = Path(path)
        if candidate.exists() or candidate.with_suffix(candidate.suffix + ".manifest.json").exists():
            raise FileExistsError("ANNOTATION_SPLIT_ALREADY_EXISTS")
    output = {}
    for split, path in (("CALIBRATION_DEV", dev_path), ("LOCKED_HOLDOUT", holdout_path)):
        target = Path(path)
        sidecar = target.with_suffix(target.suffix + ".manifest.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            for task in assignments[split]:
                handle.write(canonical(task.model_dump(mode="json")) + "\n")
        metadata = {"split_type": split, "parent_batch_sha256": parent_hash,
                    "batch_sha256": file_sha256(target), "selected_count": len(assignments[split]),
                    "seed": seed, "grouping": "connected_components_article_event_verified_groups",
                    "event_groups_sha256": file_sha256(event_groups_path) if event_groups_path else None,
                    "holdout_fraction_target": holdout_fraction}
        with sidecar.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical(metadata) + "\n")
        output[split] = {"tasks_path": str(target), "manifest_path": str(sidecar), **metadata}
    return output
