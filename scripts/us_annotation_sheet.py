"""Prepare blind CSV for one annotator, then import completed labels to JSONL."""
import argparse
import json

from backend.evaluation.annotation_sheet import import_annotation_sheet, prepare_annotation_sheet


def main() -> None:
    parser = argparse.ArgumentParser(description="US blind annotation CSV workbench")
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--tasks", required=True)
    prepare.add_argument("--csv", required=True)
    prepare.add_argument("--annotator-id", required=True)
    load = sub.add_parser("import")
    load.add_argument("--tasks", required=True)
    load.add_argument("--csv", required=True)
    load.add_argument("--draft-labels", required=True)
    load.add_argument("--allow-partial", action="store_true", help="Only for an adjudication sheet containing disputed tasks")
    args = parser.parse_args()
    result = (prepare_annotation_sheet(args.tasks, args.csv, args.annotator_id)
              if args.action == "prepare" else
              import_annotation_sheet(args.tasks, args.csv, args.draft_labels, args.allow_partial))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
