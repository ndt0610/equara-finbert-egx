"""Headline-only AI silver diagnostics; never creates or substitutes human gold."""
import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from backend.config import DEFAULT_LOCAL_MODEL_REVISION, MODEL_ID
from backend.evaluation.annotation_schema import BlindAnnotationTaskItem, Human2DAnnotationRecord, _validate_task_bindings, read_jsonl
from backend.evaluation.benchmark_2d_runner import evaluate_reference_records, majority_from_dev
from backend.storage.pit_ledger import DEFAULT_PATH, PitLedger

ROOT = Path('artifacts/evaluations/us_eval_20261115_v2')
# One entry per existing, exposed historical split row, in frozen task order.
# D/S/I = direct/sector/noise; P/U/N = positive/neutral/negative;
# M = mixed/unknown, X = not applicable. These are headline-only judgments.
HOLDOUT = '''
D P M ANALYST_RATING
D U U OTHER
D U M PRODUCT_CONTRACT
S U M MACRO_SECTOR
D P P ANALYST_RATING
D N M ANALYST_RATING
D U M ANALYST_RATING
D P P EARNINGS_GUIDANCE
D U M PRODUCT_CONTRACT
D U M ANALYST_RATING
D N N OTHER
D U M MANAGEMENT_GOVERNANCE
D P P PRODUCT_CONTRACT
D U M PRODUCT_CONTRACT
D P M OTHER
D P P REGULATORY_LEGAL
I U X OTHER
D P M OTHER
S N M MACRO_SECTOR
S N M MACRO_SECTOR
D P P ANALYST_RATING
S N M REGULATORY_LEGAL
D P M ANALYST_RATING
D P M OTHER
D U M REGULATORY_LEGAL
S P M MACRO_SECTOR
D U M OTHER
I U X OTHER
D P P REGULATORY_LEGAL
D P M ANALYST_RATING
D P M EARNINGS_GUIDANCE
S P M MACRO_SECTOR
S U M MACRO_SECTOR
D U M PRODUCT_CONTRACT
D U M MACRO_SECTOR
S U M MACRO_SECTOR
D P M PRODUCT_CONTRACT
D U M REGULATORY_LEGAL
I U X OTHER
S U M REGULATORY_LEGAL
D P P ANALYST_RATING
D P P ANALYST_RATING
I U X OTHER
S U M MACRO_SECTOR
D U M PRODUCT_CONTRACT
D U M OTHER
D N M ANALYST_RATING
D U M OTHER
D U M PRODUCT_CONTRACT
D U M OTHER
D U M PRODUCT_CONTRACT
D P P PRODUCT_CONTRACT
S U M MACRO_SECTOR
S N M MACRO_SECTOR
S N M MACRO_SECTOR
D U M PRODUCT_CONTRACT
D N M MACRO_SECTOR
D U M OTHER
D P M OTHER
D N M ANALYST_RATING
'''.strip().splitlines()
REL = {'D': 'DIRECT_COMPANY_EVENT', 'S': 'SECTOR_MACRO_SPILLOVER', 'I': 'INCIDENTAL_OR_NOISE'}
TONE = {'P': 'POSITIVE', 'U': 'NEUTRAL', 'N': 'NEGATIVE', 'M': 'AMBIGUOUS_MIXED', 'X': 'NOT_APPLICABLE'}


