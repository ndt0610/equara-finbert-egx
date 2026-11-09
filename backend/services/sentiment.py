from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from backend.config import HF_PROVIDER, MODEL_ID, Settings
from backend.providers.hf_inference import HuggingFaceFinBERT, InferenceProviderError
from backend.providers.news import NewsAggregator, NewsItem, deduplicate
from backend.providers.transformers_local import TransformersLocalFinBERT


logger = logging.getLogger("equara")
ROOT_DIR = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT_DIR / "fixtures" / "news.json"


class AnalysisError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.context = context or {}


def aggregate_probabilities(rows: list[dict[str, float]]) -> tuple[dict[str, float], str, float]:
    if not rows:
        raise ValueError("At least one probability row is required.")
    labels = ("positive", "negative", "neutral")
    averages = {label: sum(row[label] for row in rows) / len(rows) for label in labels}

    positive = averages["positive"]
    negative = averages["negative"]
    neutral = averages["neutral"]
    if positive > negative and positive > neutral:
        sentiment = "Bullish"
    elif negative > positive and negative > neutral:
        sentiment = "Bearish"
    else:
        sentiment = "Neutral"

    return averages, sentiment, positive - negative


def _freshness(requested_at: datetime, news_started: float, news_ms: float) -> dict[str, Any]:
    """[HOÀN THIỆN] Cho giao diện hiện rõ: tin được lấy trực tiếp lúc nào và mất bao lâu."""
    return {
        "live": True,
        "requested_at_utc": requested_at.isoformat(),
        "news_collection_ms": round(news_ms),
        "total_ms": round((time.perf_counter() - news_started) * 1000),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "news_cache": "Không dùng bộ nhớ: mỗi yêu cầu lấy tin mới từ nguồn.",
    }


def _aggregate_response(
    *,
    scope: str,
    symbols: list[str],
    items: list[dict[str, Any]],
    providers: list[dict[str, str]],
    mode: str,
    inference_requests: int,
    warnings: list[str],
) -> dict[str, Any]:
    probabilities, sentiment, score = aggregate_probabilities([item["probabilities"] for item in items])
    return {
        "analysis_status": "completed",
        "data_mode": mode,
        "scope": scope,
        "symbols": symbols,
        "sentiment": sentiment,
        "probabilities": probabilities,
        "score": score,
        "news_count": len(items),
        "inference_item_count": len(items) if mode == "live" else 0,
        "inference_http_requests": inference_requests,
        "providers": providers,
        "aggregation": {
            "rule": "Equal-weight arithmetic mean of per-headline class probabilities.",
            "label_rule": "Bullish if positive is the strict maximum; Bearish if negative is the strict maximum; otherwise Neutral.",
            "score_rule": "mean(positive) - mean(negative)",
            "status": "Reconstruction choice; the article does not publish the aggregation formula.",
        },
        "inference": {
            "model": MODEL_ID,
            "provider": HF_PROVIDER if mode == "live" else "fixture vectors (no model call)",
            "parameters": {"top_k": 3, "function_to_apply": "softmax"},
            "request_mode": "one headline per HTTP request" if mode == "live" else "fixture lookup; no HTTP request",
        },
        "warnings": warnings,
        "headlines": items,
    }


