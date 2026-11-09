"""Hợp đồng báo giá/history và quy tắc hiển thị độ mới theo TG-SPEC-1 D02–D06/P01–P06.

Chưa có connector EGX được xác minh. NguonChuaCapQuyen là mặc định fail-closed. Docker, HTTP 200,
hoặc việc frontend refresh thường xuyên không đủ để gắn nhãn "Trực tiếp".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Protocol

from .dong_tien import decimal_finite

PHIEN_BAN_NGUON = "tg-quote-contract-v1"

# "verified" means contractual/use entitlement is evidenced; a successful HTTP response
# alone is only technical access and must not be recorded as "verified".
Entitlement = Literal["verified", "unavailable", "unknown"]
Origin = Literal["observed", "illustrative"]
QuoteKind = Literal["intraday", "last_trade", "official_close", "unknown"]
MarketState = Literal["open", "closed", "auction", "halted", "unknown"]


class LoiQuote(ValueError):
    """Quote có số, timestamp hoặc basis không hợp lệ."""


def parse_instant(value: datetime | str | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise LoiQuote(f"{field_name} không phải ISO 8601 hợp lệ.") from None
    else:
        raise LoiQuote(f"{field_name} phải là datetime/ISO 8601.")
    if result.tzinfo is None or result.utcoffset() is None:
        raise LoiQuote(f"{field_name} phải có timezone.")
    return result.astimezone(timezone.utc)


def _decimal_optional(value: Any, field_name: str) -> Decimal | None:
    return decimal_finite(value, field_name, allow_none=True)


@dataclass(frozen=True)
class ProviderProfile:
    profile_id: str
    provider: str
    version: str
    entitlement_status: Entitlement
    entitlement_evidence_ref: str | None
    declared_delay_seconds: int | None
    supports_quote: bool
    supports_history: bool
    supports_calendar: bool
    supports_actions: bool
    timestamp_semantics: str | None
    field_mapping_version: str | None
    max_response_age_seconds: int | None
    max_quote_age_seconds: int | None
    clock_tolerance_seconds: int = 2
    declared_delay_label: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "declared_delay_seconds",
            "max_response_age_seconds",
            "max_quote_age_seconds",
            "clock_tolerance_seconds",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise LoiQuote(f"{name} không được âm.")
        if self.entitlement_status == "verified" and not self.entitlement_evidence_ref:
            raise LoiQuote("Entitlement verified phải có evidence_ref.")


@dataclass(frozen=True)
class QuoteSnapshot:
    instrument_id: str
    symbol: str
    provider_profile_id: str | None
    source: str
    currency: str
    price_unit: str
    source_event_at: datetime | str | None
    received_at: datetime | str
    last_trade_at: datetime | str | None = None
    bid_at: datetime | str | None = None
    ask_at: datetime | str | None = None
    last: Decimal | str | int | None = None
    bid: Decimal | str | int | None = None
    ask: Decimal | str | int | None = None
    bid_size: Decimal | str | int | None = None
    ask_size: Decimal | str | int | None = None
    volume: Decimal | str | int | None = None
    volume_basis: str | None = None
    market_state: MarketState = "unknown"
    instrument_state: str = "unknown"
    quote_kind: QuoteKind = "unknown"
    data_origin: Origin = "observed"
    raw_ref: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.instrument_id.strip() or not self.symbol.strip():
            raise LoiQuote("Quote phải gắn với instrument_id và symbol đã mapping.")
        if not self.currency.strip() or not self.price_unit.strip():
            raise LoiQuote("Quote phải có currency và price_unit.")
        for name in ("source_event_at", "received_at", "last_trade_at", "bid_at", "ask_at"):
            parsed = parse_instant(getattr(self, name), name)
            object.__setattr__(self, name, parsed)
        if self.received_at is None:
            raise LoiQuote("Thiếu received_at.")
        for name in ("last", "bid", "ask", "bid_size", "ask_size", "volume"):
            value = _decimal_optional(getattr(self, name), name)
            object.__setattr__(self, name, value)
            if value is not None and name in {"last", "bid", "ask"} and value <= 0:
                raise LoiQuote(f"{name} phải lớn hơn 0.")
            if value is not None and name in {"bid_size", "ask_size", "volume"} and value < 0:
                raise LoiQuote(f"{name} không được âm.")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise LoiQuote("bid cao hơn ask; quote không hợp lệ.")
        if self.quote_kind == "official_close" and self.market_state == "open":
            raise LoiQuote("Quote official_close không được đánh dấu phiên đang mở.")
        if self.quote_kind == "official_close" and self.source_event_at is None:
            raise LoiQuote("Quote official_close phải có thời điểm đóng cửa từ nguồn.")
        if self.quote_kind == "last_trade" and self.last_trade_at is None:
            raise LoiQuote("Quote last_trade phải có last_trade_at từ nguồn.")

    def measurements(self, now: datetime | None = None) -> dict[str, float | None]:
        """Bốn đồng hồ riêng; tuổi bid/ask chỉ dùng khi có timestamp tương ứng."""
        current = parse_instant(now or datetime.now(timezone.utc), "now")
        assert current is not None

        def seconds_between(left: datetime | None, right: datetime | None) -> float | None:
            if left is None or right is None:
                return None
            return (right - left).total_seconds()

        return {
            "transport_lag_seconds": seconds_between(self.source_event_at, self.received_at),
            "response_age_seconds": seconds_between(self.received_at, current),
            "quote_age_seconds": seconds_between(self.source_event_at, current),
            "trade_age_seconds": seconds_between(self.last_trade_at, current),
            "bid_age_seconds": seconds_between(self.bid_at or self.source_event_at, current),
            "ask_age_seconds": seconds_between(self.ask_at or self.source_event_at, current),
        }

    def to_dict(self, *, now: datetime | None = None, profile: ProviderProfile | None = None) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "provider_profile_id": self.provider_profile_id,
            "source": self.source,
            "currency": self.currency,
            "price_unit": self.price_unit,
            "source_event_at": self.source_event_at.isoformat() if self.source_event_at else None,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "last_trade_at": self.last_trade_at.isoformat() if self.last_trade_at else None,
            "bid_at": self.bid_at.isoformat() if self.bid_at else None,
            "ask_at": self.ask_at.isoformat() if self.ask_at else None,
            "last": str(self.last) if self.last is not None else None,
            "bid": str(self.bid) if self.bid is not None else None,
            "ask": str(self.ask) if self.ask is not None else None,
            "bid_size": str(self.bid_size) if self.bid_size is not None else None,
            "ask_size": str(self.ask_size) if self.ask_size is not None else None,
            "volume": str(self.volume) if self.volume is not None else None,
            "volume_basis": self.volume_basis,
            "market_state": self.market_state,
            "instrument_state": self.instrument_state,
            "quote_kind": self.quote_kind,
            "data_origin": self.data_origin,
            "measurements": self.measurements(now),
            "badge": huy_hieu(self, profile, now=now),
            "raw_ref": self.raw_ref,
            "reason": self.reason,
        }


# Tên cũ được giữ làm bí danh trong giai đoạn tích hợp, nhưng hợp đồng đã chuyển sang QuoteSnapshot.
BaoGia = QuoteSnapshot


def huy_hieu(
    quote: QuoteSnapshot,
    profile: ProviderProfile | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Chọn chữ giá; chỉ ghi Trực tiếp khi entitlement, timestamp và tuổi quote đều đạt."""
    if quote.data_origin == "illustrative":
        return {"text": "Dữ liệu giả lập — không phải giá thật", "kind": "illustrative", "realtime": False}
    if profile is None:
        return {"text": "Chưa có cấu hình nguồn giá", "kind": "source_unavailable", "realtime": False}
    if not profile.supports_quote or not profile.timestamp_semantics or not profile.field_mapping_version:
        return {"text": "Chưa xác minh hợp đồng báo giá", "kind": "source_unavailable", "realtime": False}

    measurements = quote.measurements(now)
    tolerance = profile.clock_tolerance_seconds
    ages = [
        measurements.get("response_age_seconds"),
        measurements.get("quote_age_seconds"),
        measurements.get("bid_age_seconds") if quote.bid is not None else None,
        measurements.get("ask_age_seconds") if quote.ask is not None else None,
    ]
    if any(age is not None and age < -tolerance for age in ages):
        return {"text": "Thời gian nguồn không hợp lệ", "kind": "invalid_time", "realtime": False}

    if quote.quote_kind == "official_close":
        return {
            "text": "Đóng cửa chính thức",
            "kind": "official_close",
            "realtime": False,
            "source_event_at": quote.source_event_at.isoformat() if quote.source_event_at else None,
        }
    if quote.quote_kind == "last_trade":
        return {
            "text": "Phiên đã đóng · giao dịch cuối" if quote.market_state == "closed" else "Giao dịch cuối",
            "kind": "last_trade",
            "realtime": False,
            "last_trade_at": quote.last_trade_at.isoformat() if quote.last_trade_at else None,
        }
    if quote.market_state == "closed":
        return {"text": "Phiên đã đóng · loại giá chưa xác định", "kind": "closed_unknown", "realtime": False}

    if profile.declared_delay_seconds is None:
        return {"text": "Chưa xác minh độ trễ", "kind": "delay_unknown", "realtime": False}

    response_age = measurements.get("response_age_seconds")
    quote_age = measurements.get("quote_age_seconds")
    bid_age = measurements.get("bid_age_seconds") if quote.bid is not None else None
    ask_age = measurements.get("ask_age_seconds") if quote.ask is not None else None
    if (
        response_age is None
        or quote_age is None
        or profile.max_response_age_seconds is None
        or profile.max_quote_age_seconds is None
    ):
        return {"text": "Chưa đủ timestamp để xác minh độ mới", "kind": "delay_unknown", "realtime": False}
    if response_age > profile.max_response_age_seconds or quote_age > profile.max_quote_age_seconds:
        return {"text": "Giá cũ", "kind": "stale", "realtime": False}
    if (bid_age is not None and bid_age > profile.max_quote_age_seconds) or (
        ask_age is not None and ask_age > profile.max_quote_age_seconds
    ):
        return {"text": "Bid/ask cũ", "kind": "stale", "realtime": False}
    if profile.declared_delay_seconds > 0:
        rights_note = " · quyền hiển thị/tái phân phối chưa xác minh" if profile.entitlement_status != "verified" else ""
        return {
            "text": (profile.declared_delay_label or f"Trễ theo công bố nguồn · {profile.declared_delay_seconds}s") + rights_note,
            "kind": "delayed",
            "realtime": False,
        }
    if profile.entitlement_status != "verified" or not profile.entitlement_evidence_ref:
        return {"text": "Quyền sử dụng nguồn chưa xác minh", "kind": "entitlement_unverified", "realtime": False}
    if quote.market_state != "open" or quote.quote_kind != "intraday":
        return {"text": "Không phải quote intraday đang mở", "kind": "not_live", "realtime": False}
    return {"text": f"Trực tiếp · {profile.provider}", "kind": "realtime", "realtime": True}


