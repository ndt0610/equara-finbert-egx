"""Create rule suggestions for review; empty fields mean unknown, not neutral."""
import argparse
import csv
from pathlib import Path

from backend.evaluation.annotation_schema import BlindAnnotationTaskItem, read_jsonl
from backend.evaluation.lexicon_baseline import predict_lexicon
from backend.services.target_relevance import experimental_relevance
from backend.universe.catalog import universe_by_ticker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    tasks = read_jsonl(args.tasks, BlindAnnotationTaskItem)
    catalog = universe_by_ticker()
    fields = ['task_id', 'ticker', 'headline', 'item_type', 'relevance_suggestion', 'tone_suggestion',
              'tone_evidence', 'economic_implication', 'event_category', 'gold_event_cluster_key',
              'rationale_note', 'review_status']
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for task in tasks:
            relevance = experimental_relevance(task.headline, task.ticker, task.item_type, catalog)
            lexical = predict_lexicon(task.headline)
            evidence = lexical['evidence'] if task.item_type != 'SEC_FILING' else []
            writer.writerow({'task_id': task.task_id, 'ticker': task.ticker, 'headline': task.headline,
                             'item_type': task.item_type, 'relevance_suggestion': relevance,
                             'tone_suggestion': lexical['label'] if evidence else '',
                             'tone_evidence': '; '.join(item['phrase'] for item in evidence),
                             'economic_implication': '', 'event_category': '', 'gold_event_cluster_key': '',
                             'rationale_note': '', 'review_status': 'UNVERIFIED_MACHINE_SUGGESTION'})
    print(f'Wrote {len(tasks)} unverified suggestions to {path}')


if __name__ == '__main__':
    main()
