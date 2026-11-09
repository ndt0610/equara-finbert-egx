"""Tham số biên mạnh đã hiệu chuẩn cho Tin + Giá.

Hòa vốn thường được tính từ dòng tiền ở `dong_tien.py`; `k` chỉ là phần đệm tăng thêm để phân cấp
nhãn mạnh. Không có giá trị mặc định. Giá trị chỉ được đọc từ manifest đã duyệt, không từ request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from .dong_tien import decimal_finite

PHIEN_BAN_NGUONG = "tg-margins-v1"
MUC_KHOANG_V1 = 95
MUC_KHOANG_NGHIEN_CUU: tuple[int, ...] = (80, 90, 95)

Huong = Literal["buy", "sell"]
TrangThaiCanCu = Literal["unavailable", "candidate", "approved"]


class LoiNguong(ValueError):
    """Tham số biên mạnh sai kiểu, thiếu provenance hoặc không hợp lệ."""


@dataclass(frozen=True)
class BienManh:
    """Ngưỡng k dương trên V0, chỉ dùng khi manifest được phê duyệt và khớp phạm vi."""

    huong: Huong
    gia_tri: Decimal | str | int | None = None
    trang_thai: TrangThaiCanCu = "unavailable"
    instrument_scope: tuple[str, ...] = ()
    horizon_sessions: int | None = None
    cadence: str | None = None
    model_version: str | None = None
    parameter_version: str | None = None
    validation_ref: str | None = None
    approved_at: date | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.huong not in {"buy", "sell"}:
            raise LoiNguong("huong phải là buy hoặc sell.")
        value = decimal_finite(self.gia_tri, "k", allow_none=True)
        object.__setattr__(self, "gia_tri", value)
        if value is not None and value <= 0:
            raise LoiNguong("k phải dương; bằng 0 không tạo ra nhãn 'mạnh'.")
        if self.trang_thai == "approved":
            if value is None or not self.instrument_scope or self.horizon_sessions is None:
                raise LoiNguong("k approved phải có giá trị, phạm vi mã và horizon.")
            if self.horizon_sessions <= 0 or not self.cadence:
                raise LoiNguong("k approved phải có horizon dương và cadence.")
            if not self.model_version or not self.parameter_version or not self.validation_ref:
                raise LoiNguong("k approved phải trỏ tới model, parameter version và validation.")
            if not self.approved_at:
                raise LoiNguong("k approved phải có ngày duyệt.")
        if self.trang_thai == "unavailable" and value is not None:
            raise LoiNguong("Giá trị k chưa duyệt phải để null, không được dùng nháp.")

    def usable_for(self, *, instrument_id: str, horizon_sessions: int, cadence: str, model_version: str) -> bool:
        return (
            self.trang_thai == "approved"
            and self.gia_tri is not None
            and instrument_id in self.instrument_scope
            and self.horizon_sessions == horizon_sessions
            and self.cadence == cadence
            and self.model_version == model_version
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.huong,
            "value": str(self.gia_tri) if self.gia_tri is not None else None,
            "unit": "fraction_of_V0",
            "status": self.trang_thai,
            "instrument_scope": list(self.instrument_scope),
            "horizon_sessions": self.horizon_sessions,
            "cadence": self.cadence,
            "model_version": self.model_version,
            "parameter_version": self.parameter_version,
            "validation_ref": self.validation_ref,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "reason": self.reason,
        }


K_MUA_CHUA_HIEU_CHUAN = BienManh(
    huong="buy",
    gia_tri=None,
    trang_thai="unavailable",
    reason="Chưa có dữ liệu ngoài mẫu để xác nhận biên mạnh.",
)
K_BAN_CHUA_HIEU_CHUAN = BienManh(
    huong="sell",
    gia_tri=None,
    trang_thai="unavailable",
    reason="Chưa có dữ liệu ngoài mẫu để xác nhận biên mạnh.",
)
