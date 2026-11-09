"""Kịch bản V1 cho người đang nắm cổ phiếu, độc lập với tỷ trọng vốn C3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MA_KICH_BAN_MAC_DINH = "dang_nam"


@dataclass(frozen=True)
class KichBan:
    ma: str
    ten: str
    mo_ta: str
    nguoi_dung: str
    y_nghia_nhan: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ma": self.ma,
            "ten": self.ten,
            "mo_ta": self.mo_ta,
            "nguoi_dung": self.nguoi_dung,
            "mac_dinh": self.ma == MA_KICH_BAN_MAC_DINH,
            "y_nghia_nhan": dict(self.y_nghia_nhan),
        }


DANG_NAM = KichBan(
    ma=MA_KICH_BAN_MAC_DINH,
    ten="Đang nắm cổ phiếu",
    mo_ta=(
        "Đánh giá phần q cổ phiếu đang xét: mua thêm q, giữ nguyên, hay bán q và giữ tiền tới "
        "ngày đích. Không đọc vốn hoặc tỷ trọng từ tab C3."
    ),
    nguoi_dung="Người đang nắm cổ phiếu EGX",
    y_nghia_nhan={
        "mua_manh": "Bằng chứng mạnh ủng hộ mua thêm q cổ phiếu.",
        "mua": "Bằng chứng ủng hộ mua thêm q cổ phiếu.",
        "giu": "Khoảng kỳ vọng nằm trong vùng không đổi vị thế sau chi phí.",
        "ban": "Bằng chứng ủng hộ bán phần q đang xét.",
        "ban_manh": "Bằng chứng mạnh ủng hộ bán phần q đang xét.",
    },
)


def lay_kich_ban(ma: str | None = None) -> KichBan:
    """V1 chỉ có một kịch bản; không âm thầm đổi sang chế độ người mua mới."""
    if ma is None or not str(ma).strip() or str(ma).strip().lower() == MA_KICH_BAN_MAC_DINH:
        return DANG_NAM
    raise ValueError(
        "V1 chỉ hỗ trợ kịch bản 'dang_nam'. Kịch bản người mua mới chưa thuộc phạm vi này."
    )


def danh_sach_kich_ban() -> list[dict[str, Any]]:
    return [DANG_NAM.to_dict()]
