"""NSE session rules for Order Flow, ported from the standalone page's src/lib/marketSession.ts.

Times are epoch milliseconds; dates are IST ``YYYY-MM-DD``. The holiday list
follows the exchange calendar and must be updated each year.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MARKET_OPEN_MINUTE = 9 * 60 + 15
LEGACY_MARKET_CLOSE_MINUTE = 15 * 60 + 30
DERIVATIVES_CLOSE_MINUTE = 15 * 60 + 40
# From this date the derivatives close moved to 15:40 (closing auction session).
CAS_EFFECTIVE_DATE = "2026-08-03"

NSE_HOLIDAYS = frozenset({
    # 2025
    "2025-02-26", "2025-03-14", "2025-03-31", "2025-04-10", "2025-04-14", "2025-04-18",
    "2025-05-01", "2025-08-15", "2025-08-27", "2025-10-02", "2025-10-21", "2025-10-22",
    "2025-11-05", "2025-12-25",
    # 2026
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03",
    "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02",
    "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
    # 2027 (provisional)
    "2027-01-26", "2027-03-08", "2027-03-22", "2027-04-14", "2027-04-16", "2027-04-20",
    "2027-08-15", "2027-09-05", "2027-10-02", "2027-10-18", "2027-10-29", "2027-12-25",
})


def market_parts(ms: float) -> tuple[str, int, int]:
    """(IST date key, weekday with Sunday = 0, minute of the IST day)."""
    moment = datetime.fromtimestamp(ms / 1000, tz=IST)
    weekday = (moment.weekday() + 1) % 7
    return moment.strftime("%Y-%m-%d"), weekday, moment.hour * 60 + moment.minute


def is_trading_day(ms: float) -> bool:
    key, weekday, _ = market_parts(ms)
    return weekday not in (0, 6) and key not in NSE_HOLIDAYS


def market_close_minute_for(ms: float) -> int:
    key, _, _ = market_parts(ms)
    return DERIVATIVES_CLOSE_MINUTE if key >= CAS_EFFECTIVE_DATE else LEGACY_MARKET_CLOSE_MINUTE


def is_market_session_time(ms: float) -> bool:
    _, _, minute = market_parts(ms)
    return is_trading_day(ms) and MARKET_OPEN_MINUTE <= minute <= market_close_minute_for(ms)


def previous_trading_day(ms: float) -> str:
    """The IST date of the trading day before the one containing ``ms``."""
    cursor = ms
    for _ in range(100):
        cursor -= 86_400_000
        key, weekday, _ = market_parts(cursor)
        if weekday not in (0, 6) and key not in NSE_HOLIDAYS:
            return key
    raise RuntimeError("No trading day found in the last 100 days.")


def latest_trading_session_date(ms: float) -> str:
    """Today's session once it has opened; the previous trading day before that or on a closed day."""
    key, _, minute = market_parts(ms)
    if not is_trading_day(ms) or minute < MARKET_OPEN_MINUTE:
        return previous_trading_day(ms)
    return key


def is_expiry_settled(expiry: str, ms: float) -> bool:
    """An expiry settles at the derivatives close on its own date; earlier dates are settled outright."""
    key, _, minute = market_parts(ms)
    if expiry < key:
        return True
    if expiry > key:
        return False
    return minute > market_close_minute_for(ms)


def filter_live_expiries(expiries: list[str], ms: float) -> list[str]:
    """Settled expiries removed, de-duplicated, ascending."""
    unique = {e for e in expiries if isinstance(e, str) and _ISO_DATE.match(e)}
    return sorted(e for e in unique if not is_expiry_settled(e, ms))


def ist_hhmm(ms: float) -> str:
    _, _, minute = market_parts(ms)
    return f"{minute // 60:02d}{minute % 60:02d}"


def round_half_up(value: float) -> int:
    return math.floor(value + 0.5)
