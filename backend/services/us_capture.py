"""Explicit provider capture; no fixture records can enter the live ledger."""
from __future__ import annotations

from datetime import date, datetime, timedelta, time, timezone
import json
import math

from backend.config import DEFAULT_LOCAL_MODEL_REVISION, MODEL_ID
from backend.providers.transformers_local import TransformersLocalFinBERT
from backend.providers.us_market.sec_edgar_adapter import SecEdgarAdapter
from backend.providers.us_market.us_news_adapter import AlpacaNewsProvider
from backend.providers.us_market.us_price_adapter import AlpacaPriceProvider
from backend.storage.pit_ledger import PitLedger, utc_now
from backend.universe.calendar_nyse import ET, close_at, is_session
from backend.evaluation.phase3_contract import previous_sessions


def _after_baseline(timestamp: str | None, baseline: str | None) -> bool:
    if not timestamp or not baseline:
        return False
    try:
        observed = datetime.fromisoformat(timestamp)
        previous = datetime.fromisoformat(baseline)
        if observed.tzinfo is None or previous.tzinfo is None:
            return False
        return observed.astimezone(timezone.utc) >= previous.astimezone(timezone.utc)
    except ValueError:
        return False


def default_cutoff() -> str:
    return utc_now()


async def capture_sec(ledger: PitLedger, tickers: list[str], adapter: SecEdgarAdapter | None = None) -> dict:
    adapter = adapter or SecEdgarAdapter()
    prior = {x["item_id"] for x in ledger.rows("raw_news_events") if x["source_name"] == "SEC EDGAR"}
    baselines = {}
    for row in ledger.rows("ingestion_runs"):
        if row["source_name"] == "SEC EDGAR":
            for ticker in json.loads(row["config_json"]).get("successful_tickers", []):
                baselines[ticker] = max(baselines.get(ticker, ""), row["completed_at_utc"])
    started = utc_now()
    items, errors = await adapter.fetch(tickers)
    observed_at = utc_now()
    for item in items:
        item["ingested_at_utc"] = observed_at
        if item.get("publication_time_basis") == "EQUARA_FIRST_OBSERVED_UPPER_BOUND":
            item["published_at_utc"] = observed_at
    fresh = [x for x in items if x["item_id"] not in prior]
    grouped = {"LIVE_CAPTURED_PIT": [], "EXPLORATORY_RETROSPECTIVE_NON_PIT": []}
    for item in fresh:
        baseline = baselines.get(item["ticker"])
        baseline_day = datetime.fromisoformat(baseline).astimezone(ET).date().isoformat() if baseline else None
        filing_day = item.get("source_filing_date")
        tier = "LIVE_CAPTURED_PIT" if baseline_day and filing_day and filing_day >= baseline_day else "EXPLORATORY_RETROSPECTIVE_NON_PIT"
        grouped[tier].append(item)
    successful = sorted(set(tickers) - {x["ticker"] for x in errors})
    run_ids = []
    for tier, subset in grouped.items():
        if not subset and tier == "LIVE_CAPTURED_PIT":
            continue
        run = ledger.record_run("SEC EDGAR", tier, "SEC_PUBLIC_ACCESS_RIGHTS_UNREVIEWED",
                                {"items": subset, "errors": errors}, started, utc_now(),
                                {"tickers": tickers, "successful_tickers": successful,
                                 "response_sha256_by_cik": getattr(adapter, "response_hashes", {})},
                                raw_hash_sha256=getattr(adapter, "raw_batch_hash", None))
        run_ids.append(run)
        for item in subset:
            obs = ledger.add_news(run, item)
            ledger.add_score(obs, item["item_id"], MODEL_ID, DEFAULT_LOCAL_MODEL_REVISION,
                             utc_now(), "UNSCORED_STRUCTURAL_FILING")
    return {"run_ids": run_ids, "captured": len(fresh), "errors": errors,
            "captured_live": len(grouped["LIVE_CAPTURED_PIT"]),
            "captured_retrospective": len(grouped["EXPLORATORY_RETROSPECTIVE_NON_PIT"])}


