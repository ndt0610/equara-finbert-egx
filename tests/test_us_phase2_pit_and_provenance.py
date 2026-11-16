import asyncio
import importlib

import httpx

import pytest
from fastapi.testclient import TestClient
from backend.config import DEFAULT_LOCAL_MODEL_REVISION, MODEL_ID

from backend.providers.us_market.sec_edgar_adapter import ProviderUnconfigured, SecEdgarAdapter
from backend.providers.us_market.us_news_adapter import AlpacaNewsProvider
from backend.services.us_capture import capture_alpaca_news
from backend.services.event_clustering import cluster_events_v2
from backend.services.numeric_headline_parser import parse_price_target_change
from backend.services.pit_decision_snapshot import adjusted_r5, build_snapshot, event_session, chart_price_history
from backend.storage.pit_ledger import PitLedger


CUTOFF = "2026-11-13T21:15:00+00:00"  # Friday 16:15 Eastern.


def test_chart_uses_one_vintage_and_requires_enough_five_session_returns():
    from datetime import date, timedelta
    from backend.universe.calendar_nyse import is_session
    days = [date(2026, 10, 1) + timedelta(days=i) for i in range(44)]
    days = [d.isoformat() for d in days if is_session(d)][-21:]
    bars = [{'session_date': day, 'close_adj': 100 + i, 'data_feed': 'SIP', 'run_id': 'one',
             'adjustment_asof_utc': '2026-11-15T00:00:00+00:00', 'as_of_ingested_utc': '2026-11-15T00:00:00+00:00'}
            for i, day in enumerate(days)]
    chart = chart_price_history(bars, days[-1])
    assert len(chart['points']) == 21 and chart['r5_samples'] == 16
    assert chart['r5'] == pytest.approx(120 / 115 - 1)
    assert chart['b75'] <= chart['e90']
    short = chart_price_history(bars[-8:], days[-1])
    assert short['r5'] is not None and short['b75'] is None


def news(item_id, headline, published="2026-11-13T19:00:00+00:00",
         ingested="2026-11-13T19:01:00+00:00", ticker="AAPL", item_type="NEWS_HEADLINE"):
    return {"item_id": item_id, "ticker": ticker, "headline": headline,
            "source_name": "Test source", "item_type": item_type,
            "published_at_utc": published, "ingested_at_utc": ingested}


def ledger(tmp_path):
    return PitLedger(tmp_path / "pit.sqlite3")


def run(db, tier="LIVE_CAPTURED_PIT"):
    return db.record_run("Test source", tier, "TEST_ONLY", {}, "2026-11-13T18:00:00+00:00", "2026-11-13T18:01:00+00:00")


def test_ingested_after_cutoff_is_excluded(tmp_path):
    db = ledger(tmp_path)
    rid = run(db)
    db.add_news(rid, news("late", "Apple beats estimates", ingested="2026-11-13T22:30:00+00:00"))
    snap = build_snapshot(db, CUTOFF, [{"ticker": "AAPL", "quantity": 1}])
    assert {"item_id": "late", "reason": "INGESTED_AFTER_CUTOFF"} in snap["excluded_items"]
    assert snap["events"] == []


@pytest.mark.parametrize(('ticker', 'headline'), [
    ('CVX', 'Carvolix Appoints Anne Lange as Chair of the Board'),
    ('GS', 'Goldman Sachs Maintains Buy Rating on Dell Technologies'),
    ('GS', 'Goldman Sachs Initiates Coverage on Gold Fields'),
    ('JPM', 'JPMorgan Chase Downgrades Phreesia'),
])
def test_experimental_noise_detects_collision_and_third_party_ratings(ticker, headline):
    from backend.services.target_relevance import experimental_relevance
    from backend.universe.catalog import universe_by_ticker
    assert experimental_relevance(headline, ticker, 'NEWS_HEADLINE', universe_by_ticker()) == 'POSSIBLE_NOISE_UNVERIFIED'


@pytest.mark.parametrize(('ticker', 'headline'), [
    ('CVX', 'Chevron Partners With Carvolix on New Project'),
    ('GS', 'Baird Raises Price Target on Goldman Sachs'),
    ('GS', 'Goldman Sachs Raises Concerns on Inflation'),
    ('JPM', 'JPMorgan Chase Expands Program'),
    ('JPM', 'JPMorgan Chase Downgrades JPMorgan Chase Stock'),
])
def test_experimental_noise_keeps_ambiguous_or_self_coverage(ticker, headline):
    from backend.services.target_relevance import experimental_relevance
    from backend.universe.catalog import universe_by_ticker
    assert experimental_relevance(headline, ticker, 'NEWS_HEADLINE', universe_by_ticker()) != 'POSSIBLE_NOISE_UNVERIFIED'


