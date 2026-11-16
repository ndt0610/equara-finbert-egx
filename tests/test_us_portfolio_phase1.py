"""Business examples and timing boundaries for the separate US descriptive flow."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.contracts.pit_models import USPortfolioRequest
from backend.services.portfolio_exposure import analyze_us_portfolio
from backend.universe.calendar_nyse import after_close_decision, close_at, next_session
from backend.universe.catalog import load_universe


DECISION = "2026-11-13T22:00:00+00:00"
PRICE = "2026-11-13T21:00:00+00:00"
INGEST = "2026-11-13T21:10:00+00:00"


def holding(ticker, quantity, price):
    return {
        "ticker": ticker, "quantity": str(quantity),
        "price": {
            "ticker": ticker, "price_usd": str(price), "as_of": PRICE,
            "ingested_at": INGEST, "adjustment_method": "manual",
            "provenance_tier": "FIXTURE_DEMO", "source": "test fixture",
        },
    }


def news(item_id, ticker, score, *, title=None, kind="news", event_key=None,
         published="2026-11-13T18:00:00+00:00",
         ingested="2026-11-13T18:05:00+00:00",
         scored="2026-11-13T18:06:00+00:00"):
    positive = max(Decimal(score), Decimal(0))
    negative = max(-Decimal(score), Decimal(0))
    return {
        "item_id": item_id, "ticker": ticker, "title": title or f"DEMO {ticker}",
        "source": "test fixture", "source_kind": kind, "url": None,
        "published_at": published, "ingested_at": ingested, "scored_at": scored,
        "probabilities": {
            "positive": str(positive), "negative": str(negative),
            "neutral": str(1 - positive - negative),
        },
        "event_key": event_key, "provenance_tier": "FIXTURE_DEMO",
    }


def payload(*, holdings=None, items=None, cash=0, changes=None, decision=DECISION):
    return USPortfolioRequest.model_validate({
        "holdings": holdings or [holding("AAPL", 100, 100), holding("MSFT", 100, 25)],
        "cash_usd": str(cash), "decision_at": decision,
        "news": items or [], "scenario_returns": changes or {},
    })


def test_frozen_catalog_has_unique_cik_and_exchange():
    catalog = load_universe()
    assert len(catalog["items"]) == 50
    assert len({x["cik"] for x in catalog["items"]}) == 50
    assert all(len(x["cik"]) == 10 and x["exchange"] in {"Nasdaq", "NYSE"} for x in catalog["items"])
    assert "does not certify" in catalog["source_scope"]


def test_legacy_80_20_and_new_capital_weighted_event_score():
    items = [news(f"a-{i}", "AAPL", "1", title="Same Apple event") for i in range(4)]
    items += [news("b", "MSFT", "-1", title="Microsoft event")]
    items += [news(f"m-{i}", "MARKET", "-1", title=f"Context {i}", kind="context") for i in range(2)]
    result = analyze_us_portfolio(payload(items=items))
    assert Decimal(result["legacy"]["score"]) == Decimal(4) / Decimal("8.8")
    assert Decimal(result["coverage"]) == 1
    assert Decimal(result["covered_portfolio_score"]) == Decimal("0.6")
    assert Decimal(result["legacy"]["effective_ticker_shares"]["AAPL"]) == Decimal("6.4") / Decimal("8.8")
    assert Decimal(result["legacy"]["effective_ticker_shares"]["MSFT"]) == Decimal("0.4") / Decimal("8.8")
    assert Decimal(result["legacy"]["effective_context_share"]) == Decimal(2) / Decimal("8.8")
    assert result["context_news"] == ["m-0", "m-1"]
    assert len([e for e in result["events"] if e["ticker"] == "AAPL"]) == 1


def test_missing_news_is_null_not_neutral_and_coverage_is_reported():
    holdings = [holding("AAPL", 70, 100), holding("MSFT", 30, 100)]
    result = analyze_us_portfolio(payload(holdings=holdings, items=[news("b", "MSFT", "-0.5")]))
    assert result["coverage"] == "0.3"
    assert result["uncovered_equity_ratio"] == "0.7"
    assert result["covered_portfolio_score"] == "-0.5"
    assert result["raw_equity_weighted_score"] == "-0.15"
    a = next(x for x in result["holdings"] if x["ticker"] == "AAPL")
    assert a["news_status"] == "NO_VALID_NEWS"
    assert a["headline_sentiment_score"] is None
    assert a["raw_equity_contribution"] is None
    empty = analyze_us_portfolio(payload(holdings=holdings))
    assert empty["covered_portfolio_score"] is None
    assert empty["coverage"] == "0"


def test_duplicate_articles_do_not_increase_event_or_issuer_weight():
    base = payload(items=[news("a", "AAPL", "0.8"), news("b", "MSFT", "-0.5")])
    duplicated = payload(items=[news(f"a-{i}", "AAPL", "0.8") for i in range(6)] +
                         [news("b", "MSFT", "-0.5")])
    a = analyze_us_portfolio(base)
    b = analyze_us_portfolio(duplicated)
    assert a["covered_portfolio_score"] == b["covered_portfolio_score"]
    assert b["holdings"][0]["event_count"] == 1
    assert a["legacy"]["score"] != b["legacy"]["score"]


def test_first_mention_and_preferred_source_are_separate():
    items = [
        news("first", "AAPL", "0.5", title="First report", event_key="event-1",
             ingested="2026-11-13T18:05:00+00:00", scored="2026-11-13T18:06:00+00:00"),
        news("filing", "AAPL", "0.8", title="SEC filing", kind="sec_filing", event_key="event-1",
             ingested="2026-11-13T18:15:00+00:00", scored="2026-11-13T18:16:00+00:00"),
    ]
    event = next(e for e in analyze_us_portfolio(payload(items=items))["events"] if e["ticker"] == "AAPL")
    assert event["first_item_id"] == "first"
    assert event["primary_item_id"] == "filing"
    assert Decimal(event["first_item_score"]) == Decimal("0.5")


def test_conflicting_event_headlines_are_visible():
    items = [
        news("a", "AAPL", "0.8", title="Same event"),
        news("b", "AAPL", "-0.8", title="Same event"),
    ]
    result = analyze_us_portfolio(payload(items=items))
    assert result["events"][0]["conflicting_headlines"] is True
    assert result["holdings"][0]["conflicting_news"] is True
    assert result["holdings"][0]["headline_sentiment_score"] == "0.0"


def test_scenario_cash_and_corrected_arithmetic():
    result = analyze_us_portfolio(payload(changes={"AAPL": "0.05", "MSFT": "-0.04"}))
    assert result["scenario"]["change_usd"] == "400.00"
    assert result["scenario"]["new_nav_usd"] == "12900.00"
    assert Decimal(result["scenario"]["total_return"]) == Decimal("0.032")
    with_cash = analyze_us_portfolio(payload(cash=2500, changes={"AAPL": "0.05", "MSFT": "-0.04"}))
    assert with_cash["scenario"]["change_usd"] == "400.00"
    assert Decimal(with_cash["scenario"]["total_return"]) == Decimal(400) / Decimal(15000)
    assert Decimal(with_cash["scenario"]["equity_return"]) == Decimal("0.032")


def test_news_after_close_cannot_enter_earlier_decision():
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    early_decision = datetime(2026, 5, 12, 16, 0, tzinfo=et)
    later_decision = datetime(2026, 5, 12, 16, 30, tzinfo=et)
    postclose = news("late", "AAPL", "0.8", published="2026-05-12T15:00:00-04:00",
                     ingested="2026-05-12T16:05:00-04:00",
                     scored="2026-05-12T16:06:00-04:00")
    prices = [holding("AAPL", 1, 100)]
    prices[0]["price"]["as_of"] = "2026-05-12T16:00:00-04:00"
    prices[0]["price"]["ingested_at"] = "2026-05-12T16:00:00-04:00"
    before = analyze_us_portfolio(payload(holdings=prices, items=[postclose], decision=early_decision))
    after = analyze_us_portfolio(payload(holdings=prices, items=[postclose], decision=later_decision))
    assert before["coverage"] == "0"
    assert before["rejected_news"][0]["reason"] == "NOT_AVAILABLE_AT_DECISION"
    assert after["coverage"] == "1"
    assert after["schedule"]["earliest_core_execution_session"] == "2026-05-13"


def test_timestamp_and_future_price_are_rejected():
    bad = news("naive", "AAPL", "0.8", ingested="2026-11-13T18:05:00",
               scored="2026-11-13T18:06:00+00:00")
    with pytest.raises(ValueError, match="TIMEZONE_REQUIRED"):
        payload(items=[bad])
    future = [holding("AAPL", 1, 100)]
    future[0]["price"]["ingested_at"] = "2026-11-13T22:01:00+00:00"
    with pytest.raises(ValueError, match="PRICE_NOT_AVAILABLE_AT_DECISION"):
        analyze_us_portfolio(payload(holdings=future))


def test_published_holidays_early_close_and_unknown_year_fail_closed():
    assert close_at(datetime(2026, 11, 27, tzinfo=timezone.utc).date()).hour == 13
    assert next_session(datetime(2026, 11, 25, tzinfo=timezone.utc).date()).isoformat() == "2026-11-27"
    with pytest.raises(ValueError, match="DECISION_MUST_FOLLOW_COMPLETED_SESSION"):
        after_close_decision(datetime.fromisoformat("2026-11-27T12:59:00-05:00"))
    assert after_close_decision(datetime.fromisoformat("2026-11-27T13:05:00-05:00"))["earliest_core_execution_session"] == "2026-11-30"
    assert next_session(datetime(2026, 12, 31, tzinfo=timezone.utc).date()).isoformat() == "2027-01-04"
    with pytest.raises(ValueError, match="NYSE_CALENDAR_OUT_OF_RANGE"):
        next_session(datetime(2028, 12, 29, tzinfo=timezone.utc).date())


def test_api_fixture_response_and_invalid_input():
    with TestClient(app) as client:
        fixture = client.get("/api/v3/us/fixture").json()
        assert fixture["news"][0]["provenance_tier"] == "FIXTURE_DEMO"
        assert len(client.get("/api/v3/us/universe").json()["items"]) == 50
        request = {
            "holdings": [holding("AAPL", 100, 100), holding("MSFT", 100, 25)],
            "cash_usd": "0", "decision_at": fixture["decision_at"],
            "news": fixture["news"], "scenario_returns": {"AAPL": "0.05", "MSFT": "-0.04"},
        }
        response = client.post("/api/v3/us/portfolio/exposure", json=request)
        assert response.status_code == 200
        assert response.json()["scenario"]["change_usd"] == "400.00"
        request["holdings"][0]["ticker"] = "UNKNOWN"
        assert client.post("/api/v3/us/portfolio/exposure", json=request).status_code == 422
