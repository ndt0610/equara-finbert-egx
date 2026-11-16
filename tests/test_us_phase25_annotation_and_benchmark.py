import asyncio
import csv
import json
from datetime import datetime, timezone

import httpx
import pytest
from pydantic import ValidationError

from backend.config import DEFAULT_LOCAL_MODEL_REVISION, MODEL_ID
from backend.evaluation.annotation_schema import (
    BlindAnnotationTaskItem, Human2DAnnotationRecord, file_sha256,
    load_locked_labels, lock_gold_labels,
)
from backend.evaluation.annotation_sheet import import_annotation_sheet, prepare_annotation_sheet
from backend.evaluation.benchmark_2d_runner import (
    _cluster_audit, classification_metrics, evaluate_locked_benchmark, pairwise_cluster_metrics,
)
from backend.evaluation.blind_export import export_blind_annotation_batch, split_blind_batch
from backend.evaluation.inter_annotator_agreement import inter_annotator_agreement
from backend.evaluation.lexicon_baseline import predict_lexicon
from backend.providers.us_market.us_price_adapter import AlpacaPriceAccessError, AlpacaPriceProvider
from backend.storage.pit_ledger import PitLedger, canonical
from scripts.run_us_phase25_benchmark import to_markdown

STAMP = "2026-11-13T20:00:00+00:00"


def make_label(task, annotator="a", tone="NEGATIVE", implication="NEGATIVE", **changes):
    values = dict(task_id=task.task_id, observation_id=task.observation_id,
                  item_id=task.item_id, ticker=task.ticker, session_window_id=task.session_window_id,
                  annotator_id=annotator, annotated_at_utc="2026-11-14T12:00:00+00:00",
                  target_relevance="DIRECT_COMPANY_EVENT", textual_tone=tone,
                  economic_implication=implication, event_category="OTHER",
                  gold_event_cluster_key=f"{task.ticker}:{task.item_id}",
                  is_first_mention_in_cluster=True,
                  rationale_note="Economic implication differs from headline tone" if tone != implication else None)
    values.update(changes)
    return Human2DAnnotationRecord(**values)


def make_task(db, run_id, item_id, headline, ticker="AAPL"):
    obs = db.add_news(run_id, {"item_id": item_id, "ticker": ticker, "headline": headline,
                               "source_name": "Test wire", "item_type": "NEWS_HEADLINE",
                               "published_at_utc": STAMP, "ingested_at_utc": STAMP})
    return BlindAnnotationTaskItem(task_id=f"task-{item_id}", observation_id=obs,
                                   item_id=item_id, ticker=ticker, session_window_id=f"{ticker}:2026-W46",
                                   headline=headline, item_type="NEWS_HEADLINE", source_name="Test wire",
                                   published_at_utc=STAMP, ingested_at_utc=STAMP)


def write_jsonl(path, records):
    path.write_text("".join(canonical(row.model_dump(mode="json")) + "\n" for row in records), encoding="utf-8")


def test_blind_export_contains_no_model_or_machine_cluster_fields(tmp_path):
    db = PitLedger(tmp_path / "ledger.sqlite3")
    rid = db.record_run("test", "LIVE_CAPTURED_PIT", "TEST_ONLY", {}, STAMP, STAMP)
    task = make_task(db, rid, "headline-1", "Apple raises guidance")
    db.add_score(task.observation_id, task.item_id, MODEL_ID, DEFAULT_LOCAL_MODEL_REVISION,
                 STAMP, "SCORED", {"positive": .8, "neutral": .1, "negative": .1})
    output = tmp_path / "blind.jsonl"
    result = export_blind_annotation_batch(db, output, "2026-11-13T21:00:00+00:00")
    exported = json.loads(output.read_text(encoding="utf-8").strip())
    forbidden = {"p_pos", "p_neu", "p_neg", "net_score", "predicted_label", "cluster_id", "external_event_key"}
    assert not (forbidden & exported.keys())
    assert exported["observation_id"] == task.observation_id
    assert result["batch_sha256"] == file_sha256(output)


