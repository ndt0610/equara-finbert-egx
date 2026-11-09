"""So sánh các phương án bằng tiền cuối kỳ, theo TG-SPEC-1 F01–F04.

Đây là lớp số học thuần. Nó không lấy giá, không tự ước lượng chi phí và không quyết định nhãn.
Chi phí chỉ được dùng khi từng thành phần có nguồn, ngày hiệu lực và trạng thái đã xác minh.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Literal


class LoiDongTien(ValueError):
    """Input dòng tiền thiếu, sai đơn vị hoặc không hợp lệ."""


class ThieuCanCuDongTien(LoiDongTien):
    """Một hay nhiều đầu vào cần cho phép so chưa được xác minh."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__("Thiếu căn cứ dòng tiền: " + ", ".join(missing))


TrangThaiCanCu = Literal["da_xac_minh", "uoc_tinh", "chua_biet"]


def decimal_finite(value: Any, name: str, *, allow_none: bool = False) -> Decimal | None:
    """Đọc Decimal từ chuỗi/số, cấm bool, NaN và Infinity."""
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        raise LoiDongTien(f"{name} phải là số thập phân, không phải boolean.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise LoiDongTien(f"{name} không phải số thập phân hợp lệ.") from None
    if not result.is_finite():
        raise LoiDongTien(f"{name} phải hữu hạn.")
    return result


@dataclass(frozen=True)
class KhoanTien:
    """Phí đã quy thành số tiền cho đúng q và giao dịch cụ thể.

    `so_tien` là amount, không phải tỷ lệ. Việc áp biểu phí/minimum/rounding thuộc adapter chi phí
    đã xác minh; phần này không tự đoán biểu phí.
    """

    ma: str
    ten: str
    so_tien: Decimal | str | int | None = None
    tien_te: str = "EGP"
    trang_thai: TrangThaiCanCu = "chua_biet"
    nguon: str | None = None
    hieu_luc_tu: date | None = None
    hieu_luc_den: date | None = None
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        amount = decimal_finite(self.so_tien, f"{self.ma}.so_tien", allow_none=True)
        object.__setattr__(self, "so_tien", amount)
        if amount is not None and amount < 0:
            raise LoiDongTien(f"Khoản phí {self.ma} không được âm.")
        if self.trang_thai == "da_xac_minh":
            if amount is None or not self.nguon or not self.hieu_luc_tu or not self.evidence_ref:
                raise LoiDongTien(
                    f"Khoản {self.ma} đã xác minh phải có số tiền, nguồn, chứng cứ và ngày bắt đầu hiệu lực."
                )
        if self.hieu_luc_den and self.hieu_luc_tu and self.hieu_luc_den < self.hieu_luc_tu:
            raise LoiDongTien(f"Khoảng hiệu lực của {self.ma} bị đảo.")

    def amount_for(self, currency: str, as_of: date) -> Decimal | None:
        if self.trang_thai != "da_xac_minh" or self.so_tien is None:
            return None
        if self.tien_te != currency:
            return None
        if self.hieu_luc_tu is None or as_of < self.hieu_luc_tu:
            return None
        if self.hieu_luc_den is not None and as_of > self.hieu_luc_den:
            return None
        return self.so_tien

    def to_dict(self) -> dict[str, Any]:
        return {
            "ma": self.ma,
            "ten": self.ten,
            "so_tien": str(self.so_tien) if self.so_tien is not None else None,
            "tien_te": self.tien_te,
            "trang_thai": self.trang_thai,
            "nguon": self.nguon,
            "hieu_luc_tu": self.hieu_luc_tu.isoformat() if self.hieu_luc_tu else None,
            "hieu_luc_den": self.hieu_luc_den.isoformat() if self.hieu_luc_den else None,
            "evidence_ref": self.evidence_ref,
        }


@dataclass(frozen=True)
class HeSoTienMat:
    """Hệ số tích lũy tiền A từ t đến H, kèm căn cứ/kịch bản."""

    gia_tri: Decimal | str | int | None = None
    trang_thai: TrangThaiCanCu = "chua_biet"
    policy: str | None = None
    nguon: str | None = None
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        factor = decimal_finite(self.gia_tri, "A", allow_none=True)
        object.__setattr__(self, "gia_tri", factor)
        if factor is not None and factor <= 0:
            raise LoiDongTien("A phải dương.")
        if self.trang_thai == "da_xac_minh" and factor is None:
            raise LoiDongTien("A đã xác minh phải có giá trị.")
        if self.policy == "idle_cash_zero_return" and factor != Decimal("1"):
            raise LoiDongTien("Policy tiền mặt không sinh lãi yêu cầu A=1 chính xác.")
        if self.trang_thai == "da_xac_minh" and not (self.policy or self.nguon):
            raise LoiDongTien("A đã xác minh phải ghi policy hoặc nguồn.")
        if self.trang_thai == "da_xac_minh" and not self.evidence_ref:
            raise LoiDongTien("A đã xác minh phải có evidence_ref cho giả định/chính sách tiền mặt.")

    def usable(self) -> bool:
        return self.trang_thai == "da_xac_minh" and self.gia_tri is not None


@dataclass(frozen=True)
class ScenarioDongTien:
    """Lượng cổ phiếu và giá thực thi tham chiếu cho một quyết định."""

    instrument_id: str
    symbol: str
    scenario_id: str
    q: Decimal | str | int
    lot_size: Decimal | str | int
    lot_evidence_ref: str | None
    currency: str
    as_of: date
    horizon_sessions: int
    reference_price: Decimal | str | int
    buy_execution_price: Decimal | str | int | None
    sell_execution_price: Decimal | str | int | None
    buy_fees: tuple[KhoanTien, ...]
    sell_fees_now: tuple[KhoanTien, ...]
    cash_factor: HeSoTienMat
    quote_evidence_ref: str | None = None
    cost_model_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("q", "lot_size", "reference_price", "buy_execution_price", "sell_execution_price"):
            value = decimal_finite(
                getattr(self, field_name),
                field_name,
                allow_none=field_name.endswith("execution_price"),
            )
            object.__setattr__(self, field_name, value)
            if value is not None and value <= 0:
                raise LoiDongTien(f"{field_name} phải lớn hơn 0.")
        if not self.instrument_id.strip() or not self.symbol.strip() or not self.scenario_id.strip():
            raise LoiDongTien("Phải có định danh, mã cổ phiếu đã mapping và scenario_id.")
        if not self.lot_evidence_ref:
            raise LoiDongTien("Thiếu bằng chứng lot_size của mã.")
        if self.lot_size is None or self.lot_size <= 0:
            raise LoiDongTien("lot_size phải là số dương.")
        if self.q % self.lot_size != 0:
            raise LoiDongTien("q không khớp bội số lot_size của mã.")
        if isinstance(self.horizon_sessions, bool) or not isinstance(self.horizon_sessions, int) or self.horizon_sessions <= 0:
            raise LoiDongTien("Horizon phải là số phiên dương.")
        if len(self.currency.strip()) != 3 or self.currency.upper() != self.currency:
            raise LoiDongTien("currency phải là mã ISO viết hoa gồm ba ký tự.")


@dataclass(frozen=True)
class CashflowBaselines:
    instrument_id: str
    symbol: str
    scenario_id: str
    q: Decimal
    currency: str
    as_of: date
    horizon_sessions: int
    C_mua: Decimal
    C_ban: Decimal
    A: Decimal
    V0: Decimal
    B_mua: Decimal
    B_ban: Decimal
    evidence_refs: tuple[str, ...]
    cost_model_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "scenario_id": self.scenario_id,
            "q": str(self.q),
            "currency": self.currency,
            "as_of": self.as_of.isoformat(),
            "horizon_sessions": self.horizon_sessions,
            "C_mua": str(self.C_mua),
            "C_ban": str(self.C_ban),
            "A": str(self.A),
            "V0": str(self.V0),
            "B_mua": str(self.B_mua),
            "B_ban": str(self.B_ban),
            "evidence_refs": list(self.evidence_refs),
            "cost_model_id": self.cost_model_id,
            "formulas": {
                "C_mua": "q * ask + verified_buy_fees",
                "C_ban": "q * bid - verified_sell_fees_now",
                "B_mua": "C_mua * A",
                "B_ban": "C_ban * A",
                "V0": "q * reference_price",
            },
        }


