"""Bộ phân loại nhãn thuần theo TG-SPEC-1 F03–F06.

Không fit mô hình, không lấy giá và không nhận khoảng/biên do request công khai truyền vào. Chỉ
nhận snapshot, dòng tiền và ForecastArtifact nội bộ có provenance/validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
from typing import Any, Literal

from .dong_tien import CashflowBaselines, decimal_finite
from .nguong import BienManh

Label = Literal["mua_manh", "mua", "giu", "ban", "ban_manh"]
Origin = Literal["observed", "illustrative"]
VALUE_BASIS = "total_terminal_cash_after_exit_costs"

_STATUS_ORDER = (
    "invalid_data",
    "inconsistent_cashflows",
    "source_unavailable",
    "not_actionable_now",
    "stale",
    "not_calibrated",
    "insufficient_data",
)


class LoiForecast(ValueError):
    """Artifact dự báo có cận, đơn vị hoặc provenance không hợp lệ."""


def _timestamp(value: str | None, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LoiForecast(f"{field} phải là chuỗi ISO 8601 có timezone.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise LoiForecast(f"{field} không phải ISO 8601 hợp lệ.") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise LoiForecast(f"{field} phải chứa timezone.")
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class ForecastArtifact:
    instrument_id: str
    symbol: str
    scenario_id: str
    horizon_sessions: int
    cadence: str
    quantity: Decimal | str | int
    currency: str
    value_basis: Literal["total_terminal_cash_after_exit_costs"]
    terminal_cost_model_id: str | None
    corporate_action_method_ref: str | None
    as_of: str
    target_at: str
    mean_value: Decimal | str | int | None
    mean_interval_lower: Decimal | str | int | None
    mean_interval_upper: Decimal | str | int | None
    mean_interval_method: str | None
    nominal_level: int | None
    outcome_interval_lower: Decimal | str | int | None
    outcome_interval_upper: Decimal | str | int | None
    outcome_interval_method: str | None
    model_version: str | None
    feature_manifest_id: str | None
    source_snapshot_id: str | None
    training_cutoff: str | None
    validation_ref: str | None
    risk_validation_ref: str | None
    approval_status: Literal["approved", "candidate", "unavailable"] = "unavailable"
    limitation_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "quantity",
            "mean_value",
            "mean_interval_lower",
            "mean_interval_upper",
            "outcome_interval_lower",
            "outcome_interval_upper",
        ):
            value = decimal_finite(getattr(self, name), name, allow_none=True)
            object.__setattr__(self, name, value)
        if self.quantity is None or self.quantity <= 0:
            raise LoiForecast("quantity phải là số dương trong kịch bản dự báo.")
        if len(self.currency.strip()) != 3 or self.currency.upper() != self.currency:
            raise LoiForecast("currency phải là mã ISO viết hoa gồm ba ký tự.")
        if self.value_basis != VALUE_BASIS:
            raise LoiForecast("Forecast phải là tổng tiền cuối kỳ sau chi phí thoát vị thế.")
        if isinstance(self.horizon_sessions, bool) or not isinstance(self.horizon_sessions, int) or self.horizon_sessions <= 0:
            raise LoiForecast("horizon_sessions phải dương.")
        as_of = _timestamp(self.as_of, "as_of")
        target_at = _timestamp(self.target_at, "target_at")
        training_cutoff = _timestamp(self.training_cutoff, "training_cutoff")
        if as_of is None or target_at is None or target_at <= as_of:
            raise LoiForecast("as_of và target_at phải hợp lệ, target_at phải ở tương lai.")
        if training_cutoff is not None and training_cutoff >= as_of:
            raise LoiForecast("training_cutoff phải trước thời điểm dự báo để tránh nhìn trước.")
        for name in (
            "mean_value",
            "mean_interval_lower",
            "mean_interval_upper",
            "outcome_interval_lower",
            "outcome_interval_upper",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise LoiForecast(f"{name} không được âm khi biểu diễn tổng tiền cuối kỳ.")
        if self.nominal_level is not None and self.nominal_level != 95:
            raise LoiForecast("TG-SPEC-1 V1 chỉ nhận khoảng danh nghĩa 95%.")
        if self.mean_interval_lower is not None and self.mean_interval_upper is not None:
            if self.mean_interval_lower > self.mean_interval_upper:
                raise LoiForecast("mean_interval_lower phải <= mean_interval_upper.")
            if self.mean_value is not None and not (
                self.mean_interval_lower <= self.mean_value <= self.mean_interval_upper
            ):
                raise LoiForecast("mean_value phải nằm trong khoảng I_m.")
        if self.outcome_interval_lower is not None and self.outcome_interval_upper is not None:
            if self.outcome_interval_lower > self.outcome_interval_upper:
                raise LoiForecast("outcome_interval_lower phải <= outcome_interval_upper.")

    @property
    def mean_interval_available(self) -> bool:
        return (
            self.mean_value is not None
            and self.mean_interval_lower is not None
            and self.mean_interval_upper is not None
            and bool(self.mean_interval_method)
            and self.nominal_level == 95
        )

    @property
    def outcome_interval_available(self) -> bool:
        return (
            self.outcome_interval_lower is not None
            and self.outcome_interval_upper is not None
            and bool(self.outcome_interval_method)
            and bool(self.risk_validation_ref)
        )


@dataclass(frozen=True)
class ReadinessEvidence:
    """Điều kiện được xác lập bởi backend từ nguồn/snapshot, không từ request của UI."""

    data_origin: Origin = "observed"
    source_status: Literal["verified", "unavailable", "invalid"] = "unavailable"
    source_profile_ref: str | None = None
    snapshot_id: str | None = None
    actionable: bool = False
    snapshot_stale: bool = False
    mapping_verified: bool = False
    model_scope_verified: bool = False
    limitation_codes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Signal:
    status: str
    label: Label | None
    data_origin: Origin
    reason_codes: tuple[str, ...]
    reason_vi: tuple[str, ...]
    instrument_id: str | None
    symbol: str | None
    scenario_id: str | None
    as_of: str | None
    target_at: str | None
    forecast_id: str | None
    calculation: dict[str, str | None]
    risk: dict[str, str | int | None]
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "label": self.label,
            "data_origin": self.data_origin,
            "reason_codes": list(self.reason_codes),
            "reason_vi": list(self.reason_vi),
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "scenario_id": self.scenario_id,
            "as_of": self.as_of,
            "target_at": self.target_at,
            "forecast_id": self.forecast_id,
            "calculation": dict(self.calculation),
            "risk": dict(self.risk),
            "evidence_refs": list(self.evidence_refs),
        }


_REASON_TEXT = {
    "invalid_data": "Dữ liệu đầu vào không hợp lệ.",
    "inconsistent_cashflows": "Các dòng tiền mua/bán mâu thuẫn; chưa thể so sánh.",
    "source_unavailable": "Chưa có nguồn giá/quyền dữ liệu đủ xác minh.",
    "not_actionable_now": "Kịch bản hiện không thể thực hiện theo trạng thái phiên/quote.",
    "stale": "Snapshot đã cũ; cần cập nhật lại trước khi kết luận.",
    "not_calibrated": "Chưa có dự báo/khoảng đã kiểm định cho mã, horizon và cadence này.",
    "insufficient_data": "Chưa đủ dữ liệu hoặc chi phí đã xác minh cho phép so.",
    "inconclusive": "Khoảng ước lượng còn cắt qua nhiều vùng quyết định.",
    "strong_grade_unavailable": "Biên 'mạnh' chưa được xác nhận; nhãn thường vẫn xét riêng.",
    "illustrative": "Đây là kết quả giả lập, không phải giá hay dự báo thật.",
}


def _ordered_reasons(reasons: set[str]) -> tuple[str, ...]:
    priority = {code: index for index, code in enumerate(_STATUS_ORDER)}
    return tuple(sorted(reasons, key=lambda code: (priority.get(code, len(priority)), code)))


def _status_for(reasons: tuple[str, ...], label: Label | None) -> str:
    if "illustrative" in reasons and label is not None:
        return "illustrative"
    for code in _STATUS_ORDER:
        if code in reasons:
            return code
    return "ready" if label is not None else "inconclusive"


def _empty_signal(
    reasons: set[str],
    *,
    baseline: CashflowBaselines | None,
    forecast: ForecastArtifact | None,
    forecast_id: str | None,
    readiness: ReadinessEvidence,
) -> Signal:
    ordered = _ordered_reasons(reasons)
    calculation: dict[str, str | None] = {
        "C_mua": str(baseline.C_mua) if baseline else None,
        "C_ban": str(baseline.C_ban) if baseline else None,
        "A": str(baseline.A) if baseline else None,
        "V0": str(baseline.V0) if baseline else None,
        "B_mua": str(baseline.B_mua) if baseline else None,
        "B_ban": str(baseline.B_ban) if baseline else None,
        "mean": str(forecast.mean_value) if forecast and forecast.mean_value is not None else None,
        "L": str(forecast.mean_interval_lower) if forecast and forecast.mean_interval_lower is not None else None,
        "U": str(forecast.mean_interval_upper) if forecast and forecast.mean_interval_upper is not None else None,
        "k_mua": None,
        "k_ban": None,
        "buy_lower_gain": None,
        "sell_lower_gain": None,
        "quantity": str(forecast.quantity) if forecast else (str(baseline.q) if baseline else None),
        "currency": forecast.currency if forecast else (baseline.currency if baseline else None),
        "value_basis": forecast.value_basis if forecast else None,
        "terminal_cost_model_id": forecast.terminal_cost_model_id if forecast else None,
        "corporate_action_method_ref": forecast.corporate_action_method_ref if forecast else None,
        "training_cutoff": forecast.training_cutoff if forecast else None,
    }
    risk: dict[str, str | int | None] = {
        "lower": str(forecast.outcome_interval_lower)
        if forecast and forecast.outcome_interval_lower is not None
        else None,
        "upper": str(forecast.outcome_interval_upper)
        if forecast and forecast.outcome_interval_upper is not None
        else None,
        "nominal_level": forecast.nominal_level if forecast else None,
        "method": forecast.outcome_interval_method if forecast else None,
        "validation_ref": forecast.risk_validation_ref if forecast else None,
    }
    refs = set(readiness.evidence_refs)
    if readiness.source_profile_ref:
        refs.add(readiness.source_profile_ref)
    if baseline:
        refs.update(baseline.evidence_refs)
    if forecast:
        refs.update(
            x
            for x in (
                forecast.validation_ref,
                forecast.risk_validation_ref,
                forecast.terminal_cost_model_id,
                forecast.corporate_action_method_ref,
            )
            if x
        )
    return Signal(
        status=_status_for(ordered, None),
        label=None,
        data_origin=readiness.data_origin,
        reason_codes=ordered,
        reason_vi=tuple(_REASON_TEXT.get(code, code) for code in ordered),
        instrument_id=baseline.instrument_id if baseline else (forecast.instrument_id if forecast else None),
        symbol=baseline.symbol if baseline else (forecast.symbol if forecast else None),
        scenario_id=forecast.scenario_id if forecast else None,
        as_of=forecast.as_of if forecast else None,
        target_at=forecast.target_at if forecast else None,
        forecast_id=forecast_id,
        calculation=calculation,
        risk=risk,
        evidence_refs=tuple(sorted(refs)),
    )


def evaluate_signal(
    baseline: CashflowBaselines | None,
    forecast: ForecastArtifact | None,
    readiness: ReadinessEvidence,
    *,
    forecast_id: str | None = None,
    k_buy: BienManh | None = None,
    k_sell: BienManh | None = None,
) -> Signal:
    """Phát một trong năm nhãn hoặc abstain; dữ liệu thiếu không bao giờ đổi thành Giữ."""
    reason_aliases = {
        "risk_not_validated": "not_calibrated",
        "model_not_validated": "not_calibrated",
        "history_unavailable": "insufficient_data",
        "provider_limit": "insufficient_data",
        "quote_stale": "stale",
    }
    reasons = {reason_aliases.get(code, code) for code in readiness.limitation_codes}
    if readiness.data_origin == "illustrative":
        reasons.add("illustrative")
    if readiness.source_status == "invalid" or not readiness.mapping_verified:
        reasons.add("invalid_data")
    elif readiness.source_status != "verified" or not readiness.source_profile_ref:
        reasons.add("source_unavailable")
    if not readiness.actionable:
        reasons.add("not_actionable_now")
    if readiness.snapshot_stale:
        reasons.add("stale")
    if baseline is None:
        reasons.add("insufficient_data")
    if forecast is None:
        reasons.add("not_calibrated")

    if forecast is not None and baseline is not None:
        if (
            forecast.instrument_id != baseline.instrument_id
            or forecast.symbol.upper() != baseline.symbol.upper()
            or forecast.scenario_id != baseline.scenario_id
        ):
            reasons.add("invalid_data")
        if forecast.quantity != baseline.q or forecast.currency != baseline.currency:
            reasons.add("invalid_data")
        if forecast.value_basis != VALUE_BASIS:
            reasons.add("invalid_data")
        if (
            not baseline.cost_model_id
            or not forecast.terminal_cost_model_id
            or forecast.terminal_cost_model_id != baseline.cost_model_id
            or not forecast.corporate_action_method_ref
        ):
            reasons.add("insufficient_data")
        if forecast.horizon_sessions != baseline.horizon_sessions:
            reasons.add("not_calibrated")
        if forecast.approval_status != "approved" or not readiness.model_scope_verified:
            reasons.add("not_calibrated")
        if not forecast.model_version or not forecast.cadence:
            reasons.add("not_calibrated")
        if not forecast.validation_ref or not forecast.source_snapshot_id or not forecast.feature_manifest_id:
            reasons.add("not_calibrated")
        if not forecast.training_cutoff:
            reasons.add("not_calibrated")
        if not readiness.snapshot_id or forecast.source_snapshot_id != readiness.snapshot_id:
            reasons.add("stale")
        if forecast.as_of[:10] != baseline.as_of.isoformat():
            reasons.add("stale")
        if not forecast.mean_interval_available:
            reasons.add("not_calibrated")
        if not forecast.outcome_interval_available:
            reasons.add("not_calibrated")
        if forecast.limitation_codes:
            if "insufficient_data" in forecast.limitation_codes:
                reasons.add("insufficient_data")
            if "stale" in forecast.limitation_codes:
                reasons.add("stale")
            if "not_calibrated" in forecast.limitation_codes:
                reasons.add("not_calibrated")
        if baseline.B_ban > baseline.B_mua:
            reasons.add("inconsistent_cashflows")

    # Only the explicitly separate /examples path may return an illustrative label. Public /snapshot
    # services must not construct ReadinessEvidence(data_origin="illustrative").
    blocking = set(_STATUS_ORDER) & reasons
    if blocking or baseline is None or forecast is None:
        return _empty_signal(
            reasons,
            baseline=baseline,
            forecast=forecast,
            forecast_id=forecast_id,
            readiness=readiness,
        )

    assert forecast.mean_interval_lower is not None
    assert forecast.mean_interval_upper is not None
    assert forecast.mean_value is not None
    assert baseline.V0 > 0
    L = forecast.mean_interval_lower
    U = forecast.mean_interval_upper
    B_buy = baseline.B_mua
    B_sell = baseline.B_ban

    k_buy_value: Decimal | None = None
    if k_buy and k_buy.usable_for(
        instrument_id=baseline.instrument_id,
        horizon_sessions=baseline.horizon_sessions,
        cadence=forecast.cadence,
        model_version=forecast.model_version or "",
    ):
        k_buy_value = k_buy.gia_tri
    k_sell_value: Decimal | None = None
    if k_sell and k_sell.usable_for(
        instrument_id=baseline.instrument_id,
        horizon_sessions=baseline.horizon_sessions,
        cadence=forecast.cadence,
        model_version=forecast.model_version or "",
    ):
        k_sell_value = k_sell.gia_tri

    label: Label | None = None
    with localcontext() as ctx:
        ctx.prec = 28
        buy_margin = k_buy_value * baseline.V0 if k_buy_value is not None else None
        sell_margin = k_sell_value * baseline.V0 if k_sell_value is not None else None
        if buy_margin is not None and L > B_buy + buy_margin:
            label = "mua_manh"
        elif L > B_buy:
            label = "mua"
            if k_buy_value is None:
                reasons.add("strong_grade_unavailable")
        elif sell_margin is not None and U < B_sell - sell_margin:
            label = "ban_manh"
        elif U < B_sell:
            label = "ban"
            if k_sell_value is None:
                reasons.add("strong_grade_unavailable")
        elif L >= B_sell and U <= B_buy:
            label = "giu"
        else:
            reasons.add("inconclusive")

        buy_lower_gain = (L - B_buy) / baseline.V0
        sell_lower_gain = (B_sell - U) / baseline.V0

    ordered = _ordered_reasons(reasons)
    refs = set(readiness.evidence_refs)
    refs.update(baseline.evidence_refs)
    if readiness.source_profile_ref:
        refs.add(readiness.source_profile_ref)
    refs.update(
        x
        for x in (
            forecast.validation_ref,
            forecast.risk_validation_ref,
            forecast.terminal_cost_model_id,
            forecast.corporate_action_method_ref,
        )
        if x
    )
    if k_buy_value is not None and k_buy and k_buy.validation_ref:
        refs.add(k_buy.validation_ref)
    if k_sell_value is not None and k_sell and k_sell.validation_ref:
        refs.add(k_sell.validation_ref)
    return Signal(
        status=_status_for(ordered, label),
        label=label,
        data_origin=readiness.data_origin,
        reason_codes=ordered,
        reason_vi=tuple(_REASON_TEXT.get(code, code) for code in ordered),
        instrument_id=baseline.instrument_id,
        symbol=baseline.symbol,
        scenario_id=forecast.scenario_id,
        as_of=forecast.as_of,
        target_at=forecast.target_at,
        forecast_id=forecast_id,
        calculation={
            "C_mua": str(baseline.C_mua),
            "C_ban": str(baseline.C_ban),
            "A": str(baseline.A),
            "V0": str(baseline.V0),
            "B_mua": str(B_buy),
            "B_ban": str(B_sell),
            "mean": str(forecast.mean_value),
            "L": str(L),
            "U": str(U),
            "k_mua": str(k_buy_value) if k_buy_value is not None else None,
            "k_ban": str(k_sell_value) if k_sell_value is not None else None,
            "buy_lower_gain": str(buy_lower_gain),
            "sell_lower_gain": str(sell_lower_gain),
            "quantity": str(baseline.q),
            "currency": baseline.currency,
            "value_basis": forecast.value_basis,
            "terminal_cost_model_id": forecast.terminal_cost_model_id,
            "corporate_action_method_ref": forecast.corporate_action_method_ref,
            "training_cutoff": forecast.training_cutoff,
        },
        risk={
            "lower": str(forecast.outcome_interval_lower)
            if forecast.outcome_interval_lower is not None
            else None,
            "upper": str(forecast.outcome_interval_upper)
            if forecast.outcome_interval_upper is not None
            else None,
            "nominal_level": forecast.nominal_level,
            "method": forecast.outcome_interval_method,
            "validation_ref": forecast.risk_validation_ref,
        },
        evidence_refs=tuple(sorted(refs)),
    )
