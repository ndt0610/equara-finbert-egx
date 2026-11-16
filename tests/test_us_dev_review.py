import pytest
from scripts.prepare_us_dev_review import validate_draft


def record(**changes):
    result = {'headline':'Example headline','textual_tone_ai':'NEUTRAL', 'ticker':'AAPL',
              'event_cluster_candidate':'AI_SINGLE_1','target_relevance_ai':'DIRECT_COMPANY_EVENT',
              'economic_implication_ai':'NEUTRAL'}
    result.update(changes)
    return result


def test_review_draft_rejects_inconsistent_same_headline_tone():
    with pytest.raises(ValueError, match='IDENTICAL_HEADLINE_TONE_CONFLICT'):
        validate_draft([record(), record(ticker='MSFT', textual_tone_ai='NEGATIVE', event_cluster_candidate='AI_SINGLE_2')])


def test_review_draft_requires_abstention_when_relevance_unknown():
    with pytest.raises(ValueError, match='AI_UNRESOLVED_MUST_ABSTAIN'):
        validate_draft([record(target_relevance_ai='', economic_implication_ai='POSITIVE')])
    validate_draft([record(target_relevance_ai='', economic_implication_ai='', event_cluster_candidate='')])