async def capture_alpaca_news(ledger: PitLedger, tickers: list[str],
                              provider: AlpacaNewsProvider | None = None,
                              model: TransformersLocalFinBERT | None = None) -> dict:
    provider = provider or AlpacaNewsProvider()
    prior = {x["item_id"] for x in ledger.rows("raw_news_events")}
    baselines = {}
    for row in ledger.rows("ingestion_runs"):
        if row["source_name"] == "Alpaca News":
            for ticker in json.loads(row["config_json"]).get("successful_tickers", []):
                baselines[ticker] = max(baselines.get(ticker, ""), row["completed_at_utc"])
    started = utc_now()
    items = await provider.fetch(tickers)
    observed_at = utc_now()
    for item in items:
        item["ingested_at_utc"] = observed_at
    fresh = [x for x in items if x["item_id"] not in prior]
    scoreable = [item for item in fresh if item["headline"].strip()]
    if scoreable:
        model = model or TransformersLocalFinBERT()
        scores = await model.classify_many([item["headline"] for item in scoreable])
        if len(scores) != len(scoreable):
            raise ValueError("MODEL_RESULT_COUNT_MISMATCH")
    score_by_id = {item["item_id"]: probabilities for item, probabilities in zip(scoreable, scores if scoreable else [])}
    grouped = {"LIVE_CAPTURED_PIT": [], "EXPLORATORY_RETROSPECTIVE_NON_PIT": []}
    for item in fresh:
        baseline = baselines.get(item["ticker"])
        published = item.get("published_at_utc")
        tier = "LIVE_CAPTURED_PIT" if _after_baseline(published, baseline) else "EXPLORATORY_RETROSPECTIVE_NON_PIT"
        grouped[tier].append(item)
    run_ids = []
    for tier, subset in grouped.items():
        if not subset and tier == "LIVE_CAPTURED_PIT":
            continue
        run = ledger.record_run("Alpaca News", tier, provider.license_tag, subset, started, utc_now(),
                                {"tickers": tickers, "successful_tickers": tickers,
                                 "lookback_calendar_days": getattr(provider, "lookback_calendar_days", None),
                                 "max_pages": getattr(provider, "max_pages", None)},
                                raw_hash_sha256=getattr(provider, "raw_batch_hash", None))
        run_ids.append(run)
        for item in subset:
            obs = ledger.add_news(run, item)
            probabilities = score_by_id.get(item["item_id"])
            ledger.add_score(obs, item["item_id"], model.model_id if probabilities else MODEL_ID,
                             model.revision if probabilities else DEFAULT_LOCAL_MODEL_REVISION,
                             utc_now(), "SCORED" if probabilities else "SKIPPED_INVALID_TEXT", probabilities)
    return {"run_ids": run_ids, "captured": len(fresh), "scored": len(scoreable),
            "captured_live": len(grouped["LIVE_CAPTURED_PIT"]),
            "captured_retrospective": len(grouped["EXPLORATORY_RETROSPECTIVE_NON_PIT"])}


async def capture_alpaca_prices(ledger: PitLedger, tickers: list[str],
                                provider: AlpacaPriceProvider | None = None,
                                end_ts_utc: datetime | None = None) -> dict:
    provider = provider or AlpacaPriceProvider()
    started = utc_now()
    bars = await provider.fetch(tickers, end_ts_utc)
    observed_at = utc_now()
    for bar in bars:
        bar["as_of_ingested_utc"] = observed_at
        bar["adjustment_asof_utc"] = observed_at if bar.get("close_adj") is not None else None
    # Historical bars and retroactive adjusted values are explicitly research-only.
    run = ledger.record_run("Alpaca Prices", "EXPLORATORY_RETROSPECTIVE_NON_PIT",
                            provider.license_tag, bars, started, utc_now(),
                            {"tickers": tickers, "feed": getattr(provider, "feed", None),
                             "requested_end_ts_utc": end_ts_utc.isoformat() if end_ts_utc else None,
                             "effective_end_ts_utc": getattr(provider, "effective_end_ts_utc", None)},
                            raw_hash_sha256=getattr(provider, "raw_batch_hash", None))
    for bar in bars:
        ledger.add_bar(run, bar)
    return {"run_id": run, "captured": len(bars), "provenance_tier": "EXPLORATORY_RETROSPECTIVE_NON_PIT",
            "feed": getattr(provider, "feed", None), "end_ts_utc": getattr(provider, "effective_end_ts_utc", None)}


