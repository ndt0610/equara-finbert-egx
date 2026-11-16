from datetime import date, datetime, timedelta, timezone
import asyncio

import pytest

from backend.evaluation.phase3_contract import (
    advance_sessions, aggregate_event_variants, previous_sessions, provenance_verdict,
    purged_training_indices, realized_return,
)
from backend.evaluation.phase3_panel import _events_at_decision, build_phase3_panel
from backend.evaluation.signal_validation_phase3 import _features, _standardize, run_walk_forward_phase3
from backend.services.us_capture import capture_daily_price_vintage, price_vintage_readiness
from backend.storage.pit_ledger import PitLedger
from backend.universe.calendar_nyse import is_session
import numpy as np


def test_unvalidated_relevance_filter_cannot_be_used_for_strict_pit():
    ledger = PitLedger(':memory:')
    with pytest.raises(ValueError, match='UNVALIDATED_RELEVANCE_REQUIRES_DIAGNOSTIC'):
        build_phase3_panel(ledger, ['AAPL'], '2026-10-01', '2026-11-13', relevance_filter='direct_only')
    ledger.close()


def test_horizon_overlap_purge_at_decision_ten():
    samples = [{"decision_index": t, "label_available_at_utc": "2026-11-13T20:00:00+00:00"} for t in range(1, 10)]
    accepted, purged = purged_training_indices(samples, evaluation_index=10, horizon=5,
                                               evaluation_cutoff_utc=datetime(2026, 11, 13, 21, tzinfo=timezone.utc))
    assert [samples[i]["decision_index"] for i in accepted] == [1, 2, 3, 4, 5]
    assert [samples[i]["decision_index"] for i in purged] == [6, 7, 8, 9]


def test_open_next_session_avoids_close_t_gap_illusion():
    close_t = 100  # Known to the decision maker; never used as a fill.
    outcome = realized_return(open_adj_next_session=110, close_adj_exit_session=110)
    assert close_t != 110
    assert outcome["gross"] == 0.0
    assert realized_return(110, 110, 10)["net"] == pytest.approx(-.002)


def test_non_pit_provenance_blocks_actionability():
    result = provenance_verdict({"EXPLORATORY_RETROSPECTIVE_NON_PIT"}, True)
    assert result == {"report_validity_tier": "EXPLORATORY_NON_PIT_DIAGNOSTIC_ONLY",
                      "actionability_gate_passed": False, "actionability_reason": "NON_PIT_DATA_SOURCE"}


def test_first_mention_differs_from_cluster_mean():
    cutoff = datetime(2026, 11, 13, 21, tzinfo=timezone.utc)
    items = {}
    for index, score in enumerate((.9, .1, .1, .1)):
        items[f"n{index}"] = {"item_id": f"n{index}", "net_score": score,
                              "scoring_status": "SCORED", "ingested_at_utc": f"2026-11-13T1{index}:00:00+00:00"}
    clusters = [{"item_ids": list(items), "score": .3, "earliest_item_id": "n0"}]
    variants = aggregate_event_variants(clusters, items, cutoff)
    assert variants["first_mention"] == pytest.approx(.9)
    assert variants["mean"] == pytest.approx(.3)


def test_panel_keeps_late_history_out_of_strict_pit_and_uses_next_open():
    ledger = PitLedger(":memory:")
    day = date(2026, 11, 6)
    history = previous_sessions(day, 20)
    entry, exit_day = advance_sessions(day, 1), advance_sessions(day, 5)
    run = ledger.record_run("synthetic", "LIVE_CAPTURED_PIT", "test", {},
                            "2026-11-06T20:00:00+00:00", "2026-11-13T22:00:00+00:00")
    for index, session in enumerate(history):
        observed = "2026-11-07T02:00:00+00:00"
        ledger.add_bar(run, {"ticker": "AAPL", "session_date": session.isoformat(),
                             "open_raw": 100, "close_raw": 100 + index,
                             "open_adj": 100, "close_adj": 100 + index,
                             "as_of_ingested_utc": observed, "adjustment_asof_utc": observed,
                             "data_feed": "SIP"})
    for session, opened, closed in ((entry, 130, 135), (exit_day, 140, 143)):
        ledger.add_bar(run, {"ticker": "AAPL", "session_date": session.isoformat(),
                             "open_raw": opened, "close_raw": closed,
                             "open_adj": opened, "close_adj": closed,
                             "as_of_ingested_utc": "2026-11-14T00:00:00+00:00",
                             "adjustment_asof_utc": "2026-11-14T00:00:00+00:00",
                             "data_feed": "SIP"})
    strict = build_phase3_panel(ledger, ["AAPL"], day.isoformat(), day.isoformat())
    assert not strict["rows"]
    assert strict["excluded"][0]["reason"] == "MISSING_COHERENT_ASOF_PRICE_VINTAGE"
    diagnostic = build_phase3_panel(ledger, ["AAPL"], day.isoformat(), day.isoformat(),
                                    allow_retrospective_diagnostic=True)
    row = diagnostic["rows"][0]
    assert row["gross_return"] == pytest.approx(143 / 130 - 1)
    assert "RETROSPECTIVE_PRICE_USED" in row["feature_provenance_tiers"]
    assert row["entry_session"] == entry.isoformat()
    ledger.close()