def test_sec_blind_export_keeps_each_filing_date_and_excludes_old_or_future(tmp_path):
    db = PitLedger(tmp_path / "ledger.sqlite3")
    observed = "2026-11-14T19:00:00+00:00"
    rid = db.record_run("SEC EDGAR", "EXPLORATORY_RETROSPECTIVE_NON_PIT", "TEST_ONLY",
                        {}, observed, observed)
    cases = [("apple", "AAPL", "2026-11-02"),
             ("microsoft", "MSFT", "2026-10-29"),
             ("old", "NVDA", "2019-05-02"),
             ("future", "JPM", "2026-12-01")]
    for item_id, ticker, filing_day in cases:
        db.add_news(rid, {"item_id": item_id, "ticker": ticker,
                          "headline": "Form 8-K", "source_name": "SEC EDGAR",
                          "item_type": "SEC_FILING", "published_at_utc": observed,
                          "ingested_at_utc": observed, "source_filing_date": filing_day,
                          "publication_time_basis": "EQUARA_FIRST_OBSERVED_UPPER_BOUND"})
    output = tmp_path / "sec_batch.jsonl"
    export_blind_annotation_batch(db, output, "2026-11-14T20:00:00+00:00",
                                  include_structural=True, lookback_days=30)
    tasks = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert {task["item_id"]: task["source_filing_date"] for task in tasks} == {
        "apple": "2026-11-02", "microsoft": "2026-10-29"}


def test_divergent_label_requires_rationale(tmp_path):
    db = PitLedger(tmp_path / "ledger.sqlite3")
    rid = db.record_run("test", "LIVE_CAPTURED_PIT", "TEST_ONLY", {}, STAMP, STAMP)
    task = make_task(db, rid, "x", "Company cuts costs to lift margins")
    with pytest.raises(ValidationError, match="DIVERGENCE_RATIONALE_REQUIRED"):
        make_label(task, tone="NEGATIVE", implication="POSITIVE", rationale_note="")


def test_tone_implication_divergence_benchmark_on_ten_locked_items(tmp_path):
    db = PitLedger(tmp_path / "ledger.sqlite3")
    rid = db.record_run("test", "LIVE_CAPTURED_PIT", "TEST_ONLY", {}, STAMP, STAMP)
    tones = ["NEGATIVE"] * 4 + ["POSITIVE"] * 2 + ["NEGATIVE"] * 2 + ["NEUTRAL"] * 2
    implications = ["POSITIVE"] * 4 + tones[4:]
    tasks, labels = [], []
    for index, (tone, implication) in enumerate(zip(tones, implications)):
        headline = f"Company event {index}: " + ("cuts costs" if index < 4 else "market update")
        task = make_task(db, rid, f"item-{index}", headline)
        tasks.append(task)
        labels.append(make_label(task, tone=tone, implication=implication,
                                 event_category="MA_RESTRUCTURING" if index < 4 else "OTHER"))
        p = {"positive": float(tone == "POSITIVE"), "neutral": float(tone == "NEUTRAL"),
             "negative": float(tone == "NEGATIVE")}
        db.add_score(task.observation_id, task.item_id, MODEL_ID, DEFAULT_LOCAL_MODEL_REVISION,
                     STAMP, "SCORED", p)
    duplicate = make_task(db, rid, 'duplicate-cross-ticker', tasks[0].headline, 'MSFT')
    tasks.append(duplicate)
    labels.append(make_label(duplicate, tone='NEGATIVE', implication='NEGATIVE'))
    db.add_score(duplicate.observation_id, duplicate.item_id, MODEL_ID, DEFAULT_LOCAL_MODEL_REVISION,
                 STAMP, 'SCORED', {'positive': 0., 'neutral': 0., 'negative': 1.})
    tasks_path, draft = tmp_path / "tasks.jsonl", tmp_path / "draft.jsonl"
    locked, manifest = tmp_path / "locked_gold_labels.jsonl", tmp_path / "gold_manifest.json"
    write_jsonl(tasks_path, tasks)
    write_jsonl(draft, labels)
    lock_gold_labels(tasks_path, draft, locked, manifest, "test-ten", "CALIBRATION_DEV")
    report = evaluate_locked_benchmark(tasks_path, locked, manifest, db)
    assert report["tracks"]["textual_tone"]["finbert"]["macro_f1"] == 1.0
    assert report["tracks"]["textual_tone"]["finbert"]["n"] == 11
    assert report["track_a_unique_headlines"]["finbert"]["n"] == 10
    assert report["tracks"]["economic_implication"]["finbert"]["macro_f1"] < .75
    assert {row["item_id"] for row in report["tone_implication_divergence_cases"]} == {f"item-{i}" for i in range(4)}
    assert report["divergence_by_category"]["MA_RESTRUCTURING"]["divergence_rate"] == 1.0
    assert report["finbert_implication_error_rate_on_divergence"] == 1.0
    assert "Event clustering" in to_markdown(report)


