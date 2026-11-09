"""Module 2 — Trọng số danh mục đầu tư (Portfolio Weighting) + hệ số nhạy cảm vĩ mô (macro beta).

Bài báo gốc (mục 6): lấy 4 tin macro + 1–2 tin mỗi mã, ném chung vào một rổ rồi lấy trung
bình phẳng. Ba lỗ hổng tài chính:
  (1) Mã chiếm 10% vốn có tiếng nói ngang mã chiếm 70% vốn.
  (2) Mã nào tìm được nhiều tin hơn thì nặng hơn (thiên lệch theo số lượng tin, không theo tiền).
  (3) Tin vĩ mô tác động như nhau lên mọi mã, trong khi ngân hàng nhạy với lãi suất/tỷ giá hơn
      hẳn viễn thông.

Công thức của module (lấy cảm hứng từ mô hình 1 nhân tố/CAPM: r_k = riêng_k + β_k × thị_trường):

    M          = điểm vĩ mô (Module 1 áp lên các tin macro)
    micro_k    = điểm tin riêng của mã k (Module 1 áp lên tin micro của k)
    S_k        = clip(micro_k + β_k × M, −1, 1)
    S_danh_mục = Σ_k vốn_k × S_k                    (Σ vốn_k = 1)
               = Σ vốn_k × micro_k  +  β_danh_mục × M      với β_danh_mục = Σ vốn_k × β_k

Mỗi tiêu đề còn được quy ra "đóng góp" vào điểm danh mục, nên cộng dọc cột đóng góp sẽ ra đúng
điểm danh mục — ở cả phương pháp gốc (đóng góp = s_i / N) lẫn phương pháp mới.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from backend.services.sentiment import aggregate_probabilities
from backend.upgrades.time_confidence import (
    DEFAULT_HALF_LIFE_HOURS,
    DEFAULT_MISSING_AGE_HOURS,
    DEFAULT_NEUTRAL_BAND,
    DEFAULT_PRIOR_STRENGTH,
    INSUFFICIENT_LABEL,
    GroupSignal,
    WeightedHeadline,
    aggregate_signal,
    has_enough_evidence,
    headline_score,
    label_from_score,
    weigh_headline,
)

MAX_MACRO_BETA = 3.0


@dataclass(frozen=True)
class Position:
    symbol: str
    capital_weight: float  # tỷ trọng vốn; được chuẩn hóa để tổng = 1
    macro_beta: float = 1.0  # 1.0 = nhạy vĩ mô như thị trường chung; 0 = không nhạy


def normalize_positions(positions: Sequence[Position | Mapping[str, Any]]) -> list[Position]:
    """Nhận tỷ trọng dạng % (70, 20, 10) hoặc phân số (0.7, 0.2, 0.1); chuẩn hóa về tổng = 1."""
    parsed: list[Position] = []
    for raw in positions:
        if isinstance(raw, Position):
            parsed.append(raw)
        else:
            parsed.append(
                Position(
                    symbol=str(raw["symbol"]),
                    capital_weight=float(raw.get("capital_weight", raw.get("weight", 0.0))),
                    macro_beta=float(raw.get("macro_beta", 1.0)),
                )
            )
    if not parsed:
        raise ValueError("Danh mục phải có ít nhất 1 mã.")
    symbols = [p.symbol for p in parsed]
    if len(set(symbols)) != len(symbols):
        raise ValueError("Danh mục không được có mã trùng lặp.")
    for p in parsed:
        if p.capital_weight < 0:
            raise ValueError(f"Tỷ trọng vốn của {p.symbol} âm; bản này chưa hỗ trợ bán khống.")
        if not 0.0 <= p.macro_beta <= MAX_MACRO_BETA:
            raise ValueError(f"macro_beta của {p.symbol} phải trong [0, {MAX_MACRO_BETA}].")
    total = sum(p.capital_weight for p in parsed)
    if total <= 0:
        raise ValueError("Tổng tỷ trọng vốn phải > 0.")
    return [Position(p.symbol, p.capital_weight / total, p.macro_beta) for p in parsed]


def estimate_macro_beta(stock_returns: Sequence[float], market_returns: Sequence[float]) -> float:
    """Ước lượng beta lịch sử = Cov(r_mã, r_thị_trường) / Var(r_thị_trường).

    Gợi ý thực tế: dùng lợi suất ngày 250 phiên của mã so với chỉ số EGX30 để điền macro_beta.
    """
    if len(stock_returns) != len(market_returns) or len(stock_returns) < 3:
        raise ValueError("Cần >= 3 cặp lợi suất cùng độ dài.")
    n = len(stock_returns)
    mean_s = sum(stock_returns) / n
    mean_m = sum(market_returns) / n
    cov = sum((s - mean_s) * (m - mean_m) for s, m in zip(stock_returns, market_returns)) / (n - 1)
    var = sum((m - mean_m) ** 2 for m in market_returns) / (n - 1)
    if var == 0:
        raise ValueError("Lợi suất thị trường không biến động; không ước lượng được beta.")
    return cov / var


def article_baseline(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Phương pháp GỐC của bài báo (đúng hàm lõi `aggregate_probabilities`): trung bình phẳng."""
    rows = [item["probabilities"] for item in items]
    probabilities, sentiment, score = aggregate_probabilities(rows)
    n = len(rows)
    return {
        "method": "article_equal_weight_mean",
        "score": score,
        "sentiment": sentiment,
        "probabilities": probabilities,
        "headline_count": n,
        "headline_contributions": [headline_score(item["probabilities"]) / n for item in items],
    }


