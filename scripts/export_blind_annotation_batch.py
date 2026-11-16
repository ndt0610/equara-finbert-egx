"""Export a model-blind JSONL sample. Run from repository root with python -m scripts..."""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone

from backend.evaluation.blind_export import export_blind_annotation_batch
from backend.storage.pit_ledger import DEFAULT_PATH, PitLedger


def main() -> None:
    parser = argparse.ArgumentParser(description="Export blind US annotation tasks")
    parser.add_argument("--ledger", default=str(DEFAULT_PATH))
    parser.add_argument("--output", required=True, help="New JSONL path; existing files are never overwritten")
    parser.add_argument("--cutoff-utc", default=datetime.now(timezone.utc).isoformat())
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--tickers", default="", help="Comma-separated research symbols")
    parser.add_argument("--include-structural", action="store_true")
    parser.add_argument("--seed", default="us-annotation-v1")
    parser.add_argument("--exclude-batch", action="append", default=[], help="Exclude item IDs from previously reviewed JSONL batches")
    args = parser.parse_args()
    ledger = PitLedger(args.ledger)
    try:
        prior = [json.loads(line) for path in args.exclude_batch for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
        excluded = {row['item_id'] for row in prior}
        excluded_titles = {row['headline'].strip().casefold() for row in prior}
        result = export_blind_annotation_batch(
            ledger, args.output, args.cutoff_utc, args.limit,
            [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()] or None,
            args.include_structural, args.lookback_days, args.seed, excluded, excluded_titles)
    finally:
        ledger.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
