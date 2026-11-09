"""Phần C ghép vào API: lấy tin → lọc đúng doanh nghiệp → chấm FinBERT → độ phủ và đóng góp theo vốn.

Dùng lại nguyên các thành phần đang chạy:
  - nguồn tin của lõi (EODHD → Google News RSS bậc 1 → bậc 2 khi còn dưới 10 tin phù hợp cho tin riêng;
    EODHD → BBC → Google cho vĩ mô, rồi truy vấn Google tin kinh tế khi chưa đủ tin kinh tế),
  - mô hình qua `CachedInference` của lớp nâng cấp (cùng bộ nhớ đệm 24 giờ theo tiêu đề, gửi lô ≤ 15),
  - hàm gộp của bản tái dựng `aggregate_probabilities`.

Một lượt bấm chỉ lấy tin MỘT lần. Điểm "Cách bài báo" được dựng lại từ chính lượt lấy tin đó theo
đúng cách chọn tin của tab danh mục (2 tin mới nhất mỗi mã theo bộ lọc tên cũ + 4 tin vĩ mô), để hai
cách tính dùng cùng dữ liệu. Tab 1, tab 2 và API gốc không đổi.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from backend.config import HF_PROVIDER
from backend.providers.hf_inference import InferenceProviderError
from backend.providers.news import (
    NewsAggregator,
    NewsItem,
    _sort_newest,
    company_aliases,
    company_name,
    deduplicate,
    google_stock_query,
    old_alias_filter,
    usable_news,
)
from backend.services.sentiment import AnalysisError, aggregate_probabilities
from backend.upgrades.coverage import METHOD_VERSION, CoverageConfig, HoldingScore, group_signal, summarize_portfolio
from backend.upgrades.relevance import RULES_VERSION, pattern_flags, screen, screen_macro
from backend.upgrades.service import UpgradedPortfolioService

ROOT_DIR = Path(__file__).resolve().parents[2]
EXTRA_FIXTURE_PATH = ROOT_DIR / "fixtures" / "coverage_candidates.json"
EODHD_CANDIDATE_LIMIT = 20  # đúng số mà collect_stock xin EODHD, để dựng lại được điểm cách bài báo
ARTICLE_MICRO_PER_SYMBOL = 2  # bài báo mục 6: 1–2 tiêu đề mỗi mã
ARTICLE_MACRO = 4  # bài báo mục 6: khoảng 4 tin vĩ mô
ARTICLE_PORTFOLIO_CAP = 14

DISCLAIMER = (
    "Trang này chỉ tóm tắt sắc thái của các tiêu đề tin tiếng Anh tìm được. Đây không phải tư vấn đầu tư "
    "hay khuyến nghị giao dịch chứng khoán, và không dự báo giá."
)
LIMITATIONS = (
    "\"Không có tiêu đề qua luật hiện tại\" nghĩa là các nguồn và truy vấn đã gọi không trả tiêu đề nào qua được luật lọc, không có nghĩa là công ty không có tin.",
    "Quyết định loại là tự động, chưa có người kiểm; luật có thể loại nhầm tin có nói về công ty nhưng tiêu đề không nêu tên công ty. Mỗi bản ghi chỉ ghi lý do đầu tiên khớp.",
    f"Luật lọc {RULES_VERSION} chưa được đo bằng nhãn của người; phiếu gán nhãn và script đo nằm trong scripts/.",
    "Chỉ bỏ bản lặp cùng URL (khi không có URL thì cùng tiêu đề). Nhiều tiêu đề cùng một sự kiện vẫn được tính nhiều lần; mọi tiêu đề đều được liệt kê để người xem tự thấy.",
    "FinBERT được huấn luyện trên tin tài chính tiếng Anh chung, chưa được đo riêng trên tin EGX.",
    "Cửa sổ 90 ngày, tối đa 15 tiêu đề được chấm mỗi mã, mức gọi truy vấn rộng (dưới 10 tiêu đề qua luật) và danh sách từ khóa thể thao, mẫu trang dữ liệu là cấu hình demo, chưa được chứng minh là tối ưu.",
)


def _status(provider: str, symbol: str, tier: int, status: str, **extra: Any) -> dict[str, Any]:
    return {"provider": provider, "kind": "micro", "symbol": symbol, "tier": tier, "status": status, **extra}


def _relevant_count(items: list[NewsItem], aliases: tuple[str, ...], lookback_days: int, now: datetime) -> int:
    return sum(1 for verdict in screen(items, aliases, now=now, lookback_days=lookback_days) if verdict.keep)


async def fetch_candidates(
    news: NewsAggregator,
    symbol: str,
    config: CoverageConfig,
    *,
    eodhd_configured: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Mọi ứng viên trước khi lọc của một mã, theo từng nguồn và từng bậc truy vấn.

    EODHD trước. Google bậc 1 gọi khi EODHD không cho tin phù hợp nào (đúng như `collect_stock`), hoặc khi số
    tin phù hợp còn ít hơn `tier2_below` (mặc định 10). Google bậc 2 gọi khi vẫn còn ít hơn mức đó.
    `tier2_below=None`: chỉ gọi như `collect_stock`, không gọi bậc 2.
    """
    now = now or datetime.now(timezone.utc)
    aliases = company_aliases(symbol)
    statuses: list[dict[str, Any]] = []
    eodhd_raw: list[NewsItem] | None = None
    google_raw: list[NewsItem] | None = None
    google2_raw: list[NewsItem] | None = None

    async def attempt(provider: str, tier: int, loader: Callable[[dict[str, Any]], Awaitable[list[NewsItem]]]) -> list[NewsItem]:
        meta: dict[str, Any] = {}
        try:
            items = await loader(meta)
            statuses.append(_status(provider, symbol, tier, f"candidates:{len(items)}", candidates=len(items), **meta))
            return items
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            statuses.append(_status(provider, symbol, tier, "failed", error=type(exc).__name__, **meta))
            return []

    if eodhd_configured:
        eodhd_raw = await attempt("EODHD", 1, lambda meta: news.eodhd_stock_raw(symbol, EODHD_CANDIDATE_LIMIT, meta))
    else:
        statuses.append(_status("EODHD", symbol, 1, "skipped_missing_api_key"))

    relevant = _relevant_count(eodhd_raw or [], aliases, config.lookback_days, now)
    below_target = config.tier2_below is not None and relevant < config.tier2_below
    if relevant == 0 or below_target:
        # relevant == 0: đúng như collect_stock. below_target: EODHD có tin nhưng còn dưới mức, tìm thêm trên Google.
        google_raw = await attempt("Google News RSS", 1, lambda meta: news.google_stock_raw(symbol, 1, meta))
        relevant = _relevant_count((eodhd_raw or []) + google_raw, aliases, config.lookback_days, now)
    else:
        statuses.append(_status("Google News RSS", symbol, 1, "skipped_eodhd_has_relevant"))

    if config.tier2_below is not None:
        if relevant < config.tier2_below:
            google2_raw = await attempt("Google News RSS", 2, lambda meta: news.google_stock_raw(symbol, 2, meta))
        else:
            statuses.append(_status("Google News RSS", symbol, 2, "skipped_enough_relevant"))

    return {
        "symbol": symbol,
        "eodhd_raw": eodhd_raw,
        "google_raw": google_raw,
        "google2_raw": google2_raw,
        "statuses": statuses,
        "queries": {
            "google_tier1": google_stock_query(symbol, 1),
            "google_tier2": google_stock_query(symbol, 2),
        },
    }