def test_pairwise_precision_recall_and_f1():
    gold = dict(zip("abcd", ["C1", "C1", "C1", "C2"]))
    predicted = dict(zip("abcd", ["K1", "K1", "K2", "K3"]))
    scope = {key: "NVDA:2026-W46" for key in gold}
    result = pairwise_cluster_metrics(gold, predicted, scope)
    assert result["pairwise_precision"] == 1.0
    assert result["pairwise_recall"] == pytest.approx(1 / 3)
    assert result["pairwise_f1"] == .5
    assert result["false_split_pairs"] == 2


def test_cohen_kappa_and_adjudication_queue(tmp_path):
    db = PitLedger(tmp_path / "ledger.sqlite3")
    rid = db.record_run("test", "LIVE_CAPTURED_PIT", "TEST_ONLY", {}, STAMP, STAMP)
    left = ["POSITIVE"] * 5 + ["NEGATIVE"] * 5
    right = ["POSITIVE"] * 4 + ["NEGATIVE"] + ["NEGATIVE"] * 4 + ["POSITIVE"]
    records = []
    for index in range(10):
        task = make_task(db, rid, f"i{index}", f"News {index}")
        records.extend([make_label(task, "a", left[index], left[index]),
                        make_label(task, "b", right[index], right[index])])
    result = inter_annotator_agreement(records)
    # Both annotators use each class five times: p_e = .5, p_o = .8.
    assert result["textual_tone"]["kappa"] == pytest.approx((.8 - .5) / (1 - .5))
    assert result["economic_implication"]["kappa"] == pytest.approx(.6)
    assert {x["item_id"] for x in result["adjudication_queue"]} == {"i4", "i9"}


def test_locked_hash_detects_tampering_and_holdout_needs_dev(tmp_path):
    db = PitLedger(tmp_path / "ledger.sqlite3")
    rid = db.record_run("test", "LIVE_CAPTURED_PIT", "TEST_ONLY", {}, STAMP, STAMP)
    task = make_task(db, rid, "item", "Apple profit rises")
    tasks, draft, locked, manifest = [tmp_path / name for name in ("tasks.jsonl", "draft.jsonl", "locked.jsonl", "manifest.json")]
    write_jsonl(tasks, [task])
    write_jsonl(draft, [make_label(task, tone="POSITIVE", implication="POSITIVE")])
    lock_gold_labels(tasks, draft, locked, manifest, "holdout", "LOCKED_HOLDOUT")
    with pytest.raises(ValueError, match="HOLDOUT_REQUIRES_LOCKED_DEV_BASELINE"):
        evaluate_locked_benchmark(tasks, locked, manifest, db)
    locked.write_text(locked.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="LOCKED_DATASET_HASH_MISMATCH"):
        load_locked_labels(tasks, locked, manifest)


def test_sip_price_end_uses_delay_and_surfaces_provider_error(monkeypatch):
    monkeypatch.setenv("ALPACA_PRICE_FEED", "sip")
    observed_end = []

    def handler(request):
        end = datetime.fromisoformat(request.url.params["end"])
        observed_end.append(end)
        return httpx.Response(403, json={"message": "subscription does not permit querying recent SIP data"})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AlpacaPriceProvider("test-key", "test-secret", client)
            with pytest.raises(ValueError, match="SIP_END_TOO_RECENT"):
                await provider.fetch(["AAPL"], datetime.now(timezone.utc))
            with pytest.raises(AlpacaPriceAccessError, match="ALPACA_PRICE_ACCESS_403"):
                await provider.fetch(["AAPL"])
    asyncio.run(exercise())
    assert observed_end
    assert (datetime.now(timezone.utc) - observed_end[0]).total_seconds() >= 19 * 60


