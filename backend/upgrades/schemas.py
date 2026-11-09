from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.schemas import normalize_symbol
from backend.upgrades.portfolio_weighting import MAX_MACRO_BETA


class PositionIn(BaseModel):
    symbol: str = Field(min_length=2, max_length=12)
    weight: float = Field(ge=0, description="Tỷ trọng vốn: nhận % (70) hoặc phân số (0.7); tự chuẩn hóa tổng = 1.")
    macro_beta: float = Field(default=1.0, ge=0, le=MAX_MACRO_BETA, description="Hệ số nhạy cảm với tin vĩ mô.")

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return normalize_symbol(value)


class WeightedPortfolioRequest(BaseModel):
    positions: list[PositionIn] = Field(min_length=1, max_length=5)
    half_life_micro_hours: float = Field(default=12.0, gt=0, le=24 * 30)
    half_life_macro_hours: float = Field(default=24.0, gt=0, le=24 * 30)
    prior_strength: float = Field(default=0.5, ge=0, le=10)
    neutral_band: float = Field(default=0.15, ge=0, le=0.5)

    @model_validator(mode="after")
    def check_positions(self) -> "WeightedPortfolioRequest":
        symbols = [p.symbol for p in self.positions]
        if len(set(symbols)) != len(symbols):
            raise ValueError("Danh mục không được có mã trùng lặp.")
        if sum(p.weight for p in self.positions) <= 0:
            raise ValueError("Tổng tỷ trọng vốn phải > 0.")
        return self


# ---------------------------------------------------------------------------
# [NÂNG CẤP C] Tab "Danh mục theo vốn": chỉ mã và phần vốn. Không còn β, chu kỳ bán rã hay κ.
# ---------------------------------------------------------------------------
class CoveragePositionIn(BaseModel):
    symbol: str = Field(min_length=2, max_length=12)
    weight: float = Field(ge=0, le=1e9, allow_inf_nan=False, description="Phần vốn: % (50) hoặc phân số (0.5); tự chuẩn hóa để tổng = 100%.")

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return normalize_symbol(value)


class CoverageRequest(BaseModel):
    positions: list[CoveragePositionIn] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def check_positions(self) -> "CoverageRequest":
        symbols = [p.symbol for p in self.positions]
        if len(set(symbols)) != len(symbols):
            raise ValueError("Danh mục không được có mã trùng lặp.")
        if sum(p.weight for p in self.positions) <= 0:
            raise ValueError("Tổng tỷ trọng vốn phải > 0.")
        return self


def parse_positions_query(value: str) -> list[dict[str, str]]:
    """GET ?positions=COMI:50,ETEL:30,FWRY:20  →  [{"symbol": "COMI", "weight": "50"}, ...]."""
    rows: list[dict[str, str]] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        symbol, sep, weight = part.partition(":")
        rows.append({"symbol": symbol.strip(), "weight": weight.strip() if sep else ""})
    return rows
