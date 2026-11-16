"""Alpaca daily bars in two separately requested adjustment regimes."""
from __future__ import annotations

import os
import hashlib
from datetime import date, datetime, timedelta, timezone

import httpx

from backend.providers.us_market.sec_edgar_adapter import ProviderUnconfigured
from backend.storage.pit_ledger import utc_now
from backend.universe.calendar_nyse import close_at, is_session


class AlpacaPriceAccessError(RuntimeError):
    def __init__(self, status_code: int, provider_message: str):
        self.status_code = status_code
        self.provider_message = provider_message[:240]
        super().__init__(f"ALPACA_PRICE_ACCESS_{status_code}: {self.provider_message}. For SIP historical bars, use end_ts_utc at least 20 minutes before request time or check your data entitlement.")


class AlpacaPriceProvider:
    license_tag = "ALPACA_RIGHTS_REVIEW_REQUIRED"

    def __init__(self, key: str | None = None, secret: str | None = None,
                 client: httpx.AsyncClient | None = None):
        self.key = key or os.getenv("ALPACA_API_KEY")
        self.secret = secret or os.getenv("ALPACA_SECRET_KEY")
        if not self.key or not self.secret:
            raise ProviderUnconfigured("ALPACA_API_KEY and ALPACA_SECRET_KEY required")
        self.feed = os.getenv("ALPACA_PRICE_FEED", "sip").strip().lower()
        if self.feed not in {"sip", "iex"}:
            raise ProviderUnconfigured("ALPACA_PRICE_FEED must be sip or iex")
        self.client = client
        self._raw_responses: list[bytes] = []
        self.effective_end_ts_utc: str | None = None

    @property
    def raw_batch_hash(self) -> str:
        digest = hashlib.sha256()
        for payload in self._raw_responses:
            digest.update(len(payload).to_bytes(8, "big")); digest.update(payload)
        return digest.hexdigest()

    async def _fetch(self, tickers: list[str], adjustment: str, end_ts_utc: datetime,
                     lookback_calendar_days: int) -> dict:
        headers = {"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret}
        params = {"symbols": ",".join(tickers), "timeframe": "1Day", "limit": 1000,
                  "adjustment": adjustment, "feed": self.feed,
                  "start": (end_ts_utc - timedelta(days=lookback_calendar_days)).isoformat(),
                  "end": end_ts_utc.isoformat()}
        url = "https://data.alpaca.markets/v2/stocks/bars"
        output = {}
        while True:
            if self.client is not None:
                response = await self.client.get(url, params=params, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.get(url, params=params, headers=headers)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                try:
                    message = str(response.json().get("message", "provider denied request"))
                except (ValueError, AttributeError):
                    message = "provider denied request"
                raise AlpacaPriceAccessError(response.status_code, message) from exc
            self._raw_responses.append(response.content)
            for ticker, rows in response.json().get("bars", {}).items():
                for row in rows:
                    output[(ticker, row["t"][:10])] = row
            token = response.json().get("next_page_token")
            if not token:
                break
            params["page_token"] = token
        return output

    async def fetch(self, tickers: list[str], end_ts_utc: datetime | None = None,
                    lookback_calendar_days: int = 30) -> list[dict]:
        if not 30 <= lookback_calendar_days <= 90:
            raise ValueError("INVALID_PRICE_LOOKBACK_DAYS")
        now = datetime.now(timezone.utc)
        end = end_ts_utc or (now - timedelta(minutes=20) if self.feed == "sip" else now)
        if end.tzinfo is None or end.utcoffset() is None:
            raise ValueError("TIMEZONE_REQUIRED")
        end = end.astimezone(timezone.utc)
        if end > now:
            raise ValueError("PRICE_END_IN_FUTURE")
        if self.feed == "sip" and end > now - timedelta(minutes=20):
            raise ValueError("SIP_END_TOO_RECENT_USE_20_MINUTE_DELAY")
        self.effective_end_ts_utc = end.isoformat()
        raw = await self._fetch(tickers, "raw", end, lookback_calendar_days)
        adjusted = await self._fetch(tickers, "all", end, lookback_calendar_days)
        captured = utc_now()
        return [{
            "ticker": ticker, "session_date": day, "open_raw": row["o"],
            "high_raw": row.get("h"), "low_raw": row.get("l"), "close_raw": row["c"],
            "open_adj": adjusted.get((ticker, day), {}).get("o"),
            "close_adj": adjusted.get((ticker, day), {}).get("c"), "volume": row.get("v"),
            "split_factor": None, "dividend_cash": None,
            "adjustment_asof_utc": captured, "as_of_ingested_utc": captured, "data_feed": self.feed.upper(),
        } for (ticker, day), row in sorted(raw.items())
          if is_session(date.fromisoformat(day)) and close_at(date.fromisoformat(day)).astimezone(timezone.utc) <= end]