class SentimentService:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.settings = settings
        self.news = NewsAggregator(client, settings)
        if settings.demo_mode == "fixture":
            self.inference = None
        elif settings.inference_provider == "transformers-local":
            self.inference = TransformersLocalFinBERT(
                model_id=MODEL_ID,
                revision=settings.local_model_revision,
                device_preference=settings.local_inference_device,
            )
        else:
            self.inference = HuggingFaceFinBERT(client, settings.hf_token, endpoint=settings.hf_inference_url)
        self.client = client
        self.fixture_data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def inference_metadata(self) -> dict[str, Any]:
        if self.settings.demo_mode == "fixture":
            return {
                "provider": "fixture",
                "model": MODEL_ID,
                "revision": None,
                "device": None,
                "request_mode": "fixture; no model calls",
            }
        return {
            "provider": self.settings.inference_provider,
            "model": MODEL_ID,
            "revision": getattr(self.inference, "revision", None),
            "device": getattr(self.inference, "device_name", None),
            "request_mode": getattr(self.inference, "request_mode", ""),
        }

    async def analyze_stock(self, symbol: str) -> dict[str, Any]:
        if self.settings.demo_mode == "fixture":
            return self._fixture_stock(symbol)

        requested_at, news_started = datetime.now(timezone.utc), time.perf_counter()
        # [HOÀN THIỆN] Lấy tin micro và macro song song thay vì lần lượt (cùng kết quả, ít chờ hơn).
        (micro, micro_status), (macro, macro_status) = await asyncio.gather(
            self.news.collect_stock(symbol, limit=15),
            self.news.collect_macro(limit=15),
        )
        news_ms = (time.perf_counter() - news_started) * 1000
        merged = sorted(
            deduplicate(micro + macro),
            key=lambda item: (1 if item.published_at else 0, item.published_at or ""),
            reverse=True,
        )[:15]
        providers = micro_status + macro_status
        if not merged:
            raise AnalysisError(
                "no_news_found",
                "Không tìm thấy tiêu đề phù hợp từ EODHD, BBC RSS hoặc Google News.",
                503,
                {"providers": providers},
            )

        warnings: list[str] = []
        if len(merged) < 10:
            warnings.append(f"Chỉ tìm thấy {len(merged)} tiêu đề; mục tiêu của bài báo là khoảng 10–15.")
        response = await self._infer_and_aggregate("stock", [symbol], merged, providers, warnings)
        response["data_freshness"] = _freshness(requested_at, news_started, news_ms)
        return response

    async def analyze_portfolio(self, symbols: list[str]) -> dict[str, Any]:
        if self.settings.demo_mode == "fixture":
            return self._fixture_portfolio(symbols)

        collected: list[NewsItem] = []
        providers: list[dict[str, str]] = []
        warnings: list[str] = []
        requested_at, news_started = datetime.now(timezone.utc), time.perf_counter()
        # [HOÀN THIỆN] Gọi tin của tất cả các mã và tin macro song song; asyncio.gather giữ đúng
        # thứ tự kết quả nên danh sách tin, trạng thái provider và cảnh báo y hệt bản tuần tự.
        *micro_results, (macro, macro_status) = await asyncio.gather(
            *(self.news.collect_stock(symbol, limit=2) for symbol in symbols),
            self.news.collect_macro(limit=4),
        )
        news_ms = (time.perf_counter() - news_started) * 1000
        for symbol, (micro, source_status) in zip(symbols, micro_results, strict=True):
            collected.extend(micro)
            providers.extend(source_status)
            if not micro:
                warnings.append(f"Không tìm thấy tin micro cho {symbol}.")

        collected.extend(macro)
        providers.extend(macro_status)
        merged = sorted(
            deduplicate(collected),
            key=lambda item: (1 if item.published_at else 0, item.published_at or ""),
            reverse=True,
        )[:14]
        if not merged:
            raise AnalysisError(
                "no_news_found",
                "Không tìm thấy tiêu đề phù hợp cho danh mục.",
                503,
                {"providers": providers},
            )
        if len(macro) < 4:
            warnings.append(f"Chỉ tìm thấy {len(macro)} tiêu đề macro; mục tiêu trong bài báo là khoảng 4.")
        response = await self._infer_and_aggregate("portfolio", symbols, merged, providers, warnings)
        response["data_freshness"] = _freshness(requested_at, news_started, news_ms)
        return response

    async def _infer_and_aggregate(
        self,
        scope: str,
        symbols: list[str],
        news_items: list[NewsItem],
        providers: list[dict[str, str]],
        warnings: list[str],
    ) -> dict[str, Any]:
        serialized = [item.to_dict() for item in news_items]
        needs_token = not getattr(self.inference, "self_hosted", False)  # máy chủ tự dựng không cần token
        if self.settings.inference_provider == HF_PROVIDER and needs_token and not self.settings.hf_token:
            raise AnalysisError(
                "missing_hf_token",
                "Thiếu HF_TOKEN; đã thu thập tin nhưng chưa chạy FinBERT inference.",
                424,
                {
                    "analysis_status": "blocked_before_inference",
                    "data_mode": "live",
                    "scope": scope,
                    "symbols": symbols,
                    "news_count": len(serialized),
                    "providers": providers,
                    "headlines": serialized,
                },
            )

        if self.inference is None:
            raise AnalysisError(
                "inference_provider_unavailable",
                "Inference provider chưa được khởi tạo.",
                503,
            )

        output: list[dict[str, Any]] = []
        requests_sent = 0
        try:
            if self.settings.inference_provider == "transformers-local":
                score_rows = await self.inference.classify_many([item["title"] for item in serialized])
                for item, scores in zip(serialized, score_rows, strict=True):
                    row = dict(item)
                    row["probabilities"] = scores
                    row["predicted_label"] = max(scores, key=scores.get).capitalize()
                    output.append(row)
            elif hasattr(self.inference, "classify_many"):
                # [HOÀN THIỆN] Bài báo mục 8: gửi theo lô tới ~15 tiêu đề / request HF.
                sent_before = getattr(self.inference, "http_requests", 0)
                try:
                    score_rows = await self.inference.classify_many([item["title"] for item in serialized])
                finally:
                    requests_sent = getattr(self.inference, "http_requests", 0) - sent_before
                for item, scores in zip(serialized, score_rows, strict=True):
                    row = dict(item)
                    row["probabilities"] = scores
                    row["predicted_label"] = max(scores, key=scores.get).capitalize()
                    output.append(row)
            else:
                for item in serialized:
                    row = dict(item)
                    row["probabilities"] = await self.inference.classify(row["title"])
                    requests_sent += 1
                    row["predicted_label"] = max(row["probabilities"], key=row["probabilities"].get).capitalize()
                    output.append(row)
        except InferenceProviderError as exc:
            logger.error("inference status=failed requests_sent=%d code=%s", requests_sent, exc.status_code)
            raise AnalysisError(
                "hf_inference_error",
                str(exc),
                exc.status_code,
                {"requests_sent_before_error": requests_sent, "news_count": len(serialized)},
            ) from exc

        response = _aggregate_response(
            scope=scope,
            symbols=symbols,
            items=output,
            providers=providers,
            mode="live",
            inference_requests=requests_sent,
            warnings=warnings,
        )
        response["inference"]["provider"] = self.settings.inference_provider
        response["inference"]["request_mode"] = self.inference.request_mode
        response["inference"]["revision"] = getattr(self.inference, "revision", None)
        response["inference"]["device"] = getattr(self.inference, "device_name", None)
        logger.info(
            "analysis completed mode=live inference_provider=%s scope=%s symbols=%s headlines=%d inference_http_requests=%d",
            self.settings.inference_provider,
            scope,
            ",".join(symbols),
            len(output),
            requests_sent,
        )
        return response

    def _fixture_rows(self) -> list[dict[str, Any]]:
        return self.fixture_data["items"]

    def _fixture_stock(self, symbol: str) -> dict[str, Any]:
        rows = self._fixture_rows()
        micro = [row for row in rows if row["kind"] == "micro" and row["symbol"] == symbol]
        macro = [row for row in rows if row["kind"] == "macro"]
        if not micro:
            raise AnalysisError(
                "fixture_symbol_not_available",
                "Fixture có dữ liệu minh họa cho COMI, ETEL, FWRY, ADIB và EFIH; ba mã đầu là ví dụ trong bài báo.",
                422,
            )
        selected = [dict(row) for row in micro + macro[:8]]
        for row in selected:
            row["predicted_label"] = max(row["probabilities"], key=row["probabilities"].get).capitalize()
        providers = [
            {"provider": "DEMO FIXTURE", "kind": "micro", "status": f"fixture:{len(micro)}"},
            {"provider": "DEMO FIXTURE", "kind": "macro", "status": f"fixture:{len(macro[:8])}"},
        ]
        return _aggregate_response(
            scope="stock",
            symbols=[symbol],
            items=selected,
            providers=providers,
            mode="fixture",
            inference_requests=0,
            warnings=[self.fixture_data["notice"]],
        )

    def _fixture_portfolio(self, symbols: list[str]) -> dict[str, Any]:
        rows = self._fixture_rows()
        selected: list[dict[str, Any]] = []
        providers: list[dict[str, str]] = []
        for symbol in symbols:
            micro = [row for row in rows if row["kind"] == "micro" and row["symbol"] == symbol][:2]
            if not micro:
                raise AnalysisError(
                    "fixture_symbol_not_available",
                    f"Fixture không có mã {symbol}. Ví dụ của bài báo: COMI, ETEL, FWRY; fixture kiểm thử thêm ADIB và EFIH.",
                    422,
                )
            selected.extend(dict(row) for row in micro)
            providers.append({"provider": "DEMO FIXTURE", "kind": f"micro:{symbol}", "status": f"fixture:{len(micro)}"})

        macro = [row for row in rows if row["kind"] == "macro"][:4]
        selected.extend(dict(row) for row in macro)
        providers.append({"provider": "DEMO FIXTURE", "kind": "macro", "status": f"fixture:{len(macro)}"})
        for row in selected:
            row["predicted_label"] = max(row["probabilities"], key=row["probabilities"].get).capitalize()
        return _aggregate_response(
            scope="portfolio",
            symbols=symbols,
            items=selected,
            providers=providers,
            mode="fixture",
            inference_requests=0,
            warnings=[self.fixture_data["notice"]],
        )

