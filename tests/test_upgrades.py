"""Kiểm thử 3 module nâng cấp. Chạy: python -m pytest -q tests"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

from backend.services.sentiment import aggregate_probabilities
from backend.upgrades.portfolio_weighting import (
    Position,
    article_baseline,
    estimate_macro_beta,
    normalize_positions,
    portfolio_sentiment,
)
from backend.upgrades.time_confidence import (
    INSUFFICIENT_LABEL,
    aggregate_signal,
    confidence_weight,
    has_enough_evidence,
    hours_since,
    label_from_score,
    label_with_evidence,
    softmax,
    time_decay_weight,
    weigh_headline,
)
from backend.upgrades.ttl_cache import CachedInference, TTLCache, headline_cache_key

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def item(title, kind, symbol, hours, pos, neg, neu):
    return {
        "title": title,
        "kind": kind,
        "symbol": symbol,
        "published_at": (NOW - timedelta(hours=hours)).isoformat() if hours is not None else None,
        "probabilities": {"positive": pos, "negative": neg, "neutral": neu},
    }


# ---------------- Module 1 ----------------
def test_time_decay_half_life():
    assert time_decay_weight(0, 12) == 1.0
    assert time_decay_weight(12, 12) == pytest.approx(0.5)
    assert time_decay_weight(24, 12) == pytest.approx(0.25)
    assert time_decay_weight(-5, 12) == 1.0  # lệch đồng hồ → coi như vừa đăng
    with pytest.raises(ValueError):
        time_decay_weight(1, 0)


def test_confidence_weight_prefers_clear_news():
    assert confidence_weight({"positive": 0.92, "negative": 0.03, "neutral": 0.05}) == pytest.approx(0.89)
    assert confidence_weight({"positive": 0.45, "negative": 0.45, "neutral": 0.10}) == pytest.approx(0.0)
    assert confidence_weight({"positive": 0.03, "negative": 0.02, "neutral": 0.95}) == pytest.approx(0.01)


def test_hours_since_and_missing_timestamp():
    assert hours_since("2026-11-01T10:00:00Z", NOW) == pytest.approx(2.0)
    assert hours_since("2026-11-01T17:00:00+07:00", NOW) == pytest.approx(2.0)
    assert hours_since(None, NOW) is None
    row = weigh_headline(item("x", "micro", "COMI.EGX", None, 0.9, 0.05, 0.05), NOW)
    assert row.age_is_assumed and row.age_hours == 48.0


def test_aggregate_signal_shrinks_thin_evidence():
    fresh = weigh_headline(item("a", "micro", "A", 0, 0.95, 0.0, 0.05), NOW)
    old = weigh_headline(item("b", "micro", "A", 120, 0.95, 0.0, 0.05), NOW)
    one_fresh = aggregate_signal([fresh], 0.5)
    one_old = aggregate_signal([old], 0.5)
    assert one_fresh.score == pytest.approx(0.95 * 0.95 / (0.95 + 0.5))
    assert abs(one_old.score) < 0.01  # tin 5 ngày tuổi gần như không còn tác dụng
    assert aggregate_signal([], 0.5).score == 0.0
    three = aggregate_signal([fresh, fresh, fresh], 0.5)
    assert three.score > one_fresh.score  # nhiều tin cùng chiều → tin tưởng hơn


def test_label_and_softmax():
    assert label_from_score(0.2) == "Bullish"
    assert label_from_score(-0.2) == "Bearish"
    assert label_from_score(0.1) == "Neutral"
    assert sum(softmax([2.0, 2.0, -3.0])) == pytest.approx(1.0)


# ---------------- Module 2 ----------------
def sample_items():
    return [
        item("COMI bad", "micro", "COMI.EGX", 2, 0.02, 0.95, 0.03),
        item("COMI old good", "micro", "COMI.EGX", 40, 0.90, 0.02, 0.08),
        item("ETEL good", "micro", "ETEL.EGX", 5, 0.90, 0.03, 0.07),
        item("FWRY good", "micro", "FWRY.EGX", 1, 0.93, 0.02, 0.05),
        item("macro bad", "macro", None, 3, 0.05, 0.85, 0.10),
        item("macro good", "macro", None, 30, 0.80, 0.05, 0.15),
    ]


POSITIONS = [Position("COMI.EGX", 70, 1.2), Position("ETEL.EGX", 20, 0.6), Position("FWRY.EGX", 10, 1.0)]


def test_normalize_positions_accepts_percent():
    norm = normalize_positions(POSITIONS)
    assert [p.capital_weight for p in norm] == pytest.approx([0.7, 0.2, 0.1])
    with pytest.raises(ValueError):
        normalize_positions([Position("A", -1, 1.0)])
    with pytest.raises(ValueError):
        normalize_positions([Position("A", 1, 1.0), Position("A", 1, 1.0)])


def test_contributions_add_up_to_portfolio_score():
    result = portfolio_sentiment(sample_items(), POSITIONS, NOW)
    assert sum(h["contribution"] for h in result.headlines) == pytest.approx(result.score)
    assert result.micro_part + result.macro_part == pytest.approx(result.score)
    assert sum(h.contribution for h in result.holdings) == pytest.approx(result.score)


def test_capital_weight_changes_the_answer():
    heavy_comi = portfolio_sentiment(sample_items(), POSITIONS, NOW).score
    heavy_fwry = portfolio_sentiment(
        sample_items(), [Position("COMI.EGX", 10, 1.2), Position("ETEL.EGX", 20, 0.6), Position("FWRY.EGX", 70, 1.0)], NOW
    ).score
    assert heavy_comi < heavy_fwry  # dồn tiền vào mã vừa có tin xấu → danh mục xấu hơn


def test_beta_zero_ignores_macro_and_missing_micro_uses_macro_only():
    items = sample_items()
    r = portfolio_sentiment(items, [Position("ETEL.EGX", 1, 0.0)], NOW)
    assert r.macro_part == pytest.approx(0.0)
    r2 = portfolio_sentiment(items, [Position("ADIB.EGX", 1, 1.0)], NOW)
    assert r2.holdings[0].has_micro_news is False
    assert r2.score == pytest.approx(r2.macro.score)
    assert any("không có tin riêng" in w for w in r2.warnings)


def test_clipping_keeps_score_in_range_and_attribution_exact():
    items = [item("very bad", "micro", "A", 0, 0.0, 1.0, 0.0)] * 5 + [item("macro bad", "macro", None, 0, 0.0, 1.0, 0.0)] * 5
    r = portfolio_sentiment(items, [Position("A", 1, 3.0)], NOW)
    assert r.score == pytest.approx(-1.0)
    assert sum(h["contribution"] for h in r.headlines) == pytest.approx(r.score)


def test_evidence_threshold_defaults_to_prior_strength():
    assert has_enough_evidence(0.5, 0.5) and not has_enough_evidence(0.49, 0.5)
    assert has_enough_evidence(1e-6, 0.0) and not has_enough_evidence(0.0, 0.0)
    assert label_with_evidence(-0.6, evidence=0.3) == INSUFFICIENT_LABEL
    assert label_with_evidence(-0.6, evidence=0.6) == "Bearish"
    assert label_with_evidence(-0.6, evidence=0.3, evidence_threshold=0.2) == "Bearish"


def test_only_stale_news_gives_insufficient_but_keeps_the_score():
    # Giống bộ tin thật 01/11: tin vĩ mô chính trị 44h tuổi, tin doanh nghiệp đã cũ hơn 10 ngày.
    items = [
        item("press crackdown", "macro", None, 44, 0.016, 0.927, 0.057),
        item("court fines journalist", "macro", None, 111, 0.016, 0.908, 0.076),
        item("CIB invests in IPO", "micro", "COMI.EGX", 628, 0.84, 0.008, 0.152),
    ]
    positions = [Position("COMI.EGX", 40, 1.2), Position("ETEL.EGX", 20, 0.6)]
    r = portfolio_sentiment(items, positions, NOW)
    assert r.sentiment == INSUFFICIENT_LABEL and r.evidence_status == "insufficient"
    assert r.score_label == "Bearish" and r.score < -0.15
    assert r.evidence_by_group["macro"] < 0.5 and r.evidence_by_group["COMI.EGX"] < 1e-6
    assert any(w.startswith("Không đủ tin") for w in r.warnings)
    loose = portfolio_sentiment(items, positions, NOW, evidence_threshold=0.0)
    assert loose.score == pytest.approx(r.score) and loose.sentiment == "Bearish"
    assert r.to_dict()["sentiment"] == INSUFFICIENT_LABEL


def test_one_fresh_clear_headline_is_enough():
    r = portfolio_sentiment([item("FWRY record profit", "micro", "FWRY.EGX", 1, 0.93, 0.02, 0.05)], POSITIONS, NOW)
    assert r.evidence_status == "enough" and r.sentiment != INSUFFICIENT_LABEL
    assert portfolio_sentiment(sample_items(), POSITIONS, NOW).evidence_status == "enough"


def test_macro_evidence_does_not_count_when_portfolio_ignores_macro():
    items = [item("macro bad", "macro", None, 0, 0.0, 1.0, 0.0)] * 3
    r = portfolio_sentiment(items, [Position("ETEL.EGX", 1, 0.0)], NOW)
    assert "macro" not in r.evidence_by_group and r.sentiment == INSUFFICIENT_LABEL


def test_article_baseline_matches_core_function():
    items = sample_items()
    base = article_baseline(items)
    _, sentiment, score = aggregate_probabilities([i["probabilities"] for i in items])
    assert base["score"] == pytest.approx(score)
    assert base["sentiment"] == sentiment
    assert sum(base["headline_contributions"]) == pytest.approx(score)


def test_estimate_macro_beta():
    market = [0.01, -0.02, 0.015, 0.003, -0.007]
    assert estimate_macro_beta([2 * m for m in market], market) == pytest.approx(2.0)


# ---------------- Module 3 ----------------
class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_ttl_cache_expiry_and_lru():
    clock = FakeClock()
    cache = TTLCache(ttl_seconds=10, max_items=2, clock=clock)
    cache.set("a", 1)
    assert cache.get("a") == (True, 1)
    clock.t = 11
    assert cache.get("a") == (False, None)
    assert cache.expired == 1
    cache.set("x", 1)
    cache.set("y", 2)
    cache.set("z", 3)
    assert cache.get("x") == (False, None) and cache.evictions == 1


class CountingLocal:
    request_mode = "fake local"

    def __init__(self):
        self.seen: list[str] = []

    async def classify_many(self, texts):
        self.seen.extend(texts)
        return [{"positive": 0.6, "negative": 0.3, "neutral": 0.1} for _ in texts]


class CountingHF:
    request_mode = "fake hf"

    def __init__(self):
        self.requests = 0

    async def classify(self, text):
        self.requests += 1
        return {"positive": 0.2, "negative": 0.7, "neutral": 0.1}


def test_cached_inference_only_scores_new_headlines():
    provider = CountingLocal()
    cached = CachedInference(provider, TTLCache(3600), "ProsusAI/finbert", "rev1")
    first = asyncio.run(cached.classify_many(["a", "b", "c"]))
    second = asyncio.run(cached.classify_many(["b", "c", "d", "d"]))
    assert len(first) == 3 and len(second) == 4
    assert provider.seen == ["a", "b", "c", "d"]
    assert cached.last_call == {"requested": 4, "cache_hits": 3, "model_calls": 1}


def test_cached_inference_cuts_hf_requests():
    provider = CountingHF()
    cached = CachedInference(provider, TTLCache(3600), "ProsusAI/finbert", "rev1")
    for _ in range(5):
        asyncio.run(cached.classify_many(["macro 1", "macro 2", "macro 3", "macro 4"]))
    assert provider.requests == 4  # thay vì 20


def test_cache_key_depends_on_revision():
    assert headline_cache_key("m", "r1", "Hello  world") == headline_cache_key("m", "r1", "Hello world")
    assert headline_cache_key("m", "r1", "Hello") != headline_cache_key("m", "r2", "Hello")


# ---------------- API (fixture mode: không cần model) ----------------
def test_weighted_endpoint_fixture_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "fixture")
    import importlib

    import backend.app as app_module

    app_module = importlib.reload(app_module)
    from fastapi.testclient import TestClient

    with TestClient(app_module.app) as client:
        old = client.post("/api/sentiment/portfolio", json={"symbols": ["COMI", "ETEL", "FWRY"]})
        assert old.status_code == 200
        new = client.post(
            "/api/v2/sentiment/portfolio/weighted",
            json={"positions": [{"symbol": "COMI", "weight": 70, "macro_beta": 1.2}, {"symbol": "ETEL", "weight": 20, "macro_beta": 0.6}, {"symbol": "FWRY", "weight": 10}]},
        )
        assert new.status_code == 200, new.text
        body = new.json()
        assert body["article_method"]["score"] == pytest.approx(old.json()["score"])
        assert sum(h["contribution"] for h in body["upgraded_method"]["headlines"]) == pytest.approx(body["upgraded_method"]["score"])
        bad = client.post("/api/v2/sentiment/portfolio/weighted", json={"positions": [{"symbol": "COMI", "weight": 0}]})
        assert bad.status_code == 422
        assert client.get("/api/v2/cache/stats").status_code == 200


def test_upgrade_demo_rebuild_from_saved_run_matches_and_needs_no_model(tmp_path):
    import json

    from scripts.run_upgrade_demo import compare_methods, rebuild_from_run

    stale = [
        item("press crackdown", "macro", None, 44, 0.016, 0.927, 0.057),
        item("CIB invests in IPO", "micro", "COMI.EGX", 628, 0.84, 0.008, 0.152),
    ]
    for rows in (sample_items(), stale):
        for row in rows:
            row["source"] = "test"
    real_positions = [Position("COMI.EGX", 0.6, 1.2), Position("ETEL.EGX", 0.4, 0.6)]
    case = {"title": "x", "source": "test", "logits": {"positive": 2.0, "negative": 1.9, "neutral": -3.0}}
    case["sigmoid"] = {"positive": 0.88, "negative": 0.87, "neutral": 0.05}
    case["softmax"] = {"positive": 0.52, "negative": 0.47, "neutral": 0.01}
    trace = [
        {"request": i + 1, "label": f"r{i}", "headlines": 6, "direct_ms": 400.0, "cached_ms": 100.0 if i == 0 else 0.2, "cache_hits": 0 if i == 0 else 6, "model_calls": 6 if i == 0 else 0}
        for i in range(3)
    ]
    saved = {
        "run_at_utc": NOW.isoformat(),
        "model": "ProsusAI/finbert",
        "runtime": {"torch": "2.x", "device": "cpu", "threads": 2},
        "scenario": {"now_utc": NOW.isoformat(), "positions": [p.__dict__ for p in normalize_positions(POSITIONS)], **compare_methods(sample_items(), POSITIONS, NOW)},
        "real_rss": {"now_utc": NOW.isoformat(), "positions": [p.__dict__ for p in real_positions], **compare_methods(stale, real_positions, NOW)},
        "softmax_demo": {"chosen": [case, case], "all_cases": [case]},
        "latency": {
            "repeats": 1,
            "trace": trace,
            "summary": {
                "Gọi trực tiếp\n(bài báo)": {"mean_ms": 400.0, "p95_ms": 400.0, "total_ms": 1200.0, "model_calls": 18},
                "Có TTL cache\n(code mới)": {"mean_ms": 33.5, "p95_ms": 100.0, "total_ms": 100.4, "model_calls": 6},
            },
        },
    }
    run = tmp_path / "run"
    run.mkdir()
    (run / "upgrade_results.json").write_text(json.dumps(saved), encoding="utf-8")

    results = rebuild_from_run(run, tmp_path / "out")
    assert results["scenario"]["full"]["score"] == pytest.approx(saved["scenario"]["full"]["score"])
    assert results["real_rss"]["full"]["sentiment"] == INSUFFICIENT_LABEL
    assert results["real_rss"]["module1_only"]["sentiment"] == INSUFFICIENT_LABEL
    assert results["latency"]["hf_http_requests"]["batched_direct"] == 3 and results["latency"]["hf_http_requests"]["batched_cached"] == 1
    table = (tmp_path / "out" / "BANG_SO_LIEU.md").read_text(encoding="utf-8")
    assert "Không đủ tin" in table and "Trạng thái bằng chứng" in table
    for name in ("chart1_softmax_time_decay.png", "chart2_portfolio_article_vs_upgrade.png", "chart3_latency_cache.png"):
        assert (tmp_path / "out" / name).stat().st_size > 0


def test_zero_weight_holding_cannot_supply_evidence():
    positions = [Position("COMI.EGX", 100, 0), Position("FWRY.EGX", 0, 0)]
    result = portfolio_sentiment([item("Fawry grows", "micro", "FWRY.EGX", 0, .98, .01, .01)], positions, NOW)
    assert result.sentiment == INSUFFICIENT_LABEL and result.score == 0
