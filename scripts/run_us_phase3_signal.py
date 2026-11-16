"""Offline Phase 3 walk-forward research from an existing Equara PiT ledger."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.evaluation.phase3_panel import build_phase3_panel
from backend.evaluation.signal_validation_phase3 import run_walk_forward_phase3
from backend.storage.pit_ledger import DEFAULT_PATH, PitLedger


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--tickers", required=True, help="Comma-separated tickers in the Equara US universe")
    parser.add_argument("--start", required=True, help="First NYSE decision session, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Last NYSE decision session, YYYY-MM-DD")
    parser.add_argument("--horizon", type=int, choices=(1, 5, 20), default=5)
    parser.add_argument("--cutoff-et", default="20:00")
    parser.add_argument("--allow-retrospective-diagnostic", action="store_true")
    parser.add_argument('--relevance-filter', choices=('none', 'exclude_noise', 'direct_only'), default='none')
    parser.add_argument("--min-train-sessions", type=int, default=20)
    parser.add_argument("--min-train-rows", type=int, default=40)
    parser.add_argument("--bootstrap-repetitions", type=int, default=200)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/phase3"))
    args = parser.parse_args()
    if not args.ledger.is_file():
        parser.error(f"Ledger does not exist: {args.ledger}")
    tickers = [part.strip().upper() for part in args.tickers.split(",") if part.strip()]
    ledger = PitLedger(args.ledger)
    try:
        panel = build_phase3_panel(ledger, tickers, args.start, args.end, args.horizon,
                                   args.cutoff_et, args.allow_retrospective_diagnostic, relevance_filter=args.relevance_filter)
    finally:
        ledger.close()
    report = run_walk_forward_phase3(panel, args.min_train_sessions, args.min_train_rows,
                                    bootstrap_repetitions=args.bootstrap_repetitions)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    panel_path = args.output_dir / "phase3_panel.json"
    report_path = args.output_dir / "phase3_report.json"
    panel_path.write_text(json.dumps(panel, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    holdout_active = report["predictive_metrics"][report["primary_variant"]]["holdout_active_event"]
    holdout_net = report["holdout_active_event_economic_diagnostics"]["cost_scenarios"]["10"]["branches"]["price_news"]
    summary = ["# Equara US Phase 3", "", f"- Validity: **{report['report_validity_tier']}**",
               f"- Relevance filter (unvalidated): `{args.relevance_filter}`",
               f"- Actionability: **{report['actionability_status']}**",
               f"- Reason: `{report['actionability_reason']}`",
               f"- Label maturity: `{report['walk_forward']['label_maturity_policy']}`",
               f"- Panel rows: {len(panel['rows'])}",
               f"- Walk-forward evaluated rows: {report['walk_forward']['evaluated_rows']}",
               f"- Evaluated rows with scored news: {report['predictive_metrics'][report['primary_variant']]['scored_event']['n']}",
               f"- Holdout rows with scored news: {report['predictive_metrics'][report['primary_variant']]['holdout_scored_event']['n']}",
               f"- Holdout rows with events: {holdout_active['n']}",
               f"- Holdout event basket periods: {holdout_net['period_count']}",
               f"- Holdout event net return CI at 10 bps/side: {holdout_net['mean_net_return_95ci_block_bootstrap']}",
               f"- Panel SHA-256: `{panel['panel_sha256']}`",
               f"- Report SHA-256: `{report['report_sha256']}`", "",
               "Adjusted daily-bar returns and fixed bps costs are ex-post research proxies, not observed fills.", ""]
    (args.output_dir / "phase3_summary.md").write_text("\n".join(summary), encoding="utf-8")
    print("\n".join(summary))
    print(f"Full report: {report_path}")
    print(f"Panel: {panel_path}")


if __name__ == "__main__":
    main()
