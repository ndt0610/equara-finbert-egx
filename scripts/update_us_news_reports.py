"""Rebuild retrospective reports offline, then publish one complete set."""
import argparse
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path


def run(*args):
    subprocess.run([sys.executable, '-X', 'utf8', '-m', *map(str, args)], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tickers', required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--no-publish', action='store_true', help='Generate reports without changing the active workbench')
    args = parser.parse_args()
    end = date.fromisoformat(args.end)
    start = end - timedelta(days=60)
    root = args.run_dir
    if not args.no_publish and root.resolve().parent != Path('artifacts/phase3/news_updates').resolve():
        parser.error('Published runs must be directly under artifacts/phase3/news_updates so the audit API can load them')
    root.mkdir(parents=True, exist_ok=True)
    run('scripts.run_us_finbert_ledger_audit', '--output', root / 'ledger_audit.md')
    lines = ['# Phase 3: so sánh hồi cứu', '',
             'EXPLORATORY_NON_PIT_DIAGNOSTIC_ONLY. Tin tải hồi cứu không chứng minh sẵn có tại thời điểm quyết định; các bộ lọc chưa được xác thực.', '',
             '| H | Bộ lọc | Biến thể | Dòng đánh giá | Có tin chấm điểm | Holdout có tin | Brier giá | Brier giá + tin | Rank IC giá | Rank IC giá + tin |',
             '|---|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for h in (1, 5):
        for filt in ('none', 'exclude_noise', 'direct_only'):
            out = root / 'replay' / f'h{h}_{filt}'
            run('scripts.run_us_phase3_signal', '--tickers', args.tickers, '--start', start.isoformat(), '--end', end.isoformat(),
                '--horizon', h, '--relevance-filter', filt, '--min-train-sessions', 6, '--min-train-rows', 20,
                '--allow-retrospective-diagnostic', '--output-dir', out)
            report = json.loads((out / 'phase3_report.json').read_text(encoding='utf-8'))
            if report['report_validity_tier'] != 'EXPLORATORY_NON_PIT_DIAGNOSTIC_ONLY':
                raise ValueError('Unexpected validity tier')
            for variant, metrics in report['predictive_metrics'].items():
                all_rows = metrics['all']
                vals = (h, filt, variant, all_rows['n'], metrics['scored_event']['n'], metrics['holdout_scored_event']['n'],
                        all_rows['price_only']['brier'], all_rows['price_plus_news']['brier'],
                        all_rows['price_only']['rank_ic'], all_rows['price_plus_news']['rank_ic'])
                lines.append('| ' + ' | '.join('—' if v is None else f'{v:.4f}' if isinstance(v, float) else str(v) for v in vals) + ' |')
    lines += ['', 'Các chỉ số trên toàn bộ dòng có thể bao gồm dòng không có tin; xem số dòng có tin và holdout trước khi diễn giải.', '']
    comparison = '\n'.join(lines)
    (root / 'comparison.md').write_text(comparison, encoding='utf-8')
    if args.no_publish:
        print(f'Generated reports without publishing: {root}')
        return
    Path('artifacts/evaluations/US_FINBERT_EMPIRICAL_LEDGER_AUDIT.md').write_text((root / 'ledger_audit.md').read_text(encoding='utf-8'), encoding='utf-8')
    Path('artifacts/phase3/US_PHASE3_RELEVANCE_FILTER_COMPARISON.md').write_text(comparison, encoding='utf-8')
    pointer = Path('artifacts/phase3/current_replay.json')
    tmp = pointer.with_suffix('.tmp')
    tmp.write_text(json.dumps({'run_id': root.name}) + '\n', encoding='utf-8')
    os.replace(tmp, pointer)
    print(f'Published complete retrospective report set: {root}')


if __name__ == '__main__':
    main()
