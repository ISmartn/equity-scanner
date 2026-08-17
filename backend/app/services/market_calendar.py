from __future__ import annotations

from datetime import date, timedelta


def expected_latest_session(as_of: date | None = None) -> str:
    """Latest NSE session on or before as_of (rolls weekend back to Friday)."""
    d = as_of or date.today()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


def trading_days_in_month_through(anchor: date) -> list[str]:
    """Weekdays from the 1st of anchor's month through anchor (inclusive)."""
    first = anchor.replace(day=1)
    days: list[str] = []
    d = first
    while d <= anchor:
        if _is_weekday(d):
            days.append(d.isoformat())
        d += timedelta(days=1)
    return days


def trading_days_in_range(start: date, end: date) -> list[str]:
    """Weekdays from start through end inclusive."""
    if end < start:
        start, end = end, start
    days: list[str] = []
    d = start
    while d <= end:
        if _is_weekday(d):
            days.append(d.isoformat())
        d += timedelta(days=1)
    return days


def trading_days_prior_to(anchor: date, count: int) -> list[str]:
    """`count` weekdays strictly before anchor, oldest first."""
    if count <= 0:
        return []
    days: list[str] = []
    d = anchor - timedelta(days=1)
    while len(days) < count:
        if _is_weekday(d):
            days.append(d.isoformat())
        d -= timedelta(days=1)
    days.reverse()
    return days


def trading_days_previous_and_current_month(anchor: date) -> list[str]:
    """Weekdays in the calendar month before anchor's month, plus anchor's month through anchor."""
    if anchor.month == 1:
        prev_month_anchor = anchor.replace(year=anchor.year - 1, month=12, day=1)
    else:
        prev_month_anchor = anchor.replace(month=anchor.month - 1, day=1)

    if prev_month_anchor.month == 12:
        prev_month_end = prev_month_anchor.replace(day=31)
    else:
        prev_month_end = anchor.replace(day=1) - timedelta(days=1)

    prev_days = trading_days_in_month_through(prev_month_end)
    curr_days = trading_days_in_month_through(anchor)
    merged = sorted(set(prev_days + curr_days))
    return merged