def test_future_source_filing_date_is_excluded_even_when_capture_time_is_past(tmp_path):
    db = ledger(tmp_path)
    rid = run(db)
    item = news("future-date", "Form 8-K", item_type="SEC_FILING")
    item["source_filing_date"] = "2026-12-01"
    db.add_news(rid, item)
    snap = build_snapshot(db, CUTOFF, [{"ticker": "AAPL", "quantity": 1}])
    assert {"item_id": "future-date", "reason": "SOURCE_FILING_DATE_AFTER_CUTOFF"} in snap["excluded_items"]
    assert snap["events"] == []


def test_snapshot_defaults_to_narrow_noise_filter_with_raw_comparison(tmp_path):
    db = ledger(tmp_path)
    rid = run(db)
    obs = db.add_news(rid, news('mis-tagged', 'MSTR Down 6% on Bitcoin Drop', ticker='JPM'))
    db.add_score(obs, 'mis-tagged', 'FinBERT', 'pinned', '2026-11-13T19:02:00+00:00',
                 'SCORED', {'positive': .01, 'neutral': .09, 'negative': .90})
    holdings = [{'ticker': 'JPM', 'quantity': 1}]
    filtered = build_snapshot(db, CUTOFF, holdings)
    raw = build_snapshot(db, CUTOFF, holdings, relevance_filter='none')
    assert {'item_id': 'mis-tagged', 'reason': 'EXCLUDED_TARGET_NOISE_HEURISTIC'} in filtered['excluded_items']
    assert filtered['events'] == []
    assert len(raw['events']) == 1


def test_noise_count_only_includes_items_eligible_at_cutoff(tmp_path):
    db = ledger(tmp_path)
    rid = run(db)
    db.add_news(rid, news('late-noise', 'MSTR Down 6% on Bitcoin Drop', ticker='JPM',
                            ingested='2026-11-13T22:30:00+00:00'))
    snap = build_snapshot(db, CUTOFF, [{'ticker': 'JPM', 'quantity': 1}])
    assert {'item_id': 'late-noise', 'reason': 'INGESTED_AFTER_CUTOFF'} in snap['excluded_items']
    assert not any(x['reason'] == 'EXCLUDED_TARGET_NOISE_HEURISTIC' for x in snap['excluded_items'])


def test_early_close_after_hours_moves_to_next_session():
    result = event_session("2026-11-27T18:15:00+00:00")  # 13:15 Eastern after early close.
    assert result == {"session_date": "2026-11-30", "timing": "AFTER_MARKET_CLOSE",
                      "earliest_tradable_session": "2026-11-30"}


def test_structural_filing_does_not_dilute_sentiment(tmp_path):
    db = ledger(tmp_path)
    rid = run(db)
    good = news("article", "Apple raises profit outlook")
    filing = news("filing", "Form 8-K (Item 5.02)", item_type="SEC_FILING")
    obs_good = db.add_news(rid, good)
    obs_filing = db.add_news(rid, filing)
    db.add_score(obs_good, "article", "FinBERT", "pinned", "2026-11-13T19:02:00+00:00",
                 "SCORED", {"positive": .9, "neutral": 0, "negative": .1})
    db.add_score(obs_filing, "filing", "FinBERT", "pinned", "2026-11-13T19:02:00+00:00",
                 "UNSCORED_STRUCTURAL_FILING")
    snap = build_snapshot(db, CUTOFF, [{"ticker": "AAPL", "quantity": 1}])
    assert snap["positions"][0]["sentiment_score"] == pytest.approx(.8)
    assert snap["positions"][0]["unscored_sec_filings_count"] == 1
    assert any(x["scoring_status"] == "UNSCORED_STRUCTURAL_FILING" for x in snap["events"])


