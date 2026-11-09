"""Thu một lượt MỌI ứng viên tin (trước khi lọc) cho các mã, để sau này đo luật lọc và độ phủ theo ngày.

Vì sao cần: muốn biết luật lọc đúng hay sai, và độ phủ thật sự thường là bao nhiêu, phải giữ lại cả những
tin bị loại, cùng lúc lấy, địa chỉ truy vấn và (nếu chọn) xác suất FinBERT của từng tin. Mỗi lần chạy tạo
một thư mục mới, không ghi đè lần trước.

Chạy (cần mạng; trên Colab hoặc máy có internet):
    python -m scripts.capture_candidates                       # 5 mã COMI, ETEL, FWRY, ADIB, EFIH, mọi truy vấn
    python -m scripts.capture_candidates --score               # thêm xác suất FinBERT cho mọi ứng viên
    python -m scripts.capture_candidates --no-tier2            # bỏ truy vấn Google bậc 2 (nhanh hơn, thiếu dữ liệu đo)
Kết quả: captures/<giờ chạy UTC>/capture.json và candidates.csv

Công cụ luôn thu MỌI truy vấn (EODHD nếu có khóa, Google bậc 1, Google bậc 2, tin vĩ mô, truy vấn tin kinh tế),
rồi đánh dấu tin nào web sẽ gọi và chấm. Quyết định "web gọi truy vấn nào" lấy từ chính hàm `fetch_candidates`
của web, chạy lại trên dữ liệu vừa thu, không chép lại luật.

Không bao giờ ghi khóa API: địa chỉ truy vấn đã bỏ api_token; chỉ ghi "có cấu hình EODHD hay không".
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import MODEL_ID, Settings
from backend.providers.news import NewsItem, company_aliases, company_name, google_stock_query
from backend.schemas import normalize_symbol
from backend.upgrades.coverage import METHOD_VERSION, CoverageConfig
from backend.upgrades.coverage_service import ARTICLE_MACRO, fetch_candidates
from backend.upgrades.relevance import RULES_VERSION, screen, screen_macro

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SYMBOLS = ("COMI", "ETEL", "FWRY", "ADIB", "EFIH")
CSV_FIELDS = (
    "capture_id", "captured_at_utc", "kind", "symbol", "company", "source", "list", "query_tier", "feed_position",
    "title", "url", "published_at", "new_keep", "new_reason_code", "old_filter_keep",
    "web_source_used", "web_scored", "p_positive", "p_negative", "p_neutral",
)


class _ReplayNews:
    """Trả lại các danh sách đã thu thay cho mạng, và ghi lại web gọi truy vấn nào."""

    def __init__(self, lists: dict[str, list[NewsItem] | None]) -> None:
        self.lists = lists
        self.called: set[str] = set()

    async def eodhd_stock_raw(self, symbol: str, limit: int, meta: dict[str, Any] | None = None) -> list[NewsItem]:
        self.called.add("eodhd")
        return list(self.lists.get("eodhd") or [])

    async def google_stock_raw(self, symbol: str, tier: int, meta: dict[str, Any] | None = None) -> list[NewsItem]:
        key = "google1" if tier == 1 else "google2"
        self.called.add(key)
        return list(self.lists.get(key) or [])


async def web_lists_called(
    symbol: str, lists: dict[str, list[NewsItem] | None], *, now: datetime, config: CoverageConfig, eodhd_configured: bool
) -> set[str]:
    """Các truy vấn web sẽ gọi cho mã này, quyết định bởi chính `fetch_candidates` của web."""
    replay = _ReplayNews(lists)
    await fetch_candidates(replay, symbol, config, eodhd_configured=eodhd_configured, now=now)  # type: ignore[arg-type]
    return replay.called


def build_symbol_rows(
    symbol: str,
    lists: dict[str, list[NewsItem] | None],
    *,
    now: datetime,
    config: CoverageConfig | None = None,
    web_lists: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Gắn nhãn luật mới, bộ lọc cũ và "web có dùng tin này không" cho mọi ứng viên của một mã.

    `lists` có khóa "eodhd", "google1", "google2" (None = không gọi). Thứ tự xét giống web:
    EODHD, rồi Google bậc 1, rồi bậc 2. Từ relevance-v3, nhãn của tin web dùng được tính bằng `screen` trên đúng
    các truy vấn web gọi, nên giống hệt web; tin web không dùng được xét cùng toàn bộ ứng viên, chỉ để đo.
    `web_lists`: truy vấn web gọi (từ `web_lists_called`); bỏ trống thì tự tính, coi EODHD có cấu hình khi
    `lists["eodhd"]` không phải None.
    """
    config = config or CoverageConfig()
    if web_lists is None:
        web_lists = asyncio.run(
            web_lists_called(symbol, lists, now=now, config=config, eodhd_configured=lists.get("eodhd") is not None)
        )
    aliases = company_aliases(symbol)
    entries = [
        (key, source, tier, position, item)
        for key, source, tier in (("eodhd", "EODHD", 1), ("google1", "Google News RSS", 1), ("google2", "Google News RSS", 2))
        for position, item in enumerate(lists.get(key) or [], start=1)
    ]
    every = screen([e[4] for e in entries], aliases, now=now, lookback_days=config.lookback_days, ranks=[e[2] for e in entries])
    web_index = [i for i, e in enumerate(entries) if e[0] in web_lists]
    web_verdicts = screen(
        [entries[i][4] for i in web_index], aliases, now=now, lookback_days=config.lookback_days, ranks=[entries[i][2] for i in web_index]
    )
    verdict_at = dict(zip(web_index, web_verdicts, strict=True))
    rows: list[dict[str, Any]] = []
    for index, (key, source, tier, position, item) in enumerate(entries):
        verdict = verdict_at.get(index, every[index])
        rows.append(
            {
                "kind": "micro",
                "symbol": symbol,
                "company": company_name(symbol),
                "source": source,
                "list": key,
                "query_tier": tier,
                "feed_position": position,
                "title": item.title,
                "url": item.url,
                "published_at": item.published_at,
                "description": item.description,
                "new_keep": verdict.keep,
                "new_reason_code": verdict.reason_code or "",
                "old_filter_keep": verdict.old_filter_keep,
            }
        )
    kept_web = [r for r in rows if r["list"] in web_lists and r["new_keep"]]
    kept_web.sort(key=lambda r: (1 if r["published_at"] else 0, r["published_at"] or ""), reverse=True)
    scored_ids = {id(r) for r in kept_web[: config.max_headlines_per_holding]}
    for r in rows:
        r["web_source_used"] = r["list"] in web_lists
        r["web_scored"] = id(r) in scored_ids
    return rows


