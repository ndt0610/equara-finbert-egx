"""Tạo snapshot Tin + Giá và nhãn giải thích được từ quy tắc thử nghiệm V1."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.config import Settings
from backend.schemas import normalize_symbol
from backend.services.sentiment import AnalysisError, SentimentService
from .candidate_service import FILTER_VERSION, TinGiaCandidateService, group_headlines
from .yahoo_daily import YahooDailyError, fetch_daily
from .news_timing import annotate_timing
from .rules import evaluate_rules
from backend.providers.news import STOCK_DIRECTORY

class TinGiaContextService:
    """Tin và giá độc lập với danh mục C3; nhãn theo bộ quy tắc thử nghiệm có phiên bản."""

    def __init__(self, base: SentimentService, settings: Settings) -> None:
        self.base = base
        self.settings = settings
        self.candidates = TinGiaCandidateService(base)

    async def analyze(self, raw_symbol: str) -> dict[str, Any]:
        symbol = normalize_symbol(raw_symbol)
        requested_at = datetime.now(timezone.utc)

        news_context: dict[str, Any]
        if self.settings.demo_mode == "fixture":
            analysis: dict[str, Any] | None = None
            try:
                analysis = await self.base.analyze_stock(symbol)
                fixture_rows = [
                    {
                        **row,
                        "candidate_id": f"illustrative-{index + 1}",
                        "processing_state": "unresolved",
                        "reason_code": "illustrative_fixture_only",
                        "reason": "Bản ghi minh họa; không phải ứng viên được lấy từ nguồn live và không được dùng ra nhãn.",
                        "scope": "company_candidate" if row.get("kind") == "micro" else "external_context",
                        "event_id": None,
                    }
                    for index, row in enumerate(analysis.get("headlines", []))
                ]
                candidate_batch = {
                    "batch_id": f"illustrative-{symbol}",
                    "started_at": (analysis.get("data_freshness") or {}).get("requested_at_utc"),
                    "completed_at": (analysis.get("data_freshness") or {}).get("completed_at_utc"),
                    "filter_version": FILTER_VERSION,
                    "source_scope_note": "Dữ liệu minh họa, không có response nguồn live.",
                    "persistence_status": "illustrative_not_persisted",
                    "counts": {"received": len(fixture_rows), "scored": len(fixture_rows), "company_candidates": sum(row["scope"] == "company_candidate" for row in fixture_rows), "context_candidates": sum(row["scope"] == "external_context" for row in fixture_rows), "excluded": 0, "grouped": 0, "unresolved": len(fixture_rows), "context": 0},
                    "provider_queries": analysis.get("providers", []),
                    "candidates": fixture_rows,
                    "inference_error": None,
                }
            except AnalysisError as exc:
                candidate_batch = {
                    "batch_id": f"illustrative-{symbol}", "started_at": None, "completed_at": None,
                    "filter_version": FILTER_VERSION, "source_scope_note": "Bản minh họa không có ứng viên.",
                    "persistence_status": "illustrative_not_persisted", "counts": {"received": 0, "scored": 0},
                    "provider_queries": (exc.context or {}).get("providers", []), "candidates": [], "inference_error": exc.code,
                }
            company_news = group_headlines(candidate_batch["candidates"], "company_candidate")
            macro_news = group_headlines(candidate_batch["candidates"], "external_context")
            aggregation = analysis.get("aggregation") if analysis is not None else None
            news_context = {
                "status": "available" if candidate_batch["candidates"] else "unavailable",
                "data_mode": "fixture",
                "data_origin": "illustrative",
                "aggregation": aggregation,
                "tin_gia_filter_version": FILTER_VERSION,
                "company_news": company_news,
                "macro_news": macro_news,
                "excluded_from_score": [],
                "candidate_ledger": candidate_batch,
                "fetched_at": candidate_batch.get("completed_at"),
                "warnings": ["Fixture chỉ kiểm tra cách hiển thị; không đại diện response nguồn."],
                "scope_note": "Bản minh họa; điểm là sắc thái headline, không phải điểm theo sự kiện hay % giá.",
            }
        elif symbol not in STOCK_DIRECTORY:
            news_context = {
                "status": "entity_mapping_pending", "data_mode": "live", "data_origin": "observed",
                "aggregation": None, "tin_gia_filter_version": FILTER_VERSION,
                "company_news": {"score": None, "headlines": []},
                "macro_news": {"score": None, "headlines": []},
                "excluded_from_score": [],
                "candidate_ledger": {"counts": {"received": 0, "scored": 0}, "candidates": [], "provider_queries": []},
                "warnings": ["Chưa xác minh tên và alias công ty cho mã này; chưa lấy tin theo tên mã để tránh gán nhầm doanh nghiệp."],
                "scope_note": "Có thể xem giá ngày; phân tích tin cần xác minh danh tính công ty và tên gọi trước khi thu thập.",
            }
        else:
            candidate_batch = await self.candidates.collect(symbol)
            candidate_rows = candidate_batch["candidates"]
            company_news = group_headlines(candidate_rows, "company_candidate")
            macro_news = group_headlines(candidate_rows, "external_context")
            excluded_from_score = [
                row for row in candidate_rows if row.get("processing_state") in {"excluded", "grouped"}
            ]
            news_context = {
                "status": "available" if candidate_batch["candidates"] else (
                    "empty" if any(row.get("status") == "available" for row in candidate_batch["provider_queries"]) else "unavailable"
                ),
                "data_mode": "live",
                "data_origin": "observed",
                "aggregation": {
                    "company_rule": "Equal-weight arithmetic mean of scored company headlines; descriptive preview only, no event-level or age adjustment.",
                    "company_score_rule": "mean(positive) - mean(negative)",
                    "context_rule": "Keep per-headline FinBERT probabilities; do not aggregate heterogeneous context into one score.",
                    "status": "No field in this preview is used for a decision label; cross-source event duplicates are unresolved.",
                },
                "tin_gia_filter_version": candidate_batch["filter_version"],
                "company_news": company_news,
                "macro_news": macro_news,
                "excluded_from_score": excluded_from_score,
                "candidate_ledger": candidate_batch,
                "fetched_at": candidate_batch.get("completed_at"),
                "warnings": (["Một số provider không trả được dữ liệu."] if any(row.get("status") == "failed" for row in candidate_batch["provider_queries"]) else []),
                "scope_note": (
                    "Ứng viên dưới đây được giữ từ response nguồn trước luật xử lý Tin + Giá; phạm vi chỉ gồm các query/provider đã gọi. "
                    "Điểm là xem trước theo headline, chưa gộp sự kiện; cùng một sự kiện có thể có nhiều bài. "
                    "Tin ngoài công ty là bối cảnh, chưa vào nhãn. Candidate chưa được lưu lâu dài vì quyền retention chưa xác minh."
                ),
            }
            if not candidate_batch["candidates"]:
                news_context["message"] = (
                    "Không có ứng viên trong các response nguồn của lượt này. "
                    "Kiểm tra nhật ký truy vấn bên dưới để phân biệt nguồn rỗng với lỗi kết nối."
                )

        try:
            price_context = await fetch_daily(symbol)
        except YahooDailyError as exc:
            price_context = {
                "status": "unavailable", "source": "Yahoo Finance (daily via yfinance)",
                "error_code": "daily_history_unavailable", "message": str(exc),
                "quote": None, "daily_change": None, "five_session_change": None,
                "history": [], "provider_calls": 1,
            }

        news_context['price_alignment'] = annotate_timing(
            news_context.get('candidate_ledger', {}).get('candidates', []),
            price_context.get('as_of_date'),
        )
        return {
            "feature": "tin-gia-v1",
            "symbol": symbol,
            "market": "EGX",
            "currency": "EGP",
            "requested_at": requested_at.isoformat(),
            "price": price_context,
            "news": news_context,
            "decision": evaluate_rules(price_context, news_context),
            "data_policy": {
                "refresh": "manual_on_request",
                "api_calls_per_refresh_if_configured": "Yahoo daily history: one provider history request per symbol. EODHD News credentials for article/portfolio tabs are not used by Tin + Giá.",
                "not_connected": "EGID Feed (real-time entitlement/schema not configured)",
            },
        }