def test_walk_forward_freezes_holdout_training_and_blocks_retro_actionability():
    rows = []
    for index in range(40):
        day = date(2026, 1, 1) + timedelta(days=index)
        for ticker_number, ticker in enumerate(("AAPL", "MSFT")):
            gross = ((index % 7) - 3 + ticker_number) / 100
            rows.append({"ticker": ticker, "decision_index": index,
                         "decision_date": day.isoformat(),
                         "decision_cutoff_utc": datetime.combine(day, datetime.min.time(), timezone.utc).isoformat(),
                         "label_available_at_utc": datetime.combine(day + timedelta(days=5), datetime.min.time(), timezone.utc).isoformat(),
                         "entry_open_adj": 100, "exit_close_adj": 100 * (1 + gross),
                         "exit_session": (day + timedelta(days=5)).isoformat(),
                         "gross_return": gross, "net_return_10bps": gross - .002,
                         "price_features": {name: .01 * (index + ticker_number) for name in
                                            ("r_minus_1", "r_minus_5", "r_minus_20", "sigma_20", "b75_abs_return", "e90_abs_return")},
                         "event_features": {"has_valid_event": 1, "event_cluster_count": 1,
                                            "has_sec_filing": 0, "scored_cluster_count": 1,
                                            "aggregate_scores": {name: gross for name in
                                                                 ("mean", "decay_3d", "decay_7d", "first_mention")}},
                         "feature_provenance_tiers": ["EXPLORATORY_RETROSPECTIVE_NON_PIT"]})
    panel = {"rows": rows, "horizon": 5, "panel_sha256": "synthetic", "excluded": []}
    report = run_walk_forward_phase3(panel, min_train_sessions=6, min_train_rows=12,
                                     bootstrap_repetitions=20)
    assert report["walk_forward"]["holdout_start_decision_index"] == 30
    holdout = [fold for fold in report["walk_forward"]["folds"] if fold.get("holdout")]
    assert holdout and {fold["max_training_decision_index"] for fold in holdout} == {25}
    assert report["walk_forward"]["evaluated_rows"] > 0
    assert report["report_validity_tier"] == "EXPLORATORY_NON_PIT_DIAGNOSTIC_ONLY"
    assert report["actionability_gate_passed"] is False


def _add_vintage(ledger, sessions, observed, closes, tier="LIVE_CAPTURED_PIT", opens=None):
    run = ledger.record_run("synthetic daily vintage", tier, "test", {}, observed, observed)
    for index, (session, close) in enumerate(zip(sessions, closes)):
        opened = opens[index] if opens else close
        ledger.add_bar(run, {"ticker": "AAPL", "session_date": session.isoformat(),
                             "open_raw": opened, "close_raw": close,
                             "open_adj": opened, "close_adj": close,
                             "as_of_ingested_utc": observed, "adjustment_asof_utc": observed,
                             "data_feed": "SIP"})
    return run


