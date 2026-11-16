"""Agreement diagnostics before an adjudicated gold set is used for scoring."""
from __future__ import annotations

from collections import Counter

from backend.evaluation.annotation_schema import Human2DAnnotationRecord


def cohen_kappa(left: list[str | None], right: list[str | None]) -> dict:
    if len(left) != len(right):
        raise ValueError("PAIR_LENGTH_MISMATCH")
    n = len(left)
    if n == 0:
        return {"n": 0, "observed_agreement": None, "expected_agreement": None, "kappa": None}
    observed = sum(a == b for a, b in zip(left, right)) / n
    counts_a, counts_b = Counter(left), Counter(right)
    expected = sum(counts_a[label] * counts_b[label] for label in set(counts_a) | set(counts_b)) / (n * n)
    kappa = (observed - expected) / (1 - expected) if expected < 1 else (1.0 if observed == 1 else None)
    return {"n": n, "observed_agreement": observed, "expected_agreement": expected, "kappa": kappa}


def inter_annotator_agreement(records: list[Human2DAnnotationRecord],
                              annotator_a: str | None = None, annotator_b: str | None = None) -> dict:
    ids = sorted({record.annotator_id for record in records if not record.is_adjudicated})
    if annotator_a is None or annotator_b is None:
        if len(ids) != 2:
            raise ValueError("TWO_ANNOTATORS_REQUIRED_OR_SELECT_PAIR")
        annotator_a, annotator_b = ids
    by_task = {}
    for row in records:
        if row.annotator_id in {annotator_a, annotator_b} and not row.is_adjudicated:
            by_task.setdefault(row.task_id, {})[row.annotator_id] = row
    pairs = [(task_id, group[annotator_a], group[annotator_b]) for task_id, group in sorted(by_task.items())
             if annotator_a in group and annotator_b in group]
    tone_pairs = [(a, b) for _, a, b in pairs if a.textual_tone is not None and b.textual_tone is not None]
    implication_pairs = [(a, b) for _, a, b in pairs if a.economic_implication != "NOT_APPLICABLE" and b.economic_implication != "NOT_APPLICABLE"]
    tone = cohen_kappa([a.textual_tone for a, _ in tone_pairs], [b.textual_tone for _, b in tone_pairs])
    implication = cohen_kappa([a.economic_implication for a, _ in implication_pairs],
                              [b.economic_implication for _, b in implication_pairs])
    relevance = cohen_kappa([a.target_relevance for _, a, _ in pairs], [b.target_relevance for _, _, b in pairs])
    queue = [{"task_id": task_id, "item_id": a.item_id, "ticker": a.ticker,
              "disagreed_fields": [field for field in ("target_relevance", "textual_tone", "economic_implication",
                                                 "event_category", "gold_event_cluster_key")
                                   if getattr(a, field) != getattr(b, field)],
              "annotator_ids": [annotator_a, annotator_b]}
             for task_id, a, b in pairs]
    return {"annotators": [annotator_a, annotator_b], "paired_tasks": len(pairs),
            "target_relevance": relevance, "textual_tone": tone, "economic_implication": implication,
            "adjudication_queue": [row for row in queue if row["disagreed_fields"]],
            "unpaired_tasks": sorted(set(by_task) - {task_id for task_id, _, _ in pairs})}
