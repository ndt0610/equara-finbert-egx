"""Tổng hợp sắc thái từ các tin đã thu thập và chấm, theo vốn từng mã.

s_i là điểm tin của mã; w_i là tỷ trọng vốn. Chỉ các mã có điểm mới tham gia:
C = tổng w_i của các mã có điểm; r_i = w_i/C; đóng góp = r_i*s_i; S = tổng đóng góp.
C chỉ mô tả phạm vi vốn được đại diện, không đo tỷ lệ thông tin thu đủ.
Không gán điểm hay tính khoảng giả định cho mã chưa có dữ liệu.
Tin vĩ mô hiển thị riêng. Khi không có vốn nào có điểm, S=None.
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.services.sentiment import aggregate_probabilities
from backend.upgrades.time_confidence import (
    DEFAULT_MISSING_AGE_HOURS,
    confidence_weight,
    headline_score,
    hours_since,
    label_from_score,
    time_decay_weight,
)

METHOD_VERSION = "observed-capital-v3"
DEFAULT_TIER2_BELOW = 10  # mức thấp của "top 10–15" trong bài báo
LABELS = ("positive", "negative", "neutral")
NO_NEWS = "no_news"


def _env_float(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"{name} phải là số hữu hạn.")
    return value


def _tier2_from_environment() -> int | None:
    raw = os.getenv("COVERAGE_TIER2_BELOW", "").strip().lower()
    if not raw:
        return DEFAULT_TIER2_BELOW
    if raw in {"0", "off", "false", "no", "none"}:
        return None
    return int(float(raw))


@dataclass(frozen=True)
class CoverageConfig:
    """Cấu hình phần C. Mặc định: đúng phương án đã chốt, mọi tùy chọn thử nghiệm đều tắt."""

    lookback_days: int = 90  # cửa sổ tin, để tái lập bản tái dựng; chưa được chọn tối ưu
    max_headlines_per_holding: int = 15  # tối đa 15 tin mới nhất mỗi mã, như yêu cầu một mã của bài báo
    macro_limit: int = 4  # 4 tin vĩ mô, như yêu cầu danh mục của bài báo
    # Truy vấn Google bậc 2 khi số tin phù hợp < mức này (None = không gọi bậc 2). Mặc định bật từ coverage-v2,
    # vì truy vấn bậc 1 hẹp làm độ phủ đo độ hẹp của truy vấn chứ không đo tin có hay không.
    tier2_below: int | None = DEFAULT_TIER2_BELOW
    # Các tùy chọn thử nghiệm, mặc định tắt:
    half_life_micro_hours: float | None = None  # ví dụ 12: tin càng cũ càng nhẹ
    half_life_macro_hours: float | None = None  # ví dụ 24
    prior_strength: float = 0.0  # κ, ví dụ 0.5: co điểm về 0 khi ít tin
    neutral_band: float | None = None  # ví dụ 0.15: nhãn theo |điểm| > ngưỡng thay vì theo xác suất lớn nhất
    confidence_weighting: bool = False  # trọng số |P+ − P−|

    def __post_init__(self) -> None:
        if not 1 <= self.lookback_days <= 90:
            raise ValueError("lookback_days phải trong 1–90 (truy vấn nguồn tin chỉ lấy 90 ngày).")
        if not 1 <= self.max_headlines_per_holding <= 100:
            raise ValueError("max_headlines_per_holding phải trong 1–100.")
        if not 0 <= self.macro_limit <= 30:
            raise ValueError("macro_limit phải trong 0–30.")
        if self.tier2_below is not None and self.tier2_below < 1:
            raise ValueError("tier2_below phải ≥ 1.")
        for value in (self.half_life_micro_hours, self.half_life_macro_hours):
            if value is not None and value <= 0:
                raise ValueError("Chu kỳ bán rã phải > 0.")
        if self.prior_strength < 0:
            raise ValueError("prior_strength phải ≥ 0.")
        if self.neutral_band is not None and not 0 <= self.neutral_band < 1:
            raise ValueError("neutral_band phải trong [0, 1).")

    @classmethod
    def from_environment(cls) -> "CoverageConfig":
        def as_int(name: str, default: int | None) -> int | None:
            value = _env_float(name)
            return default if value is None else int(value)

        return cls(
            lookback_days=as_int("COVERAGE_LOOKBACK_DAYS", 90),
            max_headlines_per_holding=as_int("COVERAGE_MAX_PER_HOLDING", 15),
            macro_limit=as_int("COVERAGE_MACRO_LIMIT", 4),
            tier2_below=_tier2_from_environment(),
            half_life_micro_hours=_env_float("COVERAGE_HALF_LIFE_MICRO_HOURS"),
            half_life_macro_hours=_env_float("COVERAGE_HALF_LIFE_MACRO_HOURS"),
            prior_strength=_env_float("COVERAGE_PRIOR_STRENGTH") or 0.0,
            neutral_band=_env_float("COVERAGE_NEUTRAL_BAND"),
            confidence_weighting=os.getenv("COVERAGE_CONFIDENCE_WEIGHTING", "").strip().lower() in {"1", "true", "yes", "on"},
        )

    def experimental_options_on(self) -> list[str]:
        on: list[str] = []
        if self.tier2_below is None:
            on.append("tắt truy vấn bậc 2")
        elif self.tier2_below != DEFAULT_TIER2_BELOW:
            on.append(f"truy vấn bậc 2 khi dưới {self.tier2_below} tin")
        if self.half_life_micro_hours is not None or self.half_life_macro_hours is not None:
            on.append("giảm trọng số theo tuổi tin")
        if self.prior_strength > 0:
            on.append(f"co về 0 với κ = {self.prior_strength:g}")
        if self.neutral_band is not None:
            on.append(f"vùng trung tính ±{self.neutral_band:g}")
        if self.confidence_weighting:
            on.append("trọng số theo độ rõ |P+ − P−|")
        return on

    @property
    def plain_mean(self) -> bool:
        """True khi điểm nhóm đúng là trung bình phẳng của bản tái dựng."""
        return (
            self.half_life_micro_hours is None
            and self.half_life_macro_hours is None
            and self.prior_strength == 0
            and not self.confidence_weighting
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["experimental_options_on"] = self.experimental_options_on()
        return data


# ---------------------------------------------------------------------------
# Điểm của một nhóm tin (tin riêng một mã, hoặc tin vĩ mô)
# ---------------------------------------------------------------------------
def _label_by_argmax(probabilities: Mapping[str, float]) -> str:
    positive, negative, neutral = (float(probabilities[k]) for k in LABELS)
    if positive > negative and positive > neutral:
        return "Bullish"
    if negative > positive and negative > neutral:
        return "Bearish"
    return "Neutral"


def headline_weight(row: Mapping[str, Any], kind: str, config: CoverageConfig, now: datetime) -> float:
    weight = 1.0
    half_life = config.half_life_macro_hours if kind == "macro" else config.half_life_micro_hours
    if half_life is not None:
        age = hours_since(row.get("published_at"), now)
        weight *= time_decay_weight(DEFAULT_MISSING_AGE_HOURS if age is None else age, half_life)
    if config.confidence_weighting:
        weight *= confidence_weight(row["probabilities"])
    return weight


def group_signal(
    rows: Sequence[Mapping[str, Any]],
    *,
    kind: str,
    config: CoverageConfig,
    now: datetime,
) -> dict[str, Any] | None:
    """Điểm, nhãn và phần chia của từng tiêu đề. None khi nhóm không có tin.

    `shares` cộng lại đúng bằng `score`, để giao diện cho tính tay từng tiêu đề.
    """
    if not rows:
        return None
    n = len(rows)
    scores = [headline_score(row["probabilities"]) for row in rows]
    if config.plain_mean:
        probabilities, argmax_label, score = aggregate_probabilities([row["probabilities"] for row in rows])
        weights = [1.0] * n
        shares = [s / n for s in scores]
        rule = "mean(P+) − mean(P−), mỗi tiêu đề một phiếu (công thức của bản tái dựng)"
    else:
        weights = [headline_weight(row, kind, config, now) for row in rows]
        total = sum(weights)
        denominator = total + config.prior_strength
        shares = [(w * s / denominator) if denominator > 0 else 0.0 for w, s in zip(weights, scores)]
        score = sum(shares)
        if total > 0:
            probabilities = {k: sum(w * float(row["probabilities"][k]) for w, row in zip(weights, rows)) / total for k in LABELS}
        else:
            probabilities = {k: sum(float(row["probabilities"][k]) for row in rows) / n for k in LABELS}
        argmax_label = _label_by_argmax(probabilities)
        rule = "Σ(w × s) / (Σw + κ), w theo các tùy chọn thử nghiệm đang bật"
    if config.neutral_band is None:
        label, label_rule = argmax_label, "Bullish/Bearish khi xác suất trung bình tương ứng lớn nhất, còn lại Neutral (như bản tái dựng)"
    else:
        label, label_rule = label_from_score(score, config.neutral_band), f"Bullish khi điểm > {config.neutral_band:g}, Bearish khi < −{config.neutral_band:g}, còn lại Neutral"
    label_counts = {"Bullish": 0, "Neutral": 0, "Bearish": 0}
    for row in rows:
        label_counts[_label_by_argmax(row["probabilities"])] += 1
    return {
        "n": n,
        "score": score,
        "label": label,
        "label_counts": label_counts,  # số tiêu đề theo nhãn của từng tiêu đề (xác suất lớn nhất)
        "probabilities": probabilities,
        "score_rule": rule,
        "label_rule": label_rule,
        "headline_scores": scores,
        "headline_weights": weights,
        "shares": shares,
        "score_min": min(scores),
        "score_max": max(scores),
    }


# ---------------------------------------------------------------------------
# Gộp theo vốn
# ---------------------------------------------------------------------------
@dataclass
class HoldingScore:
    symbol: str
    weight_input: float
    signal: dict[str, Any] | None  # None = không tìm thấy tin riêng phù hợp
    w: float = 0.0  # phần vốn sau chuẩn hóa (tổng = 1)
    r: float | None = None
    contribution: float | None = None
    label: str = NO_NEWS
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def has_news(self) -> bool:
        return self.signal is not None and self.signal["n"] >= 1


DIRECTION_TEXT = {
    "positive": "Điểm tổng hợp của các tin đã chấm nghiêng tích cực; chỉ đại diện cho các mã có điểm.",
    "negative": "Điểm tổng hợp của các tin đã chấm nghiêng tiêu cực; chỉ đại diện cho các mã có điểm.",
    "balanced": "Điểm tổng hợp của các tin đã chấm bằng 0; không suy diễn cho mã chưa có dữ liệu.",
    "no_company_news": "Chưa có tin được chấm cho phần vốn đã nhập, nên chưa có điểm tổng hợp.",
}

def summarize_portfolio(holdings: Sequence[HoldingScore], config: CoverageConfig | None = None) -> dict[str, Any]:
    """Tính điểm quan sát theo vốn, đóng góp từng mã và phạm vi kết quả. Sửa `holdings` tại chỗ."""
    config = config or CoverageConfig()
    if not holdings:
        raise ValueError("Danh mục phải có ít nhất 1 mã.")
    total = sum(float(h.weight_input) for h in holdings)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("Tổng tỷ trọng vốn phải > 0.")
    for h in holdings:
        if h.weight_input < 0 or not math.isfinite(h.weight_input):
            raise ValueError(f"Tỷ trọng vốn của {h.symbol} không hợp lệ.")
        h.w = float(h.weight_input) / total
        h.label = h.signal["label"] if h.has_news else NO_NEWS

    covered = [h for h in holdings if h.has_news]
    coverage = sum(h.w for h in covered)
    capital_by_label = {"Bullish": 0.0, "Bearish": 0.0, "Neutral": 0.0, NO_NEWS: 0.0}
    for h in holdings:
        capital_by_label[h.label] += h.w

    score: float | None = None
    if coverage <= 0:
        for h in holdings:
            h.r = h.contribution = None
        direction = "no_company_news"
    else:
        for h in holdings:
            if h.has_news:
                h.r = h.w / coverage
                h.contribution = h.r * h.signal["score"]
            else:
                h.r = h.contribution = None
        score = sum(h.contribution for h in covered)
        direction = "positive" if score > 0 else "negative" if score < 0 else "balanced"

    return {
        "score_scope": "observed_scored_news",
        "represented_symbols": [h.symbol for h in covered if h.w > 0],
        "unscored_symbols": [h.symbol for h in holdings if h.w > 0 and not h.has_news],
        "scope_note": "Chỉ tổng hợp tin đã chấm. Tỷ trọng vốn được đại diện không đo mức đầy đủ của tin; mã chưa có dữ liệu không được gán điểm.",
        "coverage": coverage,
        "uncovered_weight": 1.0 - coverage,
        "score": score,
        "score_rule": "S = Σ r_i × s_i với r_i = w_i / độ phủ, chỉ trên các mã có tiêu đề qua luật hiện tại",
        "sum_contributions": None if coverage <= 0 else sum(h.contribution for h in covered),
        "direction": direction,
        "direction_text": DIRECTION_TEXT[direction],
        "capital_by_label": capital_by_label,
        "capital_by_label_note": _neutral_label_note(covered),
    }


def _neutral_label_note(covered: Sequence[HoldingScore]) -> str | None:
    """Giải thích khi mã mang nhãn Neutral mà điểm khác 0 (ví dụ thật COMI 03/11: Neutral, +0,383)."""
    neutral = [h for h in covered if h.label == "Neutral" and h.signal["score"] != 0]
    if not neutral:
        return None
    listed = ", ".join(f"{h.symbol.removesuffix('.EGX')} {h.signal['score']:+.3f}" for h in neutral)
    return (
        "Nhãn của mỗi mã là lớp có xác suất trung bình lớn nhất (luật của bản tái dựng). Tiêu đề tin thường "
        f"trung tính, nên mã vẫn mang nhãn Neutral khi điểm khác 0: {listed}. Hướng nghiêng của từng mã xem ở "
        "điểm mã và cột đóng góp; điểm S tính từ điểm, không từ nhãn."
    )
