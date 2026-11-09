"""Ghép 3 module vào API mà KHÔNG sửa luồng lõi.

`UpgradedPortfolioService` dùng lại nguyên các thành phần lõi đang chạy tốt:
  - `SentimentService.news` (NewsAggregator: EODHD → Google News / BBC RSS fallback)
  - `SentimentService.inference` (local Transformers hoặc HF Inference API)
  - `aggregate_probabilities` (công thức gốc) để in song song điểm theo bài báo
và chỉ thêm: cache TTL, Time-Decay + Confidence, trọng số vốn + beta vĩ mô.

Các endpoint cũ `/api/sentiment/stock` và `/api/sentiment/portfolio` giữ nguyên hành vi (luồng
gọi trực tiếp như bài báo) — để so sánh được hai luồng trên cùng một server.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from backend.config import MODEL_ID
from backend.providers.news import NewsItem, deduplicate
from backend.services.sentiment import AnalysisError, SentimentService
from backend.upgrades.portfolio_weighting import Position, article_baseline, portfolio_sentiment
from backend.upgrades.ttl_cache import CachedInference, TTLCache

DEFAULT_INFERENCE_TTL_SECONDS = 24 * 3600
DEFAULT_NEWS_TTL_SECONDS = 10 * 60


class UpgradedPortfolioService:
    def __init__(
        self,
        base: SentimentService,
        inference_ttl_seconds: float = DEFAULT_INFERENCE_TTL_SECONDS,
        news_ttl_seconds: float = DEFAULT_NEWS_TTL_SECONDS,
    ) -> None:
        self.base = base
        self.inference_cache = TTLCache(inference_ttl_seconds, max_items=8192)
        self.news_cache = TTLCache(news_ttl_seconds, max_items=512)
        self.inference = (
            CachedInference(base.inference, self.inference_cache, MODEL_ID) if base.inference is not None else None
        )

    def cache_stats(self) -> dict[str, Any]:
        return {
            "inference_cache": self.inference_cache.stats(),
            "news_cache": self.news_cache.stats(),
            "model_calls_total": self.inference.model_calls if self.inference else 0,
        }

    async def _cached_news(self, key: tuple[str, ...], loader) -> tuple[list[NewsItem], list[dict[str, str]], bool]:
        found, value = self.news_cache.get(key)
        if found:
            items = [NewsItem(**row) for row in value["items"]]
            statuses = [dict(row, status=f"cache_hit({row['status']})", cached=True) for row in value["statuses"]]
            return items, statuses, True
        items, statuses = await loader()
        self.news_cache.set(key, {"items": [item.to_dict() for item in items], "statuses": statuses})
        return items, statuses, False

    async def analyze_weighted_portfolio(
        self,
        positions: list[Position],
        *,
        half_life_hours: dict[str, float],
        prior_strength: float,
        neutral_band: float,
        micro_per_symbol: int = 2,
        macro_limit: int = 4,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        requested_at = datetime.now(timezone.utc)
        now = now or requested_at
        symbols = [p.symbol for p in positions]

        if self.base.settings.demo_mode == "fixture":
            fixture = self.base._fixture_portfolio(symbols)  # dùng lại đúng tập tin fixture của lõi
            items = fixture["headlines"]
            providers = fixture["providers"]
            news_ms = 0.0
            inference_ms = 0.0
            inference_info = {"requested": len(items), "cache_hits": 0, "model_calls": 0, "mode": "fixture"}
            news_cache_hits = 0
        else:
            news_started = time.perf_counter()
            collected: list[NewsItem] = []
            providers: list[dict[str, str]] = []
            news_cache_hits = 0
            fetched = await asyncio.gather(
                *(
                    self._cached_news(
                        ("micro", symbol, str(micro_per_symbol)),
                        lambda s=symbol: self.base.news.collect_stock(s, limit=micro_per_symbol),
                    )
                    for symbol in symbols
                ),
                self._cached_news(("macro", str(macro_limit)), lambda: self.base.news.collect_macro(limit=macro_limit)),
            )
            for items_part, status, hit in fetched:
                collected.extend(items_part)
                providers.extend(status)
                news_cache_hits += int(hit)
            merged = sorted(
                deduplicate(collected),
                key=lambda item: (1 if item.published_at else 0, item.published_at or ""),
                reverse=True,
            )[: micro_per_symbol * len(symbols) + macro_limit]
            news_ms = (time.perf_counter() - news_started) * 1000
            if not merged:
                raise AnalysisError("no_news_found", "Không tìm thấy tiêu đề phù hợp cho danh mục.", 503, {"providers": providers})
            if self.inference is None:
                raise AnalysisError("inference_provider_unavailable", "Inference provider chưa được khởi tạo.", 503)

            inference_started = time.perf_counter()
            serialized = [item.to_dict() for item in merged]
            scores = await self.inference.classify_many([row["title"] for row in serialized])
            inference_ms = (time.perf_counter() - inference_started) * 1000
            items = []
            for row, probs in zip(serialized, scores, strict=True):
                row = dict(row)
                row["probabilities"] = probs
                row["predicted_label"] = max(probs, key=probs.get).capitalize()
                items.append(row)
            inference_info = dict(self.inference.last_call, mode=self.inference.request_mode)

        baseline = article_baseline(items)
        upgraded = portfolio_sentiment(
            items,
            positions,
            now,
            half_life_hours=half_life_hours,
            prior_strength=prior_strength,
            neutral_band=neutral_band,
        ).to_dict()
        for row, contribution in zip(upgraded["headlines"], baseline["headline_contributions"], strict=True):
            row["article_contribution"] = contribution

        return {
            "analysis_status": "completed",
            "data_mode": self.base.settings.demo_mode,
            "scope": "weighted_portfolio",
            "symbols": symbols,
            "article_method": {k: v for k, v in baseline.items() if k != "headline_contributions"},
            "upgraded_method": upgraded,
            "difference": upgraded["score"] - baseline["score"],
            "providers": providers,
            "timing_ms": {
                "news": news_ms,
                "inference": inference_ms,
                "total": (time.perf_counter() - started) * 1000,
            },
            "data_freshness": None
            if self.base.settings.demo_mode == "fixture"
            else {
                "live": True,
                "requested_at_utc": requested_at.isoformat(),
                "news_collection_ms": round(news_ms),
                "total_ms": round((time.perf_counter() - started) * 1000),
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "news_cache": f"Nhóm tin lấy trong {round(self.news_cache.ttl_seconds / 60)} phút gần nhất được dùng lại; quá hạn thì lấy mới.",
                "news_cache_ttl_seconds": self.news_cache.ttl_seconds,
                "news_groups_from_cache": news_cache_hits,
                "news_groups_total": len(symbols) + 1,
            },
            "cache": {
                "news_cache_hits_this_request": news_cache_hits,
                "inference_this_request": inference_info,
                **self.cache_stats(),
            },
        }
