"""Read-only readiness checks for the incremental US capture ledger."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from backend.evaluation.phase3_contract import advance_sessions, previous_sessions
from backend.evaluation.phase3_panel import _choose_history_vintage, _choose_outcome_vintage
from backend.services.us_capture import latest_completed_nyse_session
from backend.storage.pit_ledger import PitLedger
from backend.universe.calendar_nyse import ET, is_session


def ledger_readiness_summary(ledger: PitLedger, tickers: list[str],
                             observed_at: datetime | None = None) -> dict:
    now = observed_at or datetime.now(timezone.utc)
    latest = latest_completed_nyse_session(now)
    bars = defaultdict(list)
    for row in ledger.rows("eod_price_bars"):
        bars[(row["ticker"], row["session_date"])].append(row)
    captured_days = sorted({date.fromisoformat(day) for ticker, day in bars if ticker in tickers
                            and date.fromisoformat(day) <= latest})
    first = captured_days[0] if captured_days else latest
    sessions = []
    cursor = first
    while cursor <= latest:
        if is_session(cursor):
            sessions.append(cursor)
        cursor += timedelta(days=1)
    complete = {ticker: [] for ticker in tickers}
    matured = {"1": 0, "5": 0}
    missing = []
    for day in sessions:
        cutoff = datetime.combine(day, time(20), ET).astimezone(timezone.utc)
        asof = min(cutoff, now)
        try:
            days = previous_sessions(day, 20)
        except ValueError:
            continue
        for ticker in tickers:
            history = _choose_history_vintage(bars, ticker, days, asof, now, False)
            ready = bool(history and all(row["provenance_tier"] == "LIVE_CAPTURED_PIT"
                                         and row["data_feed"] == "SIP" for row in history))
            if day == latest and not ready:
                missing.append({"ticker": ticker, "session": day.isoformat(),
                                "reason": "MISSING_COMPLETE_LIVE_SIP_PRICE_VINTAGE"})
            if not ready:
                continue
            complete[ticker].append(day)
            for horizon in (1, 5):
                try:
                    entry, exit_day = advance_sessions(day, 1), advance_sessions(day, horizon)
                except ValueError:
                    continue
                if _choose_outcome_vintage(bars, ticker, entry, exit_day, now):
                    matured[str(horizon)] += 1
    consecutive = {}
    for ticker, days in complete.items():
        present = set(days)
        count = 0
        for day in reversed(sessions):
            if day not in present:
                break
            count += 1
        consecutive[ticker] = count
    return {"latest_completed_session": latest.isoformat(),
            "requested_tickers": tickers,
            "live_complete_21_session_samples": sum(map(len, complete.values())),
            "consecutive_complete_live_sessions_by_ticker": consecutive,
            "consecutive_complete_live_sessions_all_tickers": min(consecutive.values()) if consecutive else 0,
            "matured_labels_live_features": matured,
            "missing_latest_price_vintage": missing,
            "note": "A complete price vintage does not prove news capture coverage or an executable open fill."}
