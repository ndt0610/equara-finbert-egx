"""Descriptive US portfolio exposure, legacy comparison and price scenarios."""
from collections import defaultdict
from decimal import Decimal

from backend.contracts.pit_models import NewsItem, USPortfolioRequest
from backend.services.event_clustering import cluster_events, headline_score
from backend.universe.calendar_nyse import after_close_decision
from backend.universe.catalog import universe_by_ticker


def _number(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _eligible_news(request: USPortfolioRequest) -> tuple[list[NewsItem], list[dict]]:
    accepted, rejected = [], []
    known_ids = set()
    held_tickers = {holding.ticker for holding in request.holdings}
    for item in request.news:
        reason = None
        if item.item_id in known_ids:
            reason = "DUPLICATE_ITEM_ID"
        known_ids.add(item.item_id)
        if item.source_kind != "context" and item.ticker not in held_tickers:
            reason = reason or "TICKER_NOT_HELD"
        if item.probabilities is None or item.scored_at is None:
            reason = reason or "NO_SCORE"
        elif item.published_at is None:
            reason = reason or "UNKNOWN_PUBLICATION_TIME"
        elif item.published_at > item.ingested_at or item.ingested_at > item.scored_at:
            reason = reason or "INCONSISTENT_TIMESTAMPS"
        elif max(item.published_at, item.ingested_at, item.scored_at) > request.decision_at:
            reason = reason or "NOT_AVAILABLE_AT_DECISION"
        if reason:
            rejected.append({"item_id": item.item_id, "reason": reason})
        else:
            accepted.append(item)
    return accepted, rejected


def _legacy(items: list[NewsItem], weights: dict[str, Decimal]) -> dict:
    k = Decimal(len(weights))
    rows = []
    for item in items:
        if item.source_kind == "context":
            q = Decimal(1)
        elif item.ticker in weights:
            q = k * weights[item.ticker]
        else:
            continue
        rows.append((item, q, headline_score(item)))
    denominator = sum((q for _, q, _ in rows), Decimal(0))
    numerator = sum((q * score for _, q, score in rows), Decimal(0))
    effective = {
        ticker: _number(sum((q for item, q, _ in rows if item.ticker == ticker and item.source_kind != "context"), Decimal(0)) / denominator)
        if denominator else None for ticker in weights
    }
    macro_share = sum((q for item, q, _ in rows if item.source_kind == "context"), Decimal(0))
    return {
        "status": "legacy_headline_weighting_comparison",
        "score": _number(numerator / denominator) if denominator else None,
        "effective_ticker_shares": effective,
        "effective_context_share": _number(macro_share / denominator) if denominator else None,
        "headline_count": len(rows),
        "note": "Same eligible input batch. Every headline is a vote; context has q=1. This is not a capital-weighted issuer mean.",
    }


def analyze_us_portfolio(request: USPortfolioRequest) -> dict:
    catalog = universe_by_ticker()
    if any(h.ticker not in catalog for h in request.holdings):
        raise ValueError("TICKER_OUTSIDE_FROZEN_UNIVERSE")
    schedule = after_close_decision(request.decision_at)
    for holding in request.holdings:
        if holding.price.as_of > request.decision_at or holding.price.ingested_at > request.decision_at:
            raise ValueError("PRICE_NOT_AVAILABLE_AT_DECISION")
    accepted, rejected = _eligible_news(request)
    clusters = cluster_events(accepted)
    cluster_map = defaultdict(list)
    for cluster in clusters:
        cluster_map[cluster.ticker].append(cluster)
    equity = sum((h.quantity * h.price.price_usd for h in request.holdings), Decimal(0))
    total = equity + request.cash_usd
    if equity <= 0 or total <= 0:
        raise ValueError("POSITIVE_EQUITY_VALUE_REQUIRED")
    weights = {h.ticker: h.quantity * h.price.price_usd / equity for h in request.holdings}
    covered = Decimal(0)
    raw = Decimal(0)
    rows = []
    for holding in request.holdings:
        ticker = holding.ticker
        events = cluster_map[ticker]
        score = sum((x.score for x in events), Decimal(0)) / Decimal(len(events)) if events else None
        event_scores = [x.score for x in events]
        conflict = any(x.conflicting_headlines for x in events) or (
            any(x > 0 for x in event_scores) and any(x < 0 for x in event_scores)
        )
        weight = weights[ticker]
        value = holding.quantity * holding.price.price_usd
        contribution = weight * score if score is not None else None
        if score is not None:
            covered += weight
            raw += contribution
        change = request.scenario_returns.get(ticker, Decimal(0))
        rows.append({
            "ticker": ticker, "company_name": catalog[ticker]["company_name"],
            "quantity": _number(holding.quantity), "reference_price_usd": _number(holding.price.price_usd),
            "price_as_of": holding.price.as_of.isoformat(), "price_source": holding.price.source,
            "price_provenance_tier": holding.price.provenance_tier,
            "position_value_usd": _number(value), "equity_weight": _number(weight),
            "nav_weight": _number(value / total),
            "news_status": "COVERED" if events else "NO_VALID_NEWS",
            "conflicting_news": conflict,
            "event_count": len(events), "headline_sentiment_score": _number(score),
            "raw_equity_contribution": _number(contribution),
            "scenario_return": _number(change),
            "scenario_new_value_usd": _number(value * (1 + change)),
            "scenario_change_usd": _number(value * change),
        })
    scenario_change = sum(
        (h.quantity * h.price.price_usd * request.scenario_returns.get(h.ticker, Decimal(0))
         for h in request.holdings), Decimal(0)
    )
    context = [x for x in accepted if x.source_kind == "context"]
    news_rows = [{
        "item_id": x.item_id, "ticker": x.ticker, "title": x.title, "source": x.source,
        "source_kind": x.source_kind, "url": x.url,
        "published_at": x.published_at.isoformat() if x.published_at else None,
        "ingested_at": x.ingested_at.isoformat(), "scored_at": x.scored_at.isoformat() if x.scored_at else None,
        "score": _number(headline_score(x)), "probabilities": {k: _number(v) for k, v in x.probabilities.items()},
        "provenance_tier": x.provenance_tier,
    } for x in accepted]
    tiers = sorted({x.provenance_tier for x in accepted} | {h.price.provenance_tier for h in request.holdings})
    return {
        "feature": "us-portfolio-exposure-v1", "market": "US", "currency": "USD",
        "status": "descriptive_only", "decision_at": request.decision_at.isoformat(),
        "schedule": schedule,
        "data_provenance_tiers": tiers,
        "provenance_warning": "Tiers and timestamps are caller-supplied; this endpoint does not verify provider rights or authenticate historical availability.",
        "equity_value_usd": _number(equity), "cash_usd": _number(request.cash_usd),
        "nav_usd": _number(total), "cash_nav_weight": _number(request.cash_usd / total),
        "coverage": _number(covered), "uncovered_equity_ratio": _number(1 - covered),
        "covered_portfolio_score": _number(raw / covered) if covered else None,
        "raw_equity_weighted_score": _number(raw) if covered else None,
        "raw_score_scope": "observed contribution over total equity capital; missing issuers have null, not zero scores",
        "holdings": rows, "events": [x.model_dump(mode="json") for x in clusters],
        "news": news_rows, "context_news": [x.item_id for x in context], "rejected_news": rejected,
        "scenario": {
            "new_nav_usd": _number(total + scenario_change),
            "change_usd": _number(scenario_change),
            "total_return": _number(scenario_change / total),
            "equity_return": _number(scenario_change / equity),
            "assumption": "User-specified price changes, before fees, dividends, FX and taxes; not a news impact estimate.",
        },
        "legacy": _legacy(accepted, weights),
    }
