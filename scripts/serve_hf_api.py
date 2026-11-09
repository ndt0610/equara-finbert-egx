"""Máy chủ FinBERT tự dựng, trả lời đúng định dạng Hugging Face Inference API (text-classification).

Vì sao có file này
------------------
Bài báo (mục 5 và 8) gọi FinBERT qua Hugging Face Inference API, và mục 8 tự so sánh hai cách:
serverless (Hugging Face lo máy chủ, trả tiền theo lượt gọi) và self-hosted (tự chạy model).
Từ tháng 10/2026 tài khoản Hugging Face miễn phí không còn credit Inference Providers, nên mọi lượt
gọi đều bị HTTP 402. File này là phương án self-hosted: chạy chính FinBERT bản ghim 0bc2ac10 và
mở một địa chỉ HTTP nhận và trả JSON giống hệt Hugging Face. Nhờ vậy adapter của bài báo
(`backend/providers/hf_inference.py`) chạy thật qua HTTP mà không phải sửa một dòng nào,
chỉ đổi biến môi trường HF_INFERENCE_URL.

Đây KHÔNG phải máy chủ của Hugging Face. Model vẫn được tải từ Hugging Face Hub (miễn phí).

Định dạng (giống router.huggingface.co/hf-inference/models/ProsusAI/finbert)
    POST /models/ProsusAI/finbert
    {"inputs": "một tiêu đề" | ["nhiều", "tiêu đề"],
     "parameters": {"top_k": 3, "function_to_apply": "softmax"}}
    -> [{"label": "positive", "score": 0.93}, ...]            (1 tiêu đề)
    -> [[{"label": ..., "score": ...}, ...], [...]]           (nhiều tiêu đề, mỗi tiêu đề 1 danh sách)
    Lỗi trả {"error": "..."} kèm mã 400 / 404 / 413 / 422 / 503 như Hugging Face.

Chạy
    python -m scripts.serve_hf_api --port 8001
    # rồi ở cửa sổ khác:
    HF_INFERENCE_URL=http://127.0.0.1:8001/models/ProsusAI/finbert python -m scripts.check_hf_api
"""

from __future__ import annotations

import argparse
import os
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.config import DEFAULT_LOCAL_MODEL_REVISION, MODEL_ID
from backend.providers.hf_inference import LABELS, InferenceProviderError

MAX_INPUTS_PER_REQUEST = 64
SUPPORTED_FUNCTIONS = ("softmax",)


class Classifier(Protocol):
    revision: str

    async def classify_many(self, texts: list[str]) -> list[dict[str, float]]: ...


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


def _rows(scores: dict[str, float], top_k: int) -> list[dict[str, Any]]:
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:top_k]
    return [{"label": label, "score": score} for label, score in ranked]


def create_app(classifier: Classifier | None = None, *, revision: str | None = None, device: str = "cpu") -> FastAPI:
    """Tạo app. `classifier` dùng cho kiểm thử; để trống thì nạp FinBERT local khi khởi động."""

    stats = {"http_requests": 0, "inputs": 0, "errors": 0}

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if application.state.classifier is None:
            from backend.providers.transformers_local import TransformersLocalFinBERT

            application.state.classifier = TransformersLocalFinBERT(
                model_id=MODEL_ID,
                revision=revision or DEFAULT_LOCAL_MODEL_REVISION,
                device_preference=device,
            )
        yield

    app = FastAPI(title="FinBERT self-hosted, Hugging Face API format", lifespan=lifespan)
    app.state.classifier = classifier
    app.state.stats = stats

    @app.get("/health")
    async def health() -> dict[str, Any]:
        clf = app.state.classifier
        return {
            "status": "ok" if clf is not None else "loading",
            "model": MODEL_ID,
            "revision": getattr(clf, "revision", None),
            "device": getattr(clf, "device_name", None),
            "api_format": "huggingface text-classification",
            "server": "self-hosted (not huggingface.co)",
        }

    @app.get("/stats")
    async def get_stats() -> dict[str, int]:
        return dict(stats)

    @app.post("/models/{owner}/{name}")
    async def classify(owner: str, name: str, request: Request) -> JSONResponse:
        stats["http_requests"] += 1
        response = await _classify(f"{owner}/{name}", request)
        if response.status_code >= 400:
            stats["errors"] += 1
        return response

    async def _classify(model: str, request: Request) -> JSONResponse:
        if model != MODEL_ID:
            return _error(404, f"Model {model} không được phục vụ ở máy chủ này (chỉ có {MODEL_ID}).")
        try:
            body = await request.json()
        except ValueError:
            return _error(400, "Body không phải JSON hợp lệ.")
        if not isinstance(body, dict) or "inputs" not in body:
            return _error(400, "Thiếu trường 'inputs'.")

        inputs = body["inputs"]
        single = isinstance(inputs, str)
        texts = [inputs] if single else inputs
        if not isinstance(texts, list) or not texts or not all(isinstance(t, str) and t.strip() for t in texts):
            return _error(400, "'inputs' phải là một chuỗi hoặc danh sách chuỗi không rỗng.")
        if len(texts) > MAX_INPUTS_PER_REQUEST:
            return _error(413, f"Tối đa {MAX_INPUTS_PER_REQUEST} tiêu đề mỗi request.")

        parameters = body.get("parameters") or {}
        if not isinstance(parameters, dict):
            return _error(422, "'parameters' phải là object.")
        function = parameters.get("function_to_apply", "softmax")
        if function not in SUPPORTED_FUNCTIONS:
            return _error(422, f"function_to_apply={function!r} chưa hỗ trợ; dùng 'softmax'.")
        top_k = parameters.get("top_k", 1)
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            return _error(422, "'top_k' phải là số nguyên dương.")
        top_k = min(top_k, len(LABELS))

        clf = app.state.classifier
        if clf is None:
            return JSONResponse(status_code=503, content={"error": "Model đang nạp.", "estimated_time": 20.0})
        try:
            scores = await clf.classify_many([t.strip() for t in texts])
        except InferenceProviderError as exc:
            return _error(exc.status_code if exc.status_code >= 500 else 500, str(exc))

        stats["inputs"] += len(texts)
        rows = [_rows(row, top_k) for row in scores]
        return JSONResponse(content=rows[0] if single else rows)

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    app = create_app(
        revision=os.getenv("LOCAL_MODEL_REVISION", "").strip() or DEFAULT_LOCAL_MODEL_REVISION,
        device=os.getenv("LOCAL_INFERENCE_DEVICE", "cpu").strip().lower() or "cpu",
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
