"""Blind task and locked human-label contracts for the US research benchmark."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.storage.pit_ledger import canonical

Tone = Literal["POSITIVE", "NEUTRAL", "NEGATIVE"]
Implication = Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "AMBIGUOUS_MIXED", "NOT_APPLICABLE"]
Relevance = Literal["DIRECT_COMPANY_EVENT", "SECTOR_MACRO_SPILLOVER", "INCIDENTAL_OR_NOISE", "UNSCORABLE_ADMIN_FILING"]
Category = Literal["EARNINGS_GUIDANCE", "MA_RESTRUCTURING", "PRODUCT_CONTRACT", "REGULATORY_LEGAL",
                   "MANAGEMENT_GOVERNANCE", "ANALYST_RATING", "MACRO_SECTOR", "OTHER"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BlindAnnotationTaskItem(StrictModel):
    task_id: str = Field(min_length=1)
    observation_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    session_window_id: str = Field(min_length=1)
    headline: str = Field(min_length=1)
    item_type: Literal["NEWS_HEADLINE", "PRESS_RELEASE", "SEC_FILING"]
    source_name: str
    source_url: str | None = None
    published_at_utc: datetime
    ingested_at_utc: datetime
    publication_time_basis: str | None = None
    source_filing_date: str | None = None

    @field_validator("published_at_utc", "ingested_at_utc")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("TIMEZONE_REQUIRED")
        return value


class Human2DAnnotationRecord(StrictModel):
    task_id: str = Field(min_length=1)
    observation_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    session_window_id: str = Field(min_length=1)
    annotator_id: str = Field(min_length=1)
    annotated_at_utc: datetime
    target_relevance: Relevance
    textual_tone: Tone | None
    economic_implication: Implication
    event_category: Category
    gold_event_cluster_key: str | None = None
    is_first_mention_in_cluster: bool | None = None
    rationale_note: str | None = None
    is_adjudicated: bool = False

    @field_validator("annotated_at_utc")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("TIMEZONE_REQUIRED")
        return value

    @model_validator(mode="after")
    def validate_semantics(self):
        if self.target_relevance == "UNSCORABLE_ADMIN_FILING":
            if self.textual_tone is not None or self.economic_implication != "NOT_APPLICABLE":
                raise ValueError("ADMIN_FILING_MUST_BE_UNSCORED")
        elif self.textual_tone is None:
            raise ValueError("TEXTUAL_TONE_REQUIRED")
        relevant = self.target_relevance in {"DIRECT_COMPANY_EVENT", "SECTOR_MACRO_SPILLOVER"}
        if relevant and (self.economic_implication == "NOT_APPLICABLE" or not self.gold_event_cluster_key):
            raise ValueError("RELEVANT_ITEM_NEEDS_IMPLICATION_AND_EVENT_KEY")
        if not relevant and (self.economic_implication != "NOT_APPLICABLE" or self.gold_event_cluster_key):
            raise ValueError("IRRELEVANT_ITEM_MUST_BE_NOT_APPLICABLE")
        if self.textual_tone is not None and self.economic_implication not in {"NOT_APPLICABLE", self.textual_tone}:
            if not self.rationale_note or not self.rationale_note.strip():
                raise ValueError("DIVERGENCE_RATIONALE_REQUIRED")
        return self


class LockedAnnotationDatasetManifest(StrictModel):
    dataset_id: str = Field(min_length=1)
    created_at_utc: datetime
    split_type: Literal["CALIBRATION_DEV", "LOCKED_HOLDOUT"]
    annotator_ids: list[str] = Field(min_length=1)
    record_count: int = Field(ge=1)
    task_batch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    records_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rubric_version: str = "us-2d-v1"

    @field_validator("created_at_utc")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("TIMEZONE_REQUIRED")
        return value


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_jsonl(path: str | Path, model: type[StrictModel]) -> list:
    rows = []
    for index, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(model.model_validate_json(line))
            except Exception as exc:
                raise ValueError(f"INVALID_JSONL_LINE_{index}: {exc}") from exc
    return rows


def _validate_task_bindings(tasks: list[BlindAnnotationTaskItem], labels: list[Human2DAnnotationRecord]) -> None:
    by_id = {task.task_id: task for task in tasks}
    if len(by_id) != len(tasks) or not tasks:
        raise ValueError("DUPLICATE_OR_EMPTY_TASKS")
    seen = set()
    for label in labels:
        task = by_id.get(label.task_id)
        if task is None or (task.observation_id, task.item_id, task.ticker, task.session_window_id) != (
            label.observation_id, label.item_id, label.ticker, label.session_window_id):
            raise ValueError("LABEL_TASK_BINDING_MISMATCH")
        key = label.task_id, label.annotator_id
        if key in seen:
            raise ValueError("DUPLICATE_ANNOTATOR_TASK")
        seen.add(key)
    if {label.task_id for label in labels} != set(by_id):
        raise ValueError("UNLABELED_TASKS")
    validate_tone_consistency(tasks, labels)


def validate_tone_consistency(tasks: list[BlindAnnotationTaskItem], labels: list[Human2DAnnotationRecord]) -> None:
    by_id = {task.task_id: task for task in tasks}
    seen = {}
    for label in labels:
        task = by_id[label.task_id]
        if task.item_type == "SEC_FILING" or label.textual_tone is None:
            continue
        if label.is_adjudicated and label.rationale_note and label.rationale_note.strip():
            continue
        key = (label.annotator_id, task.headline.strip().casefold())
        if key in seen and seen[key] != label.textual_tone:
            raise ValueError("TONE_INCONSISTENCY_ON_IDENTICAL_HEADLINE")
        seen[key] = label.textual_tone


def lock_gold_labels(tasks_path: str | Path, draft_labels_path: str | Path | list[str | Path],
                     locked_labels_path: str | Path, manifest_path: str | Path,
                     dataset_id: str, split_type: Literal["CALIBRATION_DEV", "LOCKED_HOLDOUT"]) -> LockedAnnotationDatasetManifest:
    """Write-once files; hash binds exact task bytes and validated label bytes."""
    tasks = read_jsonl(tasks_path, BlindAnnotationTaskItem)
    draft_paths = draft_labels_path if isinstance(draft_labels_path, list) else [draft_labels_path]
    labels = [row for path in draft_paths for row in read_jsonl(path, Human2DAnnotationRecord)]
    _validate_task_bindings(tasks, labels)
    output = "".join(canonical(row.model_dump(mode="json")) + "\n" for row in sorted(labels, key=lambda x: (x.task_id, x.annotator_id)))
    manifest = LockedAnnotationDatasetManifest(
        dataset_id=dataset_id, created_at_utc=datetime.now(timezone.utc), split_type=split_type,
        annotator_ids=sorted({row.annotator_id for row in labels}), record_count=len(labels),
        task_batch_sha256=file_sha256(tasks_path), records_sha256=hashlib.sha256(output.encode("utf-8")).hexdigest())
    target, metadata = Path(locked_labels_path), Path(manifest_path)
    if target.exists() or metadata.exists():
        raise FileExistsError("LOCKED_DATASET_ALREADY_EXISTS")
    target.parent.mkdir(parents=True, exist_ok=True)
    metadata.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(output)
    with metadata.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical(manifest.model_dump(mode="json")) + "\n")
    return manifest


def load_locked_labels(tasks_path: str | Path, locked_labels_path: str | Path,
                       manifest_path: str | Path) -> tuple[list[BlindAnnotationTaskItem], list[Human2DAnnotationRecord], LockedAnnotationDatasetManifest]:
    manifest = LockedAnnotationDatasetManifest.model_validate_json(Path(manifest_path).read_text(encoding="utf-8"))
    if file_sha256(tasks_path) != manifest.task_batch_sha256 or file_sha256(locked_labels_path) != manifest.records_sha256:
        raise ValueError("LOCKED_DATASET_HASH_MISMATCH")
    tasks = read_jsonl(tasks_path, BlindAnnotationTaskItem)
    labels = read_jsonl(locked_labels_path, Human2DAnnotationRecord)
    _validate_task_bindings(tasks, labels)
    if len(labels) != manifest.record_count or sorted({x.annotator_id for x in labels}) != manifest.annotator_ids:
        raise ValueError("LOCKED_DATASET_MANIFEST_MISMATCH")
    return tasks, labels, manifest