@dataclass
class HoldingResult:
    symbol: str
    capital_weight: float
    macro_beta: float
    micro: GroupSignal
    macro_component: float  # β_k × M
    unclipped_score: float
    stock_score: float  # S_k sau khi chặn [-1, 1]
    clip_factor: float  # S_k / unclipped (1.0 nếu không bị chặn)
    contribution: float  # vốn_k × S_k
    has_micro_news: bool

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["micro"] = self.micro.to_dict()
        return data


@dataclass
class PortfolioResult:
    score: float
    sentiment: str
    neutral_band: float
    macro: GroupSignal
    portfolio_beta: float  # Σ vốn_k × β_k × clip_factor_k (beta hiệu lực)
    micro_part: float  # Σ vốn_k × micro_k × clip_factor_k
    macro_part: float  # β_danh_mục × M
    holdings: list[HoldingResult]
    headlines: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    # "enough" hoặc "insufficient"; khi "insufficient", sentiment = "Insufficient" và
    # score_label là nhãn mà riêng điểm số sẽ cho (để đối chiếu, không dùng làm tín hiệu).
    evidence_status: str = "enough"
    evidence_threshold: float = DEFAULT_PRIOR_STRENGTH
    evidence_by_group: dict[str, float] = field(default_factory=dict)
    score_label: str = "Neutral"

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": "time_confidence_portfolio_weighted",
            "score": self.score,
            "sentiment": self.sentiment,
            "score_label": self.score_label,
            "evidence_status": self.evidence_status,
            "evidence_threshold": self.evidence_threshold,
            "evidence_by_group": self.evidence_by_group,
            "neutral_band": self.neutral_band,
            "macro": self.macro.to_dict(),
            "portfolio_beta": self.portfolio_beta,
            "micro_part": self.micro_part,
            "macro_part": self.macro_part,
            "holdings": [h.to_dict() for h in self.holdings],
            "headlines": self.headlines,
            "warnings": self.warnings,
            "parameters": self.parameters,
        }


