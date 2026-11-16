"""Walk-forward paired price-vs-event research with explicit ex-post return proxies."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, datetime, time, timezone

import numpy as np

from backend.evaluation.phase3_contract import (
    AGGREGATION_VARIANTS, COST_BPS_ONE_WAY, PRIMARY_HORIZON,
    provenance_verdict, purged_training_indices, realized_return,
)
from backend.storage.pit_ledger import digest
from backend.universe.calendar_nyse import ET

PRICE_COLUMNS = ("r_minus_1", "r_minus_5", "r_minus_20", "sigma_20", "b75_abs_return", "e90_abs_return")
PRIMARY_VARIANT = "mean"
LOGISTIC_L2 = 10.0
RIDGE_L2 = 10.0


def _features(row: dict, include_events: bool, variant: str) -> list[float]:
    values = [float(row["price_features"][name]) for name in PRICE_COLUMNS]
    if include_events:
        event = row["event_features"]
        score = event["aggregate_scores"].get(variant)
        values.extend((float(event["has_valid_event"]), float(event["event_cluster_count"]),
                       float(event["has_sec_filing"]), float(event["scored_cluster_count"]),
                       float(score is not None), float(score) if score is not None else 0.0))
    if not all(math.isfinite(value) for value in values):
        raise ValueError("NONFINITE_FEATURE")
    return values


def _standardize(x_train: np.ndarray, x_test: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    center = x_train.mean(axis=0)
    scale = x_train.std(axis=0)
    scale[scale < 1e-12] = 1.0
    if x_train.shape[1] == len(PRICE_COLUMNS) + 6:
        # Last column is already bounded [-1, 1]. Missing news must stay at 0.
        center[-1], scale[-1] = 0.0, 1.0
    return (x_train - center) / scale, (x_test - center) / scale


def _fit_predict_ridge(x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray) -> np.ndarray:
    train, test = _standardize(x_train, x_test)
    train = np.column_stack([np.ones(len(train)), train])
    test = np.column_stack([np.ones(len(test)), test])
    penalty = np.eye(train.shape[1]) * RIDGE_L2
    penalty[0, 0] = 0
    coefficients = np.linalg.solve(train.T @ train + penalty, train.T @ y_train)
    return test @ coefficients


def _fit_predict_logistic(x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray) -> np.ndarray:
    if set(y_train) in ({0.0}, {1.0}):
        smoothed = (float(y_train.sum()) + .5) / (len(y_train) + 1)
        return np.full(len(x_test), smoothed)
    train, test = _standardize(x_train, x_test)
    train = np.column_stack([np.ones(len(train)), train])
    test = np.column_stack([np.ones(len(test)), test])
    prior = (float(y_train.sum()) + .5) / (len(y_train) + 1)
    coefficients = np.zeros(train.shape[1])
    coefficients[0] = math.log(prior / (1 - prior))
    penalty = np.eye(train.shape[1]) * LOGISTIC_L2
    penalty[0, 0] = 0
    for _ in range(50):
        probability = np.clip(1 / (1 + np.exp(-np.clip(train @ coefficients, -35, 35))), 1e-8, 1 - 1e-8)
        gradient = train.T @ (probability - y_train) + penalty @ coefficients
        weights = probability * (1 - probability)
        hessian = train.T @ (train * weights[:, None]) + penalty
        step = np.linalg.solve(hessian, gradient)
        coefficients -= step
        if np.linalg.norm(step) < 1e-7:
            break
    return np.clip(1 / (1 + np.exp(-np.clip(test @ coefficients, -35, 35))), 1e-6, 1 - 1e-6)


def _average_ranks(values: list[float]) -> np.ndarray:
    indexed = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = np.empty(len(values), dtype=float)
    cursor = 0
    while cursor < len(indexed):
        end = cursor + 1
        while end < len(indexed) and values[indexed[end]] == values[indexed[cursor]]:
            end += 1
        rank = (cursor + end - 1) / 2 + 1
        for position in indexed[cursor:end]:
            ranks[position] = rank
        cursor = end
    return ranks


def _auc(y: list[int], p: list[float]) -> float | None:
    positives = sum(y)
    negatives = len(y) - positives
    if not positives or not negatives:
        return None
    ranks = _average_ranks(p)
    return float((sum(ranks[index] for index, value in enumerate(y) if value) - positives * (positives + 1) / 2) / (positives * negatives))


def _spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    left, right = _average_ranks(a), _average_ranks(b)
    if np.std(left) == 0 or np.std(right) == 0:
        return None
    return float(np.corrcoef(left, right)[0, 1])


def _forecast_metrics(rows: list[dict], branch: str, variant: str) -> dict:
    if not rows:
        return {"n": 0, "brier": None, "log_loss": None, "auc": None, "rank_ic": None}
    y = [int(row["net_return_10bps"] > 0) for row in rows]
    p = [float(row["predictions"][variant][branch]["probability_positive_net"]) for row in rows]
    expected = [float(row["predictions"][variant][branch]["expected_gross_return"]) for row in rows]
    actual = [float(row["gross_return"]) for row in rows]
    clipped = [min(max(value, 1e-6), 1 - 1e-6) for value in p]
    return {"n": len(rows), "brier": sum((prob - target) ** 2 for prob, target in zip(p, y)) / len(rows),
            "log_loss": -sum(target * math.log(prob) + (1 - target) * math.log(1 - prob)
                             for target, prob in zip(y, clipped)) / len(rows),
            "auc": _auc(y, p), "rank_ic": _spearman(expected, actual)}


def _paired_comparison(rows: list[dict], variant: str) -> dict:
    price = _forecast_metrics(rows, "price", variant)
    news = _forecast_metrics(rows, "price_news", variant)
    deltas = {name: news[name] - price[name] if news[name] is not None and price[name] is not None else None
              for name in ("brier", "log_loss", "auc", "rank_ic")}
    return {"n": len(rows), "price_only": price, "price_plus_news": news,
            "delta_news_minus_price": deltas}


def _moving_block_ci(rows: list[dict], variant: str, horizon: int, repetitions: int, seed: int) -> dict:
    indices = sorted({row["decision_index"] for row in rows})
    session_grid = list(range(indices[0], indices[-1] + 1)) if indices else []
    if len(session_grid) < 2 * horizon or len(indices) < 2 * horizon or repetitions < 20:
        return {"status": "INSUFFICIENT_DATES_FOR_BLOCK_CI", "unique_dates": len(indices), "block_length_sessions": horizon,
                "repetitions": repetitions, "delta_95ci": {name: None for name in ("brier", "log_loss", "auc", "rank_ic")}}
    by_date = defaultdict(list)
    for row in rows:
        by_date[row["decision_index"]].append(row)
    random = np.random.default_rng(seed)
    observed = defaultdict(list)
    for _ in range(repetitions):
        sampled_dates = []
        while len(sampled_dates) < len(session_grid):
            start = int(random.integers(0, len(session_grid) - horizon + 1))
            sampled_dates.extend(session_grid[start:start + horizon])
        sample = [row for day in sampled_dates[:len(session_grid)] for row in by_date[day]]
        delta = _paired_comparison(sample, variant)["delta_news_minus_price"]
        for key, value in delta.items():
            if value is not None and math.isfinite(value):
                observed[key].append(value)
    intervals = {key: [float(np.quantile(observed[key], .025)), float(np.quantile(observed[key], .975))]
                 if len(observed[key]) >= max(20, repetitions // 2) else None
                 for key in ("brier", "log_loss", "auc", "rank_ic")}
    return {"status": "OK", "unique_dates": len(indices), "span_sessions": len(session_grid),
            "block_length_sessions": horizon,
            "repetitions": repetitions, "delta_95ci": intervals}


def _max_drawdown(returns: list[float]) -> float | None:
    if not returns:
        return None
    nav = peak = 1.0
    worst = 0.0
    for value in returns:
        nav *= 1 + value
        peak = max(peak, nav)
        worst = min(worst, nav / peak - 1)
    return worst


def _basket_mean_block_ci(values: list[float], repetitions: int, seed: int) -> list[float] | None:
    """Resample whole, nonoverlapping basket periods in contiguous four-period blocks."""
    if len(values) < 8 or repetitions < 20:
        return None
    rng = np.random.default_rng(seed)
    length = min(4, len(values) // 2)
    means = []
    for _ in range(repetitions):
        sampled = []
        while len(sampled) < len(values):
            start = int(rng.integers(0, len(values) - length + 1))
            sampled.extend(values[start:start + length])
        means.append(float(np.mean(sampled[:len(values)])))
    return [float(np.quantile(means, .025)), float(np.quantile(means, .975))]


def _portfolio_diagnostics(rows: list[dict], horizon: int, repetitions: int, seed: int) -> dict:
    """Nonoverlapping, fully liquidated baskets; diagnostic rather than fill simulation."""
    by_date = defaultdict(list)
    for row in rows:
        by_date[row["decision_date"]].append(row)
    chosen = []
    last_index = -horizon
    for day in sorted(by_date):
        index = by_date[day][0]["decision_index"]
        if index - last_index >= horizon:
            chosen.append((day, by_date[day]))
            last_index = index
    result = {}
    for bps in COST_BPS_ONE_WAY:
        periods = []
        for day, candidates in chosen:
            period = {"decision_date": day, "exit_session": candidates[0]["exit_session"],
                      "year": day[:4], "quarter": f"{day[:4]}Q{(int(day[5:7]) - 1) // 3 + 1}"}
            for branch in ("cash", "equal_weight_universe", "price", "price_news"):
                selected = ([] if branch == "cash" else candidates if branch == "equal_weight_universe" else
                            [row for row in candidates if row["predictions"][PRIMARY_VARIANT][branch]["probability_positive_net"] > .5])
                net = [realized_return(float(row["entry_open_adj"]), float(row["exit_close_adj"]), bps)["net"] for row in selected]
                period[branch] = sum(net) / len(net) if net else 0.0
                period[f"{branch}_selected"] = [row["ticker"] for row in selected]
                period[f"{branch}_ticker_net_returns"] = {row["ticker"]: value for row, value in zip(selected, net)}
                period[f"{branch}_round_trip_turnover"] = 2.0 if selected else 0.0
            periods.append(period)
        summaries = {}
        for branch in ("cash", "equal_weight_universe", "price", "price_news"):
            values = [period[branch] for period in periods]
            benchmark = [period["equal_weight_universe"] for period in periods]
            excess = [value - base for value, base in zip(values, benchmark)]
            std = float(np.std(excess, ddof=1)) if len(excess) > 1 else 0.0
            by_year, by_quarter, by_ticker = defaultdict(list), defaultdict(list), defaultdict(list)
            for period in periods:
                by_year[period["year"]].append(period[branch])
                by_quarter[period["quarter"]].append(period[branch])
                for ticker, ticker_return in period[f"{branch}_ticker_net_returns"].items():
                    by_ticker[ticker].append(ticker_return)
            summaries[branch] = {"period_count": len(values),
                                 "mean_net_return_per_period": sum(values) / len(values) if values else None,
                                 "mean_net_return_95ci_block_bootstrap": _basket_mean_block_ci(values, repetitions, seed),
                                 "information_ratio_per_period_vs_equal_weight": sum(excess) / len(excess) / std if std > 0 else None,
                                 "mean_round_trip_turnover": sum(period[f"{branch}_round_trip_turnover"] for period in periods) / len(periods) if periods else None,
                                 "max_drawdown": _max_drawdown(values),
                                 "loss_period_fraction": sum(value < 0 for value in values) / len(values) if values else None,
                                 "by_year_mean": {key: sum(vals) / len(vals) for key, vals in sorted(by_year.items())},
                                 "by_quarter_mean": {key: sum(vals) / len(vals) for key, vals in sorted(by_quarter.items())},
                                 "by_selected_ticker_net_return_mean": {key: sum(vals) / len(vals) for key, vals in sorted(by_ticker.items())}}
        result[str(bps)] = {"one_way_cost_bps": bps, "round_trip_cost_bps": 2 * bps,
                            "nonoverlapping_periods": periods, "branches": summaries}
    return {"method": "NONOVERLAPPING_EQUAL_WEIGHT_ROUND_TRIP_BASKETS_WITH_CASH_IF_NO_SELECTION",
            "selection_threshold": .5, "horizon_sessions": horizon, "cost_scenarios": result}


def run_walk_forward_phase3(panel: dict, min_train_sessions: int = 20,
                            min_train_rows: int = 40, rolling_window_sessions: int | None = None,
                            bootstrap_repetitions: int = 200, random_seed: int = 20261115) -> dict:
    """All four news variants are pre-registered; primary decision variant is mean."""
    if min_train_sessions < 2 or min_train_rows < 5 or (rolling_window_sessions is not None and rolling_window_sessions < min_train_sessions):
        raise ValueError("INVALID_WALK_FORWARD_CONFIGURATION")
    rows = panel["rows"]
    retrospective_replay = bool(panel.get("allow_retrospective_diagnostic", False))
    # Only a diagnostic replay may assume an ex-post bar was observable at the
    # exit session cutoff. The ledger's actual capture timestamp stays intact.
    maturity_rows = (
        [{**row, "label_available_at_utc": datetime.combine(
            date.fromisoformat(row["exit_session"]), time(20), ET
        ).astimezone(timezone.utc).isoformat()} for row in rows]
        if retrospective_replay else rows
    )
    dates = sorted({row["decision_index"] for row in rows})
    holdout_start = dates[math.ceil(.75 * len(dates))] if len(dates) >= 4 else None
    holdout_cutoff = (datetime.fromisoformat(next(row["decision_cutoff_utc"] for row in rows
                                             if row["decision_index"] == holdout_start))
                      if holdout_start is not None else None)
    predictions, fold_log = [], []
    for decision_index in dates:
        current = [row for row in rows if row["decision_index"] == decision_index]
        cutoff = datetime.fromisoformat(current[0]["decision_cutoff_utc"])
        training_asof = holdout_cutoff if holdout_start is not None and decision_index >= holdout_start else cutoff
        train_indices, purged = purged_training_indices(maturity_rows, decision_index,
                                                        panel["horizon"], training_asof)
        if holdout_start is not None and decision_index >= holdout_start:
            train_indices = [index for index in train_indices if rows[index]["decision_index"] < holdout_start]
        if rolling_window_sessions is not None:
            window_anchor = holdout_start if holdout_start is not None and decision_index >= holdout_start else decision_index
            train_indices = [index for index in train_indices
                             if rows[index]["decision_index"] >= window_anchor - rolling_window_sessions]
        train = [rows[index] for index in train_indices]
        trained_dates = {row["decision_index"] for row in train}
        if len(train) < min_train_rows or len(trained_dates) < min_train_sessions:
            fold_log.append({"decision_index": decision_index, "status": "INSUFFICIENT_MATURED_TRAINING_LABELS",
                             "training_rows": len(train), "training_sessions": len(trained_dates), "purged_rows": len(purged)})
            continue
        y_return = np.array([float(row["gross_return"]) for row in train], dtype=float)
        y_direction = np.array([float(row["net_return_10bps"] > 0) for row in train], dtype=float)
        output_rows = [{**row, "predictions": {}} for row in current]
        for variant in AGGREGATION_VARIANTS:
            for branch, include_events in (("price", False), ("price_news", True)):
                x_train = np.array([_features(row, include_events, variant) for row in train], dtype=float)
                x_test = np.array([_features(row, include_events, variant) for row in current], dtype=float)
                probability = _fit_predict_logistic(x_train, y_direction, x_test)
                expected = _fit_predict_ridge(x_train, y_return, x_test)
                for row, p, mean in zip(output_rows, probability, expected):
                    row["predictions"].setdefault(variant, {})[branch] = {
                        "probability_positive_net": float(p), "expected_gross_return": float(mean)}
        predictions.extend(output_rows)
        fold_log.append({"decision_index": decision_index, "status": "EVALUATED",
                         "training_rows": len(train), "training_sessions": len(trained_dates),
                         "purged_rows": len(purged), "max_training_decision_index": max(trained_dates),
                         "holdout": holdout_start is not None and decision_index >= holdout_start})
    tiers = {tier for row in rows for tier in row["feature_provenance_tiers"]}
    if retrospective_replay and rows:
        tiers.add("RETROSPECTIVE_DIAGNOSTIC_REPLAY")
    temporal_ok = not any(tier.startswith("RETROSPECTIVE_") for tier in tiers)
    verdict = provenance_verdict(tiers, temporal_ok, execution_open_observed=False)
    if not predictions and verdict["report_validity_tier"] == "PIT_COMPLIANT_RESEARCH_RUN":
        verdict["actionability_reason"] = "INSUFFICIENT_OOS_FOLDS"
    metrics = {}
    for variant in AGGREGATION_VARIANTS:
        metrics[variant] = {}
        for subset, selected in (("all", predictions),
                                 ("active_event", [row for row in predictions if row["event_features"]["has_valid_event"]]),
                                 ("scored_event", [row for row in predictions if row["event_features"]["scored_cluster_count"] > 0]),
                                 ("temporal_holdout", [row for row in predictions if holdout_start is not None and row["decision_index"] >= holdout_start]),
                                 ("holdout_scored_event", [row for row in predictions if holdout_start is not None and row["decision_index"] >= holdout_start and row["event_features"]["scored_cluster_count"] > 0]),
                                 ("holdout_active_event", [row for row in predictions if holdout_start is not None and row["decision_index"] >= holdout_start and row["event_features"]["has_valid_event"]])):
            metrics[variant][subset] = {**_paired_comparison(selected, variant),
                                        "block_bootstrap": _moving_block_ci(selected, variant, panel["horizon"],
                                                                            bootstrap_repetitions, random_seed)}
    economic = _portfolio_diagnostics(predictions, panel["horizon"], bootstrap_repetitions, random_seed)
    holdout_active_rows = [row for row in predictions if holdout_start is not None
                           and row["decision_index"] >= holdout_start and row["event_features"]["has_valid_event"]]
    holdout_economic = _portfolio_diagnostics(holdout_active_rows, panel["horizon"], bootstrap_repetitions, random_seed)
    primary_holdout = metrics[PRIMARY_VARIANT]["holdout_active_event"]
    brier_ci = primary_holdout["block_bootstrap"]["delta_95ci"]["brier"]
    net_holdout = holdout_economic["cost_scenarios"]["10"]["branches"]["price_news"]
    net_ci = net_holdout["mean_net_return_95ci_block_bootstrap"]
    preliminary = {"holdout_active_event_brier_improved": primary_holdout["delta_news_minus_price"]["brier"] is not None and primary_holdout["delta_news_minus_price"]["brier"] < 0,
                   "holdout_active_event_brier_ci_upper_below_zero": brier_ci is not None and brier_ci[1] < 0,
                   "holdout_active_news_basket_mean_net_10bps_positive": (net_holdout["mean_net_return_per_period"] or 0) > 0,
                   "holdout_active_news_basket_net_10bps_ci_lower_above_zero": net_ci is not None and net_ci[0] > 0}
    sensitivity = [row["close_next_to_exit_gross_return"] - row["gross_return"] for row in predictions
                   if row.get("close_next_to_exit_gross_return") is not None]
    report = {"feature": "equara-us-phase3-walk-forward-v1", "panel_sha256": panel["panel_sha256"],
              "horizon": panel["horizon"], "primary_horizon": PRIMARY_HORIZON,
              "primary_variant": PRIMARY_VARIANT, "variants": list(AGGREGATION_VARIANTS),
              "model_spec": {"logistic_l2": LOGISTIC_L2, "ridge_l2": RIDGE_L2,
                             "standardization": "training_fold_only", "target_binary": "net_return_after_10bps_one_way_positive",
                             "target_regression": "gross_adjusted_bar_return_proxy"},
              "walk_forward": {"min_train_sessions": min_train_sessions, "min_train_rows": min_train_rows,
                               "rolling_window_sessions": rolling_window_sessions,
                               "holdout_start_decision_index": holdout_start,
                               "holdout_training_cutoff_utc": holdout_cutoff.isoformat() if holdout_cutoff else None,
                               "holdout_policy": "final_25_percent_decision_indices_training_and_labels_frozen_at_holdout_start",
                               "folds": fold_log, "evaluated_rows": len(predictions),
                               "purge_rule": "train_decision_index+horizon<=eval_index AND label_observed_by_eval_cutoff",
                               "label_maturity_policy": ("HYPOTHETICAL_EXIT_SESSION_20_ET_EX_POST_DIAGNOSTIC"
                                                         if retrospective_replay else "ACTUAL_LEDGER_OBSERVATION_TIME")},
              **verdict, "preliminary_gate_checks": preliminary,
              "research_performance_gate_passed": all(preliminary.values()),
              "signal_acceptance_gate_passed": verdict["report_validity_tier"] == "PIT_COMPLIANT_RESEARCH_RUN" and all(preliminary.values()),
              "actionability_status": "KEEP_DESCRIPTIVE_ONLY — FIVE_LABELS_REMAIN_EXPERIMENTAL",
              "predictive_metrics": metrics, "economic_diagnostics": economic,
              "holdout_active_event_economic_diagnostics": holdout_economic,
              "entry_price_sensitivity": {"alternative": "CLOSE_ADJ_NEXT_SESSION_TO_EXIT_CLOSE_PROXY",
                                          "n": len(sensitivity),
                                          "mean_alternative_minus_primary_gross_return": float(np.mean(sensitivity)) if sensitivity else None},
              "excluded_panel_records": panel["excluded"],
              "limitations": ["Adjusted daily-bar open/close returns are ex-post proxies, not documented execution fills",
                              *(["Diagnostic replay assumes labels at exit-session 20:00 ET; actual ledger observation timestamps remain later"]
                                if retrospective_replay else []),
                              "Linear two-way bps cost is an assumption, not measured spread or slippage",
                              "Nonoverlapping basket diagnostics fully liquidate each block and are not a live portfolio account",
                              "No action labels are released from this research runner"]}
    report["report_sha256"] = digest({key: value for key, value in report.items() if key != "report_sha256"})
    return report
