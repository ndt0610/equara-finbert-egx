from __future__ import annotations

import calendar
import logging
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx

from backend.config import (
    BBC_MIDDLE_EAST_RSS,
    EODHD_NEWS_ENDPOINT,
    GOOGLE_NEWS_RSS,
    Settings,
)


logger = logging.getLogger("equara")
EGYPT_TERMS = ("egypt", "egyptian", "cairo", "egx")
NEWS_LOOKBACK_DAYS = 90
# [HOÀN THIỆN] Không bao giờ để lộ khóa API khi hiển thị địa chỉ đã gọi trên giao diện.
SECRET_QUERY_KEYS = {"api_token", "token", "apikey", "api_key", "key"}


def public_url(url: Any, params: dict[str, Any] | None = None) -> str:
    """Địa chỉ truy vấn thật (kèm tham số) nhưng đã bỏ mọi tham số bí mật như api_token."""
    full = httpx.URL(str(url), params=params) if params else httpx.URL(str(url))
    parts = urlsplit(str(full))
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in SECRET_QUERY_KEYS]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
STOCK_DIRECTORY: dict[str, dict[str, str | tuple[str, ...]]] = {
    "COMI.EGX": {
        "short": "COMI",
        "name": "Commercial International Bank",
        "aliases": ("COMI", "CIB", "Commercial International Bank"),
    },
    "ETEL.EGX": {
        "short": "ETEL",
        "name": "Telecom Egypt",
        "aliases": ("ETEL", "Telecom Egypt"),
    },
    "FWRY.EGX": {
        "short": "FWRY",
        "name": "Fawry",
        "aliases": ("FWRY", "Fawry"),
    },
    "ADIB.EGX": {
        "short": "ADIB",
        "name": "Abu Dhabi Islamic Bank Egypt",
        "aliases": ("ADIB", "Abu Dhabi Islamic Bank", "Abu Dhabi Islamic Bank Egypt"),
    },
    "EFIH.EGX": {
        "short": "EFIH",
        "name": "E-finance for Digital and Financial Investments",
        "aliases": ("EFIH", "E-finance", "E-finance for Digital and Financial Investments"),
    },
}


def company_name(symbol: str) -> str:
    return str(STOCK_DIRECTORY.get(symbol, {}).get("name", symbol.removesuffix(".EGX")))


def company_aliases(symbol: str) -> tuple[str, ...]:
    return tuple(str(a) for a in STOCK_DIRECTORY.get(symbol, {}).get("aliases", (symbol.removesuffix(".EGX"),)))


def google_stock_query(symbol: str, tier: int = 1) -> str:
    company = company_name(symbol)
    if tier == 1:
        return f'"{company}" Egypt EGX stock when:{NEWS_LOOKBACK_DAYS}d'
    return f'"{company}" when:{NEWS_LOOKBACK_DAYS}d'


