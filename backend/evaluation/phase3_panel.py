"""Build ticker/decision-date rows from the append-only ledger without hiding provenance."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

import numpy as np

from backend.config import DEFAULT_LOCAL_MODEL_REVISION, MODEL_ID
from backend.evaluation.phase3_contract import (
    AGGREGATION_VARIANTS, HORIZONS, advance_sessions, aggregate_event_variants,
    previous_sessions, realized_return,
)
from backend.services.event_clustering import cluster_events_v2
from backend.services.target_relevance import experimental_relevance
from backend.storage.pit_ledger import PitLedger, digest
from backend.universe.calendar_nyse import ET, close_at, is_session
from backend.universe.catalog import universe_by_ticker


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return None
    return result.astimezone(timezone.utc) if result.tzinfo and result.utcoffset() is not None else None


def _valid_positive(value: object) -> bool:
    try:
        number = float(value)
    except (ValueError, TypeError):
        return False
    return math.isfinite(number) and number > 0


def _valid_bar(row: dict, asof: datetime) -> bool:
    ingested, adjusted = _parse_time(row["as_of_ingested_utc"]), _parse_time(row["adjustment_asof_utc"])
    return (ingested is not None and adjusted is not None and ingested <= asof and adjusted <= asof
            and _valid_positive(row.get("open_adj")) and _valid_positive(row.get("close_adj")))


def _choose_history_vintage(bars: dict[tuple[str, str], list[dict]], ticker: str,
                            days: list[date], cutoff: datetime, run_asof: datetime,
                            allow_retrospective: bool) -> list[dict] | None:
    """All 21 adjusted bars must come from one captured adjustment regime."""
    asof = run_asof if allow_retrospective else cutoff
    by_run = defaultdict(dict)
    for day in days:
        for row in bars.get((ticker, day.isoformat()), []):
            if _valid_bar(row, asof):
                old = by_run[row["run_id"]].get(day)
                if old is None or (row["as_of_ingested_utc"], row["bar_id"]) > (old["as_of_ingested_utc"], old["bar_id"]):
                    by_run[row["run_id"]][day] = row
    candidates = []
    for run_id, per_day in by_run.items():
        if len(per_day) != len(days):
            continue
        history = [per_day[day] for day in days]
        if len({row["adjustment_asof_utc"] for row in history}) != 1:
            continue
        vintage_time = max(_parse_time(row["as_of_ingested_utc"]) for row in history)
        candidates.append((vintage_time, run_id, history))
    return max(candidates, key=lambda value: (value[0], value[1]))[2] if candidates else None


def _choose_outcome_vintage(bars: dict[tuple[str, str], list[dict]], ticker: str,
                            entry_day: date, exit_day: date, run_asof: datetime) -> tuple[dict, dict, datetime] | None:
    """Anchor the label to the first complete post-exit two-bar vintage."""
    exit_close = close_at(exit_day).astimezone(timezone.utc)
    entries = {row["run_id"]: row for row in bars.get((ticker, entry_day.isoformat()), [])
               if _valid_bar(row, run_asof) and row["data_feed"] == "SIP"}
    candidates = []
    for exit_bar in bars.get((ticker, exit_day.isoformat()), []):
        if (not _valid_bar(exit_bar, run_asof) or exit_bar["data_feed"] != "SIP"
                or _parse_time(exit_bar["as_of_ingested_utc"]) < exit_close):
            continue
        entry = entries.get(exit_bar["run_id"])
        if entry is None or entry["adjustment_asof_utc"] != exit_bar["adjustment_asof_utc"]:
            continue
        available = max(_parse_time(entry["as_of_ingested_utc"]), _parse_time(entry["adjustment_asof_utc"]),
                        _parse_time(exit_bar["as_of_ingested_utc"]), _parse_time(exit_bar["adjustment_asof_utc"]))
        candidates.append((available, exit_bar["run_id"], entry, exit_bar))
    if not candidates:
        return None
    available, _, entry, exit_bar = min(candidates, key=lambda value: (value[0], value[1]))
    return entry, exit_bar, available


def _price_features(history: list[dict]) -> dict:
    closes = np.array([float(row["close_adj"]) for row in history], dtype=float)
    changes = closes[1:] / closes[:-1] - 1
    magnitudes = np.abs(changes)
    return {"r_minus_1": float(changes[-1]), "r_minus_5": float(closes[-1] / closes[-6] - 1),
            "r_minus_20": float(closes[-1] / closes[-21] - 1),
            "sigma_20": float(np.std(changes, ddof=0)),
            "b75_abs_return": float(np.quantile(magnitudes, .75)),
            "e90_abs_return": float(np.quantile(magnitudes, .90))}


def _events_at_decision(news_rows: list[dict], score_rows: dict[str, list[dict]],
                        ticker: str, cutoff: datetime, model_id: str, revision: str,
                        allow_retrospective: bool, window_days: int) -> tuple[list[dict], set[str]]:
    selected = {}
    tiers = set()
    decision_day = cutoff.astimezone(ET).date()
    first_filing_day = decision_day - timedelta(days=window_days)
    for row in news_rows:
        if row["ticker"] != ticker:
            continue
        published, ingested = _parse_time(row["published_at_utc"]), _parse_time(row["ingested_at_utc"])
        if published is None or ingested is None:
            continue
        filing_day = row.get("source_filing_date")
        if filing_day and not (first_filing_day.isoformat() <= filing_day <= decision_day.isoformat()):
            continue
        # SEC first-observed timestamps are honest PiT upper bounds. A diagnostic
        # replay may instead place an old filing by its date-only SEC metadata.
        date_only_sec_replay = (allow_retrospective and row["item_type"] == "SEC_FILING"
                                and row.get("publication_time_basis") == "EQUARA_FIRST_OBSERVED_UPPER_BOUND"
                                and bool(filing_day) and published > cutoff)
        if not date_only_sec_replay and (published > cutoff or published < cutoff - timedelta(days=window_days)):
            continue
        if ingested > cutoff and not allow_retrospective:
            continue
        old = selected.get(row["item_id"])
        if old is None or (row["ingested_at_utc"], row["observation_id"]) > (old["ingested_at_utc"], old["observation_id"]):
            selected[row["item_id"]] = row
    events = []
    for item_id, row in sorted(selected.items()):
        ingested = _parse_time(row["ingested_at_utc"])
        tiers.add(row["provenance_tier"])
        if ingested > cutoff or (row["item_type"] == "SEC_FILING"
                                and row.get("publication_time_basis") == "EQUARA_FIRST_OBSERVED_UPPER_BOUND"
                                and _parse_time(row["published_at_utc"]) > cutoff):
            tiers.add("RETROSPECTIVE_EVENT_USED")
        scores = [score for score in score_rows.get(row["observation_id"], [])
                  if score["model_id"] == model_id and score["model_revision"] == revision
                  and _parse_time(score["scored_at_utc"]) is not None
                  and (_parse_time(score["scored_at_utc"]) <= cutoff or allow_retrospective)]
        score = max(scores, key=lambda score: (score["scored_at_utc"], score["score_id"])) if scores else None
        if score is not None and _parse_time(score["scored_at_utc"]) > cutoff:
            tiers.add("RETROSPECTIVE_SCORE_USED")
        events.append({"item_id": item_id, "ticker": ticker, "headline": row["headline"],
                       "item_type": row["item_type"], "external_event_key": row["external_event_key"],
                       "published_at_utc": row["published_at_utc"], "ingested_at_utc": row["ingested_at_utc"],
                       "scoring_status": score["scoring_status"] if score else "PENDING_SCORE",
                       "scored_at_utc": score["scored_at_utc"] if score else None,
                       "net_score": score["net_score"] if score and score["scoring_status"] == "SCORED" else None,
                       "provenance_tier": row["provenance_tier"]})
    return events, tiers


def build_phase3_panel(ledger: PitLedger, tickers: list[str], start_session: str,
                       end_session: str, horizon: int = 5, cutoff_et: str = "20:00",
                       allow_retrospective_diagnostic: bool = False,
                       window_days: int = 7, model_id: str = MODEL_ID,
                       model_revision: str = DEFAULT_LOCAL_MODEL_REVISION,
                       relevance_filter: str = 'none') -> dict:
    if relevance_filter not in {'none', 'exclude_noise', 'direct_only'}:
        raise ValueError('INVALID_RELEVANCE_FILTER')
    if relevance_filter != 'none' and not allow_retrospective_diagnostic:
        raise ValueError('UNVALIDATED_RELEVANCE_REQUIRES_DIAGNOSTIC')
    if horizon not in HORIZONS or not 1 <= window_days <= 30:
        raise ValueError("UNREGISTERED_HORIZON_OR_WINDOW")
    catalog = universe_by_ticker()
    if not tickers or len(tickers) != len(set(tickers)) or any(ticker not in catalog for ticker in tickers):
        raise ValueError("INVALID_TICKERS")
    first, last = date.fromisoformat(start_session), date.fromisoformat(end_session)
    if first > last:
        raise ValueError("INVALID_DATE_RANGE")
    cutoff_clock = time.fromisoformat(cutoff_et)
    price_rows = defaultdict(list)
    for row in ledger.rows("eod_price_bars"):
        price_rows[(row["ticker"], row["session_date"])].append(row)
    news_rows = ledger.rows("raw_news_events")
    score_rows = defaultdict(list)
    for row in ledger.rows("sentiment_scores"):
        score_rows[row["observation_id"]].append(row)
    all_sessions = []
    cursor = first
    while cursor <= last:
        if is_session(cursor):
            all_sessions.append(cursor)
        cursor += timedelta(days=1)
    rows, excluded = [], []
    run_asof = datetime.now(timezone.utc)
    for index, day in enumerate(all_sessions):
        cutoff = datetime.combine(day, cutoff_clock, ET).astimezone(timezone.utc)
        if cutoff < close_at(day).astimezone(timezone.utc):
            raise ValueError("DECISION_BEFORE_NYSE_CLOSE")
        if cutoff > run_asof:
            continue
        try:
            history_days = previous_sessions(day, 20)
            entry_day, exit_day = advance_sessions(day, 1), advance_sessions(day, horizon)
        except ValueError:
            excluded.append({"decision_date": day.isoformat(), "reason": "CALENDAR_OUT_OF_RANGE"})
            continue
        for ticker in tickers:
            history = _choose_history_vintage(price_rows, ticker, history_days, cutoff, run_asof,
                                              allow_retrospective_diagnostic)
            if history is None:
                excluded.append({"ticker": ticker, "decision_date": day.isoformat(), "reason": "MISSING_COHERENT_ASOF_PRICE_VINTAGE"})
                continue
            outcome = _choose_outcome_vintage(price_rows, ticker, entry_day, exit_day, run_asof)
            if outcome is None:
                excluded.append({"ticker": ticker, "decision_date": day.isoformat(), "reason": "MISSING_ANCHORED_OUTCOME_VINTAGE"})
                continue
            entry, exit_bar, label_available = outcome
            price = _price_features(history)
            events, event_tiers = _events_at_decision(news_rows, score_rows, ticker, cutoff,
                                                      model_id, model_revision,
                                                      allow_retrospective_diagnostic, window_days)
            if relevance_filter != 'none':
                filtered = []
                for event in events:
                    label = experimental_relevance(event['headline'], ticker, event['item_type'], catalog)
                    if relevance_filter == 'exclude_noise' and label != 'POSSIBLE_NOISE_UNVERIFIED':
                        filtered.append(event)
                    elif relevance_filter == 'direct_only' and label in {'DIRECT_MENTION_UNVERIFIED', 'UNSCORABLE_ADMIN_FILING'}:
                        filtered.append(event)
                events = filtered
            aliases = {ticker: [catalog[ticker]["company_name"], *catalog[ticker].get("aliases", []), ticker]}
            clusters = cluster_events_v2(events, aliases)
            variants = aggregate_event_variants(clusters, {item["item_id"]: item for item in events}, cutoff,
                                                strict_pit=not allow_retrospective_diagnostic)
            tiers = {bar["provenance_tier"] for bar in history} | event_tiers
            if any(_parse_time(bar["as_of_ingested_utc"]) > cutoff or _parse_time(bar["adjustment_asof_utc"]) > cutoff for bar in history):
                tiers.add("RETROSPECTIVE_PRICE_USED")
            if any(bar["data_feed"] != "SIP" for bar in history):
                tiers.add("UNVERIFIED_OR_IEX_PRICE_FEED")
            gross = realized_return(float(entry["open_adj"]), float(exit_bar["close_adj"]))["gross"]
            row = {"ticker": ticker, "decision_index": index, "decision_date": day.isoformat(),
                   "decision_cutoff_utc": cutoff.isoformat(), "entry_session": entry_day.isoformat(),
                   "exit_session": exit_day.isoformat(), "entry_open_adj": entry["open_adj"],
                   "entry_close_adj": entry["close_adj"],
                   "exit_close_adj": exit_bar["close_adj"], "gross_return": gross,
                   "close_next_to_exit_gross_return": realized_return(float(entry["close_adj"]),
                                                                        float(exit_bar["close_adj"]))["gross"],
                   "net_return_10bps": gross - .002, "label_available_at_utc": label_available.isoformat(),
                   "price_features": price,
                   "event_features": {"has_valid_event": int(bool(events)), "event_cluster_count": len(clusters),
                                      "has_sec_filing": int(any(item["item_type"] == "SEC_FILING" for item in events)),
                                      "scored_cluster_count": sum(cluster["score"] is not None for cluster in clusters),
                                      "aggregate_scores": variants},
                   "feature_provenance_tiers": sorted(tiers),
                   "feature_bar_ids": [bar["bar_id"] for bar in history],
                   "feature_price_vintage_run_id": history[0]["run_id"],
                   "outcome_bar_ids": [entry["bar_id"], exit_bar["bar_id"]],
                   "outcome_vintage_run_id": entry["run_id"],
                   "outcome_provenance_tier": entry["provenance_tier"],
                   "event_item_ids": [item["item_id"] for item in events]}
            rows.append(row)
    panel = {"feature": "equara-us-phase3-panel-v1", "tickers": tickers,
             "start_session": start_session, "end_session": end_session, "horizon": horizon,
             "cutoff_et": cutoff_et, "model_id": model_id, "model_revision": model_revision,
             "allow_retrospective_diagnostic": allow_retrospective_diagnostic,
             "window_days": window_days, "relevance_filter": relevance_filter, "rows": rows, "excluded": excluded,
             "run_asof_utc": run_asof.isoformat()}
    panel["panel_sha256"] = digest({key: value for key, value in panel.items() if key not in {"run_asof_utc", "panel_sha256", "excluded"}})
    return panel
