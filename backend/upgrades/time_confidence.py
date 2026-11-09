"""Module 1 — Trọng số thời gian (Time-Decay) và độ rõ ràng của tin (Confidence Weight).

Bài báo gốc gộp mọi tiêu đề bằng trung bình cộng phẳng: tin 1 giờ trước và tin 3 tuần trước,
tin rõ ràng 95% Negative và tin mập mờ 40/40/20 đều có cùng một phiếu. Module này cho mỗi
tiêu đề một trọng số

    w_i = w_time_i × w_conf_i

    w_time_i = 0.5 ** (số_giờ_đã_đăng / chu_kỳ_bán_rã)      # tin càng cũ càng nhẹ
    w_conf_i = |P(positive) − P(negative)|                    # tin càng rõ chiều càng nặng

rồi gộp theo trung bình có trọng số, có "co về trung tính" (shrinkage) khi bằng chứng ít:

    điểm = Σ w_i · s_i / (Σ w_i + κ)       với s_i = P(positive) − P(negative)

κ (prior_strength) là "độ hoài nghi": khi chỉ có ít tin, hoặc toàn tin cũ/mập mờ, Σw nhỏ so
với κ nên điểm bị kéo về 0 (không đủ tín hiệu) thay vì phóng đại một tin lẻ. Đây là ý tưởng
của trung bình Bayes / credibility weighting.

Module này KHÔNG gọi model, KHÔNG sửa phần lõi: nó chỉ nhận đúng các xác suất softmax mà
phần lõi (`TransformersLocalFinBERT` hoặc `HuggingFaceFinBERT`) đã trả về.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

LABELS = ("positive", "negative", "neutral")

# Tin riêng doanh nghiệp (micro) được thị trường "tiêu hóa" nhanh hơn tin vĩ mô (lãi suất,
# lạm phát, tỷ giá) — nên chu kỳ bán rã của micro ngắn hơn. Có thể đổi qua tham số API.
DEFAULT_HALF_LIFE_HOURS: dict[str, float] = {"micro": 12.0, "macro": 24.0}
DEFAULT_PRIOR_STRENGTH = 0.5
# Tiêu đề thiếu ngày đăng: không coi là "vừa ra" (sẽ thổi phồng), mặc định coi như 48 giờ.
DEFAULT_MISSING_AGE_HOURS = 48.0
DEFAULT_NEUTRAL_BAND = 0.15


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def hours_since(published_at: str | None, now: datetime) -> float | None:
    """Số giờ từ lúc đăng đến `now`; None nếu không đọc được thời điểm đăng."""
    moment = parse_timestamp(published_at)
    if moment is None:
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    # Lệch đồng hồ giữa các nguồn có thể tạo tuổi âm; chặn về 0 (coi như vừa đăng).
    return max(0.0, (now - moment).total_seconds() / 3600.0)


def time_decay_weight(age_hours: float, half_life_hours: float) -> float:
    """Trọng số suy giảm theo hàm mũ: sau mỗi `half_life_hours` giờ, trọng số giảm còn một nửa."""
    if half_life_hours <= 0:
        raise ValueError("half_life_hours phải > 0.")
    return 0.5 ** (max(0.0, float(age_hours)) / float(half_life_hours))


def headline_score(probabilities: Mapping[str, float]) -> float:
    """Điểm chiều của một tiêu đề trong [-1, 1] — cùng công thức score của bài báo/lõi."""
    return float(probabilities["positive"]) - float(probabilities["negative"])


def confidence_weight(probabilities: Mapping[str, float]) -> float:
    """Độ rõ ràng của tin = khoảng cách giữa Positive và Negative.

    Viết lại: |P+ − P−| = (1 − P_neutral) × |P+ − P−| / (P+ + P−)
      - (1 − P_neutral): tin có "nói về hướng tăng/giảm" không (Neutral thấp → cao)
      - |P+ − P−| / (P+ + P−): trong phần có hướng, tin có một chiều không (không 45/45)
    Ví dụ: (0.92, 0.03, 0.05) → 0.89 ; (0.45, 0.45, 0.10) → 0.00 ; (0.03, 0.02, 0.95) → 0.01
    """
    return abs(headline_score(probabilities))


def label_from_score(score: float, neutral_band: float = DEFAULT_NEUTRAL_BAND) -> str:
    if score > neutral_band:
        return "Bullish"
    if score < -neutral_band:
        return "Bearish"
    return "Neutral"


# Nhãn thứ tư: không nhóm tin nào có đủ bằng chứng để kết luận. Giao diện hiển thị là "Không đủ tin".
INSUFFICIENT_LABEL = "Insufficient"


def display_label(label: str) -> str:
    """Nhãn để in lên bảng/biểu đồ tiếng Việt."""
    return "Không đủ tin" if label == INSUFFICIENT_LABEL else label


def has_enough_evidence(evidence: float, threshold: float) -> bool:
    """Một nhóm tin "đủ tin" khi tổng trọng số Σw của nó ≥ ngưỡng.

    Ngưỡng mặc định là chính κ (prior_strength): Σw ≥ κ nghĩa là bằng chứng nặng hơn độ hoài nghi
    ban đầu, tức hệ số co Σw / (Σw + κ) ≥ 50%. Không thêm tham số "tự chọn" mới.
    Ví dụ với κ = 0,5: một tin rõ 90% vừa đăng (w ≈ 0,9) là đủ; một tin như vậy đã đăng 2 ngày
    (tin vĩ mô, H = 24h → w ≈ 0,9 × 0,25 ≈ 0,23) thì chưa đủ.
    """
    return evidence >= threshold if threshold > 0 else evidence > 0


def label_with_evidence(
    score: float,
    evidence: float,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
    neutral_band: float = DEFAULT_NEUTRAL_BAND,
    evidence_threshold: float | None = None,
) -> str:
    """Nhãn của một nhóm tin: Bullish / Bearish / Neutral, hoặc Insufficient nếu bằng chứng quá mỏng."""
    threshold = prior_strength if evidence_threshold is None else evidence_threshold
    if not has_enough_evidence(evidence, threshold):
        return INSUFFICIENT_LABEL
    return label_from_score(score, neutral_band)


@dataclass(frozen=True)
class WeightedHeadline:
    title: str
    kind: str
    symbol: str | None
    source: str | None
    published_at: str | None
    age_hours: float
    age_is_assumed: bool
    half_life_hours: float
    probabilities: dict[str, float]
    score: float
    time_weight: float
    confidence_weight: float
    weight: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def weigh_headline(
    item: Mapping[str, Any],
    now: datetime,
    half_life_hours: Mapping[str, float] | None = None,
    missing_age_hours: float = DEFAULT_MISSING_AGE_HOURS,
) -> WeightedHeadline:
    """Gắn trọng số thời gian × độ rõ ràng cho một headline đã có `probabilities`."""
    half_lives = {**DEFAULT_HALF_LIFE_HOURS, **(half_life_hours or {})}
    kind = str(item.get("kind") or "micro")
    probabilities = {label: float(item["probabilities"][label]) for label in LABELS}

    age = hours_since(item.get("published_at"), now)
    assumed = age is None
    if age is None:
        age = float(missing_age_hours)
    half_life = float(half_lives.get(kind, half_lives["micro"]))

    w_time = time_decay_weight(age, half_life)
    w_conf = confidence_weight(probabilities)
    return WeightedHeadline(
        title=str(item.get("title", "")),
        kind=kind,
        symbol=item.get("symbol"),
        source=item.get("source"),
        published_at=item.get("published_at"),
        age_hours=age,
        age_is_assumed=assumed,
        half_life_hours=half_life,
        probabilities=probabilities,
        score=headline_score(probabilities),
        time_weight=w_time,
        confidence_weight=w_conf,
        weight=w_time * w_conf,
    )


@dataclass(frozen=True)
class GroupSignal:
    """Kết quả gộp một nhóm tiêu đề (tin riêng của 1 mã, hoặc toàn bộ tin vĩ mô)."""

    score: float  # Σws / (Σw + κ), luôn nằm trong (-1, 1)
    weighted_mean_score: float  # Σws / Σw (chưa co về trung tính); 0 nếu Σw = 0
    evidence: float  # Σw — "khối lượng bằng chứng hiệu lực"
    shrink_factor: float  # Σw / (Σw + κ) — phần điểm được giữ lại
    effective_count: float  # (Σw)² / Σw² — số tin "thực sự đóng góp" (Kish)
    count: int
    prior_strength: float
    weighted_probabilities: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def aggregate_signal(rows: Iterable[WeightedHeadline], prior_strength: float = DEFAULT_PRIOR_STRENGTH) -> GroupSignal:
    rows = list(rows)
    if prior_strength < 0:
        raise ValueError("prior_strength phải >= 0.")
    total_w = sum(row.weight for row in rows)
    total_ws = sum(row.weight * row.score for row in rows)
    sum_sq = sum(row.weight**2 for row in rows)
    denominator = total_w + prior_strength

    if rows and total_w > 0:
        weighted_probabilities = {
            label: sum(row.weight * row.probabilities[label] for row in rows) / total_w for label in LABELS
        }
    elif rows:
        weighted_probabilities = {
            label: sum(row.probabilities[label] for row in rows) / len(rows) for label in LABELS
        }
    else:
        weighted_probabilities = {"positive": 0.0, "negative": 0.0, "neutral": 1.0}

    return GroupSignal(
        score=(total_ws / denominator) if denominator > 0 else 0.0,
        weighted_mean_score=(total_ws / total_w) if total_w > 0 else 0.0,
        evidence=total_w,
        shrink_factor=(total_w / denominator) if denominator > 0 else 0.0,
        effective_count=(total_w**2 / sum_sq) if sum_sq > 0 else 0.0,
        count=len(rows),
        prior_strength=prior_strength,
        weighted_probabilities=weighted_probabilities,
    )


def decay_table(hours: Iterable[float], half_life_hours: float) -> list[dict[str, float]]:
    """Bảng trọng số theo tuổi tin — dùng cho slide/biểu đồ."""
    return [
        {"age_hours": float(h), "half_life_hours": half_life_hours, "time_weight": time_decay_weight(h, half_life_hours)}
        for h in hours
    ]


def softmax(logits: Iterable[float]) -> list[float]:
    values = list(map(float, logits))
    top = max(values)
    exps = [math.exp(v - top) for v in values]
    total = sum(exps)
    return [v / total for v in exps]


def sigmoid(logits: Iterable[float]) -> list[float]:
    return [1.0 / (1.0 + math.exp(-float(v))) for v in logits]