def build_macro_rows(
    collected: list[NewsItem],
    economic: list[NewsItem] | None,
    *,
    google_already_called: bool,
    now: datetime,
    config: CoverageConfig | None = None,
) -> list[dict[str, Any]]:
    """Tin vĩ mô: `collected` là kết quả `collect_macro`, `economic` là truy vấn Google tin kinh tế (None = không thu).

    Web xét `collected[:max(4, macro_limit)]` bằng `judge_macro`; nếu giữ được ít hơn `macro_limit` tin và
    `collect_macro` chưa gọi Google thì gọi thêm truy vấn tin kinh tế. Các tin web không xét vẫn được chấm
    luật để đo, sau cùng, nên không làm đổi nhãn trùng của tin web dùng.
    """
    config = config or CoverageConfig()
    web_n = max(ARTICLE_MACRO, config.macro_limit)
    kept_first = sum(1 for v in screen_macro(collected[:web_n], now=now, lookback_days=config.lookback_days) if v.keep)
    web_calls_economic = kept_first < config.macro_limit and not google_already_called
    # (danh sách, vị trí đầu, web có dùng không), theo đúng thứ tự cũ.
    parts: list[tuple[list[NewsItem], str, int, bool]] = [(collected[:web_n], "macro", 0, True)]
    if economic is not None and web_calls_economic:
        parts.append((economic, "macro_economic", 0, True))
    parts.append((collected[web_n:], "macro", web_n, False))
    if economic is not None and not web_calls_economic:
        parts.append((economic, "macro_economic", 0, False))
    entries = [(name, offset + n, used, item) for items, name, offset, used in parts for n, item in enumerate(items, start=1)]
    every = screen_macro([e[3] for e in entries], now=now, lookback_days=config.lookback_days)
    web_index = [i for i, e in enumerate(entries) if e[2]]
    web_verdicts = screen_macro([entries[i][3] for i in web_index], now=now, lookback_days=config.lookback_days)
    verdict_at = dict(zip(web_index, web_verdicts, strict=True))
    rows: list[dict[str, Any]] = []
    for index, (list_name, position, used, item) in enumerate(entries):
        verdict = verdict_at.get(index, every[index])
        rows.append(
            {
                "kind": "macro", "symbol": "", "company": "", "source": item.source, "list": list_name, "query_tier": 1,
                "feed_position": position, "title": item.title, "url": item.url, "published_at": item.published_at,
                "description": item.description, "new_keep": verdict.keep, "new_reason_code": verdict.reason_code or "",
                "old_filter_keep": "", "web_source_used": used,
            }
        )
    kept_web = [r for r in rows if r["web_source_used"] and r["new_keep"]]
    kept_web.sort(key=lambda r: (1 if r["published_at"] else 0, r["published_at"] or ""), reverse=True)
    scored_ids = {id(r) for r in kept_web[: config.macro_limit]}
    for r in rows:
        r["web_scored"] = id(r) in scored_ids
    return rows


