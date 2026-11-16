from datetime import datetime, timezone
import pytest
from scripts.prepare_us_prospective_holdout import READY, eligible, overlaps, select


def row(**changes):
    item = {'ticker':'AAPL', 'item_type':'NEWS_HEADLINE', 'provenance_tier':'LIVE_CAPTURED_PIT',
            'published_at_utc':'2026-11-16T16:00:00+00:00', 'ingested_at_utc':'2026-11-16T16:01:00+00:00',
            'item_id':'article-1', 'observation_id':'observation-1', 'headline':'Apple introduces new hardware',
            'source_url':'https://example.com/news/one', 'external_event_key':'event-1'}
    item.update(changes)
    return item


def test_future_holdout_fails_closed_and_checks_real_observation_time():
    with pytest.raises(ValueError, match='HOLDOUT_WINDOW_NOT_COMPLETE'):
        select([row()], [], datetime(2026, 11, 15, tzinfo=timezone.utc))
    assert eligible(row())
    assert not eligible(row(provenance_tier='EXPLORATORY_RETROSPECTIVE_NON_PIT'))
    assert not eligible(row(ingested_at_utc='2026-11-17T01:01:00+00:00'))
    assert not eligible(row(published_at_utc='2026-11-15T16:00:00+00:00'))
    assert not eligible(row(published_at_utc='2026-11-16T16:00:00'))


def test_selection_excludes_linked_prior_stories_and_duplicate_articles():
    prior = row(item_id='old', observation_id='old-o', published_at_utc='2026-11-14T16:00:00+00:00')
    assert overlaps(prior, row(), ['Apple', 'AAPL'])
    selected, counts, excluded = select([row()], [prior], READY)
    assert selected == [] and counts['AAPL'] == 0 and excluded == 1
    other = row(item_id='article-2', observation_id='observation-2', ticker='MSFT', headline='Different article', source_url='https://example.com/two')
    selected, counts, _ = select([row(), other], [], READY)
    assert len(selected) == 1  # same external event across two tickers


def test_known_leaky_holdout_is_blocked_before_benchmark(monkeypatch):
    from types import SimpleNamespace
    from backend.evaluation import benchmark_2d_runner as runner
    manifest = SimpleNamespace(split_type='LOCKED_HOLDOUT',
        task_batch_sha256='729c26b19f8eed26d844750543fdab2e171fe8cdf474b7cc826ed44992247395')
    monkeypatch.setattr(runner, 'load_locked_labels', lambda *args: ([], [], manifest))
    monkeypatch.setattr(runner, '_resolve_gold', lambda records: {})
    with pytest.raises(ValueError, match='KNOWN_HOLDOUT_EVENT_LEAKAGE'):
        runner.evaluate_locked_benchmark('tasks', 'labels', 'manifest', None)