def test_group_split_preserves_all_tasks_without_requiring_week_groups(tmp_path):
    db = PitLedger(tmp_path / "ledger.sqlite3")
    rid = db.record_run("test", "LIVE_CAPTURED_PIT", "TEST_ONLY", {}, STAMP, STAMP)
    tasks = [make_task(db, rid, f"i{i}", f"Headline {i}") for i in range(4)]
    tasks[2] = tasks[2].model_copy(update={"session_window_id": "AAPL:2026-W47"})
    tasks[3] = tasks[3].model_copy(update={"session_window_id": "AAPL:2026-W47"})
    batch = tmp_path / "batch.jsonl"
    write_jsonl(batch, tasks)
    result = split_blind_batch(batch, tmp_path / "dev.jsonl", tmp_path / "holdout.jsonl")
    dev = {row["session_window_id"] for row in map(json.loads, (tmp_path / "dev.jsonl").read_text(encoding="utf-8").splitlines())}
    holdout = {row["session_window_id"] for row in map(json.loads, (tmp_path / "holdout.jsonl").read_text(encoding="utf-8").splitlines())}
    assert dev and holdout
    assert result["LOCKED_HOLDOUT"]["parent_batch_sha256"] == file_sha256(batch)


def test_event_split_keeps_cross_ticker_headline_and_cross_week_event(tmp_path):
    db = PitLedger(tmp_path / 'graph.sqlite3')
    rid = db.record_run('test', 'LIVE_CAPTURED_PIT', 'TEST_ONLY', {}, STAMP, STAMP)
    tasks = [make_task(db, rid, f'g{i}', f'Unique{i} independent{i}') for i in range(16)]
    tasks[1] = tasks[1].model_copy(update={'headline': tasks[0].headline, 'ticker': 'MSFT'})
    tasks[3] = tasks[3].model_copy(update={'headline': tasks[2].headline, 'session_window_id': 'AAPL:2026-W47'})
    batch = tmp_path / 'batch.jsonl'
    write_jsonl(batch, tasks)
    split_blind_batch(batch, tmp_path / 'dev.jsonl', tmp_path / 'holdout.jsonl')
    dev = {json.loads(line)['task_id'] for line in (tmp_path / 'dev.jsonl').read_text().splitlines()}
    assert (tasks[0].task_id in dev) == (tasks[1].task_id in dev)
    assert (tasks[2].task_id in dev) == (tasks[3].task_id in dev)


def test_reviewed_event_group_keeps_different_headlines_together(tmp_path):
    db = PitLedger(tmp_path / 'reviewed.sqlite3')
    rid = db.record_run('test', 'LIVE_CAPTURED_PIT', 'TEST_ONLY', {}, STAMP, STAMP)
    tasks = [make_task(db, rid, f'r{i}', f'Distinct{i} Topic{i}') for i in range(20)]
    tasks[1] = tasks[1].model_copy(update={'session_window_id': 'AAPL:2026-W47'})
    batch, groups_path = tmp_path / 'batch.jsonl', tmp_path / 'groups.json'
    write_jsonl(batch, tasks)
    groups_path.write_text(json.dumps([[tasks[0].task_id, tasks[1].task_id]]), encoding='utf-8')
    result = split_blind_batch(batch, tmp_path / 'dev.jsonl', tmp_path / 'holdout.jsonl',
                               event_groups_path=groups_path)
    dev = {json.loads(line)['task_id'] for line in (tmp_path / 'dev.jsonl').read_text().splitlines()}
    assert (tasks[0].task_id in dev) == (tasks[1].task_id in dev)
    assert result['LOCKED_HOLDOUT']['event_groups_sha256'] == file_sha256(groups_path)


