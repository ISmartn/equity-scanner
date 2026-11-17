"""One-second boards. Pure functions over a copied quote list — no database and no socket lock."""

from __future__ import annotations

import math
import statistics
from typing import Any

from datetime import datetime

from ..scanner.fo_overlay import QUADRANT_LABELS
from .baskets import default_baskets, index_reads
from .clocks import IST

TESTING_BAND = 0.003
MIN_HISTORY_BARS = 10
_CALL_RANK = {"buy": 0, "sell": 1, "wait": 2, "stand_aside": 3}
# A completed daily candle is the signal. Price may only be this far through it
# before the break is a chase rather than an entry. 0.15R is the gap the year
# replay could still fill without chasing. The day exit stays two times the risk:
# from 0.5R to 4R the average did not improve. The swing target is 2.5R. A 4R
# and a 6R target both lost more on the booked path, and the journal can still
# hold 2.5R past the cash close.
_REWARD_R = 2.0
_SWING_R = 2.5
_ENTRY_WINDOW = 0.15
# Stops are yesterday's candle, bounded by volatility. A prior range under 0.8 ATR
# is skipped: widening it to a 0.5 ATR floor made those trades the worst bucket.
# Beyond 1.5 ATR a 2R target is out of intraday reach, so the stop is capped.
_RISK_MIN_ATR = 0.5
_RISK_MAX_ATR = 1.5
_MIN_CANDLE_ATR = 0.8
# A prior candle wider than this already moved. Those breaks were the worst
# bucket in the year replay (profit factor 0.53).
_MAX_CANDLE_ATR = 1.8
_RISK_MIN_SPREADS = 4.0
# Kaufman efficiency below this is a range, not a trend, whatever the endpoints say.
_MIN_EFFICIENCY = 0.2
# Equities under ₹100 and names still within 2% of the 20-day average lost more
# than the rest of the book, in both halves of the year. Indexes are exempt.
_MIN_PRICE = 100.0
_MIN_SMA_DISTANCE_PCT = 2.0
# Names 8% or more through the 20-day average lost more than the names sitting
# between 2% and 8%. The year replay's 8–15% band was −0.09R.
_MAX_SMA_DISTANCE_PCT = 8.0
# A second path for a base the 20-day efficiency test calls noise. The last 8
# completed sessions are a coil when their high-low span is between 0.8 and 3
# ATR. The side is the break of that box, and only inside the same 0.15R window.
_COIL_MIN_ATR = 0.8
_COIL_MAX_ATR = 3.0
# Futures build-up uses the order-flow daily noise floor (0.5% price, 2% open
# interest). The options-chain 5% band is a different instrument.
_FUT_PRICE_FLOOR_PCT = 0.5
_FUT_OI_FLOOR_PCT = 2.0
_REFERENCE_ATR_PCT = 2.0
_ROLLOVER_DAYS = 2
_MAX_SPREAD_PCT = 0.3
_STALE_TICK_SEC = 30.0
_OI_PRIORITY = {
    "long_buildup": 0,
    "short_covering": 1,
    "short_buildup": 2,
    "long_unwinding": 3,
    "neutral": 4,
}
_BREAKOUT_RANK = {"triggered": 0, "testing": 1, "below": 2, "unavailable": 3}


def session_rvol(vtt: float, avg_volume_20: float | None, progress: float) -> float | None:
    """``progress`` is the expected share of a normal day's volume traded so far (U-curve)."""
    if not avg_volume_20 or avg_volume_20 <= 0 or vtt < 0:
        return None
    expected = avg_volume_20 * max(progress, 0.01)
    if expected <= 0:
        return None
    return vtt / expected


def burst_rvol(
    last_minute_volume: int | None,
    history: list[int],
    weights: list[float] | None = None,
) -> float | None:
    """Last completed minute against the median of the minutes before it.

    With ``weights`` (U-curve intensity per minute, mean 1.0) each minute is
    compared on a time-of-day basis, so the 15:00 ramp is not read as a burst
    against the midday lull.
    """
    if last_minute_volume is None or last_minute_volume < 0 or not history:
        return None
    use_weights = weights is not None and len(weights) == len(history)
    values = (
        [volume / weight if weight > 0 else float(volume) for volume, weight in zip(history, weights or [])]
        if use_weights
        else [float(volume) for volume in history]
    )
    if history[-1] == last_minute_volume:
        current = values[-1]
        baseline = values[:-1]
    else:
        current = float(last_minute_volume)
        baseline = values
    if len(baseline) < 5:
        return None
    median = statistics.median(baseline)
    if median <= 0:
        return None
    return current / median


