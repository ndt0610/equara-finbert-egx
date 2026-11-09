"""Kiểm thử phần lõi (trước đây dự án chưa có kiểm thử nào). Chạy: python -m pytest -q tests"""

from __future__ import annotations

import asyncio
import importlib
import json

import httpx
import pytest

from backend.config import Settings
from backend.providers.hf_inference import HuggingFaceFinBERT, InferenceProviderError
from backend.providers.news import NewsItem, _parse_datetime, deduplicate
from backend.schemas import normalize_symbol
from backend.services.sentiment import SentimentService, aggregate_probabilities

GOOD = [
    {"label": "positive", "score": 0.7},
    {"label": "negative", "score": 0.1},
    {"label": "neutral", "score": 0.2},
]


# ---------------- Chuẩn hóa mã, loại trùng, ngày giờ ----------------
def test_normalize_symbol():
    assert normalize_symbol(" comi ") == "COMI.EGX"
    assert normalize_symbol("ETEL.EGX") == "ETEL.EGX"
    with pytest.raises(ValueError):
        normalize_symbol("COMI.NYSE")


def test_deduplicate_by_canonical_url_then_title():
    items = [
        NewsItem("A", "https://x.com/news/1?utm=1", None, "s", "micro"),
        NewsItem("A copy", "https://X.com/news/1/", None, "s", "micro"),
        NewsItem("Same title!", None, None, "s", "macro"),
        NewsItem("same   TITLE", None, None, "s", "macro"),
    ]
    assert [i.title for i in deduplicate(items)] == ["A", "Same title!"]


def test_parse_datetime_formats():
    assert _parse_datetime("Sun, 01 Nov 2026 10:00:00 GMT") == "2026-11-01T10:00:00+00:00"
    assert _parse_datetime("2026-11-01T17:00:00+07:00") == "2026-11-01T10:00:00+00:00"
    assert _parse_datetime("not a date") is None


# ---------------- Công thức gốc của bài báo (tái dựng) ----------------
def test_aggregate_probabilities_article_rule():
    rows = [
        {"positive": 0.8, "negative": 0.1, "neutral": 0.1},
        {"positive": 0.2, "negative": 0.6, "neutral": 0.2},
    ]
    probs, label, score = aggregate_probabilities(rows)
    assert probs["positive"] == pytest.approx(0.5)
    assert score == pytest.approx(0.15)
    assert label == "Bullish"
    with pytest.raises(ValueError):
        aggregate_probabilities([])


# ---------------- Lỗi nhập liệu phải là 422, không phải 500 ----------------
@pytest.fixture()
def fixture_client(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "fixture")
    import backend.app as app_module

    app_module = importlib.reload(app_module)
    from fastapi.testclient import TestClient

    with TestClient(app_module.app, raise_server_exceptions=False) as client:
        yield client


def test_invalid_exchange_returns_422_with_vietnamese_message(fixture_client):
    response = fixture_client.post("/api/sentiment/stock", json={"symbol": "COMI.NYSE"})
    assert response.status_code == 422
    assert "EGX" in response.json()["error"]["message"]


def test_duplicate_symbols_returns_422(fixture_client):
    response = fixture_client.post("/api/sentiment/portfolio", json={"symbols": ["COMI", "comi"]})
    assert response.status_code == 422
    assert "trùng" in response.json()["error"]["message"]


# ---------------- HF API: thử lại khi 429/503 ----------------
def hf_client(responses: list[httpx.Response]) -> tuple[httpx.AsyncClient, list[int]]:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


async def _no_sleep(_seconds: float) -> None:
    return None


def test_hf_retries_after_503_then_succeeds():
    waits: list[float] = []

    async def record(seconds: float) -> None:
        waits.append(seconds)

    client, calls = hf_client([httpx.Response(503, json={"error": "loading", "estimated_time": 3.5}), httpx.Response(200, json=GOOD)])
    provider = HuggingFaceFinBERT(client, "token", sleep=record)
    scores = asyncio.run(provider.classify("CIB profit rises"))
    assert scores["positive"] == pytest.approx(0.7)
    assert len(calls) == 2 and provider.retries_used == 1
    assert waits == [3.5]  # chờ đúng estimated_time server báo