def record(task, relevance, tone, implication, category, cluster, note):
    return Human2DAnnotationRecord(task_id=task.task_id, observation_id=task.observation_id,
        item_id=task.item_id, ticker=task.ticker, session_window_id=task.session_window_id,
        annotator_id='CODEX_AI_SILVER_V6', annotated_at_utc=datetime.now(timezone.utc),
        target_relevance=relevance, textual_tone=tone, economic_implication=implication,
        event_category=category, gold_event_cluster_key=cluster or None,
        is_first_mention_in_cluster=None, rationale_note=note)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-tier', required=True, choices=['SILVER_AI_REFERENCE_V6'])
    parser.parse_args()
    if hashlib.sha256((ROOT / 'holdout.jsonl').read_bytes()).hexdigest() != '729c26b19f8eed26d844750543fdab2e171fe8cdf474b7cc826ed44992247395':
        raise ValueError('HISTORICAL_TASK_ORDER_OR_CONTENT_CHANGED')
    dev_tasks = read_jsonl(ROOT / 'dev.jsonl', BlindAnnotationTaskItem)
    tasks60 = read_jsonl(ROOT / 'holdout.jsonl', BlindAnnotationTaskItem)
    by_id = {t.task_id: t for t in dev_tasks}
    with (ROOT / 'dev_codex_ai_review_v6.csv').open(encoding='utf-8-sig', newline='') as f:
        source = list(csv.DictReader(f))
    dev = [record(by_id[r['task_id']], r['target_relevance_ai'], r['textual_tone_ai'] or None,
                  r['economic_implication_ai'], r['event_category_ai'], r['event_cluster_candidate'],
                  r['economic_rationale_v2'] or r['rationale_note'] or 'AI headline-only judgment.') for r in source]
    if len(tasks60) != 60 or len(HOLDOUT) != 60:
        raise ValueError('UNEXPECTED_HISTORICAL_SPLIT_SIZE')
    historical = []
    with (ROOT / 'holdout_codex_ai_review_v6.csv').open('w', encoding='utf-8-sig', newline='') as f:
        fields = ['row', 'task_id', 'ticker', 'headline', 'target_relevance_ai', 'textual_tone_ai',
                  'economic_implication_ai', 'event_category_ai', 'event_cluster_candidate', 'review_status', 'rationale_note']
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
        for i, (task, codes) in enumerate(zip(tasks60, HOLDOUT), 1):
            rel, tone, imp, cat = codes.split()
            relevance, textual, implication = REL[rel], TONE[tone], TONE[imp]
            cluster = 'AI_SINGLE_UNVERIFIED_' + task.task_id if rel != 'I' else None
            note = 'AI headline-only assessment; uncertainty and cross-split event overlap remain unverified.'
            historical.append(record(task, relevance, textual, implication, cat, cluster, note))
            writer.writerow(dict(row=i, task_id=task.task_id, ticker=task.ticker, headline=task.headline,
                target_relevance_ai=relevance, textual_tone_ai=textual, economic_implication_ai=implication,
                event_category_ai=cat, event_cluster_candidate=cluster or '',
                review_status='AI_HEADLINE_ONLY_EXPOSED_SPLIT_NOT_INDEPENDENT', rationale_note=note))
    _validate_task_bindings(dev_tasks, dev); _validate_task_bindings(tasks60, historical)
    blind_ids = {t.task_id for t in read_jsonl(ROOT / 'dev_blind160.jsonl', BlindAnnotationTaskItem)}
    subsets = {'dev180': (dev_tasks, dev), 'dev160_excluding_exposed20':
               ([t for t in dev_tasks if t.task_id in blind_ids], [r for r in dev if r.task_id in blind_ids]),
               'historical60_exposed_overlap': (tasks60, historical)}
    assert len(subsets['dev160_excluding_exposed20'][0]) == 160
    baseline = majority_from_dev(dev)
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    reports = {}
    ledger = PitLedger(DEFAULT_PATH)
    try:
        for name, (tasks, labels) in subsets.items():
            manifest = SimpleNamespace(dataset_id='SILVER_AI_REFERENCE_V6_' + name, split_type='AI_EXPLORATORY',
                task_batch_sha256=sha(ROOT / ('holdout.jsonl' if name.startswith('historical') else
                                               'dev_blind160.jsonl' if name.startswith('dev160') else 'dev.jsonl')),
                records_sha256=sha(ROOT / ('holdout_codex_ai_review_v6.csv' if name.startswith('historical') else 'dev_codex_ai_review_v6.csv')))
            r = evaluate_reference_records(tasks, labels, manifest, ledger, model_id=MODEL_ID,
                                           model_revision=DEFAULT_LOCAL_MODEL_REVISION, majority_override=baseline)
            r.update(reference_tier='SILVER_AI_REFERENCE_V6', reference_provenance='AI headline-only; not independent human gold',
                     baseline_majority_from='dev180_in_sample', split_leakage='historical60 overlaps or may overlap dev',
                     cluster_reference_limit='Unverified singletons treated as distinct; pairwise score is provisional',
                     inter_annotator_agreement=[])
            r['resolved_reference_count'] = r.pop('resolved_gold_count')
            if name == 'historical60_exposed_overlap':
                r['clustering'] = {'status': 'NOT_EVALUATED_UNREVIEWED_SINGLETONS', 'pairwise_precision': None,
                                   'pairwise_recall': None, 'pairwise_f1': None, 'eligible_pairs': None}
            reports[name] = r
    finally:
        ledger.close()
    (ROOT / 'phase25_v6_benchmark_report.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# Phase 2.5 — SILVER_AI_REFERENCE_V6', '',
             'AI headline-only reference; no independent human gold, no human agreement. Historical 60 is exposed and overlaps or may overlap dev; it is not independent holdout. Dev majority fitted on all 180 rows. Event singletons are unverified. Results are descriptive and may reflect circularity or correlated model errors.', '',
             '| Split | Track | Method | Scored / eligible | Macro F1 | Brier |', '|---|---|---|---:|---:|---:|']
    fmt = lambda x: '—' if x is None else f'{x:.4f}'
    for name, report in reports.items():
        for track, methods in report['tracks'].items():
            for method in ('finbert', 'lexicon', 'majority'):
                m = methods[method]
                lines.append(f"| {name} | {track} | {method} | {m['n']}/{m['eligible_count']} | {fmt(m['macro_f1'])} | {fmt(m['multiclass_brier'])} |")
        n = sum(x['eligible'] for x in report['divergence_by_category'].values())
        d = len(report['tone_implication_divergence_cases'])
        cluster = report['clustering']
        lines.extend(['', f"{name}: tone/implication disagreement {d}/{n}; FinBERT implication error on scored disagreement = {fmt(report['finbert_implication_error_rate_on_divergence'])}; pairwise precision/recall/F1 = {fmt(cluster['pairwise_precision'])}/{fmt(cluster['pairwise_recall'])}/{fmt(cluster['pairwise_f1'])}, eligible pairs {cluster['eligible_pairs']}. Unverified singleton assignments limit validity.", ''])
        for track in ('textual_tone', 'economic_implication'):
            for method in ('finbert', 'lexicon', 'majority'):
                lines.append(f"- {name} / {track} / {method} confusion (actual → predicted): `{json.dumps(report['tracks'][track][method]['confusion_matrix'])}`")
    (ROOT / 'PHASE25_V6_BENCHMARK_REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Wrote SILVER_AI_REFERENCE_V6 reports to', ROOT)


if __name__ == '__main__':
    main()