class NguonGia(Protocol):
    """Giao diện nguồn giá; parser/connector chỉ được đăng ký sau xác minh hợp đồng."""

    ten: str

    async def bao_gia(self, ma: str) -> QuoteSnapshot: ...

    async def lich_su(self, ma: str, so_phien: int) -> list[dict[str, Any]]: ...


class NguonChuaCapQuyen:
    """Nguồn mặc định khi entitlement/provider chưa được xác minh; không gọi mạng."""

    ten = "chưa có nguồn được cấp quyền"

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason or "Chưa xác minh quyền, schema, mapping và điều khoản dữ liệu EGX."

    async def bao_gia(self, ma: str) -> QuoteSnapshot:
        return QuoteSnapshot(
            instrument_id=f"EGX:{ma.upper()}",
            symbol=ma.upper(),
            provider_profile_id=None,
            source=self.ten,
            currency="EGP",
            price_unit="unknown",
            source_event_at=None,
            received_at=datetime.now(timezone.utc),
            data_origin="observed",
            reason=self.reason,
        )

    async def lich_su(self, ma: str, so_phien: int) -> list[dict[str, Any]]:
        return []


class NguonDuLieuMau:
    """Provider minh họa; dữ liệu mẫu luôn mang origin illustrative và không vào API thật."""

    ten = "dữ liệu minh họa"

    def __init__(self, kho: dict[str, dict[str, Any]]) -> None:
        self._kho = kho

    async def bao_gia(self, ma: str) -> QuoteSnapshot:
        case = self._kho.get(ma.upper())
        if case is None:
            raise LoiQuote(f"Không có fixture minh họa cho {ma!r}.")
        quote = case.get("quote", {})
        return QuoteSnapshot(
            instrument_id=str(quote.get("instrument_id", f"ILLUSTRATIVE:{ma.upper()}")),
            symbol=ma.upper(),
            provider_profile_id=None,
            source=self.ten,
            currency=str(quote.get("currency", "EGP")),
            price_unit=str(quote.get("price_unit", "per_share")),
            source_event_at=quote.get("source_event_at"),
            received_at=quote.get("received_at") or datetime.now(timezone.utc),
            last_trade_at=quote.get("last_trade_at"),
            bid_at=quote.get("bid_at"),
            ask_at=quote.get("ask_at"),
            last=quote.get("last"),
            bid=quote.get("bid"),
            ask=quote.get("ask"),
            bid_size=quote.get("bid_size"),
            ask_size=quote.get("ask_size"),
            volume=quote.get("volume"),
            volume_basis=quote.get("volume_basis"),
            market_state=quote.get("market_state", "unknown"),
            instrument_state=quote.get("instrument_state", "unknown"),
            quote_kind=quote.get("quote_kind", "unknown"),
            data_origin="illustrative",
            reason=quote.get("reason"),
        )

    async def lich_su(self, ma: str, so_phien: int) -> list[dict[str, Any]]:
        case = self._kho.get(ma.upper()) or {}
        bars = list(case.get("history") or [])
        return bars[-so_phien:] if so_phien > 0 else bars