def article_micro_selection(bundle: dict[str, Any], *, eodhd_configured: bool, limit: int = ARTICLE_MICRO_PER_SYMBOL) -> list[NewsItem]:
    """Tin riêng mà `collect_stock(symbol, limit=2)` của bản tái dựng sẽ chọn, dựng lại từ cùng lượt lấy tin."""
    symbol = bundle["symbol"]
    items: list[NewsItem] = []
    if eodhd_configured and bundle.get("eodhd_raw"):
        items, _ = usable_news(bundle["eodhd_raw"], "ok")
    if not items and bundle.get("google_raw"):
        aliases = company_aliases(symbol)
        accepted = [item for item in bundle["google_raw"] if old_alias_filter(item, aliases)][: max(limit, 20)]
        items, _ = usable_news(accepted, "used")
    return _sort_newest(items)[:limit]


def _bundle_to_cache(bundle: dict[str, Any]) -> dict[str, Any]:
    data = dict(bundle)
    for key in ("eodhd_raw", "google_raw", "google2_raw"):
        if data.get(key) is not None:
            data[key] = [item.to_dict() for item in data[key]]
    return data


def _bundle_from_cache(data: dict[str, Any]) -> dict[str, Any]:
    bundle = dict(data)
    for key in ("eodhd_raw", "google_raw", "google2_raw"):
        if bundle.get(key) is not None:
            bundle[key] = [NewsItem(**row) for row in bundle[key]]
    bundle["statuses"] = [dict(row, status=f"cache_hit({row['status']})", cached=True) for row in bundle["statuses"]]
    return bundle


