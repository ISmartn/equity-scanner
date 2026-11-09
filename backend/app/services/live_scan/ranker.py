"""One-second boards. Pure functions over a copied quote list — no database and no socket lock."""

from __future__ import annotations

import math
import statistics
from typing import Any

from ..scanner.fo_overlay import (
    OI_DOWN_THRESHOLD_PCT,
    OI_UP_THRESHOLD_PCT,
    PRICE_UP_THRESHOLD_PCT,
    QUADRANT_LABELS,
)
from .baskets import default_baskets, index_reads

TESTING_BAND = 0.003
MIN_HISTORY_BARS = 10
_CALL_RANK = {"buy": 0, "sell": 1, "wait": 2, "stand_aside": 3}
# A completed daily candle is the signal. Price may only be this far through it
# before the break is a chase rather than an entry. The day exit is two times
# the intraday-sized risk. The multi-session target is further: the full candle's
# 2R when that had to be cut to stay reachable today, otherwise four times the
# day risk. The journal can hold that target past the cash close.
_REWARD_R = 2.0
_SWING_R = 4.0
_ENTRY_WINDOW = 0.35
# Stops are yesterday's candle, bounded by volatility. Inside a 0.5 ATR range the
# stop sits in noise; beyond 1.5 ATR a 2R target is out of intraday reach.
_RISK_MIN_ATR = 0.5
_RISK_MAX_ATR = 1.5
_RISK_MIN_SPREADS = 4.0
# Kaufman efficiency below this is a range, not a trend, whatever the endpoints say.
_MIN_EFFICIENCY = 0.2
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
    """Symmetric dead-band. A flat price with rising OI is neutral, not short build-up."""
    price_up = price_change_pct > PRICE_UP_THRESHOLD_PCT
    price_down = price_change_pct < -PRICE_UP_THRESHOLD_PCT
    oi_up = oi_change_pct > OI_UP_THRESHOLD_PCT
    oi_down = oi_change_pct < OI_DOWN_THRESHOLD_PCT
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
    # had to shrink it. Otherwise four R of the day risk is the further target.
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


def _is_stale(tick_age: float | None, now: float | None) -> bool:
    """Without a clock (pure tests) nothing is stale. With one, no print or an old print is."""
    if now is None:
        return False
    return tick_age is None or tick_age > _STALE_TICK_SEC


def session_call(quote: dict[str, Any], progress: float, now: float | None = None) -> dict[str, Any]:
    """Buy or sell only on a break of yesterday's completed candle, not on tick color.

    The 20-day trend chooses the side, and only when the 20-day path is
    efficient enough to be a trend. Entry is that candle's high (buy) or low
    (sell). Stop is the other side of the same candle, bounded by ATR. The day
    exit is two times that risk. The swing exit is the multi-session target.
    A print that is merely green or red stays on Wait.
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
    quadrant = None if is_index else _quote_quadrant(quote)
    tick_age = _tick_age(quote, now)

    stance = "stand_aside"
    phase = "none"
    reason = "Daily trend and the last candle do not agree"
    plan: dict[str, Any] | None = None
    if history_bars < MIN_HISTORY_BARS or sma is None or prev_close <= 0 or ltp <= 0:
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
        blocks_buy = quadrant == "short_buildup" and not rollover
        blocks_sell = quadrant == "long_buildup" and not rollover
        side = "buy" if history_up else "sell" if history_down else None
        atr = (atr_pct / 100.0 * prev_close) if atr_pct else None
        spread = (spread_pct / 100.0 * ltp) if spread_pct else None
        if side == "buy" and prior_high and prior_low:
            plan = candle_plan("buy", prior_high, prior_low, atr=atr, spread=spread)
        elif side == "sell" and prior_high and prior_low:
            plan = candle_plan("sell", prior_low, prior_high, atr=atr, spread=spread)

        if side is not None and choppy:
            plan = None
            reason = (
                f"The 20-day path is a range (efficiency {efficiency:.2f}). "
                "The trend reading is noise; no side to take"
            )
        elif plan is None or side is None:
            if history_up or history_down:
                reason = "The 20-day trend is there, but yesterday's candle has no usable range"
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
            elif in_window and side == "buy" and blocks_buy:
                phase = "enter"
                reason = "Yesterday's high is broken, but futures show short build-up"
            elif in_window and side == "sell" and blocks_sell:
                phase = "enter"
                reason = "Yesterday's low is broken, but futures show long build-up"
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
                if quadrant == "long_buildup":
                    reason += ", with futures long build-up"
            elif in_window and side == "sell":
                stance = "sell"
                phase = "enter"
                reason = "Price is below the 20-day average. Sell the break of yesterday's low"
                if quadrant in {"short_buildup", "long_unwinding"}:
                    reason += ", with futures supply"
            else:
                phase = "late"
                reason = (
                    f"The break of yesterday's {trigger} already ran. "
                    "Do not chase ticks. Wait for a pullback to that candle"
                )

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
        "quadrant": quadrant,
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
