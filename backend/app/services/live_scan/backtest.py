"""Replay the Session Call board on daily candles, and score the saved live record.

The replay
----------
For every symbol and session it rebuilds the morning context the live board
loads (the 20 sessions before the day, same statistics as
``_daily_history_stats``), picks the side with ``trend_side``, drops ranges
under the efficiency floor, and sizes the plan with ``candle_plan``. The day's
bar then decides the outcome, under the journal's rules:

* Open through the entry inside the window: filled at the open.
* Otherwise filled at the entry if the day's range reaches it.
* Open beyond the entry window (a chase): filled at the entry if price came back
  under it, as the journal records a fresh plan on the pullback. Open through
  the stop: filled at the entry if the day's range climbs back to it.
* Whenever one bar cannot say which level came first, the session is replayed
  minute by minute through the journal's own ``advance_plan`` if the live feed
  stored that session's minute bars from open to close. Otherwise the worse
  order is booked and the trade is flagged; ``order_bounds`` gives the other end.
* The day leg books the target, the stop, or the close. The swing leg keeps the
  same stop and carries forward until its own target, the stop, or
  ``max_swing_days`` sessions.

Daily bars cannot show VWAP, session volume, the spread, or the futures OI
quadrant. Live, those gates only decide fills on a gap through the entry; a
plan first seen below its entry fills at the entry without them. The universe
is today's F&O list and today's liquid cash names, so names that were delisted
or dropped out of F&O are missing.
"""

from __future__ import annotations

import json
import math
import statistics
import threading
import time
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable

import numpy as np

from ...config import normalize_symbol
from ...db.store import TimelineStore, get_store
from ..market_calendar import expected_latest_session
from .clocks import SESSION_CLOSE, now_ist
from .journal import CallJournal, advance_plan
from .ranker import (
    _ENTRY_WINDOW,
    _MIN_EFFICIENCY,
    _REWARD_R,
    _RISK_MAX_ATR,
    _RISK_MIN_ATR,
    _SWING_R,
    candle_plan,
    trend_side,
)
from .universe import (
    CACHE_PATH,
    FULL_MODE_KEY_LIMIT,
    LIVE_INDEXES,
    MIN_CASH_HISTORY_BARS,
    _as_list,
    _profiles_for_symbols,
    select_cash_symbols,
)

WINDOW = 20
_ATR_BARS = 14
_RETURN_BARS = 5
# Calendar days loaded before ``start`` so the first session has 20 bars behind it.
_WARMUP_DAYS = 45
_TOKEN_CHUNK = 200
_SEGMENTS = {"fno", "cash", "all"}
_SIDES = {"buy", "sell", "both"}
_SWEEP_R = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0)
_CACHE_TTL_SEC = 600.0
_CACHE_SIZE = 8
_MAX_RANGE_DAYS = 6 * 366
_MIN_SESSION_MINUTES = 300
_LATEST_FIRST_MINUTE = "09:20"
_EARLIEST_LAST_MINUTE = "15:25"


@dataclass(frozen=True)
class BacktestParams:
    start: str
    end: str
    segment: str = "all"
    side: str = "both"
    reward_r: float = _REWARD_R
    swing_r: float = _SWING_R
    entry_window_r: float = _ENTRY_WINDOW
    min_efficiency: float = _MIN_EFFICIENCY
    risk_min_atr: float = _RISK_MIN_ATR
    risk_max_atr: float = _RISK_MAX_ATR
    max_swing_days: int = 20
    cost_pct: float = 0.05

    def checked(self) -> "BacktestParams":
        start = date.fromisoformat(self.start)
        end = date.fromisoformat(self.end)
        if end < start:
            raise ValueError("end must be on or after start")
        if (end - start).days > _MAX_RANGE_DAYS:
            raise ValueError("date range is limited to six years")
        if self.segment not in _SEGMENTS:
            raise ValueError("segment must be fno, cash, or all")
        if self.side not in _SIDES:
            raise ValueError("side must be buy, sell, or both")
        if not 0 < self.reward_r <= 20 or not 0 < self.swing_r <= 40:
            raise ValueError("reward_r and swing_r must be positive")
        if self.swing_r < self.reward_r:
            raise ValueError("swing_r must be at least reward_r")
        if not 0 <= self.entry_window_r <= 5:
            raise ValueError("entry_window_r must be between 0 and 5")
        if not 0 <= self.min_efficiency < 1:
            raise ValueError("min_efficiency must be between 0 and 1")
        if not 0 <= self.risk_min_atr <= self.risk_max_atr:
            raise ValueError("risk_min_atr must be between 0 and risk_max_atr")
        if not 0 <= self.max_swing_days <= 250:
            raise ValueError("max_swing_days must be between 0 and 250")
        if not 0 <= self.cost_pct <= 2:
            raise ValueError("cost_pct must be between 0 and 2")
        return replace(self, start=start.isoformat(), end=end.isoformat())


@dataclass(frozen=True, slots=True)
class BacktestSymbol:
    symbol: str
    token: str
    segment: str
    kind: str = "equity"


@dataclass(slots=True)
class Trade:
    trade_date: str
    symbol: str
    segment: str
    side: str
    entry: float
    stop: float
    target: float
    swing_target: float
    fill: float
    fill_type: str
    plan_risk: float
    stop_basis: str
    best_price: float
    close_price: float
    day_status: str
    day_r: float
    day_pct: float
    mfe_r: float
    mae_r: float
    swing_status: str
    swing_r: float | None
    swing_pct: float | None
    swing_days: int
    swing_closed_on: str | None
    efficiency: float
    atr_pct: float
    trend_pct: float
    return_5d_pct: float
    vs_sma_pct: float
    candle_atr: float
    at_20d_extreme: bool
    # The bar cannot say which came first. ``alt_day_r`` is the favourable order,
    # None when that order is a plan cancelled before its entry.
    ambiguous: bool = False
    alt_day_r: float | None = None
    # "minute" when the day was replayed through stored live minute bars.
    resolution: str = "daily"


