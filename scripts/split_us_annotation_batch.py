"""Group-split blind tasks before humans see the labels."""
import argparse
import json

from backend.evaluation.blind_export import split_blind_batch
from backend.storage.pit_ledger import DEFAULT_PATH, PitLedger


def main() -> None:
    parser = argparse.ArgumentParser(description="Split US tasks by ticker/week window")
    parser.add_argument("--batch", required=True)
    parser.add_argument("--dev-output", required=True)
    parser.add_argument("--holdout-output", required=True)
    parser.add_argument("--holdout-fraction", type=float, default=.25)
    parser.add_argument("--seed", default="us-group-split-v1")
    parser.add_argument("--ledger", default=str(DEFAULT_PATH))
    parser.add_argument("--event-groups", help="JSON list of reviewed task-id groups that must remain together")
    args = parser.parse_args()
    ledger = PitLedger(args.ledger)
    try:
        print(json.dumps(split_blind_batch(args.batch, args.dev_output, args.holdout_output,
                                           args.holdout_fraction, args.seed, ledger,
                                           args.event_groups), ensure_ascii=False, indent=2))
    finally:
        ledger.close()


if __name__ == "__main__":
    main()
