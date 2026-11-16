"""Run a benchmark only against verified locked labels and ledger observations."""
import argparse
import json
from pathlib import Path

from backend.config import DEFAULT_LOCAL_MODEL_REVISION, MODEL_ID
from backend.evaluation.benchmark_2d_runner import evaluate_locked_benchmark
from backend.storage.pit_ledger import DEFAULT_PATH, PitLedger, canonical


def to_markdown(report: dict) -> str:
    lines = [f"# US Phase 2.5 benchmark — {report['dataset_id']}", "",
             f"Split: `{report['split_type']}`. Tasks: {report['total_tasks']}. Model: `{report['model_id']}` revision `{report['model_revision']}`.",
             f"Labels SHA-256: `{report['records_sha256']}`. Task SHA-256: `{report['task_batch_sha256']}`.", "",
             "| Track | Method | N | Prediction coverage | Macro-F1 | Directional error | Brier | ECE |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    def show(value):
        return "—" if value is None else f"{value:.4f}" if isinstance(value, float) else str(value)
    for track, methods in report["tracks"].items():
        for method in ("finbert", "lexicon", "majority"):
            row = methods[method]
            lines.append(f"| {track} | {method} | {row['n']} | {show(row['prediction_coverage'])} | {show(row['macro_f1'])} | {show(row['directional_error_rate'])} | {show(row['multiclass_brier'])} | {show(row['ece'])} |")
    for method, row in report.get('track_a_unique_headlines', {}).items():
        coverage = row['n'] / row['eligible_count'] if row['eligible_count'] else None
        lines.append(f"| textual_tone_unique_headlines | {method} | {row['n']} | {show(coverage)} | {show(row['macro_f1'])} | {show(row['directional_error_rate'])} | {show(row['multiclass_brier'])} | {show(row['ece'])} |")
    cluster = report["clustering"]
    lines.extend(["", "## Event clustering", "",
                  f"Eligible pairs: {cluster['eligible_pairs']}; pairwise precision {show(cluster['pairwise_precision'])}, recall {show(cluster['pairwise_recall'])}, F1 {show(cluster['pairwise_f1'])}; macro ARI {show(cluster['macro_adjusted_rand_index'])}.",
                  f"False merges: {cluster['false_merge_pairs']}; false splits: {cluster['false_split_pairs']}.",
                  "", "## Interpretation", "",
                  "FinBERT is a textual-tone model. Track B tests transfer to ticker-specific economic implication; it does not estimate returns.",
                  "Baseline probability vectors are hard one-hot labels, not calibrated forecasts. Report per-class support and the full confusion matrices from the JSON report.",
                  "The majority baseline for holdout is fitted only on the separately locked development split.",
                  ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate locked US 2D annotations")
    parser.add_argument("--ledger", default=str(DEFAULT_PATH))
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--locked-labels", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--dev-tasks")
    parser.add_argument("--dev-labels")
    parser.add_argument("--dev-manifest")
    parser.add_argument("--model-id", default=MODEL_ID)
    parser.add_argument("--model-revision", default=DEFAULT_LOCAL_MODEL_REVISION)
    parser.add_argument("--output-dir", default="artifacts/evaluations")
    args = parser.parse_args()
    dev = (args.dev_tasks, args.dev_labels, args.dev_manifest) if all((args.dev_tasks, args.dev_labels, args.dev_manifest)) else None
    if any((args.dev_tasks, args.dev_labels, args.dev_manifest)) and dev is None:
        parser.error("Provide all three --dev-* paths together")
    ledger = PitLedger(args.ledger)
    try:
        report = evaluate_locked_benchmark(args.tasks, args.locked_labels, args.manifest,
                                           ledger, dev, args.model_id, args.model_revision)
    finally:
        ledger.close()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "phase25_benchmark_report.json"
    md_path = output / "phase25_benchmark_report.md"
    json_path.write_text(canonical(report) + "\n", encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path),
                      "dataset_id": report["dataset_id"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