def test_jaccard_ignores_company_name_but_merges_rewrites():
    a = news("a", "Microsoft Corporation (MSFT) announces cloud expansion", ticker="MSFT")
    b = news("b", "Microsoft Corporation (MSFT) faces European antitrust probe", ticker="MSFT")
    c = news("c", "Apple beats Q3 revenue expectations on strong iPhone sales")
    d = news("d", "Strong iPhone sales help Apple beat Q3 revenue estimates",
             published="2026-11-13T20:00:00+00:00")
    groups = cluster_events_v2([a, b, c, d], {"AAPL": ["Apple Inc"], "MSFT": ["Microsoft Corporation"]})
    assert len(groups) == 3
    assert any(set(x["item_ids"]) == {"c", "d"} and any("MATCH" in y or "JACCARD" in y for y in x["clustering_reason"]) for x in groups)


def test_sec_and_news_merge_only_with_explicit_key():
    filing = news("sec", "Form 8-K", item_type="SEC_FILING")
    article = news("news", "Apple reports results")
    filing["external_event_key"] = article["external_event_key"] = "accession-1"
    filing["scoring_status"] = "UNSCORED_STRUCTURAL_FILING"
    article["scoring_status"] = "SCORED"
    article["net_score"] = .8
    groups = cluster_events_v2([filing, article], {"AAPL": ["Apple"]})
    assert len(groups) == 1
    assert groups[0]["primary_item_id"] == "sec"
    assert groups[0]["score"] == .8
    assert groups[0]["clustering_reason"] == ["SHARED_EXTERNAL_KEY"]


def test_event_grouping_uses_canonical_url_and_containment_without_topic_merge():
    a = news('a', 'Chevron to restart operations at its biodiesel production facility in Ralston Iowa with capacity of almost 42M gallons per year', ticker='CVX')
    b = news('b', 'Chevron to restart Ralston biodiesel facility in Iowa', ticker='CVX')
    c = news('c', 'Chevron to restart refinery in Texas', ticker='CVX')
    d = news('d', 'Analyst updates Chevron price target', ticker='CVX')
    e = news('e', 'Barclays maintains Chevron hold rating and raises price target', ticker='CVX')
    d['source_url'] = 'https://www.moomoo.com/news/post/1004587082/barclays-chevron-target?utm_source=feed'
    e['source_url'] = 'https://www.moomoo.com/news/post/1004587082/barclays-chevron-target'
    groups = cluster_events_v2([a, b, c, d, e], {'CVX': ['Chevron']})
    assert any(set(group['item_ids']) == {'a', 'b'} and any('CONTAINMENT' in reason for reason in group['clustering_reason']) for group in groups)
    assert any(set(group['item_ids']) == {'d', 'e'} and group['clustering_reason'] == ['SHARED_CANONICAL_URL'] for group in groups)
    assert any(group['item_ids'] == ['c'] for group in groups)


def test_shared_quote_landing_page_does_not_merge_unrelated_news():
    a = news('a', 'State Street raises share stake in Nvidia', ticker='NVDA')
    b = news('b', 'Speaker Johnson favors limiting chip exports to China', ticker='NVDA')
    a['source_url'] = b['source_url'] = 'https://www.benzinga.com/quote/NVDA'
    assert len(cluster_events_v2([a, b], {'NVDA': ['Nvidia']})) == 2


def test_recurring_daily_headline_with_distinct_article_ids_stays_separate():
    a = news('a', 'Stock Market: Will S&P 500 Open Up or Down Today?', ticker='NVDA')
    b = news('b', 'Stock Market: Will S&P 500 Open Up or Down Today?', ticker='NVDA',
             published='2026-11-12T19:00:00+00:00')
    a['source_url'] = 'https://www.benzinga.com/markets/26/11/63229873/stock-market-today'
    b['source_url'] = 'https://www.benzinga.com/markets/26/11/63172206/stock-market-today'
    assert len(cluster_events_v2([a, b], {'NVDA': ['Nvidia']})) == 2


def test_price_target_arithmetic_and_conflicting_targets():
    cut = parse_price_target_change('Bernstein adjusts price target on Chevron to $233 from $248')
    raise_ = parse_price_target_change('Bernstein adjusts target price on Chevron from $193 to $206')
    assert (cut.direction, cut.previous, cut.current) == ('NUMERIC_TARGET_CUT', 248, 233)
    assert (raise_.direction, raise_.previous, raise_.current) == ('NUMERIC_TARGET_RAISE', 193, 206)
    assert parse_price_target_change('Chevron revenue rose from $193 to $206') is None
    a = news('a', 'Bernstein adjusts price target on Chevron to $233 from $248', ticker='CVX')
    b = news('b', 'Bernstein adjusts price target on Chevron to $236 from $248', ticker='CVX')
    assert len(cluster_events_v2([a, b], {'CVX': ['Chevron']})) == 2