def _item_out(item: NewsItem, tier: int, **extra: Any) -> dict[str, Any]:
    row = item.to_dict()
    row.pop("description", None)
    row["query_tier"] = tier
    row.update(extra)
    return row


def screen_bundle(bundle: dict[str, Any], config: CoverageConfig, now: datetime) -> dict[str, Any]:
    """Áp luật lọc lên mọi ứng viên của một mã. Trả tin giữ (mới nhất trước), tin loại kèm lý do, tin vượt giới hạn."""
    symbol = bundle["symbol"]
    aliases = company_aliases(symbol)
    rows = [(item, tier) for key, tier in (("eodhd_raw", 1), ("google_raw", 1), ("google2_raw", 2)) for item in bundle.get(key) or []]
    verdicts = screen([item for item, _ in rows], aliases, now=now, lookback_days=config.lookback_days, ranks=[tier for _, tier in rows])
    kept: list[tuple[NewsItem, int, str]] = []
    rejected: list[dict[str, Any]] = []
    candidates = len(rows)
    old_keep = 0
    for (item, tier), verdict in zip(rows, verdicts, strict=True):
        old_keep += int(verdict.old_filter_keep)
        if verdict.keep:
            kept.append((item, tier, verdict.matched_alias or ""))
        else:
            rejected.append(
                _item_out(
                    item,
                    tier,
                    reason_code=verdict.reason_code,
                    reason=verdict.reason,
                    old_filter_keep=verdict.old_filter_keep,
                    pattern_flags=pattern_flags(item.title),
                )
            )
    ordered = sorted(kept, key=lambda row: (1 if row[0].published_at else 0, row[0].published_at or ""), reverse=True)
    cap = config.max_headlines_per_holding
    return {
        "aliases": list(aliases),
        "candidates_total": candidates,
        "old_filter_would_keep": old_keep,
        "kept": ordered[:cap],
        "not_scored": [
            _item_out(item, tier, matched_alias=alias, reason=f"Qua luật hiện tại nhưng ngoài {cap} tiêu đề mới nhất theo ngày đăng (ngày không rõ xếp sau), không chấm")
            for item, tier, alias in ordered[cap:]
        ],
        "rejected": rejected,
    }


