"""NSE cash session clock. India has no daylight saving, so a fixed offset is enough."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from ..market_calendar import expected_latest_session

IST = timezone(timedelta(hours=5, minutes=30))

SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
FEED_START = time(9, 10)
FEED_END = time(15, 35)
ORB_END = time(9, 30)

# NSE Diwali Muhurat 2026 (circular CMTR/76941): Sunday 8 November.
# Continuous trading for non-CAS names is 14:20–15:30 IST. The feed leads
# the open by five minutes, the same lead as the regular session.
MUHURAT_DATE = date(2026, 11, 8)
MUHURAT_OPEN = time(14, 20)
MUHURAT_CLOSE = time(15, 30)
MUHURAT_FEED_START = time(14, 15)
MUHURAT_FEED_END = time(15, 35)
MUHURAT_ORB_END = time(14, 35)

_SESSION_SECONDS = (
    datetime.combine(datetime.min.date(), SESSION_CLOSE)
    - datetime.combine(datetime.min.date(), SESSION_OPEN)
).total_seconds()

IST_OFFSET_SEC = 19_800
OPEN_MINUTE_OF_DAY = SESSION_OPEN.hour * 60 + SESSION_OPEN.minute
SESSION_MINUTES = int(_SESSION_SECONDS // 60)
ORB_MINUTES = (ORB_END.hour * 60 + ORB_END.minute) - OPEN_MINUTE_OF_DAY
MUHURAT_OPEN_MINUTE = MUHURAT_OPEN.hour * 60 + MUHURAT_OPEN.minute
MUHURAT_SESSION_MINUTES = (MUHURAT_CLOSE.hour * 60 + MUHURAT_CLOSE.minute) - MUHURAT_OPEN_MINUTE
MUHURAT_ORB_MINUTES = (MUHURAT_ORB_END.hour * 60 + MUHURAT_ORB_END.minute) - MUHURAT_OPEN_MINUTE
_MUHURAT_DAY = (MUHURAT_DATE - date(1970, 1, 1)).days


def absolute_minute(epoch: float) -> int:
    """Monotonic IST minute number. Cheap enough to call on every tick."""
    return int((epoch + IST_OFFSET_SEC) // 60)


def _ist_day(epoch: float) -> int:
    return int((epoch + IST_OFFSET_SEC) // 86400)


def is_muhurat_epoch(epoch: float) -> bool:
    return _ist_day(epoch) == _MUHURAT_DAY


def open_minute_for_absolute(absolute: int) -> int:
    if absolute // 1440 == _MUHURAT_DAY:
        return MUHURAT_OPEN_MINUTE
    return OPEN_MINUTE_OF_DAY


def session_length(epoch: float) -> int:
    return MUHURAT_SESSION_MINUTES if is_muhurat_epoch(epoch) else SESSION_MINUTES


def orb_minutes(epoch: float) -> int:
    return MUHURAT_ORB_MINUTES if is_muhurat_epoch(epoch) else ORB_MINUTES


def session_minute(epoch: float) -> int:
    """Minutes since today's open. Negative before it, past the length after the close."""
    minute = absolute_minute(epoch)
    return (minute % 1440) - open_minute_for_absolute(minute)


def minute_label(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, IST).strftime("%Y-%m-%dT%H:%M")


def in_session(epoch: float) -> bool:
    minute = session_minute(epoch)
    return 0 <= minute < session_length(epoch)


def now_ist() -> datetime:
    return datetime.now(IST)


def ensure_ist(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=IST)
    return ts.astimezone(IST)


def _session_bounds(current: datetime) -> tuple[time, time, time, time, time] | None:
    """Open, close, feed start, feed end, opening-range end. None when the market is shut."""
    if current.date() == MUHURAT_DATE:
        return (MUHURAT_OPEN, MUHURAT_CLOSE, MUHURAT_FEED_START, MUHURAT_FEED_END, MUHURAT_ORB_END)
    if current.weekday() >= 5:
        return None
    return (SESSION_OPEN, SESSION_CLOSE, FEED_START, FEED_END, ORB_END)


def session_name(ts: datetime | None = None) -> str:
    current = ensure_ist(ts or now_ist())
    if current.date() == MUHURAT_DATE:
        return "muhurat"
    return "regular"


def in_feed_window(ts: datetime | None = None) -> bool:
    current = ensure_ist(ts or now_ist())
    bounds = _session_bounds(current)
    if bounds is None:
        return False
    return bounds[2] <= current.time() <= bounds[3]


def hold_through_close(ts: datetime | None = None) -> bool:
    """True when a stream started now should disconnect after the cash close."""
    current = ensure_ist(ts or now_ist())
    bounds = _session_bounds(current)
    if bounds is None:
        return False
    return current.time() < bounds[3]


def past_feed_end(ts: datetime | None = None) -> bool:
    current = ensure_ist(ts or now_ist())
    bounds = _session_bounds(current)
    if bounds is None:
        return False
    return current.time() >= bounds[3]


def in_opening_range(ts: datetime) -> bool:
    current = ensure_ist(ts)
    bounds = _session_bounds(current)
    if bounds is None:
        return False
    return bounds[0] <= current.time() < bounds[4]


def opening_range_complete(ts: datetime) -> bool:
    current = ensure_ist(ts)
    bounds = _session_bounds(current)
    if bounds is None:
        return False
    return current.time() >= bounds[4]


def session_progress(ts: datetime | None = None) -> float:
    """Fraction of today's cash session elapsed, clamped so the open print is not infinite RVOL."""
    current = ensure_ist(ts or now_ist())
    bounds = _session_bounds(current)
    if bounds is None:
        return 1.0
    open_at = current.replace(hour=bounds[0].hour, minute=bounds[0].minute, second=0, microsecond=0)
    close_at = current.replace(hour=bounds[1].hour, minute=bounds[1].minute, second=0, microsecond=0)
    span = (close_at - open_at).total_seconds()
    if span <= 0:
        return 1.0
    return max(0.02, min(1.0, (current - open_at).total_seconds() / span))


def minute_key(ts: datetime) -> str:
    current = ensure_ist(ts).replace(second=0, microsecond=0)
    return current.strftime("%Y-%m-%dT%H:%M")


def trade_date(ts: datetime | None = None) -> str:
    return ensure_ist(ts or now_ist()).date().isoformat()


def required_daily_session(ts: datetime | None = None) -> str:
    """Last completed cash session. Before today's close, that is the previous session."""
    current = ensure_ist(ts or now_ist())
    bounds = _session_bounds(current)
    if bounds is not None and current.time() < bounds[1]:
        return expected_latest_session(current.date() - timedelta(days=1))
    return expected_latest_session(current.date())