def test_raw_price_valuation_adjusted_return_and_staleness(tmp_path):
    db = ledger(tmp_path)
    rid = run(db)
    dates = ["2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
    for index, day in enumerate(dates):
        db.add_bar(rid, {"ticker": "AAPL", "session_date": day, "open_raw": 100 + index,
                         "close_raw": 100 + index, "open_adj": 50 + index,
                         "close_adj": 50 + index, "as_of_ingested_utc": "2026-11-13T21:00:00+00:00",
                         "adjustment_asof_utc": "2026-11-13T21:00:00+00:00"})
    db.add_bar(rid, {"ticker": "MSFT", "session_date": "2026-11-11", "open_raw": 20,
                     "close_raw": 20, "close_adj": 10, "as_of_ingested_utc": "2026-11-13T21:00:00+00:00",
                     "adjustment_asof_utc": "2026-11-13T21:00:00+00:00"})
    snap = build_snapshot(db, CUTOFF, [{"ticker": "AAPL", "quantity": 2}, {"ticker": "MSFT", "quantity": 1}])
    apple, microsoft = snap["positions"]
    assert apple["position_value_usd"] == "210"
    assert apple["r5_adjusted"] == pytest.approx(.1)
    assert microsoft["price_status"] == "STALE_PRICE"
    assert snap["nav_usd"] is None  # No complete current NAV with stale marks.


def test_live_portfolio_coverage_uses_raw_capital_and_null_for_missing_news(tmp_path):
    db = ledger(tmp_path)
    rid = run(db)
    for ticker, close in [("AAPL", 100), ("MSFT", 300)]:
        db.add_bar(rid, {"ticker": ticker, "session_date": "2026-11-13", "open_raw": close,
                         "close_raw": close, "close_adj": close / 2,
                         "as_of_ingested_utc": "2026-11-13T21:00:00+00:00",
                         "adjustment_asof_utc": "2026-11-13T21:00:00+00:00"})
    item = news("apple", "Apple reports higher profit")
    observation = db.add_news(rid, item)
    db.add_score(observation, "apple", "FinBERT", "test", "2026-11-13T20:00:00+00:00",
                 "SCORED", {"positive": .9, "neutral": .1, "negative": 0})
    snap = build_snapshot(db, CUTOFF, [{"ticker": "AAPL", "quantity": 1}, {"ticker": "MSFT", "quantity": 1}], 50)
    assert float(snap["nav_usd"]) == 450
    assert float(snap["coverage"]) == pytest.approx(.25)
    assert float(snap["covered_portfolio_score"]) == pytest.approx(.9)
    assert float(snap["raw_equity_weighted_score"]) == pytest.approx(.225)
    assert snap["positions"][1]["sentiment_score"] is None


def test_retrospective_snapshot_is_labeled_and_keeps_strict_pit_boundary(tmp_path):
    db = ledger(tmp_path)
    rid = run(db)
    item = news('late-capture', 'Bernstein adjusts price target on Chevron to $233 from $248',
                published='2026-11-13T19:00:00+00:00', ingested='2026-11-15T01:00:00+00:00', ticker='CVX')
    obs = db.add_news(rid, item)
    db.add_score(obs, 'late-capture', 'FinBERT', 'test', '2026-11-15T01:01:00+00:00',
                 'SCORED', {'positive': .6, 'neutral': .3, 'negative': .1})
    db.add_bar(rid, {'ticker': 'CVX', 'session_date': '2026-11-13', 'open_raw': 100,
                     'close_raw': 100, 'close_adj': 100,
                     'as_of_ingested_utc': '2026-11-15T01:00:00+00:00',
                     'adjustment_asof_utc': '2026-11-15T01:00:00+00:00'})
    holdings = [{'ticker': 'CVX', 'quantity': 2}]
    strict = build_snapshot(db, CUTOFF, holdings, cash_usd=50, scenario_returns={'CVX': .10})
    replay = build_snapshot(db, CUTOFF, holdings, cash_usd=50, strict_pit_mode=False,
                            scenario_returns={'CVX': .10})
    assert strict['events'] == [] and strict['valuation_complete'] is False
    assert replay['report_validity_tier'] == 'EXPLORATORY_NON_PIT_DIAGNOSTIC_ONLY'
    assert 'DIAGNOSTIC_RETROSPECTIVE_REPLAY_VIEW' in replay['provenance_tiers']
    assert replay['events'][0]['retrospective_used'] is True
    assert replay['events'][0]['p_pos'] == pytest.approx(.6)
    assert replay['events'][0]['numeric_target_info']['finbert_direction_disagrees'] is True
    assert replay['nav_usd'] == '250'
    assert replay['scenario']['change_usd'] == '20.0'
    assert replay['legacy_comparison']['headline_count'] == 1


def test_audit_summary_endpoint_reads_ledger_without_hardcoded_counts(tmp_path, monkeypatch):
    app_module = importlib.import_module('backend.app')
    db = ledger(tmp_path)
    rid = run(db)
    obs = db.add_news(rid, news('one', 'Apple beats estimates'))
    db.add_score(obs, 'one', MODEL_ID, DEFAULT_LOCAL_MODEL_REVISION, '2026-11-13T19:02:00+00:00',
                 'SCORED', {'positive': .8, 'neutral': .1, 'negative': .1})
    monkeypatch.setattr(app_module, 'PitLedger', lambda: ledger(tmp_path))
    monkeypatch.setattr(app_module, 'ARTIFACTS_DIR', tmp_path)
    with TestClient(app_module.app) as client:
        response = client.get('/api/v3/us/audit-summary')
    assert response.status_code == 200
    summary = response.json()
    assert summary['ledger_counts']['sec_filings'] == 0
    assert summary['ledger_counts']['scored_news'] == 1
    assert summary['ledger_counts']['sip_price_bars'] == 0
    assert summary['artifact_status']['phase3_reports_loaded'] == 0


def test_snapshot_hash_ignores_newer_observations(tmp_path):
    db = ledger(tmp_path)
    rid = run(db)
    db.add_news(rid, news("initial", "Apple raises outlook"))
    before = build_snapshot(db, CUTOFF, [{"ticker": "AAPL", "quantity": 1}])
    db.add_news(rid, news("late", "Apple cuts outlook", ingested="2026-11-13T22:00:00+00:00"))
    after = build_snapshot(db, CUTOFF, [{"ticker": "AAPL", "quantity": 1}])
    assert before["snapshot_sha256"] == after["snapshot_sha256"]
    assert {"item_id": "late", "reason": "INGESTED_AFTER_CUTOFF"} in after["excluded_items"]


def test_append_only_and_unconfigured_provider(tmp_path):
    db = ledger(tmp_path)
    rid = run(db)
    with pytest.raises(Exception, match="APPEND_ONLY"):
        db.db.execute("DELETE FROM ingestion_runs WHERE run_id=?", (rid,))
    with pytest.raises(ProviderUnconfigured):
        SecEdgarAdapter(user_agent="")


def test_sec_adapter_keeps_ambiguous_acceptance_raw():
    payload = {"filings": {"recent": {
        "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002"],
        "form": ["8-K", "10-Q"],
        "acceptanceDateTime": ["2026-11-13T16:05:00.000Z", "2026-11-02T16:05:00.000Z"],
        "filingDate": ["2026-11-13", "2026-11-02"],
        "primaryDocument": ["report.htm", "quarter.htm"], "items": ["2.02", ""]}}}

    async def exercise():
        def handler(request):
            assert request.headers["User-Agent"] == "Equara/1.0 (research@example.com)"
            return httpx.Response(200, json=payload)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = SecEdgarAdapter("Equara/1.0 (research@example.com)", client)
            items, errors = await adapter.fetch(["AAPL"])
            assert errors == []
            assert len(items) == 2
            assert items[0]["provider_accepted_raw"] == "2026-11-13T16:05:00.000Z"
            assert items[0]["provider_accepted_at_utc"] is None
            assert items[0]["published_at_utc"] == items[0]["ingested_at_utc"]
            assert items[0]["publication_time_basis"] == "EQUARA_FIRST_OBSERVED_UPPER_BOUND"
            assert {item["item_id"]: item["source_filing_date"] for item in items} == {
                "SEC:0000320193:0000320193-26-000001": "2026-11-13",
                "SEC:0000320193:0000320193-26-000002": "2026-11-02"}
            assert len(adapter.raw_batch_hash) == 64
    asyncio.run(exercise())


