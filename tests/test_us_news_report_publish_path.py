import sys

import pytest

from scripts import update_us_news_reports


def test_published_replay_must_be_where_audit_api_looks(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'argv', ['update_us_news_reports', '--tickers', 'AAPL',
                                     '--end', '2026-11-13', '--run-dir', str(tmp_path / 'elsewhere')])
    with pytest.raises(SystemExit) as error:
        update_us_news_reports.main()
    assert error.value.code == 2
    assert not (tmp_path / 'elsewhere').exists()
