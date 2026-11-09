from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,8}(?:\.EGX)?$")


def normalize_symbol(value: str) -> str:
    symbol = value.strip().upper()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise ValueError("Chỉ nhập mã cổ phiếu EGX, ví dụ COMI hoặc COMI.EGX.")
    if not symbol.endswith(".EGX"):
        symbol = f"{symbol}.EGX"
    return symbol


class StockAnalysisRequest(BaseModel):
    symbol: str = Field(min_length=2, max_length=12)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return normalize_symbol(value)


class PortfolioAnalysisRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=5)

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, values: list[str]) -> list[str]:
        normalized = [normalize_symbol(value) for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("Danh mục không được có mã trùng lặp.")
        return normalized

