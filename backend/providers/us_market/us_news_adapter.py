"""Optional licensed news adapter; only metadata/headlines are retained locally."""
from __future__ import annotations

import os
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx

from backend.providers.us_market.sec_edgar_adapter import ProviderUnconfigured
from backend.storage.pit_ledger import utc_now


class UsNewsProvider(Protocol):
    async def fetch(self, tickers: list[str]) -> list[dict]: ...


class AlpacaNewsProvider:
    license_tag = "ALPACA_RIGHTS_REVIEW_REQUIRED"

    def __init__(self, key: str | None = None, secret: str | None = None,
                 client: httpx.AsyncClient | None = None, lookback_calendar_days: int = 7,
                 max_pages: int = 200):
        if not 1 <= lookback_calendar_days <= 365 or not 1 <= max_pages <= 1000:
            raise ValueError("INVALID_NEWS_CAPTURE_CONFIGURATION")
        self.lookback_calendar_days = lookback_calendar_days
        self.max_pages = max_pages
        self.key = key or os.getenv("ALPACA_API_KEY")
        self.secret = secret or os.getenv("ALPACA_SECRET_KEY")
        if not self.key or not self.secret:
            raise ProviderUnconfigured("ALPACA_API_KEY and ALPACA_SECRET_KEY required")
        self.client = client
        self._raw_responses: list[bytes] = []

    @property
    def raw_batch_hash(self) -> str:
        digest = hashlib.sha256()
        for payload in self._raw_responses:
            digest.update(len(payload).to_bytes(8, "big")); digest.update(payload)
        return digest.hexdigest()

    async def fetch(self, tickers: list[str]) -> list[dict]:
        headers = {"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret}
        params = {"symbols": ",".join(tickers), "limit": 50, "sort": "desc",
                  "start": (datetime.now(timezone.utc) - timedelta(days=self.lookback_calendar_days)).isoformat()}
        rows = []
        for _ in range(self.max_pages):
            if self.client is not None:
                response = await self.client.get("https://data.alpaca.markets/v1beta1/news", params=params, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.get("https://data.alpaca.markets/v1beta1/news", params=params, headers=headers)
            response.raise_for_status()
            self._raw_responses.append(response.content)
            page = response.json()
            rows.extend(page.get("news", []))
            token = page.get("next_page_token")
            if not token:
                break
            params["page_token"] = token
        else:
            raise ValueError("NEWS_PAGE_LIMIT_REACHED")
        captured = utc_now()
        return [{
            "item_id": f"ALPACA:{row['id']}:{ticker}", "ticker": ticker, "cik": None,
            "headline": row["headline"], "summary": None, "source_name": row.get("source", "Alpaca News"),
            "source_url": row.get("url"), "external_event_key": str(row["id"]),
            "item_type": "NEWS_HEADLINE", "sec_form_type": None, "sec_items": [],
            "published_at_utc": row.get("created_at"), "provider_accepted_at_utc": None,
            "ingested_at_utc": captured,
        } for row in rows for ticker in row.get("symbols", []) if ticker in tickers]
