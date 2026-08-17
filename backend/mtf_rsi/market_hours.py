from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# NSE cash equity / index cash session (approx; ignores special half-days)
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)


def market_session_info(now: datetime | None = None) -> dict:
    """Return NSE session state for UI banners."""
    now = now or datetime.now(tz=IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)

    weekday = now.weekday()  # Mon=0 … Sun=6
    is_weekday = weekday < 5
    t = now.time()
    in_hours = is_weekday and SESSION_OPEN <= t <= SESSION_CLOSE

    if not is_weekday:
        reason = "weekend"
        label = "Market closed (weekend)"
    elif t < SESSION_OPEN:
        reason = "pre_open"
        label = "Market closed (pre-open)"
    elif t > SESSION_CLOSE:
        reason = "after_hours"
        label = "Market closed (after hours)"
    else:
        reason = "open"
        label = "Market open"

    return {
        "is_open": in_hours,
        "reason": reason,
        "label": label,
        "now_ist": now.isoformat(),
        "session_open": "09:15",
        "session_close": "15:30",
        "timezone": "Asia/Kolkata",
    }