def portfolio_sentiment(
    items: Sequence[Mapping[str, Any]],
    positions: Sequence[Position | Mapping[str, Any]],
    now: datetime,
    *,
    half_life_hours: Mapping[str, float] | None = None,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
    missing_age_hours: float = DEFAULT_MISSING_AGE_HOURS,
    neutral_band: float = DEFAULT_NEUTRAL_BAND,
    evidence_threshold: float | None = None,
) -> PortfolioResult:
    """Điểm sentiment thực chất của túi tiền nhà đầu tư (Module 1 + Module 2).

    Trạng thái "Không đủ tin": nếu không nhóm tin nào liên quan tới danh mục (tin riêng của một mã
    đang nắm, hoặc tin vĩ mô khi β danh mục > 0) có Σw ≥ ngưỡng (mặc định = κ), nhãn là
    "Insufficient" thay vì Bullish/Bearish/Neutral. Điểm số vẫn được tính và trả về để minh bạch.
    """
    holdings_in = normalize_positions(positions)
    half_lives = {**DEFAULT_HALF_LIFE_HOURS, **(half_life_hours or {})}
    weighted: list[WeightedHeadline] = [
        weigh_headline(item, now, half_lives, missing_age_hours) for item in items
    ]

    macro_rows = [row for row in weighted if row.kind == "macro"]
    macro = aggregate_signal(macro_rows, prior_strength)
    macro_denominator = macro.evidence + prior_strength

    warnings: list[str] = []
    holdings: list[HoldingResult] = []
    held = {p.symbol for p in holdings_in}
    for position in holdings_in:
        micro_rows = [row for row in weighted if row.kind != "macro" and row.symbol == position.symbol]
        micro = aggregate_signal(micro_rows, prior_strength)
        macro_component = position.macro_beta * macro.score
        unclipped = micro.score + macro_component
        clipped = max(-1.0, min(1.0, unclipped))
        clip_factor = (clipped / unclipped) if unclipped != 0 else 1.0
        if not micro_rows:
            warnings.append(f"{position.symbol}: không có tin riêng — điểm chỉ phản ánh β × vĩ mô.")
        if clip_factor < 1.0:
            warnings.append(f"{position.symbol}: điểm {unclipped:+.3f} vượt [-1, 1], đã chặn về {clipped:+.3f}.")
        holdings.append(
            HoldingResult(
                symbol=position.symbol,
                capital_weight=position.capital_weight,
                macro_beta=position.macro_beta,
                micro=micro,
                macro_component=macro_component,
                unclipped_score=unclipped,
                stock_score=clipped,
                clip_factor=clip_factor,
                contribution=position.capital_weight * clipped,
                has_micro_news=bool(micro_rows),
            )
        )

    orphan = [row for row in weighted if row.kind != "macro" and row.symbol not in held]
    if orphan:
        warnings.append(f"Bỏ qua {len(orphan)} tin micro của mã không có trong danh mục.")
    if not macro_rows:
        warnings.append("Không có tin vĩ mô — thành phần β × M = 0.")

    by_symbol = {h.symbol: h for h in holdings}
    portfolio_beta = sum(h.capital_weight * h.macro_beta * h.clip_factor for h in holdings)
    micro_part = sum(h.capital_weight * h.micro.score * h.clip_factor for h in holdings)
    macro_part = portfolio_beta * macro.score
    score = sum(h.contribution for h in holdings)

    # Quy đổi đóng góp từng tiêu đề (cộng lại = score).
    headline_rows: list[dict[str, Any]] = []
    for row in weighted:
        data = row.to_dict()
        if row.kind == "macro":
            share = (row.weight * row.score / macro_denominator) if macro_denominator > 0 else 0.0
            data["capital_weight"] = None
            data["macro_beta_applied"] = portfolio_beta
            data["contribution"] = portfolio_beta * share
        elif row.symbol in by_symbol:
            h = by_symbol[row.symbol]
            denominator = h.micro.evidence + prior_strength
            share = (row.weight * row.score / denominator) if denominator > 0 else 0.0
            data["capital_weight"] = h.capital_weight
            data["macro_beta_applied"] = None
            data["contribution"] = h.capital_weight * h.clip_factor * share
        else:
            data["capital_weight"] = 0.0
            data["macro_beta_applied"] = None
            data["contribution"] = 0.0
        headline_rows.append(data)

    if all(row.age_is_assumed for row in weighted) and weighted:
        warnings.append("Không tiêu đề nào có ngày đăng; tuổi tin được giả định, Time-Decay kém tin cậy.")

    threshold = float(prior_strength if evidence_threshold is None else evidence_threshold)
    evidence_by_group = {h.symbol: h.micro.evidence for h in holdings if h.capital_weight > 0}
    if sum(p.capital_weight * p.macro_beta for p in holdings_in) > 0:
        evidence_by_group["macro"] = macro.evidence
    enough = any(has_enough_evidence(value, threshold) for value in evidence_by_group.values())
    score_label = label_from_score(score, neutral_band)
    if not enough:
        strongest = max(evidence_by_group.items(), key=lambda kv: kv[1])
        name = "tin vĩ mô" if strongest[0] == "macro" else f"tin riêng {strongest[0]}"
        warnings.append(
            f"Không đủ tin: không nhóm tin nào có tổng trọng số Σw ≥ {threshold:g} (mạnh nhất là {name}, Σw = {strongest[1]:.3f}). "
            f"Điểm {score:+.3f} ({score_label}) chỉ để tham khảo, không nên coi là tín hiệu."
        )

    return PortfolioResult(
        score=score,
        sentiment=score_label if enough else INSUFFICIENT_LABEL,
        score_label=score_label,
        evidence_status="enough" if enough else "insufficient",
        evidence_threshold=threshold,
        evidence_by_group=evidence_by_group,
        neutral_band=neutral_band,
        macro=macro,
        portfolio_beta=portfolio_beta,
        micro_part=micro_part,
        macro_part=macro_part,
        holdings=holdings,
        headlines=headline_rows,
        warnings=warnings,
        parameters={
            "half_life_hours": half_lives,
            "prior_strength": prior_strength,
            "missing_age_hours": missing_age_hours,
            "neutral_band": neutral_band,
            "evidence_threshold": threshold,
            "positions": [asdict(p) for p in holdings_in],
            "now_utc": now.isoformat(),
        },
    )


def equal_capital_positions(symbols: Iterable[str]) -> list[Position]:
    """Dùng cho bước 'chỉ bật Module 1' trong phân tích tách lớp (ablation)."""
    symbols = list(symbols)
    return [Position(symbol, 1.0 / len(symbols), 1.0) for symbol in symbols]