def test_outcome_label_stays_anchored_after_later_price_recapture():
    ledger = PitLedger(":memory:")
    day = date(2026, 11, 6)
    history = previous_sessions(day, 20)
    entry, exit_day = advance_sessions(day, 1), advance_sessions(day, 5)
    _add_vintage(ledger, history, "2026-11-06T23:30:00+00:00", [100] * 21)
    first_outcome = "2026-11-13T23:30:00+00:00"
    _add_vintage(ledger, [entry, exit_day], first_outcome, [110, 120])
    before = build_phase3_panel(ledger, ["AAPL"], day.isoformat(), day.isoformat())["rows"][0]
    _add_vintage(ledger, [entry, exit_day], "2026-12-10T23:30:00+00:00", [55, 60])
    after = build_phase3_panel(ledger, ["AAPL"], day.isoformat(), day.isoformat())["rows"][0]
    assert after["label_available_at_utc"] == before["label_available_at_utc"] == first_outcome
    assert after["gross_return"] == before["gross_return"] == pytest.approx(120 / 110 - 1)
    assert after["outcome_vintage_run_id"] == before["outcome_vintage_run_id"]
    accepted, _ = purged_training_indices([after], 6, 5,
                                           datetime(2026, 11, 16, 1, tzinfo=timezone.utc))
    assert accepted == [0]
    ledger.close()


def test_split_regime_uses_one_recent_adjusted_price_vintage():
    ledger = PitLedger(":memory:")
    day = date(2026, 11, 6)
    history = previous_sessions(day, 20)
    _add_vintage(ledger, history[:-1], "2026-11-05T23:30:00+00:00", [100] * 20)
    live_run = _add_vintage(ledger, history, "2026-11-06T23:30:00+00:00", [50] * 21)
    entry, exit_day = advance_sessions(day, 1), advance_sessions(day, 5)
    _add_vintage(ledger, [entry, exit_day], "2026-11-13T23:30:00+00:00", [50, 50])
    row = build_phase3_panel(ledger, ["AAPL"], day.isoformat(), day.isoformat())["rows"][0]
    assert row["price_features"]["r_minus_20"] == pytest.approx(0)
    assert row["feature_price_vintage_run_id"] == live_run
    assert row["feature_provenance_tiers"] == ["LIVE_CAPTURED_PIT"]
    ledger.close()


def test_timely_sip_daily_window_can_be_live_pit():
    day = date(2026, 11, 6)
    bars = [{"ticker": "AAPL", "session_date": session.isoformat(),
             "open_raw": 50, "close_raw": 50, "open_adj": 50, "close_adj": 50}
            for session in previous_sessions(day, 20)]
    captured = datetime(2026, 11, 6, 23, 30, tzinfo=timezone.utc)  # 18:30 ET
    readiness = price_vintage_readiness(bars, "AAPL", day, captured, "sip")
    assert readiness["live"] is True
    assert price_vintage_readiness(bars, "AAPL", day,
                                   datetime(2026, 11, 7, 2, tzinfo=timezone.utc), "sip")["live"] is False
    assert price_vintage_readiness(bars, "AAPL", day, captured, "iex")["live"] is False


def test_daily_capture_records_complete_timely_window_as_one_live_run(monkeypatch):
    from backend.services import us_capture

    captured = datetime(2026, 11, 6, 23, 30, tzinfo=timezone.utc)
    class ClockDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return captured if tz is not None else captured.replace(tzinfo=None)

    class FakeProvider:
        feed = "sip"
        license_tag = "TEST"
        raw_batch_hash = "a" * 64
        effective_end_ts_utc = "2026-11-06T23:10:00+00:00"

        async def fetch(self, tickers, lookback_calendar_days):
            assert lookback_calendar_days == 60
            assert tickers == ["AAPL"]
            return [{"ticker": "AAPL", "session_date": day.isoformat(),
                     "open_raw": 50, "close_raw": 50, "open_adj": 50, "close_adj": 50,
                     "data_feed": "SIP"} for day in previous_sessions(date(2026, 11, 6), 20)]

    monkeypatch.setattr(us_capture, "datetime", ClockDatetime)
    ledger = PitLedger(":memory:")
    result = asyncio.run(capture_daily_price_vintage(ledger, ["AAPL"], FakeProvider()))
    assert result["readiness"]["AAPL"]["live"] is True
    assert len({bar["run_id"] for bar in ledger.rows("eod_price_bars")}) == 1
    assert {bar["provenance_tier"] for bar in ledger.rows("eod_price_bars")} == {"LIVE_CAPTURED_PIT"}
    ledger.close()