def test_hf_gives_up_after_max_retries_on_429():
    client, calls = hf_client([httpx.Response(429, headers={"Retry-After": "1"})])
    provider = HuggingFaceFinBERT(client, "token", max_retries=2, sleep=_no_sleep)
    with pytest.raises(InferenceProviderError) as info:
        asyncio.run(provider.classify("x"))
    assert info.value.status_code == 429
    assert len(calls) == 3


def test_hf_does_not_retry_auth_errors():
    client, calls = hf_client([httpx.Response(401)])
    provider = HuggingFaceFinBERT(client, "token", sleep=_no_sleep)
    with pytest.raises(InferenceProviderError):
        asyncio.run(provider.classify("x"))
    assert len(calls) == 1


# ---------------- Luồng live (tin + inference giả lập): thứ tự & kết quả giữ nguyên ----------------
def hf_batch_client(batch_status: int = 200) -> tuple[httpx.AsyncClient, list[object]]:
    """Giả lập HF: `inputs` là chuỗi → 1 danh sách 3 nhãn; là mảng → mỗi đầu vào 1 danh sách (bài báo mục 8)."""
    bodies: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.content)["inputs"]
        bodies.append(inputs)
        if isinstance(inputs, list):
            if batch_status != 200:
                return httpx.Response(batch_status, json={"error": "inputs must be a string"})
            return httpx.Response(200, json=[GOOD for _ in inputs])
        return httpx.Response(200, json=GOOD)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), bodies


def test_hf_batch_sends_up_to_15_headlines_per_request():
    client, bodies = hf_batch_client()
    provider = HuggingFaceFinBERT(client, "token", sleep=_no_sleep)
    scores = asyncio.run(provider.classify_many([f"headline {i}" for i in range(16)]))
    assert len(scores) == 16 and scores[0]["positive"] == pytest.approx(0.7)
    assert [len(b) if isinstance(b, list) else 1 for b in bodies] == [15, 1]  # 2 request thay vì 16
    assert provider.http_requests == 2 and provider.batch_supported is True


def test_hf_batch_falls_back_to_single_when_rejected_and_remembers():
    client, bodies = hf_batch_client(batch_status=400)
    provider = HuggingFaceFinBERT(client, "token", sleep=_no_sleep)
    first = asyncio.run(provider.classify_many(["a", "b", "c"]))
    assert len(first) == 3 and provider.batch_supported is False
    assert isinstance(bodies[0], list) and bodies[1:] == ["a", "b", "c"]  # 1 lô bị từ chối + 3 request đơn
    bodies.clear()
    asyncio.run(provider.classify_many(["d", "e"]))
    assert bodies == ["d", "e"]  # lần sau không thử lô nữa
    assert "one headline" in provider.request_mode


def test_hf_batch_wrong_shape_falls_back():
    client, calls = hf_client([httpx.Response(200, json=GOOD)])  # trả 1 kết quả cho 2 đầu vào
    provider = HuggingFaceFinBERT(client, "token", sleep=_no_sleep)
    scores = asyncio.run(provider.classify_many(["a", "b"]))
    assert len(scores) == 2 and len(calls) == 3 and provider.batch_supported is False


def test_hf_batch_auth_error_is_not_masked_by_fallback():
    client, calls = hf_client([httpx.Response(401)])
    provider = HuggingFaceFinBERT(client, "token", sleep=_no_sleep)
    with pytest.raises(InferenceProviderError) as info:
        asyncio.run(provider.classify_many(["a", "b"]))
    assert info.value.status_code == 401 and len(calls) == 1