@dataclass
class NewsItem:
    title: str
    url: str | None
    published_at: str | None
    source: str
    kind: str
    symbol: str | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_url(value: str | None) -> str:
    if not value:
        return ""
    parts = urlsplit(value.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def _normalize_title(value: str) -> str:
    value = re.sub(r"\s+", " ", value.casefold()).strip()
    return re.sub(r"[^\w\s]", "", value)


def deduplicate(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    result: list[NewsItem] = []
    for item in items:
        key = _canonical_url(item.url) or _normalize_title(item.title)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _parse_datetime(value: str | None, parsed: Any = None) -> str | None:
    if parsed is not None:
        try:
            stamp = calendar.timegm(parsed)
            return datetime.fromtimestamp(stamp, timezone.utc).isoformat()
        except (OverflowError, OSError, TypeError, ValueError):
            pass
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            moment = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def _sort_newest(items: list[NewsItem]) -> list[NewsItem]:
    def sort_key(item: NewsItem) -> tuple[int, str]:
        return (1 if item.published_at else 0, item.published_at or "")

    return sorted(items, key=sort_key, reverse=True)


def _is_within_lookback(item: NewsItem) -> bool:
    if not item.published_at:
        return True
    try:
        published = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_LOOKBACK_DAYS)
    return published.astimezone(timezone.utc) >= cutoff


def _is_egypt_related(text: str) -> bool:
    lowered = text.casefold()
    return any(term in lowered for term in EGYPT_TERMS)


def old_alias_filter(item: "NewsItem", aliases: tuple[str, ...]) -> bool:
    """Bộ lọc tên của bản tái dựng: alias (không phân biệt hoa thường) nằm trong tiêu đề + mô tả.

    Đây là phép so chuỗi con, nên "comi" khớp cả "coming". Phần C không sửa hàm này; luật mới
    nằm ở backend/upgrades/relevance.py và chỉ dùng cho tab nâng cấp.
    """
    text = f"{item.title} {item.description or ''}".casefold()
    return any(alias.casefold() in text for alias in aliases)


def usable_news(items: list[NewsItem], prefix: str) -> tuple[list[NewsItem], str]:
    distinct = deduplicate(items)
    recent = [item for item in distinct if _is_within_lookback(item)]
    if recent:
        return recent, f"{prefix}:{len(recent)}"
    return [], f"stale:{len(distinct)}" if distinct else "empty:0"


class NewsAggregator:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    async def collect_stock(self, symbol: str, limit: int = 15) -> tuple[list[NewsItem], list[dict[str, str]]]:
        statuses: list[dict[str, str]] = []
        items: list[NewsItem] = []

        if self.settings.eodhd_news_api_token:
            meta: dict[str, Any] = {}
            try:
                items = await self._eodhd_stock(symbol, max(limit, 20), meta)
                items, status = usable_news(items, "ok")
                statuses.append({"provider": "EODHD", "kind": "micro", "status": status, **meta})
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                logger.warning("provider=eodhd kind=micro status=failed error=%s", type(exc).__name__)
                statuses.append({"provider": "EODHD", "kind": "micro", "status": "failed", **meta})
        else:
            statuses.append({"provider": "EODHD", "kind": "micro", "status": "skipped_missing_api_key"})

        if not items:
            meta = {}
            try:
                items = await self._google_stock(symbol, max(limit, 20), meta)
                items, status = usable_news(items, "used")
                statuses.append({"provider": "Google News RSS", "kind": "micro", "status": status, **meta})
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                logger.warning("provider=google_news kind=micro status=failed error=%s", type(exc).__name__)
                statuses.append({"provider": "Google News RSS", "kind": "micro", "status": "failed", **meta})
        else:
            statuses.append({"provider": "Google News RSS", "kind": "micro", "status": "skipped_eodhd_nonempty"})

        for row in statuses:
            row.setdefault("symbol", symbol)  # giao diện biết lượt gọi này là tin của mã nào
        return _sort_newest(items)[:limit], statuses

    async def collect_macro(self, limit: int = 5) -> tuple[list[NewsItem], list[dict[str, str]]]:
        statuses: list[dict[str, str]] = []
        items: list[NewsItem] = []

        if self.settings.eodhd_news_api_token:
            meta: dict[str, Any] = {}
            try:
                items = await self._eodhd_egypt_macro(meta)
                items, status = usable_news(items, "ok")
                statuses.append({"provider": "EODHD general news + Egypt filter", "kind": "macro", "status": status, **meta})
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                logger.warning("provider=eodhd kind=macro status=failed error=%s", type(exc).__name__)
                statuses.append({"provider": "EODHD general news + Egypt filter", "kind": "macro", "status": "failed", **meta})
        else:
            statuses.append({"provider": "EODHD general news + Egypt filter", "kind": "macro", "status": "skipped_missing_api_key"})

        if not items:
            meta = {}
            try:
                items = await self._bbc_macro(meta)
                items, status = usable_news(items, "used")
                statuses.append({"provider": "BBC RSS", "kind": "macro", "status": status, **meta})
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                logger.warning("provider=bbc_rss kind=macro status=failed error=%s", type(exc).__name__)
                statuses.append({"provider": "BBC RSS", "kind": "macro", "status": "failed", **meta})
        else:
            statuses.append({"provider": "BBC RSS", "kind": "macro", "status": "skipped_eodhd_nonempty"})

        if not items:
            meta = {}
            try:
                items = await self._google_macro(meta)
                items, status = usable_news(items, "used")
                statuses.append({"provider": "Google News RSS", "kind": "macro", "status": status, **meta})
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                logger.warning("provider=google_news kind=macro status=failed error=%s", type(exc).__name__)
                statuses.append({"provider": "Google News RSS", "kind": "macro", "status": "failed", **meta})
        else:
            previous_provider = "BBC RSS" if any(row.get("provider") == "BBC RSS" and row.get("status", "").startswith("used:") for row in statuses) else "EODHD"
            statuses.append({"provider": "Google News RSS", "kind": "macro", "status": f"skipped_{previous_provider.lower().replace(' ', '_')}_nonempty"})

        return _sort_newest(items)[:limit], statuses

    async def _get(self, url: str, params: dict[str, Any] | None, meta: dict[str, Any] | None) -> httpx.Response:
        """GET thật tới nguồn tin; ghi lại lúc gọi, địa chỉ (đã bỏ khóa API), mã HTTP và thời gian chờ."""
        fetched_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        if meta is not None:
            meta["query_url"] = public_url(url, params)
            meta["fetched_at"] = fetched_at.isoformat()
        try:
            response = await self.client.get(url, params=params)
        finally:
            if meta is not None:
                meta["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
        if meta is not None:
            meta["http_status"] = response.status_code
        return response

    async def _eodhd_stock(self, symbol: str, limit: int, meta: dict[str, Any] | None = None) -> list[NewsItem]:
        response = await self._get(
            EODHD_NEWS_ENDPOINT,
            {
                "s": symbol,
                "limit": min(max(limit, 1), 1000),
                "api_token": self.settings.eodhd_news_api_token,
                "fmt": "json",
            },
            meta,
        )
        if response.status_code >= 400:
            raise httpx.HTTPStatusError("EODHD request failed", request=response.request, response=response)
        payload = response.json()
        if not isinstance(payload, list):
            return []
        items: list[NewsItem] = []
        for row in payload:
            if not isinstance(row, dict) or not row.get("title"):
                continue
            items.append(
                NewsItem(
                    title=str(row["title"]).strip(),
                    url=row.get("link"),
                    published_at=_parse_datetime(row.get("date")),
                    source="EODHD",
                    kind="micro",
                    symbol=symbol,
                    description=row.get("content"),
                )
            )
        return items

    async def _eodhd_egypt_macro(self, meta: dict[str, Any] | None = None) -> list[NewsItem]:
        response = await self._get(
            EODHD_NEWS_ENDPOINT,
            {"limit": 100, "api_token": self.settings.eodhd_news_api_token, "fmt": "json"},
            meta,
        )
        if response.status_code >= 400:
            raise httpx.HTTPStatusError("EODHD request failed", request=response.request, response=response)
        payload = response.json()
        if not isinstance(payload, list):
            return []
        items: list[NewsItem] = []
        for row in payload:
            if not isinstance(row, dict) or not row.get("title"):
                continue
            title = str(row["title"]).strip()
            description = row.get("content")
            if not _is_egypt_related(f"{title} {description or ''}"):
                continue
            items.append(
                NewsItem(
                    title=title,
                    url=row.get("link"),
                    published_at=_parse_datetime(row.get("date")),
                    source="EODHD",
                    kind="macro",
                    description=description,
                )
            )
        return items

    async def _rss(self, url: str, params: dict[str, str] | None = None, meta: dict[str, Any] | None = None) -> Any:
        response = await self._get(url, params, meta)
        if response.status_code >= 400:
            raise httpx.HTTPStatusError("RSS request failed", request=response.request, response=response)
        parsed = feedparser.parse(response.content)
        if parsed.bozo and not parsed.entries:
            raise ValueError("RSS response could not be parsed")
        return parsed

    async def _bbc_macro(self, meta: dict[str, Any] | None = None) -> list[NewsItem]:
        parsed = await self._rss(BBC_MIDDLE_EAST_RSS, None, meta)
        items: list[NewsItem] = []
        for row in parsed.entries:
            title = str(row.get("title", "")).strip()
            description = str(row.get("summary", "")).strip()
            if not title or not _is_egypt_related(f"{title} {description}"):
                continue
            items.append(
                NewsItem(
                    title=title,
                    url=row.get("link"),
                    published_at=_parse_datetime(row.get("published"), row.get("published_parsed")),
                    source="BBC RSS",
                    kind="macro",
                    description=description or None,
                )
            )
        return items

    async def _google_macro(self, meta: dict[str, Any] | None = None) -> list[NewsItem]:
        parsed = await self._rss(
            GOOGLE_NEWS_RSS,
            {"q": f"Egypt economy OR Egyptian economy OR EGX when:{NEWS_LOOKBACK_DAYS}d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
            meta,
        )
        return self._google_entries(parsed.entries, kind="macro", symbol=None, egypt_only=True)

    async def google_macro_raw(self, meta: dict[str, Any] | None = None) -> list[NewsItem]:
        """[NÂNG CẤP C] Đúng truy vấn Google vĩ mô của bản tái dựng (tin kinh tế Ai Cập), gọi trực tiếp.

        Phần C gọi khi các tin vĩ mô của `collect_macro` không có đủ tin về kinh tế hay thị trường.
        """
        return await self._google_macro(meta)

    async def _google_stock(self, symbol: str, limit: int, meta: dict[str, Any] | None = None) -> list[NewsItem]:
        # Bộ lọc của bản tái dựng (giữ nguyên): alias nằm ở đâu đó trong tiêu đề hoặc mô tả.
        aliases = company_aliases(symbol)
        accepted = [
            item for item in await self.google_stock_raw(symbol, tier=1, meta=meta) if old_alias_filter(item, aliases)
        ]
        return accepted[:limit]

    async def google_stock_raw(self, symbol: str, tier: int = 1, meta: dict[str, Any] | None = None) -> list[NewsItem]:
        """[NÂNG CẤP C] Mọi mục của feed Google News cho một mã, theo đúng thứ tự feed, CHƯA lọc tên.

        Bậc 1 là đúng truy vấn của bản tái dựng. Bậc 2 (chỉ khi bật trong cấu hình phần C) bỏ bớt
        "Egypt EGX stock" để tìm rộng hơn; kết quả vẫn phải đi qua luật lọc của phần C.
        """
        parsed = await self._rss(
            GOOGLE_NEWS_RSS,
            {"q": google_stock_query(symbol, tier), "hl": "en-US", "gl": "US", "ceid": "US:en"},
            meta,
        )
        return self._google_entries(parsed.entries, kind="micro", symbol=symbol, egypt_only=False)

    async def eodhd_stock_raw(self, symbol: str, limit: int = 20, meta: dict[str, Any] | None = None) -> list[NewsItem]:
        """[NÂNG CẤP C] Tin EODHD gắn với mã, chưa lọc (cùng lệnh gọi mà `collect_stock` dùng)."""
        return await self._eodhd_stock(symbol, limit, meta)

    @staticmethod
    def _google_entries(entries: Any, kind: str, symbol: str | None, egypt_only: bool) -> list[NewsItem]:
        items: list[NewsItem] = []
        for row in entries:
            title = str(row.get("title", "")).strip()
            description = str(row.get("summary", "")).strip()
            if not title:
                continue
            if egypt_only and not _is_egypt_related(f"{title} {description}"):
                continue
            items.append(
                NewsItem(
                    title=title,
                    url=row.get("link"),
                    published_at=_parse_datetime(row.get("published"), row.get("published_parsed")),
                    source="Google News RSS",
                    kind=kind,
                    symbol=symbol,
                    description=description or None,
                )
            )
        return items