def write_capture(out_dir: Path, meta: dict[str, Any], rows: list[dict[str, Any]], statuses: list[dict[str, Any]]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=False)
    for row in rows:
        row.setdefault("capture_id", meta["capture_id"])
        row.setdefault("captured_at_utc", meta["captured_at_utc"])
    (out_dir / "capture.json").write_text(
        json.dumps({"meta": meta, "providers": statuses, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    with (out_dir / "candidates.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            probs = row.get("probabilities") or {}
            writer.writerow({**row, "p_positive": probs.get("positive", ""), "p_negative": probs.get("negative", ""), "p_neutral": probs.get("neutral", "")})
    return out_dir


async def capture(symbols: list[str], *, tier2: bool, score: bool, out_root: Path, transport: Any = None) -> Path:
    import httpx

    from backend.services.sentiment import SentimentService

    settings = Settings.from_environment()
    if settings.demo_mode != "live":
        raise SystemExit("Cần DEMO_MODE=live để thu tin thật.")
    config = CoverageConfig.from_environment()
    now = datetime.now(timezone.utc)
    capture_id = now.strftime("%Y-%m-%dT%H%M%SZ")
    statuses: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0), follow_redirects=True, transport=transport) as client:
        service = SentimentService(client, settings)
        news = service.news

        async def attempt(provider: str, symbol: str, tier: int, coro_factory) -> list[NewsItem] | None:
            meta: dict[str, Any] = {}
            try:
                items = await coro_factory(meta)
                statuses.append({"provider": provider, "symbol": symbol, "tier": tier, "status": f"candidates:{len(items)}", **meta})
                return items
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                statuses.append({"provider": provider, "symbol": symbol, "tier": tier, "status": "failed", "error": type(exc).__name__, **meta})
                return []

        for symbol in symbols:
            lists: dict[str, list[NewsItem] | None] = {"eodhd": None, "google1": None, "google2": None}
            if settings.eodhd_api_token:
                lists["eodhd"] = await attempt("EODHD", symbol, 1, lambda m, s=symbol: news.eodhd_stock_raw(s, 20, m))
            lists["google1"] = await attempt("Google News RSS", symbol, 1, lambda m, s=symbol: news.google_stock_raw(s, 1, m))
            if tier2:
                lists["google2"] = await attempt("Google News RSS", symbol, 2, lambda m, s=symbol: news.google_stock_raw(s, 2, m))
            called = await web_lists_called(symbol, lists, now=now, config=config, eodhd_configured=bool(settings.eodhd_api_token))
            if "google2" in called and lists["google2"] is None:
                statuses.append({"provider": "Google News RSS", "symbol": symbol, "tier": 2, "status": "not_captured_but_web_would_call"})
            rows.extend(build_symbol_rows(symbol, lists, now=now, config=config, web_lists=called))

        macro, macro_status = await news.collect_macro(limit=15)
        statuses.extend(dict(row, symbol=None) for row in macro_status)
        google_already_called = any(
            row.get("provider") == "Google News RSS" and "skipped" not in str(row.get("status", "")) for row in macro_status
        )
        economic = None
        if not google_already_called:
            economic = await attempt("Google News RSS (tin kinh tế, phần C)", None, 1, lambda m: news.google_macro_raw(m))
        rows.extend(build_macro_rows(macro, economic, google_already_called=google_already_called, now=now, config=config))

        model_meta: dict[str, Any] = {"scored": False}
        if score:
            titles = list(dict.fromkeys(row["title"] for row in rows))
            probabilities = await service.inference.classify_many(titles)
            by_title = dict(zip(titles, probabilities, strict=True))
            for row in rows:
                row["probabilities"] = by_title[row["title"]]
            model_meta = {
                "scored": True,
                "model": MODEL_ID,
                "provider": settings.inference_provider,
                "revision": getattr(service.inference, "revision", None),
                "device": getattr(service.inference, "device_name", None),
                "titles_scored": len(titles),
            }

    meta = {
        "capture_id": capture_id,
        "captured_at_utc": now.isoformat(),
        "runtime": "Colab" if "COLAB_RELEASE_TAG" in os.environ else platform.system(),
        "python": sys.version.split()[0],
        "symbols": symbols,
        "relevance_rules": RULES_VERSION,
        "method_version": METHOD_VERSION,
        "lookback_days": config.lookback_days,
        "tier2_below": config.tier2_below,
        "macro_limit": config.macro_limit,
        "tier2_called": tier2,
        "eodhd_configured": bool(settings.eodhd_api_token),
        "queries": {s: {"google_tier1": google_stock_query(s, 1), "google_tier2": google_stock_query(s, 2)} for s in symbols},
        "model": model_meta,
    }
    return write_capture(out_root / capture_id, meta, rows, statuses)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="Các mã EGX, cách nhau bằng dấu phẩy.")
    parser.add_argument("--tier2", dest="tier2", action="store_true", default=True, help="Gọi truy vấn Google bậc 2 cho mọi mã (mặc định).")
    parser.add_argument("--no-tier2", dest="tier2", action="store_false", help="Không gọi truy vấn Google bậc 2.")
    parser.add_argument("--score", action="store_true", help="Chấm FinBERT cho mọi ứng viên (kể cả tin bị loại).")
    parser.add_argument("--out", default=str(ROOT / "captures"))
    args = parser.parse_args()
    symbols = [normalize_symbol(s) for s in args.symbols.split(",") if s.strip()]
    out = asyncio.run(capture(symbols, tier2=args.tier2, score=args.score, out_root=Path(args.out)))
    print(f"Đã lưu: {out}")


if __name__ == "__main__":
    main()