def testing_band(atr_pct: float | None) -> float:
    if atr_pct is None or atr_pct <= 0:
        return TESTING_BAND
    return min(0.006, max(0.001, 0.15 * atr_pct / 100.0))


def level_state(ltp: float, level: float | None, latched: bool, band: float = TESTING_BAND) -> str:
    if level is None or level <= 0 or ltp <= 0:
        return "unavailable"
    if latched or ltp >= level:
        return "triggered"
    if ltp >= level * (1.0 - band):
        return "testing"
    return "below"


def _pct(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return (numerator - denominator) / denominator * 100.0


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None or isinstance(value, float) and math.isnan(value):
        return None
    return round(float(value), digits)


def _vol_scale(atr_pct: float | None) -> float:
    """Multiply a percent move by this to express it in reference-volatility units."""
    if atr_pct is None or atr_pct <= 0:
        return 1.0
    return _REFERENCE_ATR_PCT / min(10.0, max(0.5, atr_pct))


def _tick_age(quote: dict[str, Any], now: float | None) -> float | None:
    seen = quote.get("last_tick_at")
    if now is None or not isinstance(seen, (int, float)):
        return None
    return max(0.0, now - float(seen))


def _level_row(ltp: float, level: float | None, latched: bool, band: float) -> dict[str, Any]:
    state = level_state(ltp, level, latched, band)
    distance = None
    if level and level > 0 and ltp > 0:
        distance = (level - ltp) / level * 100.0
    return {
        "level": _round(level, 2) if level else None,
        "state": state,
        "distance_pct": _round(distance, 2),
    }


def _bursts(quote: dict[str, Any]) -> float | None:
    weights = quote.get("minute_weights")
    return burst_rvol(
        quote.get("last_minute_volume"),
        list(quote.get("minute_history") or []),
        list(weights) if weights else None,
    )


def _segment(quote: dict[str, Any]) -> str:
    segment = quote.get("segment")
    if segment in {"fno", "cash", "index"}:
        return str(segment)
    return "index" if quote.get("kind") == "index" else "fno"


def rank_momentum(quote: dict[str, Any], progress: float) -> dict[str, Any]:
    ltp = float(quote.get("ltp") or 0)
    prev_close = float(quote.get("prev_close") or 0)
    atp = float(quote.get("atp") or 0)
    day_high = float(quote.get("day_high") or 0)
    day_low = float(quote.get("day_low") or 0)
    atr_pct = _optional_float(quote.get("atr_pct"))
    change_pct = _pct(ltp, prev_close) if ltp and prev_close else None
    vwap_dist_pct = _pct(ltp, atp) if ltp and atp else None
    day_range = day_high - day_low
    range_pos = ((ltp - day_low) / day_range) if ltp and day_range > 0 else None
    sess = session_rvol(float(quote.get("vtt") or 0), quote.get("avg_volume_20"), progress)
    burst = _bursts(quote)
    on_scan = bool(quote.get("on_last_scan"))
    scale = _vol_scale(atr_pct)
    change_atr = (change_pct / atr_pct) if change_pct is not None and atr_pct else None
    # A 2% move in a 1% ATR name outranks a 3% move in a 5% ATR name.
    score = scale * ((change_pct or 0.0) + 0.25 * (vwap_dist_pct or 0.0))
    if sess is not None and sess > 0:
        score += 2.0 * math.log1p(sess)
    if on_scan:
        score += 3.0
    return {
        "symbol": quote["symbol"],
        "company_name": quote.get("company_name"),
        "sector": quote.get("sector"),
        "kind": quote.get("kind") or "equity",
        "segment": _segment(quote),
        "ltp": _round(ltp, 2) if ltp else None,
        "change_pct": _round(change_pct, 2),
        "change_atr": _round(change_atr, 2),
        "vwap_dist_pct": _round(vwap_dist_pct, 2),
        "day_range_pos": _round(range_pos, 3),
        "session_rvol": _round(sess, 2),
        "burst_rvol": _round(burst, 2),
        "on_last_scan": on_scan,
        "scanner_pattern": quote.get("scanner_pattern"),
        "scanner_score": _round(quote.get("scanner_score"), 1),
        "myb_status": quote.get("myb_status"),
        "score": _round(score, 3),
    }


def rank_breakout(quote: dict[str, Any]) -> dict[str, Any]:
    ltp = float(quote.get("ltp") or 0)
    band = testing_band(_optional_float(quote.get("atr_pct")))
    prev = _level_row(ltp, _optional_float(quote.get("prior_high")), bool(quote.get("latch_prev_high")), band)
    orb_level = quote.get("orb_high") if quote.get("orb_locked") else None
    orb = _level_row(ltp, _optional_float(orb_level), bool(quote.get("latch_orb")), band)
    if not quote.get("orb_locked"):
        orb = {
            "level": _round(_optional_float(quote.get("orb_high")), 2),
            "state": "pending" if quote.get("orb_high") else "unavailable",
            "distance_pct": None,
        }
    pivot = _level_row(ltp, _optional_float(quote.get("scanner_pivot")), bool(quote.get("latch_pivot")), band)
    myb = _level_row(ltp, _optional_float(quote.get("myb_level")), bool(quote.get("latch_myb")), band)
    states = [prev["state"], orb["state"], pivot["state"], myb["state"]]
    best = min(states, key=lambda state: _BREAKOUT_RANK.get(state, 9))
    distances = [
        row["distance_pct"]
        for row in (prev, orb, pivot, myb)
        if isinstance(row.get("distance_pct"), (int, float)) and row["state"] in {"testing", "below"}
    ]
    nearest = min(distances) if distances else None
    return {
        "symbol": quote["symbol"],
        "company_name": quote.get("company_name"),
        "sector": quote.get("sector"),
        "kind": quote.get("kind") or "equity",
        "segment": _segment(quote),
        "ltp": _round(ltp, 2) if ltp else None,
        "state": best,
        "nearest_distance_pct": _round(nearest, 2) if nearest is not None else None,
        "prior_high": prev,
        "opening_range": orb,
        "pivot": pivot,
        "multi_year": myb,
        "on_last_scan": bool(quote.get("on_last_scan")),
        "scanner_pattern": quote.get("scanner_pattern"),
        "myb_status": quote.get("myb_status"),
    }


def classify_oi(price_change_pct: float, oi_change_pct: float) -> str:
    """Order-flow build-up. A move inside the daily noise floor is neutral.

    Price up with open interest up is long build-up. Price down with open
    interest up is short build-up. Price up with open interest down is short
    covering. Price down with open interest down is long unwinding. A flat
    price with rising open interest stays neutral.
    """
    price_up = price_change_pct > _FUT_PRICE_FLOOR_PCT
    price_down = price_change_pct < -_FUT_PRICE_FLOOR_PCT
    oi_up = oi_change_pct > _FUT_OI_FLOOR_PCT
    oi_down = oi_change_pct < -_FUT_OI_FLOOR_PCT
    if price_up and oi_up:
        return "long_buildup"
    if price_up and oi_down:
        return "short_covering"
    if price_down and oi_up:
        return "short_buildup"
    if price_down and oi_down:
        return "long_unwinding"
    return "neutral"


def _oi_read(quote: dict[str, Any]) -> tuple[float | None, float | None, str | None]:
    fut_ltp = float(quote.get("fut_ltp") or 0)
    fut_prev = float(quote.get("fut_prev_close") or 0)
    oi = float(quote.get("fut_oi") or 0)
    poi = quote.get("fut_poi")
    price_change = _pct(fut_ltp, fut_prev) if fut_ltp and fut_prev else None
    oi_change = None
    if poi and float(poi) > 0 and oi > 0:
        oi_change = (oi - float(poi)) / float(poi) * 100.0
    if price_change is None or oi_change is None:
        return price_change, oi_change, None
    return price_change, oi_change, classify_oi(price_change, oi_change)


def _rollover(quote: dict[str, Any]) -> bool:
    days = quote.get("days_to_expiry")
    return isinstance(days, int) and 0 <= days <= _ROLLOVER_DAYS


def rank_oi(quote: dict[str, Any]) -> dict[str, Any]:
    fut_ltp = float(quote.get("fut_ltp") or 0)
    cash_ltp = float(quote.get("ltp") or 0)
    oi = float(quote.get("fut_oi") or 0)
    poi = quote.get("fut_poi")
    price_change, oi_change, quadrant = _oi_read(quote)
    quadrant = quadrant or "neutral"
    basis = (fut_ltp - cash_ltp) if fut_ltp and cash_ltp else None
    return {
        "symbol": quote["symbol"],
        "company_name": quote.get("company_name"),
        "sector": quote.get("sector"),
        "segment": _segment(quote),
        "cash_ltp": _round(cash_ltp, 2) if cash_ltp else None,
        "fut_ltp": _round(fut_ltp, 2) if fut_ltp else None,
        "future_expiry": quote.get("future_expiry"),
        "price_change_pct": _round(price_change, 2),
        "oi": int(oi) if oi else None,
        "poi": int(float(poi)) if poi else None,
        "poi_source": quote.get("fut_poi_source") or None,
        "oi_change_pct": _round(oi_change, 2),
        "quadrant": quadrant,
        "quadrant_label": QUADRANT_LABELS.get(quadrant, quadrant),
        "rollover_week": _rollover(quote),
        "basis": _round(basis, 2),
        "on_last_scan": bool(quote.get("on_last_scan")),
    }


def _quote_quadrant(quote: dict[str, Any]) -> str | None:
    return _oi_read(quote)[2]


def _beyond(side: str, price: float, limit: float) -> bool:
    """True when ``price`` is strictly past ``limit`` in the trade's direction."""
    if side == "buy":
        return price > limit + 1e-9
    return price < limit - 1e-9


def trend_side(prev_close: float, sma: float | None, trend_pct: float | None) -> str | None:
    """Above the 20-day average with a rising 20-day path buys; below and falling sells."""
    if sma is None or prev_close <= 0:
        return None
    if prev_close > sma and (trend_pct or 0) > 0:
        return "buy"
    if prev_close < sma and (trend_pct or 0) < 0:
        return "sell"
    return None


def candle_plan(
    side: str,
    entry: float,
    stop: float,
    *,
    atr: float | None = None,
    spread: float | None = None,
    reward_r: float = _REWARD_R,
    swing_r: float = _SWING_R,
    risk_min_atr: float = _RISK_MIN_ATR,
    risk_max_atr: float = _RISK_MAX_ATR,
) -> dict[str, Any] | None:
    """Entry and stop from yesterday's candle, risk bounded by ATR and the live spread."""
    raw = entry - stop if side == "buy" else stop - entry
    if raw <= 0:
        return None
    risk = raw
    basis = "candle"
    if atr and atr > 0:
        floor = risk_min_atr * atr
        if spread and spread > 0:
            floor = max(floor, _RISK_MIN_SPREADS * spread)
        cap = max(floor, risk_max_atr * atr)
        if risk < floor:
            risk, basis = floor, "atr_floor"
        elif risk > cap:
            risk, basis = cap, "atr_cap"
    stop_price = entry - risk if side == "buy" else entry + risk
    exit_price = entry + reward_r * risk if side == "buy" else entry - reward_r * risk
    raw_exit = entry + reward_r * raw if side == "buy" else entry - reward_r * raw
    extended = entry + swing_r * risk if side == "buy" else entry - swing_r * risk
    # The uncapped candle is the multi-session target only when the day plan
    # had to shrink it. Otherwise 2.5R of the day risk is the further target.
    if _beyond(side, raw_exit, exit_price):
        swing_exit, swing_basis = raw_exit, "candle"
    else:
        swing_exit, swing_basis = extended, "multi_r"
    return {
        "entry": entry,
        "stop": stop_price,
        "exit": exit_price,
        "swing_exit": swing_exit,
        "swing_basis": swing_basis,
        "risk": risk,
        "basis": basis,
    }


def _weekend(now: float | None) -> bool:
    """Saturday and Sunday, including the one-hour Muhurat session."""
    if now is None:
        return False
    return datetime.fromtimestamp(now, IST).weekday() >= 5


def _return_against(side: str, value: Any) -> bool:
    """True when the 5-day move is known and does not go with the side."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    if side == "buy":
        return float(value) <= 0
    return float(value) >= 0


def _sma_distance_pct(prev_close: float, sma: float) -> float:
    if sma <= 0:
        return 0.0
    return abs(prev_close - sma) / sma * 100.0


def _narrow_candle(prior_high: float | None, prior_low: float | None, atr: float | None) -> bool:
    if atr is None or atr <= 0 or prior_high is None or prior_low is None:
        return False
    return (prior_high - prior_low) < _MIN_CANDLE_ATR * atr


def _wide_candle(prior_high: float | None, prior_low: float | None, atr: float | None) -> bool:
    if atr is None or atr <= 0 or prior_high is None or prior_low is None:
        return False
    return (prior_high - prior_low) > _MAX_CANDLE_ATR * atr


def _at_range_extreme(side: str, level: float | None, high_20: float | None, low_20: float | None) -> bool:
    """True when the break level is already the high or low of the last 20 sessions."""
    if level is None or level <= 0:
        return False
    if side == "buy":
        return high_20 is not None and high_20 > 0 and level >= high_20
    return low_20 is not None and low_20 > 0 and level <= low_20


_FUTURES_LABEL = {
    "long_buildup": "futures long build-up",
    "short_buildup": "futures short build-up",
    "short_covering": "futures short covering",
    "long_unwinding": "futures long unwinding",
    "neutral": "futures neutral",
}


def _futures_block(side: str, quadrant: str | None, rollover: bool) -> str | None:
    """Veto only the two readings whose price sign fights the side.

    A buy into short build-up, and a sell into long build-up, stand aside.
    Short covering and long unwinding are labelled, not blocked: five live
    sessions were not enough to show they help. Near-month open interest
    during rollover week is a roll, so it is ignored. All-months open
    interest is not on this feed.
    """
    if rollover or quadrant is None:
        return None
    trigger = "high" if side == "buy" else "low"
    if side == "buy" and quadrant == "short_buildup":
        return f"Yesterday's {trigger} is broken, but futures show short build-up"
    if side == "sell" and quadrant == "long_buildup":
        return f"Yesterday's {trigger} is broken, but futures show long build-up"
    return None


def _futures_label(quadrant: str | None, rollover: bool) -> str | None:
    """The reading to show on a call. A roll is not a build-up."""
    if rollover:
        return "rollover week"
    if quadrant is None:
        return None
    return _FUTURES_LABEL.get(quadrant)


def _coil_watch(reason: str) -> bool:
    """The 20-day story stood aside, so a tight base is still allowed to speak."""
    return reason.startswith((
        "The 20-day path is a range",
        "Daily trend and the last candle do not agree",
        "The 5-day move is against this side",
        "Price is still within 2% of the 20-day average",
        "Yesterday's range is under 0.8 ATR",
        "Yesterday's range is over 1.8 ATR",
        "Yesterday's high is already the 20-day high",
        "Yesterday's low is already the 20-day low",
        "The 20-day trend is there, but yesterday's candle has no usable range",
    ))


def _coil_break(
    quote: dict[str, Any],
    *,
    ltp: float,
    atr: float | None,
    spread: float | None,
    quadrant: str | None,
    rollover: bool,
    participating: bool,
    wide_spread: bool,
    spread_pct: float | None,
    above_vwap: bool,
    below_vwap: bool,
) -> dict[str, Any] | None:
    """Buy or sell a break of the last 8 sessions when that span is a coil.

    The side is the break itself. A print still inside the box is not a call.
    The same 0.15R window, VWAP, spread, volume, and futures vetoes apply.
    """
    if atr is None or atr <= 0:
        return None
    high = _optional_float(quote.get("coil_high"))
    low = _optional_float(quote.get("coil_low"))
    if high is None or low is None or high <= low:
        return None
    width = high - low
    if width < _COIL_MIN_ATR * atr or width > _COIL_MAX_ATR * atr:
        return None
    box = f"{low:.2f}–{high:.2f}"
    if low < ltp < high:
        return {
            "stance": "stand_aside",
            "phase": "none",
            "reason": f"Price is inside an 8-day coil ({box}). A call needs a break of that range.",
            "plan": None,
            "setup": "coil",
        }
    if ltp >= high:
        side = "buy"
        plan = candle_plan("buy", high, low, atr=atr, spread=spread)
        trigger = "high"
    else:
        side = "sell"
        plan = candle_plan("sell", low, high, atr=atr, spread=spread)
        trigger = "low"
    if plan is None:
        return None
    level = high if side == "buy" else low
    if _at_range_extreme(
        side,
        level,
        _optional_float(quote.get("high_20")),
        _optional_float(quote.get("low_20")),
    ):
        return None
    crossed = (ltp - plan["entry"]) if side == "buy" else (plan["entry"] - ltp)
    in_window = 0 <= crossed <= _ENTRY_WINDOW * plan["risk"]
    futures_block = _futures_block(side, quadrant, rollover)
    if not in_window:
        return {
            "stance": "stand_aside",
            "phase": "late",
            "reason": (
                f"The break of the 8-day coil ({box}) already ran. "
                "Do not chase ticks. Wait for a pullback to that range"
            ),
            "plan": plan,
            "setup": "coil",
        }
    if futures_block:
        fought = "short build-up" if side == "buy" else "long build-up"
        return {
            "stance": "stand_aside",
            "phase": "enter",
            "reason": f"The 8-day coil is broken, but futures show {fought}",
            "plan": plan,
            "setup": "coil",
        }
    if side == "buy" and not above_vwap:
        reason = "The 8-day coil is broken higher, but price is still under VWAP"
        stance = "wait"
    elif side == "sell" and not below_vwap:
        reason = "The 8-day coil is broken lower, but price is still above VWAP"
        stance = "wait"
    elif wide_spread and spread_pct is not None:
        reason = f"The 8-day coil is broken, but the spread is {spread_pct:.2f}%. Wait for the book"
        stance = "wait"
    elif not participating:
        reason = "The 8-day coil is broken, but volume is still light"
        stance = "wait"
    elif side == "buy":
        reason = f"An 8-day coil ({box}) is breaking higher. Buy the break of {high:.2f}"
        label = _futures_label(quadrant, rollover)
        if label:
            reason += f", {label}"
        stance = "buy"
    else:
        reason = f"An 8-day coil ({box}) is breaking lower. Sell the break of {low:.2f}"
        label = _futures_label(quadrant, rollover)
        if label:
            reason += f", {label}"
        stance = "sell"
    return {"stance": stance, "phase": "enter", "reason": reason, "plan": plan, "setup": "coil", "trigger": trigger}


def _is_stale(tick_age: float | None, now: float | None) -> bool:
    """Without a clock (pure tests) nothing is stale. With one, no print or an old print is."""
    if now is None:
        return False
    return tick_age is None or tick_age > _STALE_TICK_SEC


def session_call(quote: dict[str, Any], progress: float, now: float | None = None) -> dict[str, Any]:
    """Buy or sell on a break of yesterday's candle, or of a tight 8-day coil.

    The 20-day trend chooses the first side, and only when the path is
    efficient, the close is at least 2% through the 20-day average, and the
    5-day move agrees. When that story stands aside, a coil of the last 8
    sessions can still call the break of its own high or low. Non-F&O names
    and prices under ₹100 stay aside. Stop is the other side of the level,
    bounded by ATR. The day exit is two times that risk. The swing exit is
    2.5R. A buy into futures short build-up, or a sell into long build-up,
    stands aside. Other futures readings are labelled on the call. A print
    that is merely green or red stays on Wait.
    """
    ltp = float(quote.get("ltp") or 0)
    prev_close = float(quote.get("prev_close") or 0)
    atp = float(quote.get("atp") or 0)
    sma = _optional_float(quote.get("sma20"))
    prior_high = _optional_float(quote.get("prior_high"))
    prior_low = _optional_float(quote.get("prior_low"))
    trend = quote.get("trend_20_pct")
    trend_pct = float(trend) if isinstance(trend, (int, float)) else None
    efficiency = quote.get("efficiency_20")
    efficiency = float(efficiency) if isinstance(efficiency, (int, float)) else None
    atr_pct = _optional_float(quote.get("atr_pct"))
    spread_pct = quote.get("spread_pct")
    spread_pct = float(spread_pct) if isinstance(spread_pct, (int, float)) else None
    history_bars = int(quote.get("history_bars") or 0)
    kind = str(quote.get("kind") or "equity")
    is_index = kind == "index"
    change_pct = _pct(ltp, prev_close) if ltp and prev_close else None
    vs_sma = _pct(ltp, sma) if ltp and sma else None
    sess = session_rvol(float(quote.get("vtt") or 0), quote.get("avg_volume_20"), progress)
    burst = _bursts(quote)
    rollover = _rollover(quote)
    _, oi_change, quadrant = (None, None, None) if is_index else _oi_read(quote)
    tick_age = _tick_age(quote, now)

    stance = "stand_aside"
    phase = "none"
    reason = "Daily trend and the last candle do not agree"
    setup: str | None = None
    plan: dict[str, Any] | None = None
    if _weekend(now):
        reason = "Weekend session. A one-hour day does not fit this break"
    elif not is_index and _segment(quote) == "cash":
        reason = "Non-F&O names stay off the session call"
    elif history_bars < MIN_HISTORY_BARS or sma is None or prev_close <= 0 or ltp <= 0:
        reason = "Not enough daily history for a call"
    else:
        trend = trend_side(prev_close, sma, trend_pct)
        history_up = trend == "buy"
        history_down = trend == "sell"
        choppy = efficiency is not None and efficiency < _MIN_EFFICIENCY
        above_vwap = atp <= 0 or ltp >= atp
        below_vwap = atp <= 0 or ltp <= atp
        participating = is_index or (sess is not None and sess >= 0.8) or (burst is not None and burst >= 1.2)
        max_spread = max(_MAX_SPREAD_PCT, 0.15 * (atr_pct or 0))
        wide_spread = not is_index and spread_pct is not None and spread_pct > max_spread
        side = "buy" if history_up else "sell" if history_down else None
        atr = (atr_pct / 100.0 * prev_close) if atr_pct else None
        spread = (spread_pct / 100.0 * ltp) if spread_pct else None
        if side == "buy" and prior_high and prior_low:
            plan = candle_plan("buy", prior_high, prior_low, atr=atr, spread=spread)
        elif side == "sell" and prior_high and prior_low:
            plan = candle_plan("sell", prior_low, prior_high, atr=atr, spread=spread)
        futures_block = _futures_block(side or "", quadrant, rollover) if side else None
        return_5d = quote.get("return_5d_pct")

        if side is not None and choppy:
            plan = None
            reason = (
                f"The 20-day path is a range (efficiency {efficiency:.2f}). "
                "The trend reading is noise; no side to take"
            )
        elif plan is None or side is None:
            if history_up or history_down:
                reason = "The 20-day trend is there, but yesterday's candle has no usable range"
        elif not is_index and prev_close < _MIN_PRICE:
            plan = None
            reason = "Price is under ₹100. That book lost more than the rest"
        elif _return_against(side, return_5d):
            plan = None
            reason = "The 5-day move is against this side"
        elif _sma_distance_pct(prev_close, sma) < _MIN_SMA_DISTANCE_PCT:
            plan = None
            reason = "Price is still within 2% of the 20-day average"
        elif _narrow_candle(prior_high, prior_low, atr):
            plan = None
            reason = "Yesterday's range is under 0.8 ATR. The stop would sit in noise"
        elif _wide_candle(prior_high, prior_low, atr):
            plan = None
            reason = "Yesterday's range is over 1.8 ATR. The break is already extended"
        elif _sma_distance_pct(prev_close, sma) >= _MAX_SMA_DISTANCE_PCT:
            plan = None
            reason = "Price is more than 8% through the 20-day average"
        elif _at_range_extreme(
            side,
            prior_high if side == "buy" else prior_low,
            _optional_float(quote.get("high_20")),
            _optional_float(quote.get("low_20")),
        ):
            plan = None
            edge = "high" if side == "buy" else "low"
            reason = f"Yesterday's {edge} is already the 20-day {edge}"
        else:
            entry = plan["entry"]
            risk = plan["risk"]
            crossed = (ltp - entry) if side == "buy" else (entry - ltp)
            in_window = 0 <= crossed <= _ENTRY_WINDOW * risk
            trigger = "high" if side == "buy" else "low"
            if crossed < 0:
                stance = "wait"
                phase = "wait"
                if side == "buy":
                    reason = "Uptrend. Green ticks are not an entry. Buy only through yesterday's high"
                else:
                    reason = "Downtrend. Red ticks are not an entry. Sell only through yesterday's low"
            elif in_window and futures_block:
                phase = "enter"
                reason = futures_block
            elif in_window and side == "buy" and not above_vwap:
                stance = "wait"
                phase = "enter"
                reason = "Yesterday's high is broken, but price is still under VWAP"
            elif in_window and side == "sell" and not below_vwap:
                stance = "wait"
                phase = "enter"
                reason = "Yesterday's low is broken, but price is still above VWAP"
            elif in_window and wide_spread:
                stance = "wait"
                phase = "enter"
                reason = f"Yesterday's {trigger} is broken, but the spread is {spread_pct:.2f}%. Wait for the book"
            elif in_window and not participating:
                stance = "wait"
                phase = "enter"
                reason = f"Yesterday's {trigger} is broken, but volume is still light"
            elif in_window and side == "buy":
                stance = "buy"
                phase = "enter"
                reason = "Price is above the 20-day average. Buy the break of yesterday's high"
                label = _futures_label(quadrant, rollover)
                if label:
                    reason += f", {label}"
            elif in_window and side == "sell":
                stance = "sell"
                phase = "enter"
                reason = "Price is below the 20-day average. Sell the break of yesterday's low"
                label = _futures_label(quadrant, rollover)
                if label:
                    reason += f", {label}"
            else:
                phase = "late"
                reason = (
                    f"The break of yesterday's {trigger} already ran. "
                    "Do not chase ticks. Wait for a pullback to that candle"
                )
        if stance in {"buy", "sell", "wait"}:
            setup = "trend"
        cheap = not is_index and prev_close < _MIN_PRICE
        too_far = _sma_distance_pct(prev_close, sma) >= _MAX_SMA_DISTANCE_PCT
        if stance == "stand_aside" and phase == "none" and not cheap and not too_far and _coil_watch(reason):
            coil = _coil_break(
                quote,
                ltp=ltp,
                atr=atr,
                spread=spread,
                quadrant=quadrant,
                rollover=rollover,
                participating=participating,
                wide_spread=wide_spread,
                spread_pct=spread_pct,
                above_vwap=above_vwap,
                below_vwap=below_vwap,
            )
            if coil is not None:
                stance = coil["stance"]
                phase = coil["phase"]
                reason = coil["reason"]
                plan = coil["plan"]
                setup = coil["setup"]

    conviction = abs(change_pct or 0) * _vol_scale(atr_pct)
    if sess is not None and sess > 0:
        conviction += min(sess, 3)
    if stance == "wait" and plan is not None and ltp > 0:
        distance_pct = abs(ltp - plan["entry"]) / plan["entry"] * 100.0
        conviction = max(0.0, 5.0 - distance_pct * _vol_scale(atr_pct))
    if stance == "stand_aside":
        conviction = 0
    return {
        "symbol": quote["symbol"],
        "company_name": quote.get("company_name"),
        "sector": quote.get("sector"),
        "kind": kind,
        "segment": _segment(quote),
        "ltp": _round(ltp, 2) if ltp else None,
        "change_pct": _round(change_pct, 2),
        "vs_sma_pct": _round(vs_sma, 2),
        "trend_20_pct": _round(trend_pct, 2),
        "efficiency_20": _round(efficiency, 2),
        "atr_pct": _round(atr_pct, 2),
        "return_5d_pct": _round(
            float(quote["return_5d_pct"]) if isinstance(quote.get("return_5d_pct"), (int, float)) else None,
            2,
        ),
        "session_rvol": _round(sess, 2),
        "spread_pct": _round(spread_pct, 3),
        "stance": stance,
        "stance_label": {"buy": "Buy", "sell": "Sell", "wait": "Wait", "stand_aside": "Stand aside"}[stance],
        "reason": reason,
        "entry": _round(plan["entry"], 2) if plan else None,
        "stop": _round(plan["stop"], 2) if plan else None,
        "exit": _round(plan["exit"], 2) if plan else None,
        "swing_exit": _round(plan["swing_exit"], 2) if plan else None,
        "swing_basis": plan["swing_basis"] if plan else None,
        "stop_basis": plan["basis"] if plan else None,
        "plan_phase": phase,
        "setup": setup,
        "coil_high": _round(_optional_float(quote.get("coil_high")), 2),
        "coil_low": _round(_optional_float(quote.get("coil_low")), 2),
        "quadrant": quadrant,
        "oi_change_pct": _round(oi_change, 2),
        "rollover_week": rollover,
        "on_last_scan": bool(quote.get("on_last_scan")),
        "tick_age_sec": _round(tick_age, 1),
        "stale": _is_stale(tick_age, now),
        "score": _round(conviction, 2),
    }


def rank_boards(
    quotes: list[dict[str, Any]],
    *,
    progress: float,
    baskets: dict[str, list[str]] | None = None,
    now: float | None = None,
) -> dict[str, list[dict[str, Any]]]:
    priced = [quote for quote in quotes if quote.get("ltp")]
    momentum = [rank_momentum(quote, progress) for quote in priced]
    momentum.sort(key=lambda row: float(row.get("score") or 0), reverse=True)

    breakout = [rank_breakout(quote) for quote in priced]
    breakout.sort(
        key=lambda row: (
            _BREAKOUT_RANK.get(str(row.get("state")), 9),
            row.get("nearest_distance_pct") if row.get("nearest_distance_pct") is not None else 999,
        )
    )

    oi_rows = [
        rank_oi(quote)
        for quote in quotes
        if quote.get("future_key") and (quote.get("fut_ltp") or quote.get("fut_oi"))
    ]
    oi_rows.sort(
        key=lambda row: (
            _OI_PRIORITY.get(str(row.get("quadrant")), 9),
            -abs(float(row["oi_change_pct"])) if row.get("oi_change_pct") is not None else 0.0,
        )
    )
    calls = [session_call(quote, progress, now) for quote in priced]
    calls.sort(
        key=lambda row: (
            _CALL_RANK.get(str(row.get("stance")), 9),
            0 if row.get("kind") == "index" else 1,
            -float(row.get("score") or 0),
        )
    )
    reads = index_reads(quotes, baskets or default_baskets())
    for row in calls:
        if row.get("kind") == "index":
            row.update(reads.get(str(row.get("symbol"))) or {})
    return {"momentum": momentum, "breakout": breakout, "oi": oi_rows, "calls": calls}


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number