def test_cluster_audit_counts_cross_week_false_split(tmp_path):
    db = PitLedger(tmp_path / 'crossweek.sqlite3')
    rid = db.record_run('test', 'LIVE_CAPTURED_PIT', 'TEST_ONLY', {}, STAMP, STAMP)
    first = make_task(db, rid, 'ralston-a', 'Chevron restarts Ralston plant', 'CVX')
    second = make_task(db, rid, 'ralston-b', 'Iowa biodiesel facility resumes operations', 'CVX')
    second = second.model_copy(update={'session_window_id': 'CVX:2026-W47'})
    gold = {task.task_id: make_label(task, gold_event_cluster_key='CVX_RALSTON') for task in (first, second)}
    raw = {row['observation_id']: row for row in db.rows('raw_news_events')}
    result = _cluster_audit([first, second], gold, raw)
    assert result['comparison_scope'] == 'ticker_across_all_session_windows'
    assert result['false_split_pairs'] == 1


def test_inconsistent_same_headline_tone_rejected(tmp_path):
    from backend.evaluation.annotation_schema import validate_tone_consistency
    db = PitLedger(tmp_path / 'tone.sqlite3')
    rid = db.record_run('test', 'LIVE_CAPTURED_PIT', 'TEST_ONLY', {}, STAMP, STAMP)
    a = make_task(db, rid, 'tone-a', 'Same news')
    b = make_task(db, rid, 'tone-b', 'Same news', 'MSFT')
    with pytest.raises(ValueError, match='TONE_INCONSISTENCY_ON_IDENTICAL_HEADLINE'):
        validate_tone_consistency([a, b], [make_label(a), make_label(b, tone='POSITIVE', implication='POSITIVE')])


def test_financial_lexicon_handles_simple_negation():
    assert predict_lexicon("Company beats estimates")["label"] == "POSITIVE"
    assert predict_lexicon("Company fails to beat estimates")["label"] == "NEGATIVE"
    assert predict_lexicon("Company faces antitrust probe")["label"] == "NEGATIVE"
    numeric = predict_lexicon('Bernstein adjusts price target on Chevron to $233 from $248')
    assert numeric['label'] == 'NEGATIVE'
    assert any('NUMERIC_TARGET_CUT' in entry['phrase'] for entry in numeric['evidence'])
    assert predict_lexicon('Bernstein adjusts price target on Chevron from $248 to $260')['label'] == 'POSITIVE'


def test_nonfinite_probabilities_are_rejected(tmp_path):
    db = PitLedger(tmp_path / "ledger.sqlite3")
    rid = db.record_run("test", "LIVE_CAPTURED_PIT", "TEST_ONLY", {}, STAMP, STAMP)
    task = make_task(db, rid, "bad-prob", "Apple update")
    with pytest.raises(ValueError, match="INVALID_PROBABILITIES"):
        db.add_score(task.observation_id, task.item_id, MODEL_ID, DEFAULT_LOCAL_MODEL_REVISION,
                     STAMP, "SCORED", {"positive": float("nan"), "neutral": 0, "negative": 0})


def test_sip_daily_bar_requires_session_close_before_requested_end(monkeypatch):
    monkeypatch.setenv("ALPACA_PRICE_FEED", "sip")

    def handler(request):
        adjusted = request.url.params["adjustment"] == "all"
        return httpx.Response(200, json={"bars": {"AAPL": [{"t": "2026-11-13T05:00:00Z",
                                                         "o": 50 if adjusted else 100,
                                                         "c": 51 if adjusted else 101}]}})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AlpacaPriceProvider("test-key", "test-secret", client)
            partial = await provider.fetch(["AAPL"], datetime.fromisoformat("2026-11-13T20:50:00+00:00"))
            complete = await provider.fetch(["AAPL"], datetime.fromisoformat("2026-11-13T21:00:00+00:00"))
            assert partial == []
            assert complete[0]["close_raw"] == 101
            assert complete[0]["close_adj"] == 51
    asyncio.run(exercise())