def test_alpaca_news_pipeline_uses_model_probabilities(tmp_path):
    class FakeProvider:
        license_tag = "TEST_ONLY"
        async def fetch(self, tickers):
            return [news("n1", "Apple profit rises", published="2026-11-13T19:00:00+00:00")]

    class FakeFinbert:
        model_id = "ProsusAI/finbert"
        revision = "test-pinned"
        async def classify_many(self, texts):
            assert texts == ["Apple profit rises"]
            return [{"positive": .8, "neutral": .1, "negative": .1}]

    db = ledger(tmp_path)
    result = asyncio.run(capture_alpaca_news(db, ["AAPL"], FakeProvider(), FakeFinbert()))
    assert result["scored"] == 1
    assert result["captured_retrospective"] == 1
    assert db.rows("sentiment_scores")[0]["net_score"] == pytest.approx(.7)
    snap = build_snapshot(db, CUTOFF, [{"ticker": "AAPL", "quantity": 1}])
    assert snap["positions"][0]["sentiment_score"] is None
    assert {"item_id": "n1", "reason": "INGESTED_AFTER_CUTOFF"} in snap["excluded_items"]


def test_alpaca_news_uses_documented_page_limit_and_paginates():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.params["limit"] == "50"
        page = request.url.params.get("page_token")
        article_id = 2 if page else 1
        return httpx.Response(200, json={
            "news": [{"id": article_id, "headline": f"Article {article_id}",
                      "source": "Test source", "symbols": ["AAPL"],
                      "created_at": "2026-11-13T19:00:00Z", "url": None}],
            "next_page_token": None if page else "next-page",
        })

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AlpacaNewsProvider("test-key", "test-secret", client)
            items = await provider.fetch(["AAPL"])
            assert len(items) == 2
            assert {item["item_id"] for item in items} == {"ALPACA:1:AAPL", "ALPACA:2:AAPL"}
            assert len(provider.raw_batch_hash) == 64

    asyncio.run(exercise())
    assert len(requests) == 2
    assert requests[1].url.params["page_token"] == "next-page"