def latest_completed_nyse_session(observed_at: datetime) -> date:
    """Most recent core session closed long enough for the conservative SIP delay."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    now = observed_at.astimezone(timezone.utc)
    day = now.astimezone(ET).date()
    for _ in range(10):
        if is_session(day) and close_at(day).astimezone(timezone.utc) + timedelta(minutes=20) <= now:
            return day
        day -= timedelta(days=1)
    raise ValueError("NO_RECENT_COMPLETED_NYSE_SESSION")


def price_vintage_readiness(bars: list[dict], ticker: str, latest_day: date,
                            observed_at: datetime, feed: str) -> dict:
    """A live vintage is a complete, same-request adjusted trailing window."""
    try:
        required = {day.isoformat() for day in previous_sessions(latest_day, 20)}
    except ValueError:
        return {"live": False, "reason": "CALENDAR_HISTORY_OUT_OF_RANGE"}
    records = {bar["session_date"]: bar for bar in bars if bar["ticker"] == ticker}
    missing = sorted(required - records.keys())
    valid = all(day in records and all(
        isinstance(records[day].get(key), (int, float)) and math.isfinite(records[day][key]) and records[day][key] > 0
        for key in ("open_adj", "close_adj", "open_raw", "close_raw"))
                for day in required)
    feed_ok = feed.lower() == "sip" and all(records[day].get("data_feed", feed.upper()) == "SIP"
                                             for day in required if day in records)
    now = observed_at.astimezone(timezone.utc)
    cutoff = datetime.combine(latest_day, time(20), ET).astimezone(timezone.utc)
    timely = close_at(latest_day).astimezone(timezone.utc) + timedelta(minutes=20) <= now <= cutoff
    ready = not missing and valid and feed_ok and timely
    reason = ("READY" if ready else "MISSING_TRAILING_SESSIONS" if missing else
              "INVALID_ADJUSTED_BARS" if not valid else "NON_SIP_FEED" if not feed_ok else
              "CAPTURE_OUTSIDE_DECISION_WINDOW")
    return {"live": ready, "reason": reason, "missing_sessions": missing,
            "latest_session": latest_day.isoformat(), "decision_cutoff_utc": cutoff.isoformat()}


async def capture_daily_price_vintage(ledger: PitLedger, tickers: list[str],
                                      provider: AlpacaPriceProvider | None = None) -> dict:
    """Capture 60 calendar days so each current decision has >=21 NYSE sessions."""
    provider = provider or AlpacaPriceProvider()
    started = utc_now()
    fetched = await provider.fetch(tickers, lookback_calendar_days=60)
    observed_at = datetime.now(timezone.utc)
    latest = latest_completed_nyse_session(observed_at)
    bars = [bar for bar in fetched if bar["session_date"] <= latest.isoformat()]
    for bar in bars:
        bar["as_of_ingested_utc"] = observed_at.isoformat()
        bar["adjustment_asof_utc"] = observed_at.isoformat() if bar.get("close_adj") is not None else None
    readiness = {ticker: price_vintage_readiness(bars, ticker, latest, observed_at, provider.feed)
                 for ticker in tickers}
    run_ids = {}
    for tier, subset_tickers in (
        ("LIVE_CAPTURED_PIT", [ticker for ticker in tickers if readiness[ticker]["live"]]),
        ("EXPLORATORY_RETROSPECTIVE_NON_PIT", [ticker for ticker in tickers if not readiness[ticker]["live"]]),
    ):
        subset = [bar for bar in bars if bar["ticker"] in subset_tickers]
        if not subset:
            continue
        run_id = ledger.record_run("Alpaca Prices Daily Vintage", tier, provider.license_tag,
                                   subset, started, utc_now(),
                                   {"tickers": subset_tickers, "requested_tickers": tickers,
                                    "latest_session": latest.isoformat(), "captured_at_utc": observed_at.isoformat(),
                                    "effective_end_ts_utc": provider.effective_end_ts_utc,
                                    "feed": provider.feed, "lookback_calendar_days": 60,
                                    "readiness": {ticker: readiness[ticker] for ticker in subset_tickers}},
                                   raw_hash_sha256=provider.raw_batch_hash)
        run_ids[tier] = run_id
        for bar in subset:
            ledger.add_bar(run_id, bar)
    return {"run_ids": run_ids, "captured": len(bars), "latest_session": latest.isoformat(),
            "captured_at_utc": observed_at.isoformat(), "readiness": readiness}


async def score_pending_alpaca_headlines(ledger: PitLedger,
                                         model: TransformersLocalFinBERT | None = None) -> dict:
    """Append scores for previously captured headlines missing the pinned model revision."""
    scored = {(row["observation_id"], row["model_id"], row["model_revision"])
              for row in ledger.rows("sentiment_scores") if row["scoring_status"] == "SCORED"}
    pending = [row for row in ledger.rows("raw_news_events")
               if row["source_name"] == "Alpaca News" and row["headline"].strip()
               and (row["observation_id"], MODEL_ID, DEFAULT_LOCAL_MODEL_REVISION) not in scored]
    if not pending:
        return {"scored": 0, "pending": 0}
    model = model or TransformersLocalFinBERT()
    if model.model_id != MODEL_ID or model.revision != DEFAULT_LOCAL_MODEL_REVISION:
        raise ValueError("UNREGISTERED_SCORING_MODEL")
    probabilities = await model.classify_many([row["headline"] for row in pending])
    if len(probabilities) != len(pending):
        raise ValueError("MODEL_RESULT_COUNT_MISMATCH")
    for row, values in zip(pending, probabilities):
        ledger.add_score(row["observation_id"], row["item_id"], model.model_id,
                         model.revision, utc_now(), "SCORED", values)
    return {"scored": len(pending), "pending": 0}
