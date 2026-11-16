"""Allow scheduled daily capture only in the current NYSE session's PiT window."""
from datetime import datetime, time, timedelta
from backend.universe.calendar_nyse import ET, close_at, is_session


def allowed(now):
    local = now.astimezone(ET)
    day = local.date()
    return is_session(day) and close_at(day) + timedelta(minutes=20) <= local < datetime.combine(day, time(20), ET)


if __name__ == '__main__':
    current = datetime.now(ET)
    if allowed(current):
        print(f'Capture permitted for NYSE session {current.date()} at {current.isoformat()}')
    elif not is_session(current.date()):
        print(f'Skipped: no NYSE session at {current.isoformat()}')
        raise SystemExit(2)
    else:
        print(f'Missed NYSE capture window at {current.isoformat()}')
        raise SystemExit(3)
