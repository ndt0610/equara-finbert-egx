from datetime import datetime
from backend.universe.calendar_nyse import ET
from scripts.us_pit_run_window import allowed


def test_scheduled_capture_window_respects_session_close_and_dst():
    assert allowed(datetime(2026, 11, 16, 17, 30, tzinfo=ET))
    assert allowed(datetime(2026, 7, 6, 18, 30, tzinfo=ET))
    assert not allowed(datetime(2026, 11, 15, 17, 30, tzinfo=ET))
    assert not allowed(datetime(2026, 11, 16, 16, 19, tzinfo=ET))
    assert not allowed(datetime(2026, 11, 16, 20, 0, tzinfo=ET))
    assert allowed(datetime(2026, 11, 27, 13, 20, tzinfo=ET))
