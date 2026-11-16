"""Locked 2D sentiment and event-clustering benchmark; no return prediction claims."""
from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
from math import comb, isfinite
from pathlib import Path
import re

from backend.config import DEFAULT_LOCAL_MODEL_REVISION, MODEL_ID
from backend.evaluation.annotation_schema import (
    BlindAnnotationTaskItem, Human2DAnnotationRecord, LockedAnnotationDatasetManifest,
    load_locked_labels,
)
from backend.evaluation.inter_annotator_agreement import inter_annotator_agreement
from backend.evaluation.lexicon_baseline import LABELS, VERSION, predict_lexicon
from backend.services.event_clustering import cluster_events_v2
from backend.storage.pit_ledger import PitLedger
from backend.universe.catalog import universe_by_ticker


def _resolve_gold(records: list[Human2DAnnotationRecord]) -> dict[str, Human2DAnnotationRecord]:
    by_task = defaultdict(list)
    for row in records:
        by_task[row.task_id].append(row)
    resolved = {}
    compared = ("target_relevance", "textual_tone", "economic_implication", "event_category", "gold_event_cluster_key")
    for task_id, rows in by_task.items():
        adjudicated = [row for row in rows if row.is_adjudicated]
        if len(adjudicated) > 1:
            raise ValueError(f"MULTIPLE_ADJUDICATIONS:{task_id}")
        if adjudicated:
            resolved[task_id] = adjudicated[0]
        elif all(tuple(getattr(row, key) for key in compared) == tuple(getattr(rows[0], key) for key in compared) for row in rows[1:]):
            resolved[task_id] = rows[0]
        else:
            raise ValueError(f"UNRESOLVED_ANNOTATOR_DISAGREEMENT:{task_id}")
    return resolved


def _is_economic_eligible(row: Human2DAnnotationRecord) -> bool:
    return row.target_relevance in {"DIRECT_COMPANY_EVENT", "SECTOR_MACRO_SPILLOVER"} and row.economic_implication in LABELS


def majority_from_dev(records: list[Human2DAnnotationRecord]) -> dict[str, str]:
    gold = _resolve_gold(records)
    tone = Counter(row.textual_tone for row in gold.values() if row.textual_tone in LABELS)
    implication = Counter(row.economic_implication for row in gold.values() if _is_economic_eligible(row))
    if not tone or not implication:
        raise ValueError("DEV_SET_MISSING_TRACK_LABELS")
    preference = {"NEUTRAL": 0, "POSITIVE": 1, "NEGATIVE": 2}
    select = lambda counts: sorted(LABELS, key=lambda label: (-counts[label], preference[label]))[0]
    return {"textual_tone": select(tone), "economic_implication": select(implication)}


def _hard_prediction(label: str) -> dict:
    return {"label": label, "probabilities": {name: float(name == label) for name in LABELS}}


def classification_metrics(rows: list[tuple[str, dict]], ece_bins: int = 5) -> dict:
    """Rows are (gold label, {label, probabilities}); ECE uses max-class confidence."""
    if ece_bins < 2:
        raise ValueError("ECE_BINS_TOO_SMALL")
    matrix = {gold: {pred: 0 for pred in LABELS} for gold in LABELS}
    valid = []
    for gold, prediction in rows:
        pred = prediction["label"]
        probabilities = prediction["probabilities"]
        if gold not in LABELS or pred not in LABELS or set(probabilities) != set(LABELS):
            raise ValueError("INVALID_BENCHMARK_LABEL_OR_PROBABILITIES")
        values = [float(probabilities[label]) for label in LABELS]
        if any(not isfinite(value) or value < 0 or value > 1 for value in values) or abs(sum(values) - 1) > 1e-5:
            raise ValueError("INVALID_BENCHMARK_PROBABILITIES")
        matrix[gold][pred] += 1
        valid.append((gold, pred, probabilities))
    n = len(valid)
    per_class = {}
    for label in LABELS:
        tp = matrix[label][label]
        support = sum(matrix[label].values())
        predicted = sum(matrix[actual][label] for actual in LABELS)
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"support": support, "precision": precision, "recall": recall, "f1": f1}
    severe = matrix["POSITIVE"]["NEGATIVE"] + matrix["NEGATIVE"]["POSITIVE"]
    brier = sum(sum((float(probs[label]) - float(gold == label)) ** 2 for label in LABELS)
                for gold, _, probs in valid) / n if n else None
    buckets = defaultdict(list)
    for gold, pred, probs in valid:
        confidence = max(float(value) for value in probs.values())
        index = min(int(confidence * ece_bins), ece_bins - 1)
        buckets[index].append((confidence, float(gold == pred)))
    ece = sum(len(bucket) / n * abs(sum(x for x, _ in bucket) / len(bucket) - sum(y for _, y in bucket) / len(bucket))
              for bucket in buckets.values()) if n else None
    return {"n": n, "status": "OK" if n else "NO_SCORED_ITEMS", "label_order": list(LABELS),
            "confusion_matrix": matrix, "per_class": per_class,
            "macro_f1": sum(row["f1"] for row in per_class.values()) / 3 if n else None,
            "directional_error_count": severe, "directional_error_rate": severe / n if n else None,
            "multiclass_brier": brier, "ece": ece, "ece_bins": ece_bins}


