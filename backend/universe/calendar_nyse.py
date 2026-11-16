"""Core NYSE schedule frozen from the published 2026-2028 NYSE holiday calendar.

This module deliberately refuses other years and cannot know unscheduled closures.
Update the calendar evidence before using it outside 2026-2028 or for execution.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HOLIDAYS = frozenset(date.fromisoformat(x) for x in (
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
    "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06",
    "2027-11-25", "2027-12-24",
    "2028-01-17", "2028-02-21", "2028-04-14", "2028-05-29",
    "2028-06-19", "2028-07-04", "2028-09-04", "2028-11-23",
    "2028-12-25",
))
EARLY_CLOSE = frozenset(date.fromisoformat(x) for x in (
    "2026-11-27", "2026-12-24", "2027-11-26",
    "2028-07-03", "2028-11-24",
))
SOURCE = "https://www.nyse.com/trade/hours-calendars"


def is_session(day: date) -> bool:
    if day.year not in {2026, 2027, 2028}:
        raise ValueError("NYSE_CALENDAR_OUT_OF_RANGE")
    return day.weekday() < 5 and day not in HOLIDAYS


def close_at(day: date) -> datetime:
    if not is_session(day):
        raise ValueError("NOT_A_NYSE_SESSION")
    return datetime.combine(day, time(13 if day in EARLY_CLOSE else 16), ET)


def next_session(day: date) -> date:
    cursor = day + timedelta(days=1)
    while cursor.year <= 2028:
        if is_session(cursor):
            return cursor
        cursor += timedelta(days=1)
    raise ValueError("NYSE_CALENDAR_OUT_OF_RANGE")


def after_close_decision(timestamp: datetime) -> dict:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    local = timestamp.astimezone(ET)
    day = local.date()
    if not is_session(day) or local < close_at(day):
        raise ValueError("DECISION_MUST_FOLLOW_COMPLETED_SESSION")
    return {
        "decision_session": day.isoformat(),
        "close_at": close_at(day).isoformat(),
        "earliest_core_execution_session": next_session(day).isoformat(),
        "calendar_source": SOURCE,
        "execution_price_status": "not_observed",
    }
