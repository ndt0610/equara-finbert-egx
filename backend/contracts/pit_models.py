"""Time-aware records. A timestamp supplied by a caller is not verified PiT evidence."""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ProvenanceTier = Literal[
    "FIXTURE_DEMO", "EXPLORATORY_RETROSPECTIVE_NON_PIT", "LIVE_CAPTURED_PIT"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return value


class NewsItem(StrictModel):
    item_id: str = Field(min_length=1)
    ticker: str
    title: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_kind: Literal["sec_filing", "issuer_release", "news", "context"]
    url: str | None = None
    published_at: datetime | None
    ingested_at: datetime
    scored_at: datetime | None
    probabilities: dict[str, Decimal] | None = None
    event_key: str | None = None
    provenance_tier: ProvenanceTier

    @field_validator("published_at", "ingested_at", "scored_at")
    @classmethod
    def validate_time(cls, value):
        return aware(value) if value is not None else None

    @model_validator(mode="after")
    def validate_probabilities(self):
        if self.probabilities is not None:
            if set(self.probabilities) != {"positive", "neutral", "negative"}:
                raise ValueError("THREE_PROBABILITIES_REQUIRED")
            if any(not p.is_finite() or p < 0 or p > 1 for p in self.probabilities.values()):
                raise ValueError("INVALID_PROBABILITY")
            if abs(sum(self.probabilities.values()) - Decimal(1)) > Decimal("0.000001"):
                raise ValueError("PROBABILITIES_MUST_SUM_TO_ONE")
        return self


class PriceBar(StrictModel):
    ticker: str
    price_usd: Decimal = Field(gt=0)
    as_of: datetime
    ingested_at: datetime
    adjustment_method: Literal["raw", "split", "dividend", "all", "manual"]
    provenance_tier: ProvenanceTier
    source: str

    @field_validator("as_of", "ingested_at")
    @classmethod
    def validate_time(cls, value):
        return aware(value)

    @field_validator("price_usd")
    @classmethod
    def finite_price(cls, value):
        if not value.is_finite():
            raise ValueError("PRICE_MUST_BE_FINITE")
        return value


class EventCluster(StrictModel):
    event_id: str
    ticker: str
    item_ids: tuple[str, ...]
    earliest_ingested_at: datetime
    first_item_id: str
    primary_item_id: str
    cluster_score_method: Literal["equal_member_mean", "primary_item"]
    first_item_score: Decimal
    score: Decimal
    grouping_status: Literal["exact_title", "caller_event_key"]
    conflicting_headlines: bool

    @field_validator("earliest_ingested_at")
    @classmethod
    def validate_time(cls, value):
        return aware(value)


class DataProvenanceManifest(StrictModel):
    source: str
    retrieved_at: datetime
    source_url: str | None = None
    rights_status: Literal["verified", "unverified", "fixture"]
    data_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    provenance_tier: ProvenanceTier

    @field_validator("retrieved_at")
    @classmethod
    def validate_time(cls, value):
        return aware(value)


class Holding(StrictModel):
    ticker: str
    quantity: Decimal = Field(ge=0)
    price: PriceBar

    @field_validator("quantity")
    @classmethod
    def finite_quantity(cls, value):
        if not value.is_finite():
            raise ValueError("QUANTITY_MUST_BE_FINITE")
        return value


class USPortfolioRequest(StrictModel):
    holdings: list[Holding] = Field(min_length=1, max_length=20)
    cash_usd: Decimal = Field(ge=0)
    decision_at: datetime
    news: list[NewsItem] = Field(default_factory=list)
    scenario_returns: dict[str, Decimal] = Field(default_factory=dict)

    @field_validator("decision_at")
    @classmethod
    def validate_time(cls, value):
        return aware(value)

    @field_validator("cash_usd")
    @classmethod
    def finite_cash(cls, value):
        if not value.is_finite():
            raise ValueError("CASH_MUST_BE_FINITE")
        return value

    @model_validator(mode="after")
    def validate_unique(self):
        symbols = [h.ticker for h in self.holdings]
        if len(set(symbols)) != len(symbols):
            raise ValueError("DUPLICATE_HOLDING")
        if any(h.ticker != h.price.ticker for h in self.holdings):
            raise ValueError("PRICE_TICKER_MISMATCH")
        if set(self.scenario_returns) - set(symbols):
            raise ValueError("SCENARIO_TICKER_NOT_HELD")
        for value in self.scenario_returns.values():
            if not value.is_finite() or value <= -1:
                raise ValueError("SCENARIO_RETURN_MUST_EXCEED_MINUS_ONE")
        return self
