"""Descriptive ledger audit: model scores and agreement, never accuracy without gold labels."""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path

from backend.config import DEFAULT_LOCAL_MODEL_REVISION, MODEL_ID
from backend.evaluation.lexicon_baseline import LABELS, predict_lexicon
from backend.services.event_clustering import cluster_events_v2, content_tokens
from backend.services.numeric_headline_parser import parse_price_target_change
from backend.services.target_relevance import experimental_relevance
from backend.storage.pit_ledger import DEFAULT_PATH, PitLedger
from backend.universe.catalog import universe_by_ticker


def _legacy_assignment(payload: list[dict], aliases: dict[str, list[str]]) -> dict[str, int]:
    """Frozen pre-upgrade complete-link rule, used only for a paired audit."""
    groups: list[list[dict]] = []
    for item in sorted(payload, key=lambda x: (x['ticker'], x.get('published_at_utc') or '', x['item_id'])):
        tokens = content_tokens(item['headline'], item['ticker'], aliases.get(item['ticker'], []))
        def linked(other: dict) -> bool:
            if item['ticker'] != other['ticker']:
                return False
            if item.get('external_event_key') and item['external_event_key'] == other.get('external_event_key'):
                return True
            old = content_tokens(other['headline'], other['ticker'], aliases.get(item['ticker'], []))
            if not tokens or not old:
                return False
            if tokens == old:
                return True
            hours = abs((datetime.fromisoformat(item['published_at_utc']) -
                         datetime.fromisoformat(other['published_at_utc'])).total_seconds()) / 3600
            return hours <= 24 and len(tokens & old) / len(tokens | old) >= .55
        group = next((group for group in groups if all(linked(other) for other in group)), None)
        if group is None:
            groups.append([item])
        else:
            group.append(item)
    return {item['item_id']: index for index, group in enumerate(groups) for item in group}


