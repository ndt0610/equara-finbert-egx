"""Kiểm thử phần "hiện rõ dữ liệu lấy trực tiếp": mỗi lượt gọi nguồn tin ghi lúc gọi, địa chỉ đã gọi
(không lộ khóa API), mã HTTP, thời gian chờ; response có khối data_freshness; tin dùng lại được đánh dấu."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from backend.config import Settings
from backend.providers.news import NewsAggregator, public_url
from backend.services.sentiment import SentimentService
from backend.upgrades.portfolio_weighting import Position
from backend.upgrades.service import UpgradedPortfolioService

SECRET = "eodhd_secret_khong_duoc_hien"
NOW = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def _rss(*titles: str) -> bytes:
    items = "".join(
        f"<item><title>{t}</title><link>https://news.example/{i}</link><pubDate>{NOW}</pubDate>"
        f"<description>Egypt EGX {t}</description></item>"
        for i, t in enumerate(titles)
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{items}</channel></rss>'.encode()


def _handler(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    if host == "eodhd.com":
        return httpx.Response(200, json=[])  # như thực tế: HTTP 200, danh sách rỗng
    if host == "news.google.com":
        return httpx.Response(200, content=_rss("Commercial International Bank CIB profit rises in Egypt"))
    if host == "feeds.bbci.co.uk":
        return httpx.Response(200, content=_rss("Egypt inflation slows", "Egypt central bank holds rates"))
    return httpx.Response(404)


def _settings(monkeypatch, token: str | None = SECRET) -> Settings:
    monkeypatch.setenv("DEMO_MODE", "live")
    monkeypatch.setenv("INFERENCE_PROVIDER", "hf-inference")
    monkeypatch.setenv("HF_INFERENCE_URL", "http://selfhosted.local/models/ProsusAI/finbert")
    if token:
        monkeypatch.setenv("EODHD_NEWS_API_TOKEN", token)
    else:
        monkeypatch.delenv("EODHD_NEWS_API_TOKEN", raising=False)
    return Settings.from_environment()


def test_public_url_drops_secret_parameters():
    url = public_url("https://eodhd.com/api/news", {"s": "COMI.EGX", "api_token": SECRET, "fmt": "json"})
    assert SECRET not in url and "api_token" not in url and "s=COMI.EGX" in url


def test_each_news_call_records_time_url_status_and_never_the_token(monkeypatch):
    news = NewsAggregator(httpx.AsyncClient(transport=httpx.MockTransport(_handler)), _settings(monkeypatch))
    items, statuses = asyncio.run(news.collect_stock("COMI.EGX", limit=15))
    assert [s["provider"] for s in statuses] == ["EODHD", "Google News RSS"]
    eodhd, google = statuses
    assert eodhd["status"] == "empty:0" and eodhd["http_status"] == 200
    assert SECRET not in eodhd["query_url"] and "s=COMI.EGX" in eodhd["query_url"]
    assert google["status"] == "used:1" and google["query_url"].startswith("https://news.google.com/rss/search?q=")
    for row in statuses:
        assert row["symbol"] == "COMI.EGX"
        assert datetime.fromisoformat(row["fetched_at"]).tzinfo is not None
        assert isinstance(row["elapsed_ms"], int) and row["elapsed_ms"] >= 0
    assert items[0].source == "Google News RSS"

    _, macro = asyncio.run(news.collect_macro(limit=4))
    assert [m["provider"] for m in macro] == ["EODHD general news + Egypt filter", "BBC RSS", "Google News RSS"]
    assert "fetched_at" in macro[1] and "fetched_at" not in macro[2]  # Google bị bỏ qua: không có lượt gọi
    assert all(SECRET not in str(row) for row in statuses + macro)


def test_live_response_has_freshness_block(monkeypatch):
    service = SentimentService(httpx.AsyncClient(transport=httpx.MockTransport(_handler)), _settings(monkeypatch, None))

    async def fake_classify(texts):
        return [{"positive": 0.2, "negative": 0.1, "neutral": 0.7} for _ in texts]

    monkeypatch.setattr(service.inference, "classify_many", fake_classify)
    result = asyncio.run(service.analyze_stock("COMI.EGX"))
    fresh = result["data_freshness"]
    assert fresh["live"] is True and fresh["news_collection_ms"] >= 0
    assert datetime.fromisoformat(fresh["requested_at_utc"]) <= datetime.fromisoformat(fresh["completed_at_utc"])
    called = [p for p in result["providers"] if "fetched_at" in p]
    assert {p["provider"] for p in called} == {"Google News RSS", "BBC RSS"}  # EODHD chưa có token: không gọi


def test_weighted_portfolio_marks_reused_news(monkeypatch):
    service = SentimentService(httpx.AsyncClient(transport=httpx.MockTransport(_handler)), _settings(monkeypatch, None))

    async def fake_classify(texts):
        return [{"positive": 0.2, "negative": 0.1, "neutral": 0.7} for _ in texts]

    monkeypatch.setattr(service.inference, "classify_many", fake_classify)
    upgraded = UpgradedPortfolioService(service)
    args = dict(half_life_hours={"micro": 12, "macro": 24}, prior_strength=0.5, neutral_band=0.05)
    positions = [Position("COMI.EGX", 70, 1.2), Position("ETEL.EGX", 30, 0.6)]
    first = asyncio.run(upgraded.analyze_weighted_portfolio(positions, **args))
    second = asyncio.run(upgraded.analyze_weighted_portfolio(positions, **args))
    assert first["data_freshness"]["news_groups_from_cache"] == 0
    assert not any(p.get("cached") for p in first["providers"])
    assert second["data_freshness"]["news_groups_from_cache"] == 3 == second["data_freshness"]["news_groups_total"]
    reused = [p for p in second["providers"] if "fetched_at" in p]
    assert reused and all(p["cached"] and p["status"].startswith("cache_hit(") for p in reused)
    # giờ gọi giữ nguyên lần lấy thật đầu tiên, nên giao diện ghi "dùng lại tin đã lấy lúc …"
    assert {p["fetched_at"] for p in reused} <= {p["fetched_at"] for p in first["providers"] if "fetched_at" in p}


def test_stale_sources_continue_to_next_feed(monkeypatch):
    from backend.providers.news import NewsItem
    news = NewsAggregator(None, _settings(monkeypatch))
    async def stale(*args, **kwargs):
        return [NewsItem("Old news", None, "2000-01-01T00:00:00+00:00", "test", "macro", None)]
    async def fresh(*args, **kwargs):
        return [NewsItem("Egypt today", None, datetime.now(timezone.utc).isoformat(), "RSS", "macro", None)]
    for name in ("_eodhd_stock", "_eodhd_egypt_macro", "_bbc_macro"):
        monkeypatch.setattr(news, name, stale)
    for name in ("_google_stock", "_google_macro"):
        monkeypatch.setattr(news, name, fresh)
    for rows, statuses in (asyncio.run(news.collect_stock("COMI.EGX")), asyncio.run(news.collect_macro())):
        assert [row.title for row in rows] == ["Egypt today"]
        assert all(s["status"] == "stale:1" for s in statuses[:-1])
        assert statuses[-1]["status"] == "used:1"

def test_failed_sources_continue(monkeypatch):
    async def failed(*args, **kwargs):
        raise httpx.ConnectError("offline")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
            news = NewsAggregator(client, _settings(monkeypatch))
            for method in ("_eodhd_stock", "_eodhd_egypt_macro", "_bbc_macro"):
                monkeypatch.setattr(news, method, failed)
            for items, statuses in (await news.collect_stock("COMI.EGX"), await news.collect_macro()):
                assert items and all(row["status"] == "failed" for row in statuses[:-1])
                assert statuses[-1]["status"].startswith("used:")
    asyncio.run(run())
