"""Structured, descriptive US ledger audit for the local research workbench."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from statistics import mean, pstdev

from backend.config import DEFAULT_LOCAL_MODEL_REVISION, MODEL_ID
from backend.services.numeric_headline_parser import parse_price_target_change
from backend.services.target_relevance import experimental_relevance
from backend.storage.pit_ledger import PitLedger
from backend.universe.catalog import universe_by_ticker


def audit_summary(ledger: PitLedger, artifacts: Path) -> dict:
    raw = ledger.rows('raw_news_events')
    bars = ledger.rows('eod_price_bars')
    latest = {}
    for row in ledger.rows('sentiment_scores'):
        if (row['model_id'], row['model_revision'], row['scoring_status']) != (MODEL_ID, DEFAULT_LOCAL_MODEL_REVISION, 'SCORED'):
            continue
        old = latest.get(row['observation_id'])
        if old is None or (row['scored_at_utc'], row['score_id']) > (old['scored_at_utc'], old['score_id']):
            latest[row['observation_id']] = row
    news = [row for row in raw if row['item_type'] != 'SEC_FILING' and row['observation_id'] in latest]
    catalog = universe_by_ticker()
    categories = defaultdict(list)
    by_ticker = defaultdict(list)
    for row in news:
        category = experimental_relevance(row['headline'], row['ticker'], row['item_type'], catalog)
        categories[category].append(row)
        by_ticker[row['ticker']].append(row)
    distribution = []
    for label, rows in sorted(categories.items()):
        scores = [latest[row['observation_id']] for row in rows]
        predictions = Counter(max(('POSITIVE', 'NEUTRAL', 'NEGATIVE'),
            key=lambda name: score[{'POSITIVE': 'p_pos', 'NEUTRAL': 'p_neu', 'NEGATIVE': 'p_neg'}[name]]) for score in scores)
        values = [float(score['net_score']) for score in scores]
        distribution.append({'category': label, 'count': len(rows), 'positive': predictions['POSITIVE'],
                             'neutral': predictions['NEUTRAL'], 'negative': predictions['NEGATIVE'],
                             'mean_net': mean(values), 'sd_net': pstdev(values)})
    noise_effect = []
    for ticker, rows in sorted(by_ticker.items()):
        kept = [row for row in rows if experimental_relevance(row['headline'], ticker, row['item_type'], catalog) != 'POSSIBLE_NOISE_UNVERIFIED']
        original = mean(float(latest[row['observation_id']]['net_score']) for row in rows)
        revised = mean(float(latest[row['observation_id']]['net_score']) for row in kept) if kept else None
        noise_effect.append({'ticker': ticker, 'news_count': len(rows), 'excluded_count': len(rows)-len(kept),
                             'raw_mean': original, 'filtered_mean': revised,
                             'delta': revised-original if revised is not None else None})
    numeric_mismatches = []
    for row in news:
        change = parse_price_target_change(row['headline'])
        score = latest[row['observation_id']]
        net = float(score['net_score'])
        if change and ((change.direction == 'NUMERIC_TARGET_CUT' and net > .10) or
                       (change.direction == 'NUMERIC_TARGET_RAISE' and net < -.10)):
            numeric_mismatches.append({'ticker': row['ticker'], 'headline': row['headline'],
                                       'previous': str(change.previous), 'current': str(change.current),
                                       'direction': change.direction, 'net_score': net})
    selected = []
    for row in news:
        if any(marker in row['headline'].casefold() for marker in (
            'maintains chevron hold', 'maintains outperform on exxon', 'seeks dismissal of fairview',
            'rejects $28 per share bid', 'raised its mstr stake')):
            score = latest[row['observation_id']]
            selected.append({'ticker': row['ticker'], 'headline': row['headline'],
                             'p_pos': score['p_pos'], 'p_neu': score['p_neu'],
                             'p_neg': score['p_neg'], 'net_score': score['net_score']})
    source_pairs = []
    batch_path = artifacts / 'evaluations/alpaca_first_us_batch.jsonl'
    groups_path = artifacts / 'evaluations/us_batch_candidate_event_groups_v2.json'
    curated_path = artifacts / 'evaluations/us_batch_curated_event_groups_v4.json'
    if batch_path.is_file() and groups_path.is_file() and curated_path.is_file():
        tasks = {row['task_id']: row for line in batch_path.read_text(encoding='utf-8').splitlines()
                 if (row := json.loads(line))}
        candidates = json.loads(groups_path.read_text(encoding='utf-8'))
        curated = {frozenset(ids) for ids in json.loads(curated_path.read_text(encoding='utf-8'))}
        for name, ids in candidates.items():
            if frozenset(ids) not in curated:
                continue
            for aid, bid in combinations(ids, 2):
                a, b = tasks[aid], tasks[bid]
                names = {a['source_name'].casefold(), b['source_name'].casefold()}
                if not any('benzinga' in value for value in names) or not any('fiscal.ai' in value for value in names):
                    continue
                benzinga = a if 'benzinga' in a['source_name'].casefold() else b
                fiscal = b if benzinga is a else a
                if benzinga['observation_id'] not in latest or fiscal['observation_id'] not in latest:
                    continue
                x = float(latest[benzinga['observation_id']]['net_score'])
                y = float(latest[fiscal['observation_id']]['net_score'])
                source_pairs.append({'group': name, 'benzinga_net': x, 'fiscal_net': y, 'absolute_gap': abs(x-y)})
    phase3 = []
    pointer = artifacts / 'phase3/current_replay.json'
    replay_root = artifacts / 'phase3/replay_cluster_v3'
    if pointer.is_file():
        name = json.loads(pointer.read_text(encoding='utf-8'))['run_id']
        if Path(name).name != name:
            raise ValueError('INVALID_REPLAY_RUN_ID')
        replay_root = artifacts / 'phase3/news_updates' / name / 'replay'
    for horizon in (1, 5):
        for relevance_filter in ('none', 'exclude_noise', 'direct_only'):
            path = replay_root / f'h{horizon}_{relevance_filter}/phase3_report.json'
            if not path.is_file():
                continue
            report = json.loads(path.read_text(encoding='utf-8'))
            metrics = report['predictive_metrics'][report['primary_variant']]
            phase3.append({'horizon': horizon, 'relevance_filter': relevance_filter,
                           'evaluated_rows': metrics['all']['n'], 'scored_event_rows': metrics['scored_event']['n'],
                           'price_brier': metrics['all']['price_only']['brier'],
                           'price_news_brier': metrics['all']['price_plus_news']['brier'],
                           'validity_tier': report['report_validity_tier'], 'report_sha256': report['report_sha256']})
    return {'ledger_counts': {'sec_filings': sum(row['item_type'] == 'SEC_FILING' for row in raw),
                              'scored_news': len(news), 'sip_price_bars': sum(row['data_feed'] == 'SIP' for row in bars)},
            'distribution': distribution, 'noise_effect': noise_effect,
            'source_pairs': source_pairs, 'numeric_mismatches': numeric_mismatches,
            'mixed_headlines': selected, 'phase3': phase3,
            'method': 'Descriptive ledger scores and retrospective artifacts; no human gold, no trading signal.',
            'artifact_status': {'curated_groups_available': curated_path.is_file(),
                                'phase3_reports_loaded': len(phase3)}}
