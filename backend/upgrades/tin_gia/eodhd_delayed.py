"""Adapter EODHD cho giá EGX bị trễ và nến EOD.

Không gọi WebSocket real-time của EODHD cho mã EGX: tài liệu nhà cung cấp hiện chỉ nêu stream
real-time cho Mỹ/Châu Âu; API toàn cầu là delayed. Adapter này chỉ phục vụ bối cảnh hiển thị,
không đủ bid/ask hoặc quyền/cadence để phát nhãn giao dịch.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

import httpx

from .dong_tien import decimal_finite
from .nguon_gia import ProviderProfile, QuoteSnapshot

EODHD_DELAYED_URL = "https://eodhd.com/api/real-time"
EODHD_EOD_URL = "https://eodhd.com/api/eod"
DELAYED_PROFILE_ID = "eodhd-egx-delayed-v1"
# Nhà cung cấp nêu độ trễ global equities 15–20 phút: giữ đầu trên làm nhãn bảo thủ.
DECLARED_DELAY_UPPER_SECONDS = 20 * 60
# Hai ngưỡng sau chỉ là hàng rào UI để đánh dấu response/quote cũ, chưa phải tham số thị trường.
MAX_RESPONSE_AGE_SECONDS = 3 * 60
MAX_QUOTE_AGE_SECONDS = 30 * 60


class EODHDDataError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _ticker(symbol: str) -> str:
    value = symbol.strip().upper()
    if value.endswith(".EGX"):
        value = value[:-4]
    if not re.fullmatch(r"[A-Z0-9]{2,8}", value):
        raise EODHDDataError("invalid_symbol", "Chỉ hỗ trợ mã EGX gồm 2–8 ký tự chữ/số.")
    return f"{value}.EGX"


def _decimal_or_none(raw: Any, field: str):
    if raw is None:
        return None
    return decimal_finite(raw, field)


class EODHDDelayedSource:
    """Lấy snapshot delayed và lịch sử ngày từ API EODHD, không log/trả token."""

    def __init__(self, client: httpx.AsyncClient, api_token: str) -> None:
        self.client = client
        self._api_token = api_token.strip()

    async def _get_json(self, url: str, params: dict[str, str]) -> Any:
        safe_params = {**params, "api_token": self._api_token, "fmt": "json"}
        try:
            response = await self.client.get(url, params=safe_params, follow_redirects=False)
        except httpx.RequestError:
            raise EODHDDataError("provider_network_error", "Không kết nối được EODHD.") from None
        if response.status_code in {401, 403}:
            raise EODHDDataError(
                "provider_access_denied",
                "EODHD từ chối quyền truy cập hoặc mã này chưa nằm trong gói dữ liệu.",
            )
        if response.status_code == 404:
            raise EODHDDataError("provider_symbol_not_found", "EODHD không tìm thấy mã EGX này.")
        if response.status_code >= 400:
            raise EODHDDataError("provider_http_error", f"EODHD trả HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError:
            raise EODHDDataError("provider_invalid_json", "EODHD không trả JSON hợp lệ.") from None

    async def quote(self, symbol: str) -> tuple[QuoteSnapshot, ProviderProfile, dict[str, Any]]:
        ticker = _ticker(symbol)
        raw = await self._get_json(
            f"{EODHD_DELAYED_URL}/{ticker}",
            {},
        )
        received = datetime.now(timezone.utc)
        if not isinstance(raw, dict) or str(raw.get("code", "")).upper() != ticker:
            raise EODHDDataError("provider_mapping_mismatch", "Mã trong phản hồi EODHD không khớp mã đã yêu cầu.")
        try:
            if isinstance(raw.get("timestamp"), bool):
                raise ValueError
            timestamp = int(raw["timestamp"])
            source_event_at = datetime.fromtimestamp(timestamp, timezone.utc)
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            raise EODHDDataError("provider_timestamp_invalid", "Timestamp quote EODHD thiếu hoặc không hợp lệ.") from None

        last = _decimal_or_none(raw.get("close"), "close")
        previous_close = _decimal_or_none(raw.get("previousClose"), "previousClose")
        if last is None or previous_close is None or last <= 0 or previous_close <= 0:
            raise EODHDDataError("provider_price_invalid", "EODHD thiếu giá hiện tại hoặc giá đóng cửa trước.")
        profile = ProviderProfile(
            profile_id=DELAYED_PROFILE_ID,
            provider="EODHD Live (Delayed)",
            version="eodhd-live-delayed-api-v1",
            # HTTP 200 proves this token received this response; it does not prove the
            # project's redistribution/display rights. Keep contractual entitlement unknown.
            entitlement_status="unknown",
            entitlement_evidence_ref=None,
            declared_delay_seconds=DECLARED_DELAY_UPPER_SECONDS,
            declared_delay_label="Giá trễ khoảng 15–20 phút theo công bố EODHD",
            supports_quote=True,
            supports_history=True,
            supports_calendar=False,
            supports_actions=False,
            timestamp_semantics="Unix epoch seconds; thời điểm quote do EODHD trả về.",
            field_mapping_version="eodhd-real-time-egx-map-v1",
            max_response_age_seconds=MAX_RESPONSE_AGE_SECONDS,
            max_quote_age_seconds=MAX_QUOTE_AGE_SECONDS,
        )
        quote = QuoteSnapshot(
            instrument_id=f"EGX:{ticker[:-4]}",
            symbol=ticker,
            provider_profile_id=profile.profile_id,
            source=profile.provider,
            currency="EGP",
            price_unit="EGP/share",
            source_event_at=source_event_at,
            received_at=received,
            last=last,
            volume=_decimal_or_none(raw.get("volume"), "volume"),
            volume_basis="session_volume",
            market_state="unknown",
            instrument_state="unknown",
            quote_kind="intraday",
            data_origin="observed",
            raw_ref=f"eodhd-live-delayed:{ticker}:{timestamp}",
            reason="Snapshot toàn cầu bị trễ; endpoint không cung cấp bid/ask hoặc trạng thái phiên EGX.",
        )
        context = {
            "ticker": ticker,
            "as_of": source_event_at.isoformat(),
            "received_at": received.isoformat(),
            "last": str(last),
            "previous_close": str(previous_close),
            "change": str(last - previous_close),
            "change_pct": str((last - previous_close) / previous_close),
            "open": str(_decimal_or_none(raw.get("open"), "open")) if raw.get("open") is not None else None,
            "high": str(_decimal_or_none(raw.get("high"), "high")) if raw.get("high") is not None else None,
            "low": str(_decimal_or_none(raw.get("low"), "low")) if raw.get("low") is not None else None,
            "volume": str(quote.volume) if quote.volume is not None else None,
        }
        return quote, profile, context

    async def daily_history(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        ticker = _ticker(symbol)
        raw = await self._get_json(
            f"{EODHD_EOD_URL}/{ticker}",
            {"from": start.isoformat(), "to": end.isoformat(), "period": "d", "order": "a"},
        )
        if not isinstance(raw, list):
            raise EODHDDataError("provider_history_invalid", "EODHD không trả danh sách nến ngày.")
        bars: list[dict[str, Any]] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            try:
                bar_date = date.fromisoformat(str(row["date"]))
                close = decimal_finite(row.get("close"), "history.close")
                adjusted = decimal_finite(row.get("adjusted_close"), "history.adjusted_close", allow_none=True)
            except (KeyError, ValueError):
                continue
            if close is None or close <= 0:
                continue
            bars.append({
                "date": bar_date.isoformat(),
                "close": str(close),
                "adjusted_close": str(adjusted) if adjusted is not None else None,
                "raw_ref": f"eodhd-eod:{ticker}:{bar_date.isoformat()}",
            })
        return bars
