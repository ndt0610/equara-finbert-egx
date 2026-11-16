"""Capture a coherent price vintage, SEC filings and Alpaca news after NYSE close."""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.services.us_capture import (capture_alpaca_news, capture_daily_price_vintage,
                                         capture_sec, score_pending_alpaca_headlines)
from backend.services.us_daily_health import ledger_readiness_summary
from backend.storage.pit_ledger import DEFAULT_PATH, PitLedger
from backend.universe.catalog import universe_by_ticker
from backend.providers.us_market.us_news_adapter import AlpacaNewsProvider


async def _capture(ledger: PitLedger, tickers: list[str], include_sec: bool = True, news_lookback_days: int = 7, news_only: bool = False) -> dict:
    results = {}
    operations = [
        # Price eligibility expires at the 20:00 ET decision cutoff; collect it first.
        ("alpaca_price_vintage", lambda: capture_daily_price_vintage(ledger, tickers)),
        ("alpaca_news", lambda: capture_alpaca_news(ledger, tickers, provider=AlpacaNewsProvider(lookback_calendar_days=news_lookback_days))),
        ("pending_finbert", lambda: score_pending_alpaca_headlines(ledger)),
    ]
    if news_only:
        operations = [op for op in operations if op[0] != 'alpaca_price_vintage']
    if include_sec and not news_only:
        operations.insert(1, ("sec", lambda: capture_sec(ledger, tickers)))
    for name, operation in operations:
        try:
            results[name] = {"status": "OK", "result": await operation()}
        except Exception as exc:
            # Leave other independent sources running; no credentials or response body in output.
            results[name] = {"status": "ERROR", "error_type": type(exc).__name__}
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", required=True, help="Comma-separated Equara US ticker symbols")
    parser.add_argument("--ledger", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--health-only", action="store_true", help="Read ledger without network requests")
    parser.add_argument("--skip-sec", action="store_true", help="Use existing SEC capture; run Alpaca stages only")
    parser.add_argument("--news-only", action="store_true", help="Capture Alpaca news and score pending headlines only")
    parser.add_argument("--news-lookback-days", type=int, choices=range(1, 366), default=7, metavar="DAYS")
    parser.add_argument("--output", type=Path, help="JSON status path; defaults differ for capture and health-only")
    args = parser.parse_args()
    tickers = [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()]
    catalog = universe_by_ticker()
    if not tickers or len(set(tickers)) != len(tickers) or any(ticker not in catalog for ticker in tickers):
        parser.error("Tickers must be distinct members of the Equara US universe")
    output_path = args.output or Path("artifacts/phase3/daily_health_status.json" if args.health_only
                                      else "artifacts/phase3/daily_capture_status.json")
    ledger = PitLedger(args.ledger)
    try:
        stages = {} if args.health_only else asyncio.run(_capture(ledger, tickers, include_sec=not args.skip_sec, news_lookback_days=args.news_lookback_days, news_only=args.news_only))
        health = ledger_readiness_summary(ledger, tickers)
    finally:
        ledger.close()
    result = {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "mode": "HEALTH_ONLY" if args.health_only else "DAILY_CAPTURE",
              "stages": stages, "ledger_readiness": health}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Latest NYSE session: {health['latest_completed_session']}")
    print(f"Complete live 21-session samples: {health['live_complete_21_session_samples']}")
    print(f"Consecutive complete sessions, all tickers: {health['consecutive_complete_live_sessions_all_tickers']}")
    print(f"Matured labels H=1/H=5: {health['matured_labels_live_features']}")
    print(f"Missing latest vintage: {[row['ticker'] for row in health['missing_latest_price_vintage']]}")
    for name, stage in stages.items():
        print(f"{name}: {stage['status']}" + (f" ({stage['error_type']})" if stage['status'] == 'ERROR' else ""))
    print(f"Status JSON: {output_path}")
    if any(stage["status"] == "ERROR" for stage in stages.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
