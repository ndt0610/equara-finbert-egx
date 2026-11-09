"""Kiểm thử máy chủ FinBERT tự dựng theo định dạng Hugging Face (scripts/serve_hf_api.py).

Model thật được thay bằng bộ phân loại giả trả đúng xác suất FinBERT local đã lưu, để kiểm thử
chạy nhanh và không cần tải model. Phần HTTP là thật: máy chủ uvicorn mở cổng trên 127.0.0.1.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from backend.config import MODEL_ID, Settings, is_huggingface_url
from backend.providers.hf_inference import HuggingFaceFinBERT
from backend.providers.news import NewsItem
from backend.services.sentiment import SentimentService
from scripts.check_hf_api import DEFAULT_REFERENCE, load_reference, run_check, summary_lines, write_result
from scripts.serve_hf_api import MAX_INPUTS_PER_REQUEST, create_app

REFERENCE = load_reference(DEFAULT_REFERENCE)
BY_TITLE = dict(zip(REFERENCE["titles"], REFERENCE["probabilities"]))
NEUTRAL = {"positive": 0.1, "negative": 0.1, "neutral": 0.8}


class FakeFinBERT:
    revision = "0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031"
    device_name = "cpu"

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    async def classify_many(self, texts: list[str]) -> list[dict[str, float]]:
        self.batches.append(list(texts))
        return [dict(BY_TITLE.get(text, NEUTRAL)) for text in texts]


@pytest.fixture
def live_server():
    """Máy chủ tự dựng chạy thật trên một cổng trống, ghi lại header của mọi request nhận được."""
    fake = FakeFinBERT()
    app = create_app(fake)
    seen_headers: list[dict[str, str]] = []

    @app.middleware("http")
    async def record(request, call_next):
        seen_headers.append({k.lower(): v for k, v in request.headers.items()})
        return await call_next(request)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    assert server.started, "máy chủ không khởi động được"
    yield {
        "url": f"http://127.0.0.1:{port}/models/{MODEL_ID}",
        "base": f"http://127.0.0.1:{port}",
        "app": app,
        "fake": fake,
        "headers": seen_headers,
    }
    server.should_exit = True
    thread.join(timeout=5)
    sock.close()


def test_only_https_huggingface_hosts_get_the_token():
    assert is_huggingface_url("https://router.huggingface.co/hf-inference/models/ProsusAI/finbert")
    assert is_huggingface_url("https://huggingface.co/api")
    assert not is_huggingface_url("http://router.huggingface.co/x")  # không mã hóa
    assert not is_huggingface_url("https://huggingface.co.evil.example/x")
    assert not is_huggingface_url("http://127.0.0.1:8001/models/ProsusAI/finbert")


def test_server_speaks_the_huggingface_text_classification_format():
    fake = FakeFinBERT()
    client = TestClient(create_app(fake))
    url = f"/models/{MODEL_ID}"
    title = REFERENCE["titles"][0]
    params = {"top_k": 3, "function_to_apply": "softmax"}

    one = client.post(url, json={"inputs": title, "parameters": params})
    assert one.status_code == 200
    rows = one.json()
    assert [r["label"] for r in rows] == sorted(BY_TITLE[title], key=lambda k: -BY_TITLE[title][k])
    assert {r["label"]: r["score"] for r in rows} == BY_TITLE[title]

    many = client.post(url, json={"inputs": REFERENCE["titles"][:3], "parameters": params}).json()
    assert len(many) == 3 and all(len(r) == 3 for r in many)  # mỗi tiêu đề một danh sách 3 nhãn
    assert fake.batches[-1] == REFERENCE["titles"][:3]  # cả lô chạy model một lần

    assert len(client.post(url, json={"inputs": title}).json()) == 1  # top_k mặc định = 1 như HF
    assert client.post("/models/other/model", json={"inputs": title}).status_code == 404
    assert client.post(url, json={"text": title}).status_code == 400
    assert client.post(url, json={"inputs": ["ok", ""]}).status_code == 400
    assert client.post(url, json={"inputs": ["x"] * (MAX_INPUTS_PER_REQUEST + 1)}).status_code == 413
    bad = client.post(url, json={"inputs": title, "parameters": {"function_to_apply": "sigmoid"}})
    assert bad.status_code == 422 and "error" in bad.json()
    assert client.get("/stats").json() == {"http_requests": 8, "inputs": 5, "errors": 5}
    assert client.get("/health").json()["server"] == "self-hosted (not huggingface.co)"


def test_article_adapter_runs_over_real_http_without_token(live_server):
    async def go():
        async with httpx.AsyncClient(timeout=10) as client:
            return await run_check(REFERENCE, client, None, endpoint=live_server["url"])

    result = asyncio.run(go())
    assert result["ok"] and result["self_hosted"] and result["server"].startswith("self-hosted")
    assert result["http_requests"] == 1 and result["batch_supported"] is True
    assert result["one_by_one"]["http_requests"] == 7
    assert result["max_abs_diff"] < 1e-12 and result["labels_agree"] == 7
    stats = httpx.get(f"{live_server['base']}/stats").json()
    # máy chủ đếm đúng: 1 request khởi động + 3 vòng x (1 lô 7 tiêu đề + 7 request 1 tiêu đề)
    assert stats == {"http_requests": 1 + 3 * (1 + 7), "inputs": 1 + 3 * (7 + 7), "errors": 0}
    lines = summary_lines(result)
    assert "CHẠY THẬT qua HTTP" in lines[0] and "không phải máy chủ của Hugging Face" in lines[-1]


def test_hf_token_is_never_sent_to_a_self_hosted_server(live_server, tmp_path):
    token = "hf_secret_khong_duoc_roi_khoi_may"

    async def go():
        async with httpx.AsyncClient(timeout=10) as client:
            return await run_check(REFERENCE, client, token, endpoint=live_server["url"], compare_one_by_one=False)

    result = asyncio.run(go())
    assert result["ok"]
    posts = [h for h in live_server["headers"] if "content-type" in h]
    assert posts and all("authorization" not in h for h in posts)
    path = write_result(result, tmp_path)
    assert path.name == "self_hosted_api_check.json" and token not in path.read_text(encoding="utf-8")


def test_web_app_portfolio_flow_through_self_hosted_server(monkeypatch):
    """Luồng danh mục của web app: INFERENCE_PROVIDER=hf-inference trỏ vào máy chủ tự dựng, không cần HF_TOKEN."""
    fake = FakeFinBERT()
    server_app = create_app(fake)
    monkeypatch.setenv("DEMO_MODE", "live")
    monkeypatch.setenv("INFERENCE_PROVIDER", "hf-inference")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACEHUB_API_TOKEN", raising=False)
    monkeypatch.setenv("HF_INFERENCE_URL", f"http://selfhosted.local/models/{MODEL_ID}")
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=server_app))
    service = SentimentService(client, Settings.from_environment())

    async def fake_stock(symbol, limit):
        return (
            [NewsItem(f"{symbol} headline {i}", f"https://n/{symbol}/{i}", None, "test", "micro", symbol) for i in range(limit)],
            [{"provider": "test", "kind": "micro", "status": f"ok:{limit}"}],
        )

    async def fake_macro(limit):
        titles = REFERENCE["titles"][:limit]
        return (
            [NewsItem(t, f"https://n/macro/{i}", None, "test", "macro") for i, t in enumerate(titles)],
            [{"provider": "test", "kind": "macro", "status": f"used:{limit}"}],
        )

    monkeypatch.setattr(service.news, "collect_stock", fake_stock)
    monkeypatch.setattr(service.news, "collect_macro", fake_macro)
    result = asyncio.run(service.analyze_portfolio(["COMI.EGX", "ETEL.EGX", "FWRY.EGX", "ADIB.EGX", "EFIH.EGX"]))
    assert result["news_count"] == 14  # 4 macro + 2 x 5 mã
    assert result["inference_http_requests"] == 1 and len(fake.batches) == 1  # 14 tiêu đề, 1 request
    assert "self-hosted" in result["inference"]["request_mode"]
    assert server_app.state.stats["http_requests"] == 1
    asyncio.run(client.aclose())