def test_live_portfolio_flow_with_parallel_news(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "live")
    monkeypatch.setenv("INFERENCE_PROVIDER", "hf-inference")
    monkeypatch.setenv("HF_TOKEN", "test-token")
    client, calls = hf_batch_client()
    service = SentimentService(client, Settings.from_environment())

    async def fake_stock(symbol, limit):
        await asyncio.sleep(0.01 if symbol.startswith("COMI") else 0)  # về đích lệch nhau
        if symbol == "FWRY.EGX":
            return [], [{"provider": "Google News RSS", "kind": "micro", "status": "empty:0"}]
        return (
            [NewsItem(f"{symbol} headline {i}", f"https://n/{symbol}/{i}", f"2026-11-01T0{i}:00:00+00:00", "test", "micro", symbol) for i in range(limit)],
            [{"provider": "Google News RSS", "kind": "micro", "status": f"ok:{limit}"}],
        )

    async def fake_macro(limit):
        return (
            [NewsItem(f"Egypt macro {i}", f"https://n/macro/{i}", f"2026-10-31T0{i}:00:00+00:00", "test", "macro") for i in range(limit)],
            [{"provider": "BBC RSS", "kind": "macro", "status": f"used:{limit}"}],
        )

    monkeypatch.setattr(service.news, "collect_stock", fake_stock)
    monkeypatch.setattr(service.news, "collect_macro", fake_macro)
    result = asyncio.run(service.analyze_portfolio(["COMI.EGX", "ETEL.EGX", "FWRY.EGX"]))
    assert result["news_count"] == 8  # 2 COMI + 2 ETEL + 0 FWRY + 4 macro
    assert result["inference_http_requests"] == 1 == len(calls)  # 8 tiêu đề trong 1 request (bài báo mục 8)
    assert len(calls[0]) == 8
    assert result["warnings"][0] == "Không tìm thấy tin micro cho FWRY.EGX."
    assert [p["kind"] for p in result["providers"]] == ["micro", "micro", "micro", "macro"]
    assert result["sentiment"] == "Bullish" and result["score"] == pytest.approx(0.6)
    json.dumps(result)  # serialize được


# ---------------- GET như sơ đồ mục 3 bài báo: cùng JSON với POST ----------------
def test_get_routes_match_post_routes(fixture_client):
    get_stock = fixture_client.get("/api/sentiment/stock", params={"symbol": "COMI"})
    post_stock = fixture_client.post("/api/sentiment/stock", json={"symbol": "COMI"})
    assert get_stock.status_code == 200 and get_stock.json() == post_stock.json()
    get_port = fixture_client.get("/api/sentiment/portfolio", params={"symbols": "COMI, ETEL,FWRY"})
    post_port = fixture_client.post("/api/sentiment/portfolio", json={"symbols": ["COMI", "ETEL", "FWRY"]})
    assert get_port.status_code == 200 and get_port.json() == post_port.json()


def test_get_routes_validate_like_post(fixture_client):
    bad = fixture_client.get("/api/sentiment/stock", params={"symbol": "COMI.NYSE"})
    assert bad.status_code == 422 and "EGX" in bad.json()["error"]["message"]
    dup = fixture_client.get("/api/sentiment/portfolio", params={"symbols": "COMI,comi"})
    assert dup.status_code == 422 and "trùng" in dup.json()["error"]["message"]
    missing = fixture_client.get("/api/sentiment/stock")
    assert missing.status_code == 422


@pytest.mark.parametrize("value", ["NaN", float("inf"), -0.2, 1.2, 0.71])
def test_invalid_softmax_is_rejected(value):
    rows = [dict(row) for row in GOOD]
    rows[0]["score"] = value
    with pytest.raises(InferenceProviderError):
        HuggingFaceFinBERT._scores_from_rows(rows)

def test_softmax_missing_label():
    with pytest.raises(InferenceProviderError):
        HuggingFaceFinBERT._scores_from_rows(GOOD[:-1])


def test_rounded_four_decimal_softmax():
    values = [0.8869, 0.0712, 0.0420]
    rows = [dict(row, score=value) for row, value in zip(GOOD, values)]
    assert HuggingFaceFinBERT._scores_from_rows(rows) == {r["label"]: r["score"] for r in rows}
