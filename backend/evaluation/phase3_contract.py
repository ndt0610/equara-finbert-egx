"""Pre-registered, leakage-aware return and event-feature contracts."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

from backend.universe.calendar_nyse import is_session

HORIZONS = (1, 5, 20)
PRIMARY_HORIZON = 5
COST_BPS_ONE_WAY = (0, 10, 25)
AGGREGATION_VARIANTS = ("mean", "decay_3d", "decay_7d", "first_mention")


def advance_sessions(day: date, count: int) -> date:
    if count < 0:
        raise ValueError("NEGATIVE_SESSION_COUNT")
    cursor = day
    for _ in range(count):
        cursor += timedelta(days=1)
        while not is_session(cursor):
            cursor += timedelta(days=1)
    return cursor


def previous_sessions(day: date, count: int) -> list[date]:
    if count < 0:
        raise ValueError("NEGATIVE_SESSION_COUNT")
    result = [day]
    cursor = day
    for _ in range(count):
        cursor -= timedelta(days=1)
        while not is_session(cursor):
            cursor -= timedelta(days=1)
        result.append(cursor)
    return list(reversed(result))


def realized_return(open_adj_next_session: float, close_adj_exit_session: float,
                    cost_bps_one_way: float = 0) -> dict:
    """Ex-post adjusted-bar proxy, not a documented fill or corporate-action cashflow."""
    values = (open_adj_next_session, close_adj_exit_session, cost_bps_one_way)
    if any(not math.isfinite(float(value)) for value in values) or open_adj_next_session <= 0 or close_adj_exit_session <= 0 or cost_bps_one_way < 0:
        raise ValueError("INVALID_RETURN_INPUT")
    gross = close_adj_exit_session / open_adj_next_session - 1
    return {"gross": gross, "net": gross - 2 * cost_bps_one_way / 10000,
            "return_basis": "ADJUSTED_OPEN_NEXT_TO_ADJUSTED_EXIT_CLOSE_PROXY",
            "cost_method": "LINEAR_TWO_WAY_BPS_APPROXIMATION"}


def purged_training_indices(samples: list[dict], evaluation_index: int, horizon: int,
                            evaluation_cutoff_utc: datetime | None = None) -> tuple[list[int], list[int]]:
    """A training label must have finished and become observed by the evaluation cutoff."""
    if horizon not in HORIZONS:
        raise ValueError("UNREGISTERED_HORIZON")
    if evaluation_cutoff_utc is not None and (evaluation_cutoff_utc.tzinfo is None or evaluation_cutoff_utc.utcoffset() is None):
        raise ValueError("TIMEZONE_REQUIRED")
    accepted, purged = [], []
    for index, sample in enumerate(samples):
        decision_index = sample["decision_index"]
        if decision_index >= evaluation_index:
            continue
        label_available = sample.get("label_available_at_utc")
        available = True
        if evaluation_cutoff_utc is not None:
            if label_available is None:
                available = False
            else:
                value = datetime.fromisoformat(label_available) if isinstance(label_available, str) else label_available
                if value.tzinfo is None or value.utcoffset() is None:
                    available = False
                else:
                    available = value.astimezone(timezone.utc) <= evaluation_cutoff_utc.astimezone(timezone.utc)
        if decision_index + horizon <= evaluation_index and available:
            accepted.append(index)
        else:
            purged.append(index)
    return accepted, purged


def aggregate_event_variants(clusters: list[dict], items_by_id: dict[str, dict],
                             decision_cutoff_utc: datetime,
                             strict_pit: bool = True) -> dict[str, float | None]:
    """One score per cluster; unscored structural filings never become zero votes."""
    if decision_cutoff_utc.tzinfo is None or decision_cutoff_utc.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    scored = []
    for cluster in clusters:
        if cluster.get("score") is None:
            continue
        members = [items_by_id[item_id] for item_id in cluster["item_ids"] if item_id in items_by_id]
        members = [x for x in members if x.get("scoring_status") == "SCORED" and x.get("net_score") is not None]
        if not members:
            continue
        first = min(members, key=lambda x: (x["ingested_at_utc"], x["item_id"]))
        first_time = datetime.fromisoformat(first["ingested_at_utc"])
        if first_time.tzinfo is None or first_time.utcoffset() is None:
            raise ValueError("FUTURE_OR_NAIVE_EVENT_IN_FEATURES")
        if first_time > decision_cutoff_utc:
            if strict_pit:
                raise ValueError("FUTURE_OR_NAIVE_EVENT_IN_FEATURES")
            first_time = datetime.fromisoformat(first["published_at_utc"])
            if first_time.tzinfo is None or first_time.utcoffset() is None or first_time > decision_cutoff_utc:
                raise ValueError("RETROSPECTIVE_EVENT_LACKS_PRIOR_SOURCE_TIME")
        age_days = max(0.0, (decision_cutoff_utc - first_time).total_seconds() / 86400)
        scored.append((float(cluster["score"]), float(first["net_score"]), age_days))
    if not scored:
        return {name: None for name in AGGREGATION_VARIANTS}
    mean = sum(score for score, _, _ in scored) / len(scored)
    first = sum(score for _, score, _ in scored) / len(scored)
    def decay(half_life: float) -> float:
        weights = [2 ** (-age / half_life) for _, _, age in scored]
        return sum(weight * score for weight, (score, _, _) in zip(weights, scored)) / sum(weights)
    return {"mean": mean, "decay_3d": decay(3), "decay_7d": decay(7), "first_mention": first}


def provenance_verdict(tiers: set[str], temporal_contract_ok: bool,
                       execution_open_observed: bool = False) -> dict:
    if not tiers:
        return {"report_validity_tier": "INSUFFICIENT_OBSERVATIONS", "actionability_gate_passed": False,
                "actionability_reason": "NO_EVALUATION_ROWS"}
    if any(tier != "LIVE_CAPTURED_PIT" for tier in tiers):
        return {"report_validity_tier": "EXPLORATORY_NON_PIT_DIAGNOSTIC_ONLY", "actionability_gate_passed": False,
                "actionability_reason": "NON_PIT_DATA_SOURCE"}
    if not temporal_contract_ok:
        return {"report_validity_tier": "TEMPORAL_CONTRACT_FAILED", "actionability_gate_passed": False,
                "actionability_reason": "TEMPORAL_CONTRACT_FAILED"}
    return {"report_validity_tier": "PIT_COMPLIANT_RESEARCH_RUN", "actionability_gate_passed": False,
            "actionability_reason": "OPEN_EXECUTION_NOT_OBSERVED" if not execution_open_observed else "PERFORMANCE_GATE_NOT_EVALUATED"}
