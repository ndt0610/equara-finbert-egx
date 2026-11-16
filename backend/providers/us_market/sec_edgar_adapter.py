"""SEC submissions metadata adapter. Acceptance is not web availability."""
from __future__ import annotations

import asyncio
import hashlib
import os

import httpx

from backend.storage.pit_ledger import utc_now
from backend.universe.catalog import universe_by_ticker

FORMS = {"8-K", "10-Q", "10-K", "6-K"}


class ProviderUnconfigured(ValueError):
    pass


class SecEdgarAdapter:
    def __init__(self, user_agent: str | None = None, client: httpx.AsyncClient | None = None):
        self.user_agent = user_agent if user_agent is not None else os.getenv("SEC_EDGAR_USER_AGENT", "")
        if not self.user_agent.strip() or "@" not in self.user_agent:
            raise ProviderUnconfigured("SEC_EDGAR_USER_AGENT must identify an app and contact email")
        self.client = client
        self._lock = asyncio.Lock()
        self._next_request = 0.0
        self.response_hashes: dict[str, str] = {}
        self._raw_responses: list[bytes] = []

    @property
    def raw_batch_hash(self) -> str:
        digest = hashlib.sha256()
        for payload in self._raw_responses:
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
        return digest.hexdigest()

    async def _get(self, cik: str) -> dict:
        async with self._lock:
            loop = asyncio.get_running_loop()
            await asyncio.sleep(max(0, self._next_request - loop.time()))
            self._next_request = loop.time() + 0.21  # Below five requests per second.
            url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
            if self.client is not None:
                response = await self.client.get(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
            else:
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.get(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
            response.raise_for_status()
            self.response_hashes[cik] = hashlib.sha256(response.content).hexdigest()
            self._raw_responses.append(response.content)
            return response.json()

    async def fetch(self, tickers: list[str]) -> tuple[list[dict], list[dict]]:
        catalog = universe_by_ticker()
        events, errors = [], []
        for ticker in tickers:
            if ticker not in catalog:
                errors.append({"ticker": ticker, "reason": "OUTSIDE_UNIVERSE"})
                continue
            cik = str(catalog[ticker]["cik"])
            try:
                raw = await self._get(cik)
                captured = utc_now()
                recent = raw["filings"]["recent"]
                n = len(recent["accessionNumber"])
                for i in range(n):
                    form = recent["form"][i]
                    if form not in FORMS:
                        continue
                    accession = recent["accessionNumber"][i]
                    accepted_raw = recent.get("acceptanceDateTime", [None] * n)[i]
                    # The JSON acceptance clock cannot prove first public availability. Its
                    # timezone encoding is not independently established here; keep raw text.
                    primary = recent.get("primaryDocument", [""] * n)[i]
                    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{primary}" if primary else None
                    events.append({
                        "item_id": f"SEC:{cik}:{accession}", "ticker": ticker, "cik": cik,
                        "headline": f"Form {form}" + (f" (Items {recent['items'][i]})" if recent.get("items") and recent["items"][i] else ""),
                        "summary": None, "source_name": "SEC EDGAR", "source_url": url,
                        "external_event_key": accession, "item_type": "SEC_FILING",
                        "sec_form_type": form, "sec_items": [x.strip() for x in (recent.get("items", [""] * n)[i] or "").split(",") if x.strip()],
                        "published_at_utc": captured, "provider_accepted_at_utc": None,
                        "provider_accepted_raw": accepted_raw, "ingested_at_utc": captured,
                        "publication_time_basis": "EQUARA_FIRST_OBSERVED_UPPER_BOUND",
                        "source_filing_date": recent.get("filingDate", [None] * n)[i],
                    })
            except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
                errors.append({"ticker": ticker, "reason": type(exc).__name__})
        return events, errors