def test_missing_sentiment_score_remains_zero_after_fold_transform():
    base = {"price_features": {name: .01 for name in
                               ("r_minus_1", "r_minus_5", "r_minus_20", "sigma_20", "b75_abs_return", "e90_abs_return")}}
    missing = {**base, "event_features": {"has_valid_event": 0, "event_cluster_count": 0,
                                          "has_sec_filing": 0, "scored_cluster_count": 0,
                                          "aggregate_scores": {"mean": None}}}
    scored = {**base, "event_features": {"has_valid_event": 1, "event_cluster_count": 1,
                                         "has_sec_filing": 0, "scored_cluster_count": 1,
                                         "aggregate_scores": {"mean": .8}}}
    train = np.array([_features(missing, True, "mean"), _features(scored, True, "mean")])
    transformed, _ = _standardize(train, train)
    assert transformed[0, -1] == 0
    assert transformed[1, -1] == pytest.approx(.8)


def test_single_retrospective_price_vintage_runs_diagnostic_replay_only():
    ledger = PitLedger(":memory:")
    first, last = date(2026, 9, 1), date(2026, 11, 13)
    days = [first + timedelta(days=offset) for offset in range((last - first).days + 1)
            if is_session(first + timedelta(days=offset))]
    observed = "2026-11-14T00:00:00+00:00"
    _add_vintage(ledger, days, observed,
                 [100 + index * .2 + (index % 4) * .1 for index in range(len(days))],
                 tier="EXPLORATORY_RETROSPECTIVE_NON_PIT")
    panel = build_phase3_panel(ledger, ["AAPL"], "2026-10-07", "2026-11-06",
                               allow_retrospective_diagnostic=True)
    assert len(panel["rows"]) > 15
    assert {row["label_available_at_utc"] for row in panel["rows"]} == {observed}
    strict_maturity = run_walk_forward_phase3(
        {**panel, "allow_retrospective_diagnostic": False},
        min_train_sessions=5, min_train_rows=5, bootstrap_repetitions=20)
    assert strict_maturity["walk_forward"]["evaluated_rows"] == 0
    diagnostic = run_walk_forward_phase3(panel, min_train_sessions=5,
                                        min_train_rows=5, bootstrap_repetitions=20)
    assert diagnostic["walk_forward"]["evaluated_rows"] > 0
    assert diagnostic["walk_forward"]["label_maturity_policy"] == "HYPOTHETICAL_EXIT_SESSION_20_ET_EX_POST_DIAGNOSTIC"
    assert diagnostic["report_validity_tier"] == "EXPLORATORY_NON_PIT_DIAGNOSTIC_ONLY"
    assert diagnostic["signal_acceptance_gate_passed"] is False
    assert diagnostic["actionability_gate_passed"] is False
    assert {row["label_available_at_utc"] for row in panel["rows"]} == {observed}
    ledger.close()


def test_sec_date_only_replay_is_diagnostic_and_strict_pit_stays_empty():
    filing = {"observation_id": "obs-sec", "item_id": "sec-8k", "ticker": "AAPL",
              "headline": "Form 8-K", "item_type": "SEC_FILING", "external_event_key": "accession",
              "published_at_utc": "2026-11-14T19:00:00+00:00",
              "ingested_at_utc": "2026-11-14T19:00:00+00:00",
              "source_filing_date": "2026-11-02",
              "publication_time_basis": "EQUARA_FIRST_OBSERVED_UPPER_BOUND",
              "provenance_tier": "EXPLORATORY_RETROSPECTIVE_NON_PIT"}
    cutoff = datetime(2026, 11, 6, 1, tzinfo=timezone.utc)  # Nov 5, 20:00 ET.
    strict, strict_tiers = _events_at_decision([filing], {}, "AAPL", cutoff,
                                                "ProsusAI/finbert", "pinned", False, 7)
    replay, replay_tiers = _events_at_decision([filing], {}, "AAPL", cutoff,
                                                "ProsusAI/finbert", "pinned", True, 7)
    assert strict == [] and strict_tiers == set()
    assert [item["item_id"] for item in replay] == ["sec-8k"]
    assert replay_tiers == {"EXPLORATORY_RETROSPECTIVE_NON_PIT", "RETROSPECTIVE_EVENT_USED"}
    assert replay[0]["net_score"] is None