class CoverageService:
    def __init__(self, upgraded: UpgradedPortfolioService, config: CoverageConfig | None = None) -> None:
        self.upgraded = upgraded
        self.base = upgraded.base
        self.config = config or CoverageConfig()
        self.extra_fixture = (
            json.loads(EXTRA_FIXTURE_PATH.read_text(encoding="utf-8")) if EXTRA_FIXTURE_PATH.exists() else {"items": []}
        )

    # ---------------- lấy dữ liệu ----------------
    def _fixture_bundle(self, symbol: str) -> dict[str, Any]:
        rows = [r for r in self.base._fixture_rows() if r["kind"] == "micro" and r["symbol"] == symbol]
        extra = [r for r in self.extra_fixture.get("items", []) if r.get("symbol") == symbol]
        fields = ("title", "url", "published_at", "source", "kind", "symbol", "description")
        items = [NewsItem(**{k: r.get(k) for k in fields}) for r in rows + [dict(e, kind="micro") for e in extra]]
        return {
            "symbol": symbol,
            "eodhd_raw": None,
            "google_raw": items,  # dùng chung đường lọc với Google; nguồn ghi "DEMO FIXTURE"
            "google2_raw": None,
            "statuses": [_status("DEMO FIXTURE", symbol, 1, f"candidates:{len(items)}", candidates=len(items))],
            "queries": {},
            "fixture_article_micro": rows[:ARTICLE_MICRO_PER_SYMBOL],
        }

    async def _live_bundle(self, symbol: str, now: datetime) -> tuple[dict[str, Any], bool]:
        key = ("coverage", RULES_VERSION, symbol, str(self.config.tier2_below), str(self.config.lookback_days))
        found, value = self.upgraded.news_cache.get(key)
        if found:
            return _bundle_from_cache(value), True
        bundle = await fetch_candidates(
            self.base.news, symbol, self.config, eodhd_configured=bool(self.base.settings.eodhd_news_api_token), now=now
        )
        self.upgraded.news_cache.set(key, _bundle_to_cache(bundle))
        return bundle, False

    # ---------------- chấm điểm ----------------
    def _check_inference_ready(self, symbols: list[str]) -> None:
        settings = self.base.settings
        provider = self.base.inference
        # Chỉ adapter Hugging Face gọi huggingface.co mới cần token (máy chủ tự dựng và FinBERT trong notebook thì không).
        needs_token = getattr(provider, "provider_name", None) == HF_PROVIDER and not getattr(provider, "self_hosted", False)
        if needs_token and not settings.hf_token:
            raise AnalysisError(
                "missing_hf_token",
                "Thiếu HF_TOKEN; đã thu thập tin nhưng chưa chạy FinBERT inference.",
                424,
                {"analysis_status": "blocked_before_inference", "scope": "coverage_portfolio", "symbols": symbols},
            )
        if self.upgraded.inference is None:
            raise AnalysisError("inference_provider_unavailable", "Inference provider chưa được khởi tạo.", 503)

    async def _score_titles(self, titles: list[str], symbols: list[str]) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
        unique = list(dict.fromkeys(titles))
        if not unique:
            return {}, {"requested": 0, "cache_hits": 0, "model_calls": 0}
        self._check_inference_ready(symbols)
        try:
            scores = await self.upgraded.inference.classify_many(unique)
        except InferenceProviderError as exc:
            raise AnalysisError("hf_inference_error", str(exc), exc.status_code, {"titles_requested": len(unique)}) from exc
        info = dict(self.upgraded.inference.last_call, mode=self.upgraded.inference.request_mode)
        return dict(zip(unique, scores, strict=True)), info

    # ---------------- luồng chính ----------------
    async def analyze(self, positions: list[tuple[str, float]], *, now: datetime | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        requested_at = datetime.now(timezone.utc)
        now = now or requested_at
        config = self.config
        symbols = [symbol for symbol, _ in positions]
        fixture = self.base.settings.demo_mode == "fixture"
        macro_fetch = max(ARTICLE_MACRO, config.macro_limit)

        news_started = time.perf_counter()
        news_cache_hits = 0
        if fixture:
            bundles = [self._fixture_bundle(symbol) for symbol in symbols]
            macro_rows = [dict(r) for r in self.base._fixture_rows() if r["kind"] == "macro"][:macro_fetch]
            macro_items = [NewsItem(**{k: r.get(k) for k in ("title", "url", "published_at", "source", "kind", "symbol", "description")}) for r in macro_rows]
            macro_status = [{"provider": "DEMO FIXTURE", "kind": "macro", "status": f"fixture:{len(macro_items)}"}]
        else:
            fetched = await asyncio.gather(
                *(self._live_bundle(symbol, now) for symbol in symbols),
                self.upgraded._cached_news(("macro", str(macro_fetch)), lambda: self.base.news.collect_macro(limit=macro_fetch)),
            )
            *bundle_results, (macro_items, macro_status, macro_hit) = fetched
            bundles = [bundle for bundle, _ in bundle_results]
            news_cache_hits = sum(int(hit) for _, hit in bundle_results) + int(macro_hit)
        news_ms = (time.perf_counter() - news_started) * 1000

        screened = [screen_bundle(bundle, config, now) for bundle in bundles]
        eodhd_configured = bool(self.base.settings.eodhd_news_api_token)
        if fixture:
            article_micro = [NewsItem(**{k: r.get(k) for k in ("title", "url", "published_at", "source", "kind", "symbol", "description")}) for b in bundles for r in b["fixture_article_micro"]]
        else:
            article_micro = [item for b in bundles for item in article_micro_selection(b, eodhd_configured=eodhd_configured)]
        article_macro = list(macro_items)[:ARTICLE_MACRO]
        if fixture:
            # Fixture: đúng thứ tự và cách chọn của `_fixture_portfolio` (không sắp xếp lại).
            article_items = article_micro + article_macro
        else:
            article_items = sorted(
                deduplicate(article_micro + article_macro),
                key=lambda item: (1 if item.published_at else 0, item.published_at or ""),
                reverse=True,
            )[:ARTICLE_PORTFOLIO_CAP]
        # Vĩ mô cho phần C: chỉ tin nói về kinh tế hay thị trường (judge_macro). Thiếu thì gọi thêm truy vấn
        # Google tin kinh tế của bản tái dựng. Ô cách bài báo vẫn dùng đúng macro_items như tab 2.
        macro_candidates: list[NewsItem] = []
        macro_kept: list[NewsItem] = []
        macro_rejected: list[dict[str, Any]] = []

        def run_macro_screen(items: list[NewsItem]) -> None:
            # Xét lại TOÀN BỘ ứng viên vĩ mô mỗi lần thêm tin, để chọn bản giữ trong nhóm trùng không phụ thuộc thứ tự.
            macro_candidates.extend(items)
            macro_kept.clear()
            macro_rejected.clear()
            for item, verdict in zip(macro_candidates, screen_macro(macro_candidates, now=now, lookback_days=config.lookback_days), strict=True):
                if verdict.keep:
                    macro_kept.append(item)
                else:
                    macro_rejected.append(dict(item.to_dict(), reason_code=verdict.reason_code, reason=verdict.reason))

        run_macro_screen(list(macro_items))
        google_macro_called = any(
            row.get("provider") == "Google News RSS" and "skipped" not in str(row.get("status", "")) for row in macro_status
        )
        macro_extra_status: list[dict[str, Any]] = []
        if not fixture and len(macro_kept) < config.macro_limit and not google_macro_called:

            async def load_google_macro() -> tuple[list[NewsItem], list[dict[str, Any]]]:
                meta: dict[str, Any] = {}
                try:
                    items = await self.base.news.google_macro_raw(meta)
                    status = f"candidates:{len(items)}"
                except (httpx.HTTPError, ValueError, TypeError) as exc:
                    items, status = [], "failed"
                    meta["error"] = type(exc).__name__
                return items, [{"provider": "Google News RSS (tin kinh tế, phần C)", "kind": "macro", "status": status, **meta}]

            extra_items, macro_extra_status, extra_hit = await self.upgraded._cached_news(
                ("coverage_macro_google", str(config.lookback_days)), load_google_macro
            )
            news_cache_hits += int(extra_hit)
            run_macro_screen(list(extra_items))
        elif not fixture:
            reason = "skipped_enough_economic" if len(macro_kept) >= config.macro_limit else "skipped_google_macro_already_called"
            macro_extra_status = [{"provider": "Google News RSS (tin kinh tế, phần C)", "kind": "macro", "status": reason}]
        macro_used = sorted(macro_kept, key=lambda item: (1 if item.published_at else 0, item.published_at or ""), reverse=True)[
            : config.macro_limit
        ]

        # Chấm FinBERT một lần cho mọi tiêu đề cần (tin riêng đã lọc, tin cách bài báo, tin vĩ mô).
        inference_started = time.perf_counter()
        if fixture:
            probs_by_title = {
                r["title"]: r["probabilities"]
                for r in self.base._fixture_rows() + self.extra_fixture.get("items", [])
                if r.get("probabilities")
            }
            inference_info: dict[str, Any] = {"requested": 0, "cache_hits": 0, "model_calls": 0, "mode": "fixture"}
        else:
            titles = [item.title for s in screened for item, _, _ in s["kept"]]
            titles += [item.title for item in article_items] + [item.title for item in macro_used]
            probs_by_title, inference_info = await self._score_titles(titles, symbols)
        inference_ms = (time.perf_counter() - inference_started) * 1000

        # Từng mã
        holdings: list[HoldingScore] = []
        for (symbol, weight), bundle, screen in zip(positions, bundles, screened, strict=True):
            rows = []
            for item, tier, alias in screen["kept"]:
                probabilities = probs_by_title[item.title]
                rows.append(
                    _item_out(
                        item,
                        tier,
                        matched_alias=alias,
                        probabilities=probabilities,
                        predicted_label=max(probabilities, key=probabilities.get).capitalize(),
                    )
                )
            signal = group_signal(rows, kind="micro", config=config, now=now)
            if signal:
                for row, score, weight_h, share in zip(rows, signal["headline_scores"], signal["headline_weights"], signal["shares"], strict=True):
                    row.update(score=score, weight=weight_h, share_of_holding_score=share)
            dated = [row["published_at"] for row in rows if row.get("published_at")]
            holdings.append(
                HoldingScore(
                    symbol=symbol,
                    weight_input=weight,
                    signal=signal,
                    extra={
                        "short": symbol.removesuffix(".EGX"),
                        "company": company_name(symbol),
                        "aliases": screen["aliases"],
                        "headlines": rows,
                        "rejected": screen["rejected"],
                        "not_scored": screen["not_scored"],
                        "candidates_total": screen["candidates_total"],
                        "old_filter_would_keep": screen["old_filter_would_keep"],
                        "oldest_published_at": min(dated) if dated else None,
                        "newest_published_at": max(dated) if dated else None,
                        "undated_count": len(rows) - len(dated),
                        "tier2_called": bundle.get("google2_raw") is not None,
                        "providers": bundle["statuses"],
                    },
                )
            )
        portfolio = summarize_portfolio(holdings, config)

        holding_out = []
        for h in holdings:
            sig = h.signal or {}
            for row in h.extra["headlines"]:
                row["contribution"] = None if h.r is None else h.r * row["share_of_holding_score"]
            holding_out.append(
                {
                    "symbol": h.symbol,
                    "weight_input": h.weight_input,
                    "w": h.w,
                    "has_news": h.has_news,
                    "n": sig.get("n", 0),
                    "score": sig.get("score"),
                    "label": h.label,
                    "probabilities": sig.get("probabilities"),
                    "score_min": sig.get("score_min"),
                    "score_max": sig.get("score_max"),
                    "label_counts": sig.get("label_counts"),
                    "r": h.r,
                    "contribution": h.contribution,
                    **h.extra,
                }
            )

        # Vĩ mô: điểm riêng, không cộng vào S.
        macro_rows = []
        for item in macro_used:
            probabilities = probs_by_title[item.title]
            macro_rows.append(
                dict(item.to_dict(), probabilities=probabilities, predicted_label=max(probabilities, key=probabilities.get).capitalize())
            )
        macro_signal = group_signal(macro_rows, kind="macro", config=config, now=now)
        if macro_signal:
            for row, score, share in zip(macro_rows, macro_signal["headline_scores"], macro_signal["shares"], strict=True):
                row.update(score=score, share_of_macro_score=share)

        # Cách bài báo, cùng lượt lấy tin.
        article_rows = []
        for item in article_items:
            probabilities = probs_by_title[item.title]
            article_rows.append(
                dict(
                    item.to_dict(),
                    probabilities=probabilities,
                    score=probabilities["positive"] - probabilities["negative"],
                    predicted_label=max(probabilities, key=probabilities.get).capitalize(),
                )
            )
        article = None
        if article_rows:
            probs, sentiment, score = aggregate_probabilities([row["probabilities"] for row in article_rows])
            article = {
                "method": "article_equal_weight_mean",
                "score": score,
                "sentiment": sentiment,
                "probabilities": probs,
                "headline_count": len(article_rows),
                "selection": "2 tin mới nhất mỗi mã theo bộ lọc tên cũ (alias trong tiêu đề hoặc mô tả) + 4 tin vĩ mô, gộp lại, tối đa 14; mỗi tiêu đề một phiếu, không theo vốn",
                "headlines": article_rows,
            }

        providers = [row for b in bundles for row in b["statuses"]] + list(macro_status) + list(macro_extra_status)
        total_ms = (time.perf_counter() - started) * 1000
        notes = list(LIMITATIONS)
        if fixture:
            notes.insert(0, self.base.fixture_data["notice"])
        return {
            "analysis_status": "completed",
            "data_mode": self.base.settings.demo_mode,
            "scope": "coverage_portfolio",
            "method_version": METHOD_VERSION,
            "relevance_rules": RULES_VERSION,
            "symbols": symbols,
            "config": {
                **config.to_dict(),
                "inference_batch_size": getattr(self.base.inference, "batch_size", None),
                "eodhd_candidate_limit": EODHD_CANDIDATE_LIMIT,
            },
            "holdings": holding_out,
            "portfolio": portfolio,
            "macro": None
            if macro_signal is None and not macro_rejected
            else {
                "n": 0 if macro_signal is None else macro_signal["n"],
                "score": None if macro_signal is None else macro_signal["score"],
                "label": None if macro_signal is None else macro_signal["label"],
                "label_counts": None if macro_signal is None else macro_signal["label_counts"],
                "probabilities": None if macro_signal is None else macro_signal["probabilities"],
                "score_rule": None if macro_signal is None else macro_signal["score_rule"],
                "headlines": macro_rows,
                "rejected": macro_rejected,
                "keep_rule": "Chỉ giữ tin vĩ mô có từ về kinh tế hay thị trường trong tiêu đề (lạm phát, lãi suất, tỷ giá, IMF, chứng khoán, …).",
                "note": "Tin kinh tế và thị trường Ai Cập, không tính vào điểm tin doanh nghiệp.",
            },
            "article_method": article,
            "providers": providers,
            "notes": notes,
            "disclaimer": DISCLAIMER,
            "timing_ms": {"news": news_ms, "inference": inference_ms, "total": total_ms},
            "data_freshness": None
            if fixture
            else {
                "live": True,
                "requested_at_utc": requested_at.isoformat(),
                "news_collection_ms": round(news_ms),
                "total_ms": round(total_ms),
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "news_cache": f"Nhóm tin lấy trong {round(self.upgraded.news_cache.ttl_seconds / 60)} phút gần nhất được dùng lại; quá hạn thì lấy mới.",
                "news_cache_ttl_seconds": self.upgraded.news_cache.ttl_seconds,
                "news_groups_from_cache": news_cache_hits,
                "news_groups_total": len(symbols) + 1,
            },
            "cache": {
                "news_cache_hits_this_request": news_cache_hits,
                "inference_this_request": inference_info,
                **self.upgraded.cache_stats(),
            },
        }