def audit(ledger: PitLedger, batch_path: Path, groups_path: Path,
          curated_path: Path | None = None) -> str:
    raw = {row['observation_id']: row for row in ledger.rows('raw_news_events')}
    scores = {}
    for row in ledger.rows('sentiment_scores'):
        if row['model_id'] == MODEL_ID and row['model_revision'] == DEFAULT_LOCAL_MODEL_REVISION and row['scoring_status'] == 'SCORED':
            old = scores.get(row['observation_id'])
            if old is None or (row['scored_at_utc'], row['score_id']) > (old['scored_at_utc'], old['score_id']):
                scores[row['observation_id']] = row
    catalog = universe_by_ticker()
    all_news = [row for row in raw.values() if row['item_type'] != 'SEC_FILING' and row['observation_id'] in scores]
    batch = [json.loads(line) for line in batch_path.read_text(encoding='utf-8').splitlines()]
    by_task = {task['task_id']: task for task in batch}
    groups = json.loads(groups_path.read_text(encoding='utf-8'))
    curated = json.loads(curated_path.read_text(encoding='utf-8')) if curated_path else []
    curated_keys = {frozenset(ids) for ids in curated}
    if curated and (len(curated_keys) != len(curated) or not curated_keys <= {frozenset(ids) for ids in groups.values()}):
        raise ValueError('CURATED_GROUPS_NOT_IN_CANDIDATES')
    lines = ['# Equara: kiểm toán điểm FinBERT trong ledger', '',
             'Đây là thống kê điểm mô hình đã lưu, không đo độ chính xác hay lợi suất. Nhóm liên quan và nhóm sự kiện là giả thuyết chưa có nhãn người độc lập. Các nhóm ứng viên và ngưỡng sửa đổi đã được xem trên batch này; các tỷ lệ khớp dưới đây chỉ là chẩn đoán trong mẫu, không phải recall độc lập trên holdout.', '',
             f'- Bản ghi tin có điểm: {len(all_news)}', f'- Tác vụ batch: {len(batch)}',
             f'- Nhóm sự kiện ứng viên: {len(groups)}; nhóm chọn lọc: {len(curated)}', '']
    by_category = defaultdict(list)
    for row in all_news:
        by_category[experimental_relevance(row['headline'], row['ticker'], row['item_type'], catalog)].append(scores[row['observation_id']])
    lines += ['## Phân phối điểm theo quy tắc liên quan', '',
              '| Nhóm quy tắc | N | Dương | Trung tính | Âm | Trung bình net | Độ lệch chuẩn net |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for category, values in sorted(by_category.items()):
        labels = Counter(max(LABELS, key=lambda label: values[i][{'POSITIVE':'p_pos','NEUTRAL':'p_neu','NEGATIVE':'p_neg'}[label]]) for i in range(len(values)))
        net = [float(v['net_score']) for v in values]
        lines.append(f"| {category} | {len(values)} | {labels['POSITIVE']} | {labels['NEUTRAL']} | {labels['NEGATIVE']} | {statistics.mean(net):.4f} | {statistics.pstdev(net):.4f} |")
    lines += ['', '### Ảnh hưởng cơ học của việc bỏ mẫu nghi nhiễu trên trung bình điểm theo mã', '',
              '| Mã | N tin | N nghi nhiễu | Trung bình gốc | Trung bình sau bỏ | Chênh lệch |',
              '|---|---:|---:|---:|---:|---:|']
    for ticker in sorted({row['ticker'] for row in all_news}):
        subset = [row for row in all_news if row['ticker'] == ticker]
        kept = [row for row in subset if experimental_relevance(row['headline'], ticker, row['item_type'], catalog) != 'POSSIBLE_NOISE_UNVERIFIED']
        original = statistics.mean(float(scores[row['observation_id']]['net_score']) for row in subset)
        revised = statistics.mean(float(scores[row['observation_id']]['net_score']) for row in kept) if kept else None
        lines.append(f"| {ticker} | {len(subset)} | {len(subset)-len(kept)} | {original:.4f} | {revised:.4f} | {revised-original:+.4f} |" if revised is not None else
                     f"| {ticker} | {len(subset)} | {len(subset)} | {original:.4f} | — | — |")
    lines += ['', 'Chênh lệch này là phép tính trên các bài đã thu thập, chưa phải tác động lên NAV hoặc hiệu quả dự báo.']
    lines += ['', '## Đồng thuận FinBERT và lexicon trên batch', '',
              '| FinBERT \\ Lexicon | POSITIVE | NEUTRAL | NEGATIVE |', '|---|---:|---:|---:|']
    matrix = {a: Counter() for a in LABELS}
    opposite = []
    for task in batch:
        if task['item_type'] == 'SEC_FILING' or task['observation_id'] not in scores:
            continue
        score = scores[task['observation_id']]
        finbert = max(LABELS, key=lambda label: score[{'POSITIVE':'p_pos','NEUTRAL':'p_neu','NEGATIVE':'p_neg'}[label]])
        lexical = predict_lexicon(task['headline'])['label']
        matrix[finbert][lexical] += 1
        if {finbert, lexical} == {'POSITIVE', 'NEGATIVE'}:
            opposite.append((task['ticker'], task['headline'], finbert, lexical))
    for label in LABELS:
        lines.append('| ' + label + ' | ' + ' | '.join(str(matrix[label][other]) for other in LABELS) + ' |')
    lines += ['', f'Bất đồng dương/âm: {len(opposite)}; đây là bất đồng giữa hai mô hình, không phải số lỗi.', '']
    for ticker, headline, finbert, lexical in opposite[:20]:
        lines.append(f'- {ticker}: {headline} — FinBERT {finbert}, lexicon {lexical}')
    payload = [{**task, 'item_id': task['task_id'],
                'external_event_key': raw[task['observation_id']]['external_event_key']}
               for task in batch if task['item_type'] != 'SEC_FILING']
    aliases = {ticker: [ticker, row['company_name'], *row.get('aliases', [])] for ticker, row in catalog.items()}
    legacy = _legacy_assignment(payload, aliases)
    machine = {}
    reasons = Counter()
    for index, cluster in enumerate(cluster_events_v2(payload, aliases)):
        for task_id in cluster['item_ids']:
            machine[task_id] = index
        if len(cluster['item_ids']) > 1:
            reasons.update(cluster['clustering_reason'])
    lines += ['', '## Độ phân tán trong các nhóm sự kiện ứng viên', '',
              '| Nhóm | N | Các điểm net | Biên độ | Bài đầu | Trung bình | Cặp máy gom / cặp ứng viên |',
              '|---|---:|---|---:|---:|---:|---:|']
    matched = total = exact_url_pairs = old_matched = curated_matched = curated_total = curated_old = 0
    for name, ids in groups.items():
        tasks = [by_task[task_id] for task_id in ids]
        values = [float(scores[task['observation_id']]['net_score']) for task in tasks]
        first = min(tasks, key=lambda task: task['published_at_utc'])
        pair_list = list(combinations(ids, 2))
        hits = sum(machine.get(a) == machine.get(b) for a, b in pair_list)
        old_hits = sum(legacy.get(a) == legacy.get(b) for a, b in pair_list)
        exact_url_pairs += sum(bool(by_task[a].get('source_url')) and by_task[a].get('source_url') == by_task[b].get('source_url') for a, b in pair_list)
        matched += hits; total += len(pair_list); old_matched += old_hits
        if frozenset(ids) in curated_keys:
            curated_matched += hits; curated_old += old_hits; curated_total += len(pair_list)
        first_score = float(scores[first['observation_id']]['net_score'])
        lines.append(f"| {name} | {len(ids)} | {', '.join(f'{v:.3f}' for v in values)} | {max(values)-min(values):.3f} | {first_score:.3f} | {statistics.mean(values):.3f} | {hits}/{len(pair_list)} |")
    lines += ['', '### Đối chiếu quy tắc cũ và mới trên cùng batch', '',
              '| Danh sách tham chiếu | Cặp | Quy tắc cũ | Quy tắc mới |', '|---|---:|---:|---:|',
              f'| 15 nhóm chọn lọc | {curated_total} | {curated_old} | {curated_matched} |',
              f'| 22 nhóm ứng viên | {total} | {old_matched} | {matched} |', '',
              f'{exact_url_pairs}/{total} cặp ứng viên có URL giống hệt nhau trước chuẩn hóa. Các lý do liên kết cụm mới: {dict(sorted(reasons.items()))}. Cặp vẫn thiếu cần rà soát thủ công; số nhóm được chọn từ chính batch này nên không là ước lượng độ nhạy ngoài mẫu.', '']
    lines += ['### Chênh lệch giữa nguồn Benzinga và fiscal.ai trong nhóm chọn lọc', '',
              '| Nhóm | Benzinga net | fiscal.ai net | Chênh lệch tuyệt đối |',
              '|---|---:|---:|---:|']
    source_pairs = 0
    for name, ids in groups.items():
        if frozenset(ids) not in curated_keys:
            continue
        for a, b in combinations((by_task[task_id] for task_id in ids), 2):
            names = {a['source_name'].casefold(), b['source_name'].casefold()}
            if not any('benzinga' in n for n in names) or not any('fiscal.ai' in n for n in names):
                continue
            benzinga = a if 'benzinga' in a['source_name'].casefold() else b
            fiscal = b if benzinga is a else a
            x = float(scores[benzinga['observation_id']]['net_score'])
            y = float(scores[fiscal['observation_id']]['net_score'])
            lines.append(f'| {name} | {x:.3f} | {y:.3f} | {abs(x-y):.3f} |')
            source_pairs += 1
    if not source_pairs:
        lines.append('| Không có cặp trong batch | — | — | — |')
    lines += ['', 'Điểm nguồn chỉ mô tả hai cách viết tiêu đề; không quy chênh lệch cho nguồn nếu chưa kiểm soát nội dung và thời điểm.', '']
    lines += ['## Giá mục tiêu có chiều số học trái dấu với điểm FinBERT', '',
              'Chỉ xét tiêu đề chứa price target/target price và cặp giá cũ/mới tường minh. Giá mục tiêu là đánh giá của nhà phân tích, không đồng nghĩa lợi suất hay giá trị doanh nghiệp.', '',
              '| Mã | Tiêu đề | Cũ | Mới | FinBERT net |', '|---|---|---:|---:|---:|']
    numeric_cuts = []
    for row in all_news:
        change = parse_price_target_change(row['headline'])
        if change and change.direction == 'NUMERIC_TARGET_CUT':
            numeric_cuts.append((row, change))
            score = scores[row['observation_id']]
            if float(score['net_score']) > .10:
                lines.append(f"| {row['ticker']} | {row['headline'].replace('|', '/')} | {change.previous} | {change.current} | {score['net_score']:.3f} |")
    lines += ['', f'Tìm thấy {len(numeric_cuts)} tiêu đề hạ giá mục tiêu tường minh trong {len(all_news)} bài; bảng liệt kê các ca có FinBERT net > +0.10. Đây là bất đồng với chiều thay đổi giá mục tiêu, không tự động là nhãn tone sai.', '']
    lines += ['## Ca nhiều tín hiệu trong cùng tiêu đề', '', '| Mã | Tiêu đề | p+ | p0 | p− | net |', '|---|---|---:|---:|---:|---:|']
    markers = ('maintains chevron hold', 'maintains outperform on exxon', 'seeks dismissal of fairview', 'rejects $28 per share bid', 'raised its mstr stake')
    for task in batch:
        if any(marker in task['headline'].casefold() for marker in markers) and task['observation_id'] in scores:
            score = scores[task['observation_id']]
            lines.append(f"| {task['ticker']} | {task['headline'].replace('|', '/')} | {score['p_pos']:.3f} | {score['p_neu']:.3f} | {score['p_neg']:.3f} | {score['net_score']:.3f} |")
    return '\n'.join(lines) + '\n'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path, default=DEFAULT_PATH)
    parser.add_argument('--batch', type=Path, default=Path('artifacts/evaluations/alpaca_first_us_batch.jsonl'))
    parser.add_argument('--groups', type=Path, default=Path('artifacts/evaluations/us_batch_candidate_event_groups_v2.json'))
    parser.add_argument('--curated-groups', type=Path, default=Path('artifacts/evaluations/us_batch_curated_event_groups_v4.json'))
    parser.add_argument('--output', type=Path, default=Path('artifacts/evaluations/US_FINBERT_EMPIRICAL_LEDGER_AUDIT.md'))
    args = parser.parse_args()
    ledger = PitLedger(args.ledger)
    try:
        report = audit(ledger, args.batch, args.groups, args.curated_groups)
    finally:
        ledger.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding='utf-8')
    print(f'Wrote {args.output}')


if __name__ == '__main__':
    main()