def test_news_lookback_and_page_cap_validation():
    for days in (0, 366):
        with pytest.raises(ValueError, match='INVALID_NEWS_CAPTURE_CONFIGURATION'):
            AlpacaNewsProvider('key', 'secret', lookback_calendar_days=days)
    assert AlpacaNewsProvider('key', 'secret', lookback_calendar_days=60).lookback_calendar_days == 60


def test_target_relevance_triage_does_not_confuse_missing_mention_with_ground_truth():
    from backend.services.target_relevance import classify_target_relevance
    from backend.universe.catalog import universe_by_ticker
    catalog = universe_by_ticker()
    assert classify_target_relevance('Nvidia shares decline', 'AAPL', 'NEWS_HEADLINE', catalog) == 'NO_TARGET_MENTION_REVIEW'
    assert classify_target_relevance('Apple supplier Nvidia faces delays', 'AAPL', 'NEWS_HEADLINE', catalog) == 'TARGET_MENTION_REVIEW'
    assert classify_target_relevance('Form 8-K', 'AAPL', 'SEC_FILING', catalog) == 'UNSCORABLE_ADMIN_FILING'


@pytest.mark.parametrize('ticker,headline', [('NVDA', 'What is going on with Super Micro stock?'),
    ('JPM', 'MSTR Down 6% on Bitcoin Drop'), ('GS', 'Micron Stock Is Trending Pre-Market'),
    ('JPM', 'Why Is Broadcom Stock Trending After Hours?'),
    ('UNH', 'If You Invested $1000 In UnitedHealth Group Stock')])
def test_possible_noise_is_explicitly_marked_for_review(ticker, headline):
    from backend.services.target_relevance import experimental_relevance
    from backend.universe.catalog import universe_by_ticker
    assert experimental_relevance(headline, ticker, 'NEWS_HEADLINE', universe_by_ticker()) == 'POSSIBLE_NOISE_UNVERIFIED'


@pytest.mark.parametrize('ticker,headline', [('CVX', 'Chevron Announces Expansion'),
    ('CAT', 'Caterpillar and Phoenix Service Partners'), ('XOM', 'ExxonMobil Announces Investment'),
    ('GS', 'Goldman Sachs International Discloses Results'), ('JPM', 'JPMorgan Chase Expands Program')])
def test_company_names_without_legal_suffix_are_detected(ticker, headline):
    from backend.services.target_relevance import classify_target_relevance
    from backend.universe.catalog import universe_by_ticker
    assert classify_target_relevance(headline, ticker, 'NEWS_HEADLINE', universe_by_ticker()) == 'TARGET_MENTION_REVIEW'