def test_csv_annotation_sheet_round_trip_is_blind(tmp_path):
    db = PitLedger(tmp_path / "ledger.sqlite3")
    rid = db.record_run("test", "LIVE_CAPTURED_PIT", "TEST_ONLY", {}, STAMP, STAMP)
    task = make_task(db, rid, "sample", "Apple raises guidance")
    tasks = tmp_path / "tasks.jsonl"
    sheet = tmp_path / "sheet.csv"
    draft = tmp_path / "draft.jsonl"
    write_jsonl(tasks, [task])
    prepare_annotation_sheet(tasks, sheet, "annotator-1")
    with sheet.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields, rows = reader.fieldnames, list(reader)
    assert not ({"p_pos", "p_neu", "p_neg", "net_score", "predicted_label", "cluster_id"} & set(fields))
    rows[0].update(target_relevance="DIRECT_COMPANY_EVENT", textual_tone="POSITIVE",
                   economic_implication="POSITIVE", event_category="EARNINGS_GUIDANCE",
                   gold_event_cluster_key="AAPL:guidance")
    with sheet.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    result = import_annotation_sheet(tasks, sheet, draft)
    assert result["record_count"] == 1
    assert Human2DAnnotationRecord.model_validate_json(draft.read_text(encoding="utf-8")).annotator_id == "annotator-1"


def test_disagreement_requires_adjudication_before_benchmark(tmp_path):
    db = PitLedger(tmp_path / "ledger.sqlite3")
    rid = db.record_run("test", "LIVE_CAPTURED_PIT", "TEST_ONLY", {}, STAMP, STAMP)
    task = make_task(db, rid, "disputed", "Apple outlook changes")
    tasks, draft = tmp_path / "tasks.jsonl", tmp_path / "draft.jsonl"
    write_jsonl(tasks, [task])
    a = make_label(task, "a", "POSITIVE", "POSITIVE")
    b = make_label(task, "b", "NEGATIVE", "NEGATIVE")
    write_jsonl(draft, [a, b])
    locked, manifest = tmp_path / "locked.jsonl", tmp_path / "manifest.json"
    lock_gold_labels(tasks, draft, locked, manifest, "disputed", "CALIBRATION_DEV")
    with pytest.raises(ValueError, match="UNRESOLVED_ANNOTATOR_DISAGREEMENT"):
        evaluate_locked_benchmark(tasks, locked, manifest, db)
    judge = make_label(task, "judge", "POSITIVE", "POSITIVE", is_adjudicated=True)
    adjudication = tmp_path / "adjudication.jsonl"
    write_jsonl(adjudication, [judge])
    final_locked, final_manifest = tmp_path / "final_locked.jsonl", tmp_path / "final_manifest.json"
    lock_gold_labels(tasks, [draft, adjudication], final_locked, final_manifest, "adjudicated", "CALIBRATION_DEV")
    result = evaluate_locked_benchmark(tasks, final_locked, final_manifest, db)
    assert result["resolved_gold_count"] == 1
    assert result["inter_annotator_agreement"][0]["adjudication_queue"][0]["task_id"] == task.task_id


def test_holdout_majority_is_fitted_only_on_locked_dev(tmp_path):
    db = PitLedger(tmp_path / "ledger.sqlite3")
    rid = db.record_run("test", "LIVE_CAPTURED_PIT", "TEST_ONLY", {}, STAMP, STAMP)
    dev_task = make_task(db, rid, "dev-item", "Apple raises guidance")
    hold_task = make_task(db, rid, "hold-item", "Apple cuts guidance")
    paths = {}
    for prefix, task, tone, split in (("dev", dev_task, "POSITIVE", "CALIBRATION_DEV"),
                                      ("hold", hold_task, "NEGATIVE", "LOCKED_HOLDOUT")):
        task_path, draft, locked, manifest = [tmp_path / f"{prefix}_{name}" for name in ("tasks.jsonl", "draft.jsonl", "locked.jsonl", "manifest.json")]
        write_jsonl(task_path, [task])
        write_jsonl(draft, [make_label(task, tone=tone, implication=tone)])
        lock_gold_labels(task_path, draft, locked, manifest, prefix, split)
        paths[prefix] = (task_path, locked, manifest)
    report = evaluate_locked_benchmark(*paths["hold"], db, dev_locked=paths["dev"])
    assert report["majority_classes"] == {"textual_tone": "POSITIVE", "economic_implication": "POSITIVE"}
    assert report["baseline_majority_from"] == "locked_dev"
    assert report["tracks"]["textual_tone"]["majority"]["confusion_matrix"]["NEGATIVE"]["POSITIVE"] == 1
