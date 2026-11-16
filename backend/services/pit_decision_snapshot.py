"""Rebuild a decision from observations actually captured by its cutoff."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import numpy as np

from backend.services.event_clustering import cluster_events_v2
from backend.services.numeric_headline_parser import parse_price_target_change
from backend.services.target_relevance import experimental_relevance
from backend.storage.pit_ledger import PitLedger, digest
from backend.universe.calendar_nyse import ET, SOURCE, close_at, is_session, next_session
from backend.universe.catalog import universe_by_ticker


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo and parsed.utcoffset() is not None else None


def event_session(published_at: str) -> dict:
    published = _time(published_at)
    if published is None:
        raise ValueError("MISSING_TIMEZONE")
    local = published.astimezone(ET)
    day = local.date()
    if not is_session(day):
        return {"session_date": next_session(day).isoformat(), "timing": "NON_SESSION",
                "earliest_tradable_session": next_session(day).isoformat()}
    if local > close_at(day):
        following = next_session(day).isoformat()
        return {"session_date": following, "timing": "AFTER_MARKET_CLOSE",
                "earliest_tradable_session": following}
    return {"session_date": day.isoformat(), "timing": "REGULAR_SESSION",
            "earliest_tradable_session": day.isoformat()}


def adjusted_r5(bars: list[dict]) -> float | None:
    """Five session close-to-close return; adjustments must be observed by cutoff."""
    days = sorted({b["session_date"] for b in bars})
    if len(days) < 6:
        return None
    expected = [days[-1]]
    cursor = datetime.fromisoformat(days[-1]).date()
    while len(expected) < 6:
        cursor -= timedelta(days=1)
        if is_session(cursor):
            expected.append(cursor.isoformat())
    if set(expected) - set(days):
        return None
    by_day = {b["session_date"]: b for b in bars}
    old = by_day[days[-6]].get("close_adj")
    new = by_day[days[-1]].get("close_adj")
    return new / old - 1 if old and new else None


def chart_price_history(bars: list[dict], decision_session: str) -> dict:
    """Use one SIP adjustment vintage, with consecutive sessions for each R5."""
    runs = {}
    for bar in bars:
        if bar['data_feed'] != 'SIP' or not bar.get('close_adj') or not bar.get('adjustment_asof_utc'):
            continue
        key = (bar['run_id'], bar['adjustment_asof_utc'])
        runs.setdefault(key, {})[bar['session_date']] = bar
    eligible = [(max(x['as_of_ingested_utc'] for x in by_day.values()), key, by_day)
                for key, by_day in runs.items() if decision_session in by_day]
    if not eligible:
        return {'points': [], 'r5': None, 'b75': None, 'e90': None, 'r5_samples': 0}
    _, _, by_day = max(eligible, key=lambda x: (x[0], x[1]))
    dates = sorted(by_day)[-21:]
    series = [by_day[d] for d in dates]
    values = [abs(v) for i in range(5, len(series)) if (v := adjusted_r5(series[i-5:i+1])) is not None]
    current = adjusted_r5(series)
    return {'points': [{'session_date': x['session_date'], 'close_adj': x['close_adj']} for x in series],
            'r5': current, 'b75': float(np.quantile(values, .75)) if len(values) >= 10 else None,
            'e90': float(np.quantile(values, .90)) if len(values) >= 10 else None, 'r5_samples': len(values)}


def completed_session_schedule(cutoff: datetime) -> dict:
    """Weekend and premarket decisions inherit the last completed NYSE session."""
    local = cutoff.astimezone(ET)
    day = local.date()
    while not is_session(day) or local < close_at(day):
        day -= timedelta(days=1)
    return {"decision_session": day.isoformat(), "close_at": close_at(day).isoformat(),
            "earliest_core_execution_session": next_session(day).isoformat(),
            "calendar_source": SOURCE, "execution_price_status": "not_observed"}


def build_snapshot(ledger: PitLedger, decision_ts_utc: str, holdings: list[dict],
                   cash_usd: float = 0, strict_pit_mode: bool = True, window_days: int = 7,
                   relevance_filter: str = 'exclude_noise', scenario_returns: dict[str, float] | None = None) -> dict:
    if relevance_filter not in {'none', 'exclude_noise'}:
        raise ValueError('INVALID_RELEVANCE_FILTER')
    cutoff = _time(decision_ts_utc)
    if cutoff is None:
        raise ValueError("TIMEZONE_REQUIRED")
    if cutoff > datetime.now(timezone.utc):
        raise ValueError("FUTURE_DECISION_CUTOFF")
    schedule = completed_session_schedule(cutoff)
    if not 1 <= window_days <= 90:
        raise ValueError("INVALID_WINDOW")
    catalog = universe_by_ticker()
    tickers = [x["ticker"] for x in holdings]
    if len(tickers) != len(set(tickers)) or not tickers or len(tickers) > 20 or any(x not in catalog for x in tickers):
        raise ValueError("INVALID_HOLDINGS")
    quantities = {x["ticker"]: Decimal(str(x["quantity"])) for x in holdings}
    if any(not x.is_finite() or x < 0 for x in quantities.values()) or not Decimal(str(cash_usd)).is_finite() or cash_usd < 0:
        raise ValueError("INVALID_AMOUNT")
    scenarios = {ticker: Decimal(str(value)) for ticker, value in (scenario_returns or {}).items()}
    if set(scenarios) - set(tickers) or any(not value.is_finite() or value < -1 for value in scenarios.values()):
        raise ValueError('INVALID_SCENARIO_RETURNS')
    excluded = []
    selected = {}
    for row in ledger.rows("raw_news_events"):
        if row["ticker"] not in tickers:
            continue
        published, ingested = _time(row["published_at_utc"]), _time(row["ingested_at_utc"])
        replay_filing = (not strict_pit_mode and row['item_type'] == 'SEC_FILING' and
                         row['source_filing_date'] and row['source_filing_date'] <= cutoff.astimezone(ET).date().isoformat())
        reason = ("MISSING_TIMEZONE" if published is None or ingested is None else
                  "PUBLISHED_AFTER_CUTOFF" if published > cutoff and not replay_filing else
                  "INGESTED_AFTER_CUTOFF" if strict_pit_mode and ingested > cutoff else
                  "SOURCE_FILING_DATE_AFTER_CUTOFF" if row["source_filing_date"] and
                  row["source_filing_date"] > cutoff.astimezone(ET).date().isoformat() else
                  "OUTSIDE_NEWS_WINDOW" if (row['item_type'] != 'SEC_FILING' and published < cutoff - timedelta(days=window_days)) or
                  (row["source_filing_date"] and row["source_filing_date"] < (cutoff.astimezone(ET).date() - timedelta(days=window_days)).isoformat()) else None)
        if reason:
            excluded.append({"item_id": row["item_id"], "reason": reason})
            continue
        if relevance_filter == 'exclude_noise' and experimental_relevance(row['headline'], row['ticker'], row['item_type'], catalog) == 'POSSIBLE_NOISE_UNVERIFIED':
            excluded.append({'item_id': row['item_id'], 'reason': 'EXCLUDED_TARGET_NOISE_HEURISTIC'})
            continue
        previous = selected.get(row["item_id"])
        if previous is None or (ingested, row["observation_id"]) > (_time(previous["ingested_at_utc"]), previous["observation_id"]):
            selected[row["item_id"]] = row
    score_by_observation = {}
    for row in ledger.rows("sentiment_scores"):
        if row["observation_id"] not in {x["observation_id"] for x in selected.values()}:
            continue
        scored = _time(row["scored_at_utc"])
        if scored is None or (strict_pit_mode and scored > cutoff):
            excluded.append({"item_id": row["item_id"], "reason": "SCORED_AFTER_CUTOFF" if scored else "MISSING_TIMEZONE"})
            continue
        old = score_by_observation.get(row["observation_id"])
        if old is None or (scored, row["score_id"]) > (_time(old["scored_at_utc"]), old["score_id"]):
            score_by_observation[row["observation_id"]] = row
    events = []
    for item_id, row in sorted(selected.items()):
        score = score_by_observation.get(row["observation_id"])
        if not strict_pit_mode and row['item_type'] == 'SEC_FILING' and _time(row['published_at_utc']) > cutoff:
            timing = {'session_date': row['source_filing_date'], 'timing': 'RETROSPECTIVE_DATE_ONLY',
                      'earliest_tradable_session': None}
        else:
            timing = event_session(row["published_at_utc"])
        target = parse_price_target_change(row['headline'])
        net = score['net_score'] if score and score['scoring_status'] == 'SCORED' else None
        target_info = ({'previous': str(target.previous), 'current': str(target.current),
                        'direction': target.direction,
                        'finbert_direction_disagrees': bool(net is not None and
                            ((target.direction == 'NUMERIC_TARGET_CUT' and net > .10) or
                             (target.direction == 'NUMERIC_TARGET_RAISE' and net < -.10)))}
                       if target else None)
        events.append({
            "item_id": item_id, "ticker": row["ticker"], "headline": row["headline"],
            "source_name": row["source_name"], "source_url": row["source_url"],
            "item_type": row["item_type"], "sec_form_type": row["sec_form_type"],
            "sec_items": row["sec_items_json"], "external_event_key": row["external_event_key"],
            "published_at_utc": row["published_at_utc"], "provider_accepted_at_utc": row["provider_accepted_at_utc"],
            "provider_accepted_raw": row["provider_accepted_raw"],
            "publication_time_basis": row["publication_time_basis"],
            "source_filing_date": row["source_filing_date"],
            "ingested_at_utc": row["ingested_at_utc"], "scored_at_utc": score["scored_at_utc"] if score else None,
            "scoring_status": score["scoring_status"] if score else "PENDING_SCORE",
            "net_score": net,
            "p_pos": score['p_pos'] if net is not None else None,
            "p_neu": score['p_neu'] if net is not None else None,
            "p_neg": score['p_neg'] if net is not None else None,
            "relevance_label": experimental_relevance(row['headline'], row['ticker'], row['item_type'], catalog),
            "numeric_target_info": target_info,
            "retrospective_used": bool(not strict_pit_mode and _time(row['ingested_at_utc']) > cutoff),
            "provenance_tier": row["provenance_tier"], "license_tag": row["license_tag"], **timing,
        })
    aliases = {ticker: [catalog[ticker]["company_name"], *catalog[ticker].get("aliases", []), ticker] for ticker in tickers}
    clusters = cluster_events_v2(events, aliases)
    bars = {}
    eligible_chart_bars = []
    for row in ledger.rows("eod_price_bars"):
        if row["ticker"] not in tickers:
            continue
        ingested = _time(row["as_of_ingested_utc"])
        adjusted_asof = _time(row["adjustment_asof_utc"])
        if ingested is None or (strict_pit_mode and ingested > cutoff) or row["session_date"] > schedule["decision_session"]:
            excluded.append({"item_id": row["bar_id"], "reason": "INGESTED_AFTER_CUTOFF" if ingested and ingested > cutoff else "MISSING_TIMEZONE" if ingested is None else "PRICE_SESSION_AFTER_CUTOFF"})
            continue
        record = dict(row)
        if adjusted_asof is None or (strict_pit_mode and adjusted_asof > cutoff):
            record["close_adj"] = None
            record["open_adj"] = None
        eligible_chart_bars.append(record)
        key = (row["ticker"], row["session_date"])
        old = bars.get(key)
        if old is None or (ingested, row["bar_id"]) > (_time(old["as_of_ingested_utc"]), old["bar_id"]):
            bars[key] = record
    positions = []
    for ticker in tickers:
        history = sorted((v for (symbol, _), v in bars.items() if symbol == ticker), key=lambda x: x["session_date"])
        bar = history[-1] if history else None
        status = "MISSING_PRICE" if bar is None else "STALE_PRICE" if bar["session_date"] < schedule["decision_session"] else "OK"
        if status == "STALE_PRICE":
            excluded.append({"item_id": ticker, "reason": "STALE_PRICE"})
        relevant = [x for x in clusters if x["ticker"] == ticker]
        scored = [x["score"] for x in relevant if x["score"] is not None]
        position_value = quantities[ticker] * Decimal(str(bar['close_raw'])) if bar else None
        scenario_rate = scenarios.get(ticker, Decimal(0))
        positions.append({
            "ticker": ticker, "quantity": str(quantities[ticker]), "price_status": status,
            "price_session_date": bar["session_date"] if bar else None,
            "price_feed": bar["data_feed"] if bar else None,
            "close_raw": bar["close_raw"] if bar else None,
            "close_adj": bar["close_adj"] if bar else None,
            "position_value_usd": format(position_value.normalize(), "f") if position_value is not None else None,
            "scenario_return": str(scenario_rate),
            "scenario_new_value_usd": str(position_value * (1 + scenario_rate)) if position_value is not None and status == 'OK' and bar['data_feed'] != 'IEX' else None,
            "r5_adjusted": adjusted_r5(history),
            "price_chart": chart_price_history([x for x in eligible_chart_bars if x['ticker'] == ticker], schedule['decision_session']),
            "cluster_count": len(relevant), "article_count": sum(len(x["item_ids"]) for x in relevant),
            "has_conflicting_sentiment": any(x["has_conflicting_sentiment"] for x in relevant),
            "unscored_sec_filings_count": sum(x["item_type"] == "SEC_FILING" and x["scoring_status"] == "UNSCORED_STRUCTURAL_FILING" for x in events if x["ticker"] == ticker),
            "sentiment_score": sum(scored) / len(scored) if scored else None,
        })
    valuation_complete = all(x["price_status"] == "OK" and x["price_feed"] != "IEX" for x in positions)
    equity = sum((Decimal(x["position_value_usd"]) for x in positions), Decimal(0)) if valuation_complete else None
    nav = equity + Decimal(str(cash_usd)) if equity is not None else None
    covered_capital = sum((Decimal(x["position_value_usd"]) for x in positions if x["sentiment_score"] is not None), Decimal(0)) if equity is not None else None
    score_numerator = sum((Decimal(x["position_value_usd"]) * Decimal(str(x["sentiment_score"])) for x in positions if x["sentiment_score"] is not None), Decimal(0)) if equity is not None else None
    coverage = covered_capital / equity if equity and covered_capital is not None else None
    covered_score = score_numerator / covered_capital if covered_capital else None
    raw_score = score_numerator / equity if equity and covered_capital else None
    tier_set = sorted({x["provenance_tier"] for x in events} | {b["provenance_tier"] for b in bars.values()} |
                      ({'DIAGNOSTIC_RETROSPECTIVE_REPLAY_VIEW'} if not strict_pit_mode else set()))
    scenario_change = sum((Decimal(x['position_value_usd']) * scenarios.get(x['ticker'], Decimal(0))
                           for x in positions if x['position_value_usd'] is not None), Decimal(0)) if nav is not None else None
    scenario = {'change_usd': str(scenario_change) if scenario_change is not None else None,
                'new_nav_usd': str(nav + scenario_change) if nav is not None else None,
                'total_return': str(scenario_change / nav) if nav and scenario_change is not None else None,
                'assumption': 'User-specified price changes on close_raw; before fees, dividends, FX and taxes; not a news impact estimate.'}
    eligible_scores = [x for x in events if x['net_score'] is not None]
    legacy_denominator = sum((Decimal(x['position_value_usd']) *
                              sum(item['ticker'] == x['ticker'] for item in eligible_scores)
                              for x in positions if x['position_value_usd'] is not None), Decimal(0)) if equity is not None else Decimal(0)
    legacy_numerator = sum((Decimal(x['position_value_usd']) * Decimal(str(item['net_score']))
                            for x in positions if x['position_value_usd'] is not None
                            for item in eligible_scores if item['ticker'] == x['ticker']), Decimal(0)) if equity is not None else Decimal(0)
    legacy = {'score': str(legacy_numerator / legacy_denominator) if legacy_denominator else None,
              'effective_ticker_shares': {x['ticker']: str(Decimal(x['position_value_usd']) *
                  sum(item['ticker'] == x['ticker'] for item in eligible_scores) / legacy_denominator)
                  if legacy_denominator and x['position_value_usd'] is not None else None for x in positions},
              'headline_count': len(eligible_scores),
              'method': 'one_vote_per_scored_article_times_issuer_equity_value; no context articles'}
    stable = {"decision_ts_utc": cutoff.isoformat(), "strict_pit_mode": strict_pit_mode, "window_days": window_days,
              "relevance_filter": relevance_filter,
              "holdings": holdings, "cash_usd": str(cash_usd), "events": events,
              "clusters": clusters, "positions": positions,
              "equity_value_usd": str(equity) if equity is not None else None,
              "nav_usd": str(nav) if nav is not None else None,
              "coverage": str(coverage) if coverage is not None else None,
              "covered_portfolio_score": str(covered_score) if covered_score is not None else None,
              "raw_equity_weighted_score": str(raw_score) if raw_score is not None else None,
              "scenario_returns": {ticker: str(value) for ticker, value in sorted(scenarios.items())},
              "scenario": scenario, "legacy_comparison": legacy,
              "report_validity_tier": 'LIVE_CAPTURED_PIT_VIEW' if strict_pit_mode else 'EXPLORATORY_NON_PIT_DIAGNOSTIC_ONLY'}
    return {**stable, "snapshot_sha256": digest(stable), "decision_ts_et": cutoff.astimezone(ET).isoformat(),
            "schedule": schedule, "valuation_complete": valuation_complete,
            "provenance_tiers": tier_set, "excluded_items": sorted(excluded, key=lambda x: (x["item_id"], x["reason"])),
            "rights_note": "SEC public filing metadata is freely reusable; review Alpaca redistribution rights separately. IEX bars are indicative, not consolidated closing prices."}