@dataclass
class Funnel:
    sessions: int = 0
    no_trend: int = 0
    choppy: int = 0
    no_plan: int = 0
    wrong_side: int = 0
    through_stop: int = 0
    chased_gap: int = 0
    not_triggered: int = 0
    cancelled_intraday: int = 0
    filled: int = 0
    minute_resolved: int = 0


# ------------------------------------------------------------------ universe


def _fno_symbols_from_cache() -> set[str]:
    """Underlyings in the cached Upstox futures dump, whatever its age."""
    if not CACHE_PATH.exists():
        return set()
    try:
        rows = _as_list(json.loads(CACHE_PATH.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return set()
    symbols: set[str] = set()
    for row in rows:
        underlying_type = str(row.get("underlying_type") or row.get("asset_type") or "").upper()
        if underlying_type and underlying_type not in {"EQUITY", "EQ"}:
            continue
        symbol = normalize_symbol(str(row.get("underlying_symbol") or row.get("asset_symbol") or ""))
        if symbol:
            symbols.add(symbol)
    return symbols


def backtest_universe(
    segment: str,
    as_of: str,
    *,
    store: TimelineStore | None = None,
    fno_symbols: set[str] | None = None,
) -> tuple[list[BacktestSymbol], list[str]]:
    """The live universe rebuilt offline: indexes, F&O names, then liquid cash names."""
    db = store or get_store()
    warnings: list[str] = []
    fno = fno_symbols if fno_symbols is not None else _fno_symbols_from_cache()
    if not fno:
        warnings.append("No cached F&O list. Start the live scan once to download it; F&O names are missing.")
    profiles = _profiles_for_symbols(sorted(fno)) if fno else {}
    universe: list[BacktestSymbol] = []
    if segment in {"fno", "all"}:
        universe.extend(
            BacktestSymbol(symbol=item.symbol, token=item.cash_key, segment="index", kind="index")
            for item in LIVE_INDEXES
        )
        universe.extend(
            BacktestSymbol(symbol=symbol, token=str(profiles[symbol]["instrument_token"]), segment="fno")
            for symbol in sorted(profiles)
        )
    if segment in {"cash", "all"}:
        room = max(0, FULL_MODE_KEY_LIMIT - 2 * len(profiles) - len(LIVE_INDEXES))
        candidates = db.liquid_cash_profiles(as_of, MIN_CASH_HISTORY_BARS)
        chosen = select_cash_symbols(
            candidates,
            exclude=set(fno),
            room=room,
            exclude_keys={str(row["instrument_token"]) for row in profiles.values()},
        )
        universe.extend(
            BacktestSymbol(
                symbol=normalize_symbol(str(row["ticker"])),
                token=str(row["instrument_token"]),
                segment="cash",
            )
            for row in chosen
        )
    return universe, warnings


# ------------------------------------------------------------------- context


def morning_context(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
) -> dict[str, np.ndarray]:
    """Context for session ``t`` from bars ``t-20 .. t-1``. Rows before index 20 are NaN.

    Matches ``_daily_history_stats`` on a full 20-bar window: mean close, path
    efficiency over the 20 closes, simple 14-bar true range over the last close.
    """
    n = len(closes)
    out = {name: np.full(n, np.nan) for name in ("sma", "trend", "eff", "atr_pct", "ret5", "high20", "low20")}
    if n <= WINDOW:
        return out
    idx = np.arange(WINDOW, n)
    last = closes[idx - 1]
    oldest = closes[idx - WINDOW]
    csum = np.concatenate(([0.0], np.cumsum(closes)))
    out["sma"][idx] = (csum[idx] - csum[idx - WINDOW]) / WINDOW
    out["trend"][idx] = (last - oldest) / oldest * 100.0
    steps = np.concatenate(([0.0], np.cumsum(np.abs(np.diff(closes)))))
    path = steps[idx - 1] - steps[idx - WINDOW]
    with np.errstate(divide="ignore", invalid="ignore"):
        out["eff"][idx] = np.where(path > 0, np.abs(last - oldest) / path, np.nan)
    prev = np.concatenate(([np.nan], closes[:-1]))
    true_range = np.maximum.reduce([highs - lows, np.abs(highs - prev), np.abs(lows - prev)])
    true_range[0] = 0.0
    tr_sum = np.concatenate(([0.0], np.cumsum(true_range)))
    out["atr_pct"][idx] = (tr_sum[idx] - tr_sum[idx - _ATR_BARS]) / _ATR_BARS / last * 100.0
    back = closes[idx - 1 - _RETURN_BARS]
    out["ret5"][idx] = (last - back) / back * 100.0
    windows_h = np.lib.stride_tricks.sliding_window_view(highs, WINDOW)
    windows_l = np.lib.stride_tricks.sliding_window_view(lows, WINDOW)
    out["high20"][idx] = windows_h[idx - WINDOW].max(axis=1)
    out["low20"][idx] = windows_l[idx - WINDOW].min(axis=1)
    return out


# ---------------------------------------------------------------- simulation


def _r(side: str, fill: float, price: float, risk: float, cost: float) -> float:
    move = price - fill if side == "buy" else fill - price
    return (move - cost) / risk


def _pct(side: str, fill: float, price: float, cost_pct: float) -> float:
    move = (price - fill) / fill * 100.0
    return (move if side == "buy" else -move) - cost_pct


MinutePath = list[tuple[str, float, float, float, float]]


def simulate_symbol(
    item: BacktestSymbol,
    bars: list[tuple[str, float, float, float, float]],
    params: BacktestParams,
    funnel: Funnel,
    minutes: Callable[[str], MinutePath | None] | None = None,
) -> list[Trade]:
    """Every session of one symbol inside ``params.start .. params.end``. Bars oldest first.

    ``minutes(day)`` returns that session's full minute path, or None. It is only
    asked for days the daily bar cannot resolve.
    """
    clean = [bar for bar in bars if bar[1] > 0 and bar[2] > 0 and bar[3] > 0 and bar[4] > 0 and bar[2] >= bar[3]]
    if len(clean) <= WINDOW:
        return []
    dates = [bar[0] for bar in clean]
    opens = [bar[1] for bar in clean]
    highs = [bar[2] for bar in clean]
    lows = [bar[3] for bar in clean]
    closes = [bar[4] for bar in clean]
    ctx = morning_context(np.array(highs), np.array(lows), np.array(closes))
    sma_a = ctx["sma"].tolist()
    trend_a = ctx["trend"].tolist()
    eff_a = ctx["eff"].tolist()
    atr_a = ctx["atr_pct"].tolist()
    ret5_a = ctx["ret5"].tolist()
    high20_a = ctx["high20"].tolist()
    low20_a = ctx["low20"].tolist()
    n = len(clean)
    trades: list[Trade] = []
    for t in range(WINDOW, n):
        day = dates[t]
        if day < params.start:
            continue
        if day > params.end:
            break
        funnel.sessions += 1
        prev_close = closes[t - 1]
        sma = sma_a[t]
        trend = trend_a[t]
        side = trend_side(prev_close, sma, trend)
        if side is None:
            funnel.no_trend += 1
            continue
        if params.side != "both" and side != params.side:
            funnel.wrong_side += 1
            continue
        eff = eff_a[t]
        if not math.isnan(eff) and eff < params.min_efficiency:
            funnel.choppy += 1
            continue
        atr_pct = atr_a[t]
        atr = atr_pct / 100.0 * prev_close if not math.isnan(atr_pct) and atr_pct > 0 else None
        prior_high = highs[t - 1]
        prior_low = lows[t - 1]
        plan = candle_plan(
            side,
            prior_high if side == "buy" else prior_low,
            prior_low if side == "buy" else prior_high,
            atr=atr,
            reward_r=params.reward_r,
            swing_r=params.swing_r,
            risk_min_atr=params.risk_min_atr,
            risk_max_atr=params.risk_max_atr,
        )
        if plan is None:
            funnel.no_plan += 1
            continue
        entry = float(plan["entry"])
        stop = float(plan["stop"])
        target = float(plan["exit"])
        swing_target = float(plan["swing_exit"])
        plan_risk = float(plan["risk"])
        o, h, l, c = opens[t], highs[t], lows[t], closes[t]
        buy = side == "buy"
        reaches_entry = (h >= entry) if buy else (l <= entry)
        crossed_open = (o - entry) if buy else (entry - o)
        # The journal records a plan the first second price sits between the stop
        # and the entry, so a gap through either level can still fill later in the day.
        if (o <= stop) if buy else (o >= stop):
            if not reaches_entry:
                funnel.through_stop += 1
                continue
            fill, fill_type = entry, "recovery"
        elif crossed_open > params.entry_window_r * plan_risk:
            back_under = (l < entry) if buy else (h > entry)
            if not back_under:
                funnel.chased_gap += 1
                continue
            fill, fill_type = entry, "pullback"
        elif crossed_open >= 0:
            fill, fill_type = o, "open"
        elif reaches_entry:
            fill, fill_type = entry, "level"
        else:
            funnel.not_triggered += 1
            continue
        funnel.filled += 1
        risk = abs(fill - stop)
        cost = params.cost_pct / 100.0 * fill
        best = h if buy else l
        worst = l if buy else h
        stop_hit = (l <= stop) if buy else (h >= stop)
        target_hit = (h >= target) if buy else (l <= target)
        # After a pullback fill the day's extreme was most likely the gap, before the entry.
        credit_target = target_hit and fill_type != "pullback"
        if stop_hit:
            day_status, day_exit = "stopped", stop
        elif credit_target:
            day_status, day_exit = "target", target
        else:
            day_status, day_exit = "closed", c
        # A pullback that closes back under the entry may never have crossed it again.
        unconfirmed = fill_type == "pullback" and ((c < entry) if buy else (c > entry))
        ambiguous = (
            (stop_hit and (target_hit or fill_type != "open"))
            or (target_hit and not credit_target)
            or unconfirmed
        )
        alt_day_r: float | None = None
        if ambiguous:
            if target_hit:
                alt_day_r = _r(side, fill, target, risk, cost)
            elif fill_type == "recovery":
                alt_day_r = _r(side, fill, c, risk, cost)

        replayed = None
        if ambiguous and minutes is not None:
            path = minutes(day)
            if path is not None:
                replayed = replay_minutes(side, plan, path, params.entry_window_r)
                if replayed is None:
                    funnel.filled -= 1
                    funnel.cancelled_intraday += 1
                    continue
        resolution = "daily"
        if replayed is not None:
            funnel.minute_resolved += 1
            resolution = "minute"
            ambiguous, alt_day_r = False, None
            fill = float(replayed["fill_price"])
            risk = abs(fill - stop)
            cost = params.cost_pct / 100.0 * fill
            day_status = str(replayed["status"])
            day_exit = _price_at(side, fill, float(replayed["result_pct"]))
            best = _price_at(side, fill, float(replayed.get("mfe_pct") or 0.0))
            worst = _price_at(side, fill, float(replayed.get("mae_pct") or 0.0))
            swing_day = str(replayed.get("swing_status") or "")
            if swing_day in {"target", "stopped"}:
                swing_status, swing_days, swing_on = swing_day, 0, t
                swing_exit = _price_at(side, fill, float(replayed["swing_result_pct"]))
            else:
                swing_status, swing_exit, swing_days, swing_on = _swing_leg(
                    buy, t, stop, swing_target, "closed", opens, highs, lows, closes,
                    params.max_swing_days, credit_today=False,
                )
        else:
            swing_status, swing_exit, swing_days, swing_on = _swing_leg(
                buy,
                t,
                stop,
                swing_target,
                day_status,
                opens,
                highs,
                lows,
                closes,
                params.max_swing_days,
                credit_today=fill_type != "pullback",
            )
        swing_r = _r(side, fill, swing_exit, risk, cost) if swing_exit is not None else None
        swing_pct = _pct(side, fill, swing_exit, params.cost_pct) if swing_exit is not None else None
        extreme = (prior_high >= high20_a[t]) if buy else (prior_low <= low20_a[t])
        ret5 = ret5_a[t]
        trades.append(
            Trade(
                trade_date=day,
                symbol=item.symbol,
                segment=item.segment,
                side=side,
                entry=entry,
                stop=stop,
                target=target,
                swing_target=swing_target,
                fill=fill,
                fill_type=fill_type,
                plan_risk=plan_risk,
                stop_basis=str(plan["basis"]),
                best_price=best,
                close_price=c,
                day_status=day_status,
                day_r=_r(side, fill, day_exit, risk, cost),
                day_pct=_pct(side, fill, day_exit, params.cost_pct),
                mfe_r=_r(side, fill, best, risk, 0.0),
                mae_r=_r(side, fill, worst, risk, 0.0),
                swing_status=swing_status,
                swing_r=swing_r,
                swing_pct=swing_pct,
                swing_days=swing_days,
                swing_closed_on=dates[swing_on] if swing_on is not None else None,
                efficiency=eff,
                atr_pct=atr_pct,
                trend_pct=trend,
                return_5d_pct=(ret5 if buy else -ret5) if not math.isnan(ret5) else math.nan,
                vs_sma_pct=((prev_close - sma) / sma * 100.0) * (1 if buy else -1),
                candle_atr=(prior_high - prior_low) / atr if atr else math.nan,
                at_20d_extreme=bool(extreme),
                ambiguous=ambiguous,
                alt_day_r=alt_day_r,
                resolution=resolution,
            )
        )
    return trades


def _price_at(side: str, fill: float, result_pct: float) -> float:
    return fill * (1.0 + result_pct / 100.0) if side == "buy" else fill * (1.0 - result_pct / 100.0)


def full_session(path: list[tuple[str, float, float, float, float]]) -> bool:
    """Minute bars from the open to the close. A feed that joined late cannot replay the morning."""
    if len(path) < _MIN_SESSION_MINUTES:
        return False
    return path[0][0][11:16] <= _LATEST_FIRST_MINUTE and path[-1][0][11:16] >= _EARLIEST_LAST_MINUTE


def replay_minutes(
    side: str,
    plan: dict[str, Any],
    path: list[tuple[str, float, float, float, float]],
    entry_window_r: float,
) -> dict[str, Any] | None:
    """One session through the journal's own rules, one minute window at a time.

    The plan is recorded the first time a minute opens or closes between the stop
    and the entry (pending), or inside the entry window past it (filled there).
    Returns the record after the session close, or None when nothing filled.
    """
    entry = float(plan["entry"])
    stop = float(plan["stop"])
    limit = entry_window_r * float(plan["risk"])
    journal = CallJournal(path[0][0][:10])
    record: dict[str, Any] | None = None
    for minute, o, h, l, c in path:
        stamp = f"{minute}:00"
        if record is not None:
            advance_plan(record, c, stamp, high=h, low=l, first=o)
            continue
        for price, rest in ((o, True), (c, False)):
            crossed = (price - entry) if side == "buy" else (entry - price)
            beyond_stop = (price <= stop) if side == "buy" else (price >= stop)
            if beyond_stop or crossed > limit:
                continue
            status = "open" if crossed >= 0 else "pending"
            record = _plan_record(side, plan, status, price, stamp)
            if rest:
                advance_plan(record, c, stamp, high=h, low=l, first=o)
            break
    if record is None:
        return None
    journal.load([record])
    journal.close_session(f"{path[-1][0]}:59")
    final = journal.persist_rows()[0]
    if final["status"] == "cancelled":
        return None
    return final


def _plan_record(side: str, plan: dict[str, Any], status: str, price: float, stamp: str) -> dict[str, Any]:
    """The fields ``CallJournal._create`` writes, for a plan first seen at ``price``."""
    filled = status == "open"
    return {
        "session_date": stamp[:10],
        "symbol": "replay",
        "side": side,
        "entry": float(plan["entry"]),
        "stop": float(plan["stop"]),
        "exit_price": float(plan["exit"]),
        "swing_exit": float(plan["swing_exit"]),
        "swing_status": "open" if filled else "pending",
        "swing_result_pct": 0.0 if filled else None,
        "status": status,
        "opened_at": stamp,
        "entry_at": stamp if filled else None,
        "fill_price": price if filled else None,
        "last_price": price,
        "best_price": price if filled else None,
        "worst_price": price if filled else None,
        "result_pct": 0.0 if filled else None,
        "mfe_pct": 0.0 if filled else None,
        "mae_pct": 0.0 if filled else None,
    }


def _swing_leg(
    buy: bool,
    t: int,
    stop: float,
    swing_target: float,
    day_status: str,
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    max_days: int,
    *,
    credit_today: bool = True,
) -> tuple[str, float | None, int, int | None]:
    """(status, exit price, sessions held after entry day, index of the exit bar)."""
    if day_status == "stopped":
        return "stopped", stop, 0, t
    if credit_today and ((highs[t] >= swing_target) if buy else (lows[t] <= swing_target)):
        return "target", swing_target, 0, t
    last = min(len(closes) - 1, t + max_days)
    for j in range(t + 1, last + 1):
        held = j - t
        o = opens[j]
        if (o <= stop) if buy else (o >= stop):
            return "stopped", o, held, j
        if (lows[j] <= stop) if buy else (highs[j] >= stop):
            return "stopped", stop, held, j
        if (highs[j] >= swing_target) if buy else (lows[j] <= swing_target):
            return "target", swing_target, held, j
    if last - t >= max_days:
        return "timeout", closes[last], last - t, last
    return "open", None, last - t, None


# ---------------------------------------------------------------- statistics


def leg_stats(results: list[float], statuses: list[str], pcts: list[float] | None = None) -> dict[str, Any]:
    """Win rate, R expectancy, and profit factor for one leg's resolved trades."""
    count = len(results)
    counts: dict[str, int] = {}
    for status in statuses:
        counts[status] = counts.get(status, 0) + 1
    if not count:
        return {"trades": 0, "statuses": counts}
    wins = [value for value in results if value > 0]
    losses = [value for value in results if value <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    return {
        "trades": count,
        "statuses": counts,
        "win_rate_pct": round(len(wins) / count * 100.0, 1),
        "avg_r": round(sum(results) / count, 3),
        "total_r": round(sum(results), 1),
        "median_r": round(statistics.median(results), 3),
        "avg_win_r": round(gross_win / len(wins), 3) if wins else None,
        "avg_loss_r": round(-gross_loss / len(losses), 3) if losses else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "avg_pct": round(sum(pcts) / len(pcts), 3) if pcts else None,
        "std_r": round(statistics.pstdev(results), 3) if count > 1 else None,
    }


def _bucket(value: float, edges: tuple[float, ...], fmt: str = "{:g}") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    for low, high in zip(edges, edges[1:]):
        if value < high:
            return f"{fmt.format(low)}–{fmt.format(high)}" if low > -math.inf else f"< {fmt.format(high)}"
    return f"≥ {fmt.format(edges[-1])}"


_INF = math.inf
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_FILL_LABELS = {
    "level": "Crossed entry",
    "open": "Gap inside window",
    "pullback": "Back to entry after a chase",
    "recovery": "Up from through the stop",
}

# (key, label, function from trade to group label). Ordered labels sort naturally.
_DIMENSIONS: tuple[tuple[str, str, Callable[[Trade], str]], ...] = (
    ("side", "Side", lambda t: "Buy" if t.side == "buy" else "Sell"),
    ("segment", "Segment", lambda t: {"fno": "F&O", "cash": "Non-F&O", "index": "Index"}.get(t.segment, t.segment)),
    ("year", "Year", lambda t: t.trade_date[:4]),
    ("month", "Month", lambda t: t.trade_date[:7]),
    ("weekday", "Weekday", lambda t: _WEEKDAYS[date.fromisoformat(t.trade_date).weekday()]),
    ("fill", "Fill", lambda t: _FILL_LABELS.get(t.fill_type, t.fill_type)),
    ("stop_basis", "Stop basis", lambda t: {"candle": "Candle", "atr_floor": "ATR floor", "atr_cap": "ATR cap"}.get(t.stop_basis, t.stop_basis)),
    ("efficiency", "20-day efficiency", lambda t: _bucket(t.efficiency, (0.0, 0.2, 0.3, 0.4, 0.5, 0.6), "{:.1f}")),
    ("atr_pct", "ATR %", lambda t: _bucket(t.atr_pct, (-_INF, 1.5, 2.5, 4.0, 6.0))),
    ("trend", "20-day trend % (abs)", lambda t: _bucket(abs(t.trend_pct), (0.0, 3.0, 6.0, 10.0, 20.0))),
    ("return_5d", "5-day return % with the side", lambda t: _bucket(t.return_5d_pct, (-_INF, 0.0, 2.0, 5.0, 10.0))),
    ("vs_sma", "Distance from 20-day avg %", lambda t: _bucket(t.vs_sma_pct, (0.0, 2.0, 4.0, 8.0, 15.0))),
    ("candle_atr", "Yesterday's range in ATR", lambda t: _bucket(t.candle_atr, (-_INF, 0.5, 0.8, 1.2, 1.8))),
    ("extreme", "Yesterday at 20-day extreme", lambda t: "Yes" if t.at_20d_extreme else "No"),
    ("price", "Price ₹", lambda t: _bucket(t.fill, (-_INF, 100.0, 500.0, 2000.0, 5000.0), "{:.0f}")),
)


def _group_row(label: str, trades: list[Trade]) -> dict[str, Any]:
    day = [t.day_r for t in trades]
    swing = [t.swing_r for t in trades if t.swing_r is not None and t.swing_status != "open"]
    wins = sum(1 for value in day if value > 0)
    gross_win = sum(value for value in day if value > 0)
    gross_loss = -sum(value for value in day if value <= 0)
    std = statistics.pstdev(day) if len(day) > 1 else 0.0
    return {
        "group": label,
        "trades": len(day),
        "win_rate_pct": round(wins / len(day) * 100.0, 1),
        "avg_r": round(sum(day) / len(day), 3),
        "total_r": round(sum(day), 1),
        "std_r": round(std, 3),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "target_pct": round(sum(1 for t in trades if t.day_status == "target") / len(day) * 100.0, 1),
        "stopped_pct": round(sum(1 for t in trades if t.day_status == "stopped") / len(day) * 100.0, 1),
        "swing_trades": len(swing),
        "swing_avg_r": round(sum(swing) / len(swing), 3) if swing else None,
        "swing_win_rate_pct": round(sum(1 for value in swing if value > 0) / len(swing) * 100.0, 1) if swing else None,
    }


def breakdowns(trades: list[Trade]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, label, fn in _DIMENSIONS:
        groups: dict[str, list[Trade]] = {}
        for trade in trades:
            groups.setdefault(fn(trade), []).append(trade)
        rows = [_group_row(name, items) for name, items in groups.items()]
        if key == "weekday":
            rows.sort(key=lambda row: _WEEKDAYS.index(row["group"]))
        elif key in {"year", "month", "side", "segment", "fill", "stop_basis", "extreme"}:
            rows.sort(key=lambda row: row["group"])
        else:
            rows.sort(key=lambda row: _bucket_order(row["group"]))
        out.append({"key": key, "label": label, "rows": rows})
    return out


def _bucket_order(label: str) -> float:
    if label == "n/a":
        return _INF
    if label.startswith("< "):
        return -_INF
    text = label.lstrip("≥ ").split("–")[0]
    try:
        return float(text)
    except ValueError:
        return _INF


def insights(groups: list[dict[str, Any]], overall_avg_r: float, total: int) -> list[dict[str, Any]]:
    """Groups whose average R differs from the whole book by more than two standard errors."""
    min_trades = max(30, int(total * 0.01))
    found: list[dict[str, Any]] = []
    for dim in groups:
        # Fill types are defined by the bar-order assumption, so their gap to the book is not a finding.
        if dim["key"] in {"month", "fill"}:
            continue
        for row in dim["rows"]:
            n = row["trades"]
            if n < min_trades or n == total or not row["std_r"]:
                continue
            delta = row["avg_r"] - overall_avg_r
            t_stat = delta / (row["std_r"] / math.sqrt(n))
            if abs(t_stat) < 2.0:
                continue
            found.append(
                {
                    "dimension": dim["label"],
                    "group": row["group"],
                    "trades": n,
                    "avg_r": row["avg_r"],
                    "delta_r": round(delta, 3),
                    "t_stat": round(t_stat, 1),
                    "direction": "better" if delta > 0 else "worse",
                }
            )
    found.sort(key=lambda item: -abs(item["t_stat"]))
    return found[:16]


def order_bounds(trades: list[Trade]) -> dict[str, Any]:
    """The booked result assumes the worse order inside every ambiguous bar; this is the other end."""
    ambiguous = sum(1 for t in trades if t.ambiguous)
    optimistic: list[float] = []
    for t in trades:
        if not t.ambiguous:
            optimistic.append(t.day_r)
        elif t.alt_day_r is not None:
            optimistic.append(t.alt_day_r)
    return {
        "ambiguous": ambiguous,
        "ambiguous_pct": round(ambiguous / len(trades) * 100.0, 1) if trades else None,
        "minute_resolved": sum(1 for t in trades if t.resolution == "minute"),
        "optimistic_trades": len(optimistic),
        "optimistic_avg_r": round(sum(optimistic) / len(optimistic), 3) if optimistic else None,
        "optimistic_win_rate_pct": (
            round(sum(1 for value in optimistic if value > 0) / len(optimistic) * 100.0, 1) if optimistic else None
        ),
    }


def target_sweep(trades: list[Trade], cost_pct: float) -> list[dict[str, Any]]:
    """Day-leg results with the same entries and stops and a different target multiple."""
    rows: list[dict[str, Any]] = []
    for multiple in _SWEEP_R:
        results: list[float] = []
        hits = 0
        for t in trades:
            if t.day_status == "stopped":
                results.append(t.day_r)
                continue
            buy = t.side == "buy"
            level = t.entry + multiple * t.plan_risk if buy else t.entry - multiple * t.plan_risk
            risk = abs(t.fill - t.stop)
            cost = cost_pct / 100.0 * t.fill
            reached = (t.best_price >= level) if buy else (t.best_price <= level)
            # A gap fill can already sit past a near target; the target then books at the fill.
            beyond_fill = (level > t.fill) if buy else (level < t.fill)
            if reached:
                hits += 1
                results.append(_r(t.side, t.fill, level if beyond_fill else t.fill, risk, cost))
            else:
                results.append(_r(t.side, t.fill, t.close_price, risk, cost))
        if not results:
            continue
        rows.append(
            {
                "reward_r": multiple,
                "trades": len(results),
                "target_pct": round(hits / len(results) * 100.0, 1),
                "win_rate_pct": round(sum(1 for value in results if value > 0) / len(results) * 100.0, 1),
                "avg_r": round(sum(results) / len(results), 3),
                "total_r": round(sum(results), 1),
            }
        )
    return rows


def equity_curve(trades: list[Trade]) -> dict[str, Any]:
    """Equal-weight daily book: each session's mean day-leg R, accumulated."""
    by_day: dict[str, list[float]] = {}
    for trade in trades:
        by_day.setdefault(trade.trade_date, []).append(trade.day_r)
    points: list[dict[str, Any]] = []
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    green = 0
    for day in sorted(by_day):
        values = by_day[day]
        mean = sum(values) / len(values)
        cumulative += mean
        peak = max(peak, cumulative)
        drawdown = min(drawdown, cumulative - peak)
        green += 1 if mean > 0 else 0
        points.append({"date": day, "trades": len(values), "mean_r": round(mean, 3), "cum_r": round(cumulative, 3)})
    return {
        "points": points,
        "sessions": len(points),
        "green_sessions_pct": round(green / len(points) * 100.0, 1) if points else None,
        "max_drawdown_r": round(drawdown, 2),
        "final_r": round(cumulative, 2),
    }


def symbol_table(trades: list[Trade], *, min_trades: int = 5, limit: int = 15) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[Trade]] = {}
    for trade in trades:
        groups.setdefault(trade.symbol, []).append(trade)
    rows = [_group_row(symbol, items) for symbol, items in groups.items() if len(items) >= min_trades]
    rows.sort(key=lambda row: row["total_r"], reverse=True)
    return {"best": rows[:limit], "worst": list(reversed(rows[-limit:])) if len(rows) > limit else []}


def _trade_row(trade: Trade) -> dict[str, Any]:
    row = asdict(trade)
    for key, value in row.items():
        if isinstance(value, float):
            row[key] = None if math.isnan(value) else round(value, 3 if key.endswith("_r") else 2)
    return row


ASSUMPTIONS = (
    "Daily candles. VWAP, session volume, the spread, and futures OI are not modelled.",
    "When one daily bar touches two levels, the day is replayed through the journal's rules on stored live minute bars if the feed covered the full session. Otherwise the worse order is booked and the optimistic bound shows the other end.",
    "A gap inside the entry window fills at the open. A gap further than that only fills if price comes back to the entry.",
    "Universe is today's F&O list and today's liquid cash names (survivorship bias).",
    "Costs are a round-trip percent of the fill, taken off every trade.",
    "R is the move from the fill over the fill-to-stop distance.",
)


# ---------------------------------------------------------------------- run


def last_completed_session(now: datetime | None = None) -> str:
    """Today counts only after the 15:30 close; a bar for a running session is not a finished day."""
    current = now or now_ist()
    if current.time() >= SESSION_CLOSE:
        return expected_latest_session(current.date())
    return expected_latest_session(current.date() - timedelta(days=1))


def run_backtest(
    params: BacktestParams,
    *,
    store: TimelineStore | None = None,
    universe: list[BacktestSymbol] | None = None,
    trades_limit: int = 200,
    now: datetime | None = None,
) -> dict[str, Any]:
    params = params.checked()
    started = time.perf_counter()
    db = store or get_store()
    warnings: list[str] = []
    last = last_completed_session(now)
    if params.end > last:
        params = replace(params, end=max(last, params.start))
    if universe is None:
        universe, warnings = backtest_universe(params.segment, params.end, store=db)
    load_from = (date.fromisoformat(params.start) - timedelta(days=_WARMUP_DAYS)).isoformat()
    load_to = (date.fromisoformat(params.end) + timedelta(days=int(params.max_swing_days * 1.6) + 7)).isoformat()
    funnel = Funnel()
    trades: list[Trade] = []
    indexes = [item for item in universe if item.kind == "index"]
    equities = [item for item in universe if item.kind != "index"]
    if indexes:
        bars = db.index_daily_bars_between([item.token for item in indexes], load_from, load_to)
        for item in indexes:
            trades.extend(simulate_symbol(item, bars.get(item.token, []), params, funnel))
    minute_days = db.live_minute_ohlc_dates(params.start, params.end)

    def minute_source(token: str) -> Callable[[str], MinutePath | None] | None:
        if not minute_days:
            return None

        def fetch(day: str) -> MinutePath | None:
            if day not in minute_days:
                return None
            path = db.live_minute_ohlc(token, day)
            return path if full_session(path) else None

        return fetch

    for offset in range(0, len(equities), _TOKEN_CHUNK):
        chunk = equities[offset : offset + _TOKEN_CHUNK]
        bars = db.daily_bars_between([item.token for item in chunk], load_from, load_to)
        for item in chunk:
            trades.extend(
                simulate_symbol(item, bars.get(item.token, []), params, funnel, minutes=minute_source(item.token))
            )
    trades.sort(key=lambda trade: (trade.trade_date, trade.symbol))
    return summarize(
        trades,
        params,
        funnel,
        universe=universe,
        warnings=warnings,
        trades_limit=trades_limit,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
    )


def summarize(
    trades: list[Trade],
    params: BacktestParams,
    funnel: Funnel,
    *,
    universe: list[BacktestSymbol],
    warnings: list[str],
    trades_limit: int,
    elapsed_ms: float,
) -> dict[str, Any]:
    day = leg_stats([t.day_r for t in trades], [t.day_status for t in trades], [t.day_pct for t in trades])
    day["avg_mfe_r"] = round(sum(t.mfe_r for t in trades) / len(trades), 3) if trades else None
    day["avg_mae_r"] = round(sum(t.mae_r for t in trades) / len(trades), 3) if trades else None
    day["bounds"] = order_bounds(trades)
    resolved = [t for t in trades if t.swing_status != "open" and t.swing_r is not None]
    swing = leg_stats(
        [t.swing_r for t in resolved if t.swing_r is not None],
        [t.swing_status for t in trades],
        [t.swing_pct for t in resolved if t.swing_pct is not None],
    )
    swing["avg_days"] = round(sum(t.swing_days for t in resolved) / len(resolved), 1) if resolved else None
    groups = breakdowns(trades)
    recent = sorted(trades, key=lambda trade: (trade.trade_date, trade.symbol), reverse=True)[: max(0, trades_limit)]
    return {
        "params": asdict(params),
        "universe": {
            "symbols": len(universe),
            "fno": sum(1 for item in universe if item.segment == "fno"),
            "cash": sum(1 for item in universe if item.segment == "cash"),
            "index": sum(1 for item in universe if item.segment == "index"),
        },
        "first_trade": trades[0].trade_date if trades else None,
        "last_trade": trades[-1].trade_date if trades else None,
        "funnel": asdict(funnel),
        "day": day,
        "swing": swing,
        "target_sweep": target_sweep(trades, params.cost_pct),
        "curve": equity_curve(trades),
        "breakdowns": groups,
        "insights": insights(groups, day.get("avg_r") or 0.0, len(trades)) if trades else [],
        "symbols": symbol_table(trades),
        "trades": [_trade_row(trade) for trade in recent],
        "assumptions": list(ASSUMPTIONS),
        "warnings": warnings,
        "elapsed_ms": round(elapsed_ms, 1),
    }


# ------------------------------------------------------------ live record


def _journal_segment(row: dict[str, Any]) -> str:
    segment = row.get("segment")
    if segment in {"fno", "cash", "index"}:
        return str(segment)
    return "index" if row.get("kind") == "index" else "fno"


def _journal_r(result_pct: Any, fill: float, stop: float, cost_pct: float) -> float | None:
    if result_pct is None:
        return None
    risk = abs(fill - stop)
    if risk <= 0 or fill <= 0:
        return None
    return (float(result_pct) - cost_pct) / 100.0 * fill / risk


def journal_scorecard(
    rows: Iterable[dict[str, Any]],
    *,
    cost_pct: float = 0.05,
    segment: str = "all",
) -> dict[str, Any]:
    """What the live board actually did: every saved plan, both legs, in R after costs."""
    day_r: list[float] = []
    day_status: list[str] = []
    day_pct: list[float] = []
    swing_r: list[float] = []
    swing_status: list[str] = []
    funnel = {"plans": 0, "pending": 0, "open": 0, "cancelled": 0, "resolved": 0}
    by: dict[str, dict[str, list[float]]] = {"session": {}, "segment": {}, "side": {}, "status": {}}
    sessions: set[str] = set()
    for row in rows:
        row_segment = _journal_segment(row)
        if segment == "fno" and row_segment not in {"fno", "index"}:
            continue
        if segment == "cash" and row_segment != "cash":
            continue
        funnel["plans"] += 1
        session = str(row.get("session_date") or "")
        sessions.add(session)
        status = str(row.get("status") or "")
        if status in {"pending", "open", "cancelled"}:
            funnel[status] += 1
        fill = float(row.get("fill_price") or row.get("entry") or 0)
        stop = float(row.get("stop") or 0)
        if status in {"target", "stopped", "closed"}:
            value = _journal_r(row.get("result_pct"), fill, stop, cost_pct)
            if value is not None:
                funnel["resolved"] += 1
                day_r.append(value)
                day_status.append(status)
                day_pct.append(float(row["result_pct"]) - cost_pct)
                for key, label in (
                    ("session", session),
                    ("segment", {"fno": "F&O", "cash": "Non-F&O", "index": "Index"}[row_segment]),
                    ("side", "Buy" if row.get("side") == "buy" else "Sell"),
                    ("status", status),
                ):
                    by[key].setdefault(label, []).append(value)
        swing = str(row.get("swing_status") or "")
        if swing:
            swing_status.append(swing)
        if swing in {"target", "stopped"}:
            value = _journal_r(row.get("swing_result_pct"), fill, stop, cost_pct)
            if value is not None:
                swing_r.append(value)
    tables = []
    for key, label in (("session", "Session"), ("segment", "Segment"), ("side", "Side"), ("status", "Day exit")):
        group_rows = []
        for name, values in sorted(by[key].items()):
            wins = sum(1 for value in values if value > 0)
            group_rows.append(
                {
                    "group": name,
                    "trades": len(values),
                    "win_rate_pct": round(wins / len(values) * 100.0, 1),
                    "avg_r": round(sum(values) / len(values), 3),
                    "total_r": round(sum(values), 1),
                }
            )
        tables.append({"key": key, "label": label, "rows": group_rows})
    ordered = sorted(session for session in sessions if session)
    return {
        "cost_pct": cost_pct,
        "segment": segment,
        "sessions": len(ordered),
        "first_session": ordered[0] if ordered else None,
        "last_session": ordered[-1] if ordered else None,
        "funnel": funnel,
        "day": leg_stats(day_r, day_status, day_pct),
        "swing": leg_stats(swing_r, swing_status),
        "breakdowns": tables,
    }


# ------------------------------------------------------------------- cache

_cache: dict[BacktestParams, tuple[float, dict[str, Any]]] = {}
_run_lock = threading.Lock()


def cached_backtest(params: BacktestParams, *, trades_limit: int = 200) -> dict[str, Any]:
    """One run at a time; a repeat of the same parameters within ten minutes is served from memory."""
    params = params.checked()
    with _run_lock:
        hit = _cache.get(params)
        if hit is not None and time.time() - hit[0] < _CACHE_TTL_SEC:
            result = dict(hit[1])
            result["trades"] = result["trades"][:trades_limit]
            result["cached"] = True
            return result
        result = run_backtest(params, trades_limit=max(trades_limit, 500))
        if len(_cache) >= _CACHE_SIZE:
            oldest = min(_cache, key=lambda key: _cache[key][0])
            _cache.pop(oldest, None)
        _cache[params] = (time.time(), result)
    out = dict(result)
    out["trades"] = result["trades"][:trades_limit]
    out["cached"] = False
    return out
