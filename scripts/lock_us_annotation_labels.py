"""Validate human labels and create write-once SHA-256 locked files."""
import argparse
import json

from backend.evaluation.annotation_schema import lock_gold_labels


def main() -> None:
    parser = argparse.ArgumentParser(description="Lock the 2D human annotation dataset")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--draft-labels", required=True, action="append", help="Repeat for each annotator's draft JSONL")
    parser.add_argument("--locked-labels", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--split", choices=["CALIBRATION_DEV", "LOCKED_HOLDOUT"], required=True)
    args = parser.parse_args()
    manifest = lock_gold_labels(args.tasks, args.draft_labels, args.locked_labels,
                                args.manifest, args.dataset_id, args.split)
    print(json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