def pairwise_cluster_metrics(gold: dict[str, str], predicted: dict[str, str], scope: dict[str, str]) -> dict:
    if set(gold) != set(predicted) or set(gold) != set(scope):
        raise ValueError("CLUSTER_ITEM_SET_MISMATCH")
    tp = fp = fn = tn = 0
    for a, b in combinations(sorted(gold), 2):
        if scope[a] != scope[b]:
            continue
        same_gold = gold[a] == gold[b]
        same_pred = predicted[a] == predicted[b]
        if same_gold and same_pred: tp += 1
        elif same_pred: fp += 1
        elif same_gold: fn += 1
        else: tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"eligible_items": len(gold), "eligible_pairs": tp + fp + fn + tn,
            "true_merge_pairs": tp, "false_merge_pairs": fp, "false_split_pairs": fn, "true_split_pairs": tn,
            "pairwise_precision": precision, "pairwise_recall": recall, "pairwise_f1": f1,
            "false_merge_rate_among_predicted_merges": fp / (tp + fp) if tp + fp else None,
            "false_split_rate_among_gold_merges": fn / (tp + fn) if tp + fn else None}


def _adjusted_rand_index(gold: list[str], predicted: list[str]) -> float | None:
    n = len(gold)
    if n < 2:
        return None
    contingency = Counter(zip(gold, predicted))
    gold_counts, pred_counts = Counter(gold), Counter(predicted)
    sum_both = sum(comb(value, 2) for value in contingency.values())
    sum_gold = sum(comb(value, 2) for value in gold_counts.values())
    sum_pred = sum(comb(value, 2) for value in pred_counts.values())
    expected = sum_gold * sum_pred / comb(n, 2)
    maximum = (sum_gold + sum_pred) / 2
    if maximum == expected:
        same_partition = all((gold[a] == gold[b]) == (predicted[a] == predicted[b]) for a, b in combinations(range(n), 2))
        return 1.0 if same_partition else 0.0
    return (sum_both - expected) / (maximum - expected)


def _cluster_audit(tasks: list[BlindAnnotationTaskItem], gold: dict[str, Human2DAnnotationRecord],
                   raw_by_observation: dict[str, dict]) -> dict:
    chosen = [task for task in tasks if gold[task.task_id].gold_event_cluster_key]
    by_scope = defaultdict(list)
    for task in chosen:
        by_scope[task.ticker].append(task)
    actual, predicted, scope = {}, {}, {}
    ari = []
    universe = universe_by_ticker()
    for ticker, group in sorted(by_scope.items()):
        if any(task.ticker != ticker for task in group):
            raise ValueError("MIXED_TICKERS_IN_WINDOW")
        payload = []
        for task in group:
            raw = raw_by_observation.get(task.observation_id)
            if raw is None or raw["item_id"] != task.item_id or raw["ticker"] != task.ticker:
                raise ValueError("RAW_OBSERVATION_MISMATCH")
            payload.append({"item_id": task.task_id, "ticker": task.ticker,
                            "headline": task.headline, "item_type": task.item_type,
                            "published_at_utc": task.published_at_utc.isoformat(),
                            "ingested_at_utc": task.ingested_at_utc.isoformat(),
                            "external_event_key": raw["external_event_key"]})
        aliases = {ticker: [universe[ticker]["company_name"], *universe[ticker].get("aliases", []), ticker]}
        clusters = cluster_events_v2(payload, aliases)
        for index, cluster in enumerate(clusters):
            for task_id in cluster["item_ids"]:
                predicted[task_id] = f"{ticker}:K{index}"
        for task in group:
            actual[task.task_id] = f"{ticker}:{gold[task.task_id].gold_event_cluster_key}"
            scope[task.task_id] = ticker
        if len(group) >= 2:
            ordered = sorted(group, key=lambda task: task.task_id)
            score = _adjusted_rand_index([actual[x.task_id] for x in ordered], [predicted[x.task_id] for x in ordered])
            if score is not None:
                ari.append(score)
    output = pairwise_cluster_metrics(actual, predicted, scope)
    output["macro_adjusted_rand_index"] = sum(ari) / len(ari) if ari else None
    output["ari_tickers"] = len(ari)
    output["comparison_scope"] = "ticker_across_all_session_windows"
    return output


