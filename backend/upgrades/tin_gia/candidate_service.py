"""Thu thập ứng viên Tin + Giá trước khi áp luật hiển thị/chấm điểm.

Đây là adapter riêng của Tin + Giá. Nó không sửa luồng collector C3. Lượt thu hiện giữ
snapshot trong response; chưa ghi kho lịch sử vì quyền lưu nội dung từng nguồn chưa xác minh.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from backend.config import BBC_MIDDLE_EAST_RSS, EODHD_NEWS_ENDPOINT, GOOGLE_NEWS_RSS
from backend.providers.news import (
    NEWS_LOOKBACK_DAYS,
    NewsItem,
    _parse_datetime,
    company_aliases,
    google_stock_query,
    public_url,
)
from backend.services.sentiment import AnalysisError, SentimentService
from backend.upgrades.relevance import unambiguous_match, judge


FILTER_VERSION = "tin-gia-candidate-ledger-v1"
_TRACKING_KEYS = {"oc", "ved", "usg", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}


def _clean_url(value: str | None) -> str:
    if not value:
        return ""
    parts = urlsplit(value.strip())
    query = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() not in _TRACKING_KEYS and not key.casefold().startswith("utm_")
    ]
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"), urlencode(query), ""))


def _text_key(value: str | None) -> str:
    return re.sub(r"[^\w\s]", "", re.sub(r"\s+", " ", (value or "").casefold()).strip())


def _chart_page_reason(title: str) -> str | None:
    normalized = " ".join(title.casefold().split())
    if "tradingview" in normalized and ("stock price and chart" in normalized or "price and chart" in normalized):
        return "Tiêu đề là trang giá/biểu đồ TradingView, không phải bài tin."
    return None


class TinGiaCandidateService:
    """Thu các response nguồn đã cấu hình, giữ từng bản ghi và giải thích bước xử lý."""

    def __init__(self, sentiment: SentimentService) -> None:
        self.sentiment = sentiment

    async def _rss_candidates(
        self,
        *,
        provider: str,
        source_url: str,
        params: dict[str, str] | None,
        scope: str,
        kind: str,
        symbol: str | None,
        query_id: str,
        meta: dict[str, Any],
    ) -> list[dict[str, Any]]:
        parsed = await self.sentiment.news._rss(source_url, params, meta)
        rows: list[dict[str, Any]] = []
        received_at = meta.get("fetched_at") or datetime.now(timezone.utc).isoformat()
        for index, entry in enumerate(parsed.entries):
            title = str(entry.get("title") or "").strip()
            description = str(entry.get("summary") or "").strip()
            rows.append({
                "item": NewsItem(
                    title=title,
                    url=public_url(entry.get("link")) if entry.get("link") else None,
                    published_at=_parse_datetime(entry.get("published"), entry.get("published_parsed")),
                    source=provider,
                    kind=kind,
                    symbol=symbol,
                    description=description or None,
                ),
                "provider": provider,
                "query_id": query_id,
                "query_url": meta.get("query_url"),
                "query_tier": 1 if query_id.endswith("tier1") else 2 if query_id.endswith("tier2") else None,
                "received_at": received_at,
                "provider_index": index,
                "scope": scope,
            })
        meta["candidate_count_before_filter"] = len(parsed.entries)
        meta["untitled_count"] = sum(not str(row.get("title") or "").strip() for row in parsed.entries)
        return rows

    async def _eodhd_candidates(
        self,
        *,
        symbol: str | None,
        query_id: str,
        scope: str,
        limit: int,
        meta: dict[str, Any],
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "api_token": self.sentiment.news.settings.eodhd_tin_gia_news_api_token, "fmt": "json"}
        if symbol:
            params["s"] = symbol
        response = await self.sentiment.news._get(EODHD_NEWS_ENDPOINT, params, meta)
        if response.status_code >= 400:
            raise httpx.HTTPStatusError("EODHD news request failed", request=response.request, response=response)
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("EODHD response is not a list")
        rows: list[dict[str, Any]] = []
        received_at = meta.get("fetched_at") or datetime.now(timezone.utc).isoformat()
        for index, entry in enumerate(payload):
            if isinstance(entry, dict):
                title = str(entry.get("title") or "").strip()
                link = entry.get("link")
                published = _parse_datetime(entry.get("date"))
                description = entry.get("content")
            else:
                title, link, published, description = "", None, None, None
            rows.append({
                "item": NewsItem(
                    title=title,
                    url=public_url(link) if link else None,
                    published_at=published,
                    source="EODHD",
                    kind="micro" if symbol else "macro",
                    symbol=symbol,
                    description=str(description).strip() if description else None,
                ),
                "provider": "EODHD",
                "query_id": query_id,
                "query_url": meta.get("query_url"),
                "query_tier": None,
                "received_at": received_at,
                "provider_index": index,
                "scope": scope,
            })
        meta["candidate_count_before_filter"] = len(payload)
        meta["untitled_count"] = sum(not row["item"].title for row in rows)
        return rows

    async def collect(self, symbol: str) -> dict[str, Any]:
        batch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        queries: list[tuple[str, str, str, str | None, str | None, dict[str, Any]]] = []

        def add(query_id: str, provider: str, scope: str, target_symbol: str | None, kind: str | None) -> dict[str, Any]:
            meta: dict[str, Any] = {"provider": provider, "query_id": query_id, "scope": scope, "symbol": target_symbol}
            queries.append((query_id, provider, scope, target_symbol, kind, meta))
            return meta

        stock_tier1_meta = add("google_company_tier1", "Google News RSS", "company_candidate", symbol, "micro")
        stock_tier2_meta = add("google_company_tier2", "Google News RSS", "company_candidate", symbol, "micro")
        bbc_meta = add("bbc_middle_east_rss", "BBC RSS", "external_context", None, "macro")
        google_context_meta = add("google_economy_context", "Google News RSS", "external_context", None, "macro")
        query_status: list[dict[str, Any]] = []

        calls = [
            self._rss_candidates(
                provider="Google News RSS", source_url=GOOGLE_NEWS_RSS,
                params={"q": google_stock_query(symbol, 1), "hl": "en-US", "gl": "US", "ceid": "US:en"},
                scope="company_candidate", kind="micro", symbol=symbol, query_id="google_company_tier1", meta=stock_tier1_meta,
            ),
            self._rss_candidates(
                provider="Google News RSS", source_url=GOOGLE_NEWS_RSS,
                params={"q": google_stock_query(symbol, 2), "hl": "en-US", "gl": "US", "ceid": "US:en"},
                scope="company_candidate", kind="micro", symbol=symbol, query_id="google_company_tier2", meta=stock_tier2_meta,
            ),
            self._rss_candidates(
                provider="BBC RSS", source_url=BBC_MIDDLE_EAST_RSS, params=None,
                scope="external_context", kind="macro", symbol=None, query_id="bbc_middle_east_rss", meta=bbc_meta,
            ),
            self._rss_candidates(
                provider="Google News RSS", source_url=GOOGLE_NEWS_RSS,
                params={"q": f"Egypt economy OR Egyptian economy OR EGX when:{NEWS_LOOKBACK_DAYS}d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
                scope="external_context", kind="macro", symbol=None, query_id="google_economy_context", meta=google_context_meta,
            ),
        ]

        eodhd_stock_meta = None
        eodhd_context_meta = None
        if self.sentiment.news.settings.eodhd_tin_gia_news_api_token:
            eodhd_stock_meta = add("eodhd_company", "EODHD", "company_candidate", symbol, "micro")
            eodhd_context_meta = add("eodhd_general_context", "EODHD", "external_context", None, "macro")
            calls.extend([
                self._eodhd_candidates(symbol=symbol, query_id="eodhd_company", scope="company_candidate", limit=20, meta=eodhd_stock_meta),
                self._eodhd_candidates(symbol=None, query_id="eodhd_general_context", scope="external_context", limit=100, meta=eodhd_context_meta),
            ])
        else:
            query_status.extend([
                {"provider": "EODHD", "query_id": "eodhd_company", "scope": "company_candidate", "symbol": symbol, "status": "skipped_missing_api_key", "candidate_count_before_filter": 0},
                {"provider": "EODHD", "query_id": "eodhd_general_context", "scope": "external_context", "symbol": None, "status": "skipped_missing_api_key", "candidate_count_before_filter": 0},
            ])

        results = await asyncio.gather(*calls, return_exceptions=True)
        raw_rows: list[dict[str, Any]] = []
        for query, result in zip(queries, results, strict=True):
            _query_id, _provider, _scope, _target_symbol, _kind, meta = query
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, Exception):
                meta.update({
                    "status": "failed",
                    "error_code": "provider_request_failed",
                    "error_type": type(result).__name__,
                    "candidate_count_before_filter": 0,
                })
                query_status.append(meta)
                continue
            meta["status"] = "available"
            raw_rows.extend(result)
            query_status.append(meta)

        aliases = company_aliases(symbol)
        seen_exact: dict[tuple[str, str], str] = {}
        candidate_rows: list[dict[str, Any]] = []
        scoreable_rows: list[dict[str, Any]] = []

        for index, raw in enumerate(raw_rows):
            item: NewsItem = raw["item"]
            raw_title = item.title or ""
            candidate_id = hashlib.sha256(
                f"{batch_id}|{index}|{raw['query_id']}|{item.url or ''}|{raw_title}".encode("utf-8", "replace")
            ).hexdigest()[:24]
            row: dict[str, Any] = {
                "candidate_id": candidate_id,
                "batch_id": batch_id,
                "source": item.source,
                "query_id": raw["query_id"],
                "query_url": raw["query_url"],
                "query_tier": raw["query_tier"],
                "retrieved_at": raw["received_at"],
                "published_at": item.published_at,
                "title": raw_title,
                "url": item.url,
                "description": item.description,
                "scope": raw["scope"],
                "symbol": item.symbol,
                "event_id": None,
                "canonical_record_id": None,
                "probabilities": None,
                "sentiment_score": None,
                "processing_state": "unresolved",
                "reason_code": "pending_review",
                "reason": "Ứng viên đã được giữ trước lọc; cần phân xử phạm vi/sự kiện trước khi dùng trong nhãn.",
                "evidence_refs": [item.url] if item.url else [],
                "data_rights_status": "unknown",
            }

            if not raw_title.strip():
                row.update(reason_code="invalid_content", reason="Nguồn trả bản ghi không có tiêu đề; giữ lại để kiểm tra, không chấm FinBERT.")
                candidate_rows.append(row)
                continue

            page_reason = _chart_page_reason(raw_title)
            if page_reason:
                row.update(processing_state="excluded", reason_code="market_data_chart_page", reason=page_reason)
                candidate_rows.append(row)
                continue

            key = (_clean_url(item.url), _text_key(raw_title))
            if key[0] and key[1] and key in seen_exact:
                row.update(
                    processing_state="grouped",
                    canonical_record_id=seen_exact[key],
                    reason_code="exact_duplicate",
                    reason="Cùng nguồn trả cùng URL và cùng tiêu đề trong lô này; giữ liên kết tới bản xuất hiện trước.",
                )
                candidate_rows.append(row)
                continue
            if key[0] and key[1]:
                seen_exact[key] = candidate_id

            if raw["scope"] == "external_context":
                row.update(
                    processing_state="context",
                    reason_code="scope_context",
                    reason="Tin ngoài công ty được giữ để người xem đối chiếu; chưa có surprise và exposure point-in-time để đưa vào nhãn.",
                )
                scoreable_rows.append(row)
                candidate_rows.append(row)
                continue

            matched, ambiguous = unambiguous_match(raw_title, aliases)
            content_verdict = judge(item, aliases, now=now, lookback_days=NEWS_LOOKBACK_DAYS)
            if content_verdict.reason_code in {"sports", "not_news_page", "stale"}:
                row.update(processing_state="excluded", reason_code=content_verdict.reason_code,
                           reason=content_verdict.reason)
                candidate_rows.append(row)
                continue
            entity_note = None
            if symbol == "COMI.EGX" and matched == "CIB" and re.search(r"\bCIB\s+Kenya\b", raw_title, re.IGNORECASE):
                matched = None
                ambiguous = True
                entity_note = "Tiêu đề nói về CIB Kenya; chưa xác minh đây có phải COMI trên EGX hay không nên giữ ứng viên nhưng không chấm như tin COMI."
            if matched:
                row.update(
                    reason_code="pending_event_review",
                    reason="Tiêu đề nhắc rõ mã/tên công ty; chưa gắn event_id nên điểm chỉ là xem trước theo headline.",
                    matched_alias=matched,
                )
                scoreable_rows.append(row)
            else:
                description_match, _description_ambiguous = unambiguous_match(item.description or "", aliases)
                if entity_note:
                    row.update(reason_code="ambiguous_entity", reason=entity_note)
                elif description_match:
                    row.update(reason_code="name_only_in_description", reason="Tên công ty chỉ có trong mô tả; không dùng tiêu đề để chấm trực tiếp.")
                elif ambiguous:
                    row.update(reason_code="ambiguous_entity", reason="Tên trong tiêu đề có thể chỉ công ty khác; cần xác minh đối tượng.")
                else:
                    row.update(reason_code="ambiguous_entity", reason="Truy vấn tìm thấy ứng viên nhưng chưa xác nhận đúng doanh nghiệp từ tiêu đề.")
            candidate_rows.append(row)

        if self.sentiment.inference is not None and scoreable_rows:
            try:
                probabilities = await self.sentiment.inference.classify_many([row["title"] for row in scoreable_rows])
                for row, probs in zip(scoreable_rows, probabilities, strict=True):
                    row["probabilities"] = probs
                    row["sentiment_score"] = float(probs.get("positive", 0.0)) - float(probs.get("negative", 0.0))
            except Exception as exc:
                for row in scoreable_rows:
                    row["reason_code"] = "pending_scoring"
                    row["reason"] = "Ứng viên đã giữ lại nhưng hiện chưa chấm được FinBERT."
                inference_error = type(exc).__name__
            else:
                inference_error = None
        else:
            inference_error = "inference_unavailable" if scoreable_rows else None

        counts = {
            "received": len(candidate_rows),
            "scored": sum(row.get("probabilities") is not None for row in candidate_rows),
            "company_candidates": sum(row["scope"] == "company_candidate" for row in candidate_rows),
            "context_candidates": sum(row["scope"] == "external_context" for row in candidate_rows),
            "excluded": sum(row["processing_state"] == "excluded" for row in candidate_rows),
            "grouped": sum(row["processing_state"] == "grouped" for row in candidate_rows),
            "unresolved": sum(row["processing_state"] == "unresolved" for row in candidate_rows),
            "context": sum(row["processing_state"] == "context" for row in candidate_rows),
        }
        for provider_query in query_status:
            query_rows = [row for row in candidate_rows if row["query_id"] == provider_query["query_id"]]
            provider_query["candidate_count_after_review"] = len(query_rows)
            provider_query["scored_count"] = sum(row["probabilities"] is not None for row in query_rows)
            provider_query["excluded_count"] = sum(row["processing_state"] == "excluded" for row in query_rows)
            provider_query["grouped_count"] = sum(row["processing_state"] == "grouped" for row in query_rows)
            provider_query["unresolved_count"] = sum(row["processing_state"] == "unresolved" for row in query_rows)
            provider_query["context_count"] = sum(row["processing_state"] == "context" for row in query_rows)
        return {
            "batch_id": batch_id,
            "started_at": now.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "filter_version": FILTER_VERSION,
            "source_scope_note": "Đây là mọi bản ghi trong response của các truy vấn liệt kê, không phải toàn bộ tin trên Internet.",
            "persistence_status": "not_persisted_rights_unverified",
            "retention_note": "Nhật ký chỉ nằm trong response của lượt gọi hiện tại; chưa lưu lịch sử.",
            "counts": counts,
            "provider_queries": query_status,
            "candidates": candidate_rows,
            "inference_error": inference_error,
        }


def group_headlines(candidates: list[dict[str, Any]], scope: str) -> dict[str, Any]:
    rows = [
        row for row in candidates
        if row.get("scope") == scope and isinstance(row.get("probabilities"), dict)
        and row.get("processing_state") not in {"excluded", "grouped"}
    ]
    if not rows:
        return {"count": 0, "score": None, "probabilities": None, "headlines": []}
    if scope == "external_context":
        return {
            "count": len(rows),
            "score": None,
            "probabilities": None,
            "headlines": rows,
            "aggregation_status": "not_aggregated_heterogeneous_context",
        }
    event_rows = [
        row for row in rows
        if row.get("processing_state") == "representative" and row.get("event_id")
    ]
    if not event_rows:
        return {
            "count": len(rows),
            "score": None,
            "probabilities": None,
            "headlines": rows,
            "aggregation_status": "not_aggregated_events_unresolved",
        }
    # A confirmed event contributes once, through its designated representative record.
    unique_events: dict[str, dict[str, Any]] = {}
    for row in event_rows:
        unique_events.setdefault(str(row["event_id"]), row)
    rows = list(unique_events.values())
    probabilities = {
        label: sum(float(row["probabilities"].get(label, 0.0)) for row in rows) / len(rows)
        for label in ("positive", "negative", "neutral")
    }
    return {
        "count": len(rows),
        "score": probabilities["positive"] - probabilities["negative"],
        "probabilities": probabilities,
        "headlines": rows,
    }
