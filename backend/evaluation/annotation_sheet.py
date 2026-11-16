"""Human-editable blind CSV sheet and validated import to draft JSONL labels."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from backend.evaluation.annotation_schema import BlindAnnotationTaskItem, Human2DAnnotationRecord, read_jsonl, validate_tone_consistency
from backend.storage.pit_ledger import canonical

LABEL_FIELDS = ("annotator_id", "annotated_at_utc", "target_relevance", "textual_tone",
                "economic_implication", "event_category", "gold_event_cluster_key",
                "is_first_mention_in_cluster", "rationale_note", "is_adjudicated")


def prepare_annotation_sheet(tasks_path: str | Path, csv_path: str | Path, annotator_id: str) -> dict:
    if not annotator_id.strip():
        raise ValueError("ANNOTATOR_ID_REQUIRED")
    tasks = read_jsonl(tasks_path, BlindAnnotationTaskItem)
    if not tasks:
        raise ValueError("EMPTY_TASK_BATCH")
    target = Path(csv_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = list(BlindAnnotationTaskItem.model_fields) + list(LABEL_FIELDS)
    with target.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for task in tasks:
            row = task.model_dump(mode="json")
            row.update({field: "" for field in LABEL_FIELDS})
            row["annotator_id"] = annotator_id
            writer.writerow(row)
    return {"csv_path": str(target), "task_count": len(tasks), "annotator_id": annotator_id}


def import_annotation_sheet(tasks_path: str | Path, csv_path: str | Path, draft_path: str | Path,
                            allow_partial: bool = False) -> dict:
    tasks = read_jsonl(tasks_path, BlindAnnotationTaskItem)
    if not tasks:
        raise ValueError("EMPTY_TASK_BATCH")
    by_id = {task.task_id: task for task in tasks}
    now = datetime.now(timezone.utc).isoformat()
    labels = []
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = set(BlindAnnotationTaskItem.model_fields) | set(LABEL_FIELDS)
        if not required <= set(reader.fieldnames or []):
            raise ValueError("ANNOTATION_SHEET_COLUMNS_MISSING")
        for index, row in enumerate(reader, 2):
            task = by_id.get(row["task_id"])
            if task is None or any((row[field] or "") != (str(getattr(task, field)) if getattr(task, field) is not None else "")
                                   for field in ("observation_id", "item_id", "ticker", "session_window_id", "headline")):
                raise ValueError(f"ANNOTATION_SHEET_TASK_MISMATCH_LINE_{index}")
            first = row["is_first_mention_in_cluster"].strip().lower()
            if first not in {"", "true", "false"}:
                raise ValueError(f"INVALID_FIRST_MENTION_LINE_{index}")
            adjudicated = row["is_adjudicated"].strip().lower()
            if adjudicated not in {"", "true", "false"}:
                raise ValueError(f"INVALID_ADJUDICATION_FLAG_LINE_{index}")
            labels.append(Human2DAnnotationRecord(
                task_id=task.task_id, observation_id=task.observation_id, item_id=task.item_id,
                ticker=task.ticker, session_window_id=task.session_window_id,
                annotator_id=row["annotator_id"].strip(),
                annotated_at_utc=row["annotated_at_utc"].strip() or now,
                target_relevance=row["target_relevance"].strip(),
                textual_tone=row["textual_tone"].strip() or None,
                economic_implication=row["economic_implication"].strip(),
                event_category=row["event_category"].strip(),
                gold_event_cluster_key=row["gold_event_cluster_key"].strip() or None,
                is_first_mention_in_cluster=None if not first else first == "true",
                rationale_note=row["rationale_note"].strip() or None,
                is_adjudicated=adjudicated == "true"))
    if not labels or (not allow_partial and ({label.task_id for label in labels} != set(by_id) or len(labels) != len(tasks))):
        raise ValueError("ANNOTATION_SHEET_TASK_COUNT_MISMATCH")
    if len({label.task_id for label in labels}) != len(labels):
        raise ValueError("DUPLICATE_TASK_IN_SHEET")
    if len({label.annotator_id for label in labels}) != 1:
        raise ValueError("ONE_ANNOTATOR_PER_SHEET_REQUIRED")
    validate_tone_consistency(tasks, labels)
    target = Path(draft_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        for label in labels:
            handle.write(canonical(label.model_dump(mode="json")) + "\n")
    return {"draft_path": str(target), "record_count": len(labels),
            "annotator_id": labels[0].annotator_id if labels else None}