def evaluate_locked_benchmark(tasks_path: str | Path, labels_path: str | Path,
                              manifest_path: str | Path, ledger: PitLedger,
                              dev_locked: tuple[str | Path, str | Path, str | Path] | None = None,
                              model_id: str = MODEL_ID,
                              model_revision: str = DEFAULT_LOCAL_MODEL_REVISION) -> dict:
    tasks, records, manifest = load_locked_labels(tasks_path, labels_path, manifest_path)
    return evaluate_reference_records(tasks, records, manifest, ledger, dev_locked, model_id, model_revision)


def evaluate_reference_records(tasks, records, manifest, ledger, dev_locked=None,
                               model_id=MODEL_ID, model_revision=DEFAULT_LOCAL_MODEL_REVISION,
                               majority_override=None):
    """Evaluate already validated records; caller owns provenance and split claims."""
    gold = _resolve_gold(records)
    if majority_override is not None:
        majority = majority_override
    elif manifest.split_type == "LOCKED_HOLDOUT":
        if manifest.task_batch_sha256 in {
            '35a781cabb8c23c81950659c1b8d702db8a4fc0f69f5c31ba509fcbd9db69614',
            '729c26b19f8eed26d844750543fdab2e171fe8cdf474b7cc826ed44992247395',
        }:
            raise ValueError('KNOWN_HOLDOUT_EVENT_LEAKAGE')
        if dev_locked is None:
            raise ValueError("HOLDOUT_REQUIRES_LOCKED_DEV_BASELINE")
        dev_tasks, dev_records, dev_manifest = load_locked_labels(*dev_locked)
        if dev_manifest.split_type != "CALIBRATION_DEV":
            raise ValueError("BASELINE_SOURCE_MUST_BE_DEV")
        if {task.item_id for task in tasks} & {task.item_id for task in dev_tasks}:
            raise ValueError("DEV_HOLDOUT_ITEM_LEAKAGE")
        news_titles = lambda group: {task.headline.strip().casefold() for task in group
                                     if task.item_type != "SEC_FILING"}
        if news_titles(tasks) & news_titles(dev_tasks):
            raise ValueError("DEV_HOLDOUT_HEADLINE_LEAKAGE")
        majority = majority_from_dev(dev_records)
    else:
        majority = majority_from_dev(records)
    raw_rows = {row["observation_id"]: row for row in ledger.rows("raw_news_events")}
    scores = {}
    for row in ledger.rows("sentiment_scores"):
        if row["model_id"] != model_id or row["model_revision"] != model_revision or row["scoring_status"] != "SCORED":
            continue
        old = scores.get(row["observation_id"])
        if old is None or (row["scored_at_utc"], row["score_id"]) > (old["scored_at_utc"], old["score_id"]):
            scores[row["observation_id"]] = row
    for task in tasks:
        raw = raw_rows.get(task.observation_id)
        if raw is None or (raw["item_id"], raw["ticker"], raw["headline"]) != (task.item_id, task.ticker, task.headline):
            raise ValueError("TASK_LEDGER_BINDING_MISMATCH")
    tracks = {"textual_tone": {}, "economic_implication": {}}
    eligible = {"textual_tone": [task for task in tasks if gold[task.task_id].textual_tone in LABELS],
                "economic_implication": [task for task in tasks if _is_economic_eligible(gold[task.task_id])]}
    for track, candidates in eligible.items():
        for method in ("finbert", "lexicon", "majority"):
            rows = []
            for task in candidates:
                label = getattr(gold[task.task_id], track)
                if method == "finbert":
                    score = scores.get(task.observation_id)
                    if score is None:
                        continue
                    probabilities = {"POSITIVE": score["p_pos"], "NEUTRAL": score["p_neu"], "NEGATIVE": score["p_neg"]}
                    prediction = {"label": max(LABELS, key=lambda name: probabilities[name]), "probabilities": probabilities}
                elif method == "lexicon":
                    prediction = predict_lexicon(task.headline)
                    prediction["probabilities"] = {key.upper(): value for key, value in prediction["probabilities"].items()}
                else:
                    prediction = _hard_prediction(majority[track])
                rows.append((label, prediction))
            tracks[track][method] = classification_metrics(rows)
            tracks[track][method]["eligible_count"] = len(candidates)
            tracks[track][method]["prediction_coverage"] = len(rows) / len(candidates) if candidates else None
        tracks[track]["baseline_probability_policy"] = "hard_one_hot; not calibrated probabilities"
    unique_groups = defaultdict(list)
    for task in eligible['textual_tone']:
        if task.item_type != 'SEC_FILING':
            unique_groups[' '.join(re.findall(r'\w+', task.headline.casefold()))].append(task)
    unique_metrics = {}
    for method in ('finbert', 'lexicon', 'majority'):
        unique_rows = []
        for group in unique_groups.values():
            labels = {gold[t.task_id].textual_tone for t in group}
            if len(labels) != 1:
                raise ValueError('CONFLICTING_GOLD_TONE_ON_IDENTICAL_HEADLINE')
            task = min(group, key=lambda t: t.task_id)
            if method == 'finbert':
                score = scores.get(task.observation_id)
                if score is None:
                    continue
                probabilities = {'POSITIVE': score['p_pos'], 'NEUTRAL': score['p_neu'], 'NEGATIVE': score['p_neg']}
                prediction = {'label': max(LABELS, key=lambda name: probabilities[name]), 'probabilities': probabilities}
            elif method == 'lexicon':
                prediction = predict_lexicon(task.headline)
                prediction['probabilities'] = {k.upper(): v for k, v in prediction['probabilities'].items()}
            else:
                prediction = _hard_prediction(majority['textual_tone'])
            unique_rows.append((next(iter(labels)), prediction))
        unique_metrics[method] = classification_metrics(unique_rows)
        unique_metrics[method]['eligible_count'] = len(unique_groups)
    divergence_cases = []
    by_category = defaultdict(lambda: {"eligible": 0, "divergent": 0})
    for task in eligible["economic_implication"]:
        label = gold[task.task_id]
        category = by_category[label.event_category]
        category["eligible"] += 1
        if label.textual_tone != label.economic_implication:
            category["divergent"] += 1
            score = scores.get(task.observation_id)
            prediction = None if score is None else max(LABELS, key=lambda name: {
                "POSITIVE": score["p_pos"], "NEUTRAL": score["p_neu"], "NEGATIVE": score["p_neg"]}[name])
            divergence_cases.append({"task_id": task.task_id, "item_id": task.item_id, "ticker": task.ticker,
                                     "event_category": label.event_category, "textual_tone": label.textual_tone,
                                     "economic_implication": label.economic_implication,
                                     "finbert_prediction": prediction,
                                     "finbert_wrong_on_implication": prediction != label.economic_implication if prediction else None})
    for row in by_category.values():
        row["divergence_rate"] = row["divergent"] / row["eligible"] if row["eligible"] else None
    scored_divergent = [row for row in divergence_cases if row["finbert_wrong_on_implication"] is not None]
    annotators = sorted({row.annotator_id for row in records if not row.is_adjudicated})
    agreement = [inter_annotator_agreement(records, a, b) for a, b in combinations(annotators, 2)]
    return {"dataset_id": manifest.dataset_id, "split_type": manifest.split_type,
            "task_batch_sha256": manifest.task_batch_sha256, "records_sha256": manifest.records_sha256,
            "model_id": model_id, "model_revision": model_revision,
            "baseline_majority_from": "locked_dev" if manifest.split_type == "LOCKED_HOLDOUT" else "same_dev_set",
            "majority_classes": majority, "lexicon_version": VERSION,
            "total_tasks": len(tasks), "resolved_gold_count": len(gold),
            "effective_coverage": {"unit": "ticker_item_annotation_tasks",
                                   "textual_tone": len(eligible["textual_tone"]) / len(tasks),
                                   "economic_implication": len(eligible["economic_implication"]) / len(tasks),
                                   "incidental_or_noise": sum(row.target_relevance == "INCIDENTAL_OR_NOISE" for row in gold.values()),
                                   "unscorable_admin_filing": sum(row.target_relevance == "UNSCORABLE_ADMIN_FILING" for row in gold.values()),
                                   "ambiguous_mixed": sum(row.economic_implication == "AMBIGUOUS_MIXED" for row in gold.values())},
            "tracks": tracks, "track_a_unique_headlines": unique_metrics, "tone_implication_divergence_cases": divergence_cases,
            "divergence_by_category": dict(sorted(by_category.items())),
            "finbert_implication_error_rate_on_divergence": sum(row["finbert_wrong_on_implication"] for row in scored_divergent) / len(scored_divergent) if scored_divergent else None,
            "clustering": _cluster_audit(tasks, gold, raw_rows), "inter_annotator_agreement": agreement,
            "limitations": ["No trading-return or causal impact conclusion", "Small or skewed samples require uncertainty intervals before model claims",
                            "Unscored FinBERT rows reduce prediction coverage; never impute neutral"]}
