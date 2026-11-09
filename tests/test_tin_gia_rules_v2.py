from datetime import date, timedelta
import pytest
from backend.upgrades.tin_gia.rules import evaluate_rules, classify

def case(age=1, adjusted=False):
    end = date(2026, 11, 5)
    bars = [{'date':(end-timedelta(days=80-i)).isoformat(),'close':100+i*.05} for i in range(81)]
    if adjusted:
        for b in bars: b['adjusted_close'] = b['close']
        bars[-1]['close'] *= .5  # raw-only split discontinuity must not drive the rule
    row = dict(candidate_id='x',title='Telecom Egypt raises profits',scope='company_candidate',
               processing_state='unresolved',reason_code='pending_event_review',matched_alias='Telecom Egypt',
               published_at=(end-timedelta(days=age)).isoformat()+'T08:00:00+00:00',
               probabilities={'positive':.9,'negative':.05,'neutral':.05})
    return {'status':'available','price_kind':'daily_close','history':bars}, {'candidate_ledger':{'candidates':[row]}}

def test_old_single_story_loses_absolute_strength():
    fresh=evaluate_rules(*case(1)); old=evaluate_rules(*case(29))
    assert fresh['inputs']['raw_sentiment'] == pytest.approx(old['inputs']['raw_sentiment'])
    assert old['inputs']['sentiment'] < fresh['inputs']['sentiment']/10
    assert old['label'] == 'Giữ'

def test_extreme_negative_move_does_not_reverse_sell_to_hold():
    assert classify(-.8,-.09,.05,.10,4)[0] == 'sell_strong'
    assert classify(-.8,-.11,.05,.10,4)[0] == 'sell_strong'

@pytest.mark.parametrize('age',[0,-1,31])
def test_ineligible_dates_never_become_hold(age):
    assert evaluate_rules(*case(age))['label'] is None

def test_adjusted_prices_drive_returns():
    assert evaluate_rules(*case(adjusted=True))['inputs']['five_session_return'] == pytest.approx(evaluate_rules(*case())['inputs']['five_session_return'])

def test_missing_prices_never_become_hold():
    assert evaluate_rules({'status':'unavailable'}, {})['label'] is None
