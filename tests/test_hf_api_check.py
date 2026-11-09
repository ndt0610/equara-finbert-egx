"""Kiểm thử lệnh kiểm tra Hugging Face API thật (scripts/check_hf_api.py) bằng Hugging Face giả lập."""

from __future__ import annotations

import asyncio
import json

import httpx

from backend.providers.hf_inference import HuggingFaceFinBERT
from scripts.check_hf_api import DEFAULT_REFERENCE, load_reference, run_check, summary_lines, write_result

TOKEN = "hf_test_token_khong_duoc_in_ra"


async def _no_sleep(_seconds: float) -> None:
    return None


def _rows(probabilities: dict[str, float], mix: float = 0.0) -> list[dict[str, object]]:
    # mix > 0: trộn với phân phối đều, giả lập một phiên bản model khác (tổng vẫn = 1)
    p = {label: (1 - mix) * score + mix / 3 for label, score in probabilities.items()}
    return [{"label": label, "score": score} for label, score in sorted(p.items(), key=lambda kv: -kv[1])]


def _answer(inputs, by_title, mix: float = 0.0):
    # Giống Hugging Face: 1 chuỗi -> 1 danh sách nhãn; danh sách chuỗi -> mỗi chuỗi 1 danh sách nhãn
    if isinstance(inputs, str):
        return _rows(by_title[inputs], mix)
    return [_rows(by_title[title], mix) for title in inputs]


def _check(handler, token: str | None = TOKEN) -> dict:
    reference = load_reference(DEFAULT_REFERENCE)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HuggingFaceFinBERT(client, token, sleep=_no_sleep)
    return asyncio.run(run_check(reference, client, token, adapter=adapter))


def test_hf_check_real_flow_one_batch_request_and_matching_probabilities(tmp_path):
    reference = load_reference(DEFAULT_REFERENCE)
    by_title = dict(zip(reference["titles"], reference["probabilities"]))
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        assert body["parameters"] == {"top_k": 3, "function_to_apply": "softmax"}
        return httpx.Response(200, json=_answer(body["inputs"], by_title))

    result = _check(handler)
    assert len(reference["titles"]) == 7
    assert result["ok"] and result["status_code"] == 200 and result["server"] == "huggingface.co"
    assert result["http_requests"] == 1 and result["batch_supported"] is True
    assert result["one_by_one"]["ok"] and result["one_by_one"]["http_requests"] == 7
    # 1 request khởi động + 3 vòng đo, mỗi vòng 1 request theo lô và 7 request từng tiêu đề
    assert len(seen) == 1 + 3 * (1 + 7)
    assert result["timing"]["rounds"] == 3 and len(result["elapsed_seconds_each_round"]) == 3
    assert all(r.headers["Authorization"] == f"Bearer {TOKEN}" for r in seen)
    assert result["max_abs_diff"] < 1e-12 and result["labels_agree"] == 7 and result["same_model_version"]
    path = write_result(result, tmp_path)
    assert path.name == "hf_api_check.json"
    assert TOKEN not in path.read_text(encoding="utf-8")
    lines = summary_lines(result)
    assert "Hugging Face API CHẠY THẬT" in lines[0] and "7 request" in lines[4]


def test_hf_check_flags_a_different_model_version():
    reference = load_reference(DEFAULT_REFERENCE)
    by_title = dict(zip(reference["titles"], reference["probabilities"]))

    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.content)["inputs"]
        return httpx.Response(200, json=_answer(inputs, by_title, mix=0.1))

    result = _check(handler)
    assert result["ok"] and not result["same_model_version"]
    assert 1e-3 < result["max_abs_diff"] < 0.1
    assert "lệch" in summary_lines(result)[2]


def test_hf_check_reports_402_and_missing_token_without_leaking_token(tmp_path):
    calls: list[int] = []

    def no_credit(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(402, json={"error": "You have exceeded your monthly included credits"})

    result = _check(no_credit)
    assert not result["ok"] and result["status_code"] == 402 and "credit" in result["hint"]
    assert len(calls) == 1  # 402 không được thử lại, không bị che bởi việc quay về gửi từng tiêu đề
    assert TOKEN not in write_result(result, tmp_path).read_text(encoding="utf-8")

    missing = _check(no_credit, token=None)
    assert not missing["ok"] and missing["status_code"] == 424 and "HF_TOKEN" in missing["hint"]
    assert len(calls) == 1  # thiếu token thì không gửi request nào