def calculate_baselines(scenario: ScenarioDongTien) -> CashflowBaselines:
    """Tính ngưỡng tiền mặt sau chi phí; thành phần thiếu/sai hiệu lực chặn phép so."""
    missing: list[str] = []
    if scenario.buy_execution_price is None:
        missing.append("giá ask/giá mua thực thi")
    if scenario.sell_execution_price is None:
        missing.append("giá bid/giá bán thực thi")
    if not scenario.quote_evidence_ref:
        missing.append("bằng chứng quote và timestamp")
    if not scenario.cost_model_id:
        missing.append("phiên bản mô hình chi phí giao dịch")
    if not scenario.cash_factor.usable():
        missing.append("hệ số tiền mặt A")
    if not scenario.buy_fees:
        missing.append("danh sách phí mua đã xác minh (phí 0 phải có chứng cứ riêng)")
    if not scenario.sell_fees_now:
        missing.append("danh sách phí bán hiện tại đã xác minh (phí 0 phải có chứng cứ riêng)")

    buy_amounts: list[Decimal] = []
    for component in scenario.buy_fees:
        amount = component.amount_for(scenario.currency, scenario.as_of)
        if amount is None:
            missing.append(f"{component.ten} ({component.ma})")
        else:
            buy_amounts.append(amount)
    sell_amounts: list[Decimal] = []
    for component in scenario.sell_fees_now:
        amount = component.amount_for(scenario.currency, scenario.as_of)
        if amount is None:
            missing.append(f"{component.ten} ({component.ma})")
        else:
            sell_amounts.append(amount)
    if missing:
        raise ThieuCanCuDongTien(missing)

    assert scenario.buy_execution_price is not None
    assert scenario.sell_execution_price is not None
    assert scenario.cash_factor.gia_tri is not None
    with localcontext() as ctx:
        ctx.prec = 28
        buy_fees = sum(buy_amounts, Decimal("0"))
        sell_fees = sum(sell_amounts, Decimal("0"))
        c_buy = scenario.q * scenario.buy_execution_price + buy_fees
        c_sell = scenario.q * scenario.sell_execution_price - sell_fees
        factor = scenario.cash_factor.gia_tri
        v0 = scenario.q * scenario.reference_price
        b_buy = c_buy * factor
        b_sell = c_sell * factor
    if min(c_buy, c_sell, v0, b_buy, b_sell) <= 0:
        raise LoiDongTien("Dòng tiền tham chiếu phải dương; kiểm tra phí và giá bid/ask.")
    if c_sell > c_buy or b_sell > b_buy:
        raise LoiDongTien("inconsistent_cashflows: B_ban không được lớn hơn B_mua.")

    refs = [
        scenario.quote_evidence_ref,
        scenario.cost_model_id,
        scenario.cash_factor.evidence_ref,
        f"cash_policy:{scenario.cash_factor.policy}" if scenario.cash_factor.policy else None,
        scenario.cash_factor.nguon,
    ]
    refs.extend(c.evidence_ref or c.nguon for c in (*scenario.buy_fees, *scenario.sell_fees_now))
    evidence_refs = tuple(dict.fromkeys(ref for ref in refs if ref))
    return CashflowBaselines(
        instrument_id=scenario.instrument_id,
        symbol=scenario.symbol,
        scenario_id=scenario.scenario_id,
        q=scenario.q,
        currency=scenario.currency,
        as_of=scenario.as_of,
        horizon_sessions=scenario.horizon_sessions,
        C_mua=c_buy,
        C_ban=c_sell,
        A=factor,
        V0=v0,
        B_mua=b_buy,
        B_ban=b_sell,
        evidence_refs=evidence_refs,
        cost_model_id=scenario.cost_model_id,
    )
