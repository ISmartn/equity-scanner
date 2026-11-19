"""Leading features for stocks that are still inside a base.

Everything here is computed from bars up to and including the row's own date,
so a row is exactly what was knowable after that day's close. The forward
columns built by ``add_forward_outcomes`` are the only ones that look ahead,
and they are used for fitting and reporting only.

Two kinds of base are flagged on every row:

* ``candidate``   the daily list: a quiet range just under the 20-day high.
* ``w_candidate`` the weekly list: a tight range under a ten-week high that
  was set at least two weeks ago. Slower to form, and usually a longer move.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..scanner.filters import MIN_AVG_TURNOVER_INR
from .trades import DEFAULT_COST_PCT, MAIN_RULE, net_return_pct, simulate_exit

PIVOT_LOOKBACK = 20
BASE_LOW_LOOKBACK = 10
TIGHTNESS_HISTORY = 120
MIN_BARS = 130

# A stock is "in a base" (daily list) when all of these hold on the day's close.
MAX_DIST_TO_PIVOT_PCT = 6.0
MAX_RANGE_10D_PCT = 12.0
MAX_PRE_20D_RETURN_PCT = 25.0
MIN_PRICE = 20.0

# The weekly list. Ten weeks is 50 sessions; three weeks is 15.
W_PIVOT_LOOKBACK = 50
W_PIVOT_MIN_AGE = 10
W_STOP_LOOKBACK = 15
W_MAX_DIST_PCT = 10.0
W_MAX_CLOSE_SPREAD_PCT = 4.0
W_MAX_RANGE_PCT = 15.0
W_MAX_RUN_PCT = 40.0

# A breakout counts when a close within the horizon holds this far above the pivot.
LABEL_HORIZON = 5
LABEL_HOLD_PCT = 2.0

FEATURES: tuple[str, ...] = (
    "dist_to_pivot_pct",
    "tightness_pctile",
    "atr_ratio",
    "vol_dryup",
    "updown_vol_log",
    "rs_pctile",
    "rs_new_high",
    "close_tight_pct",
    "ret20_pct",
    "higher_lows",
    "pct_from_52w_high",
    "sector_accel",
    "oi_build",
    "deliv_pct_5d",
    "deliv_trend",
    "group_heat",
    "market_breadth",
    "market_breadth_chg",
)

FEATURE_LABELS: dict[str, str] = {
    "dist_to_pivot_pct": "Distance below the pivot",
    "tightness_pctile": "10-day range against its own last 120 sessions",
    "atr_ratio": "5-day ATR against 20-day ATR",
    "vol_dryup": "5-day volume against 50-day volume",
    "updown_vol_log": "Up-day volume against down-day volume, 20 sessions",
    "rs_pctile": "Relative strength against the market, 60-session rank",
    "rs_new_high": "Relative strength at a 60-session high",
    "close_tight_pct": "Spread of the last 5 closes",
    "ret20_pct": "Return over the prior 20 sessions",
    "higher_lows": "Higher lows inside the base",
    "pct_from_52w_high": "Distance below the 52-week high",
    "sector_accel": "Group strength against the market, change over 10 sessions",
    "oi_build": "Futures OI change over 5 sessions while price is flat",
    "deliv_pct_5d": "Share of volume taken as delivery, 5-session average",
    "deliv_trend": "Delivery share against its 60-session average",
    "group_heat": "Stocks in the same industry at new 20-day highs this week, against the market",
    "market_breadth": "Share of all stocks above their 50-day average",
    "market_breadth_chg": "Change in that share over 10 sessions",
}


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def compute_feature_frame(
    df: pd.DataFrame,
    *,
    bench_close: pd.Series | None = None,
    sector_accel: pd.Series | None = None,
    oi: pd.DataFrame | None = None,
    delivery: pd.Series | None = None,
) -> pd.DataFrame:
    """One row per bar of ``df`` (oldest first) with the features and the two base flags.

    ``df`` needs ``date, open, high, low, close, volume``. ``bench_close``,
    ``sector_accel`` and ``delivery`` are indexed by date string. ``oi`` is
    indexed by date with ``oi`` and ``instrument_key`` columns. All are optional;
    a missing input leaves its feature as NaN, which scores as the average.
    The market-wide and group columns are filled in afterwards by
    ``attach_cross_section``, because they need every stock's frame first.
    """
    out = pd.DataFrame(index=df.index)
    dates = df["date"].astype(str).str[:10]
    out["date"] = dates
    for column in ("open", "high", "low", "close"):
        out[column] = df[column].astype(float)
    volume = df["volume"].astype(float)
    close, high, low = out["close"], out["high"], out["low"]

    pivot = high.rolling(PIVOT_LOOKBACK, min_periods=PIVOT_LOOKBACK).max()
    prior_high = high.shift(1).rolling(PIVOT_LOOKBACK, min_periods=PIVOT_LOOKBACK).max()
    prior_low = low.shift(1).rolling(PIVOT_LOOKBACK, min_periods=PIVOT_LOOKBACK).min()
    out["pivot"] = pivot
    out["broke_today"] = close > prior_high
    out["low_break"] = close < prior_low
    out["base_low"] = low.rolling(BASE_LOW_LOOKBACK, min_periods=BASE_LOW_LOOKBACK).min()
    out["dist_to_pivot_pct"] = (pivot - close) / pivot * 100.0

    high10 = high.rolling(10, min_periods=10).max()
    low10 = low.rolling(10, min_periods=10).min()
    range10 = (high10 - low10) / close * 100.0
    out["range10_pct"] = range10
    out["tightness_pctile"] = range10.rolling(TIGHTNESS_HISTORY, min_periods=60).rank(pct=True)

    true_range = _true_range(df.assign(high=high, low=low, close=close))
    atr5 = true_range.rolling(5, min_periods=5).mean()
    atr20 = true_range.rolling(20, min_periods=20).mean()
    out["atr_ratio"] = atr5 / atr20.replace(0, np.nan)
    out["atr20_pct"] = atr20 / close * 100.0

    vol5 = volume.rolling(5, min_periods=5).mean()
    vol20 = volume.rolling(20, min_periods=20).mean()
    vol50 = volume.rolling(50, min_periods=50).mean()
    out["avg_volume_20"] = vol20
    out["vol_dryup"] = vol5 / vol50.replace(0, np.nan)

    change = close.diff()
    up_volume = volume.where(change > 0, 0.0).rolling(20, min_periods=20).sum()
    down_volume = volume.where(change < 0, 0.0).rolling(20, min_periods=20).sum()
    ratio = (up_volume + 1.0) / (down_volume + 1.0)
    out["updown_vol_log"] = np.log(ratio.clip(lower=0.05, upper=20.0))

    if bench_close is not None and len(bench_close):
        bench = dates.map(bench_close).astype(float)
        rs = close / bench.replace(0, np.nan)
        out["rs_pctile"] = rs.rolling(60, min_periods=40).rank(pct=True)
        rs_high = rs.rolling(60, min_periods=40).max()
        out["rs_new_high"] = (rs >= rs_high * 0.999).astype(float).where(rs.notna() & rs_high.notna())
    else:
        out["rs_pctile"] = np.nan
        out["rs_new_high"] = np.nan

    mean5 = close.rolling(5, min_periods=5).mean()
    out["close_tight_pct"] = close.rolling(5, min_periods=5).std(ddof=0) / mean5 * 100.0
    out["ret20_pct"] = (close / close.shift(20) - 1.0) * 100.0
    out["ret5_pct"] = (close / close.shift(5) - 1.0) * 100.0

    recent_low = low.rolling(5, min_periods=5).min()
    earlier_low = low.shift(5).rolling(15, min_periods=15).min()
    out["higher_lows"] = (recent_low > earlier_low).astype(float).where(earlier_low.notna())

    high_52w = high.rolling(252, min_periods=MIN_BARS).max()
    out["pct_from_52w_high"] = (high_52w - close) / high_52w * 100.0

    sma50 = close.rolling(50, min_periods=50).mean()
    out["sma50"] = sma50
    out["above_sma50"] = close > sma50

    if sector_accel is not None and len(sector_accel):
        out["sector_accel"] = dates.map(sector_accel).astype(float)
    else:
        out["sector_accel"] = np.nan

    out["oi_build"] = _oi_build(dates, out["ret5_pct"], oi)

    if delivery is not None and len(delivery):
        share = dates.map(delivery).astype(float)
        recent = share.rolling(5, min_periods=3).mean()
        out["deliv_pct_5d"] = recent
        out["deliv_trend"] = recent - share.rolling(60, min_periods=20).mean()
    else:
        out["deliv_pct_5d"] = np.nan
        out["deliv_trend"] = np.nan

    # Filled by attach_cross_section once every stock's frame exists.
    for name in ("group_heat", "market_breadth", "market_breadth_chg", "group_members", "group_broke"):
        out[name] = np.nan

    turnover = (close * volume).rolling(20, min_periods=20).mean()
    out["avg_turnover_inr"] = turnover
    bars = pd.Series(np.arange(1, len(df) + 1), index=df.index)
    out["liquid"] = ((bars >= MIN_BARS) & (turnover >= MIN_AVG_TURNOVER_INR) & (close >= MIN_PRICE)).fillna(False)

    out["candidate"] = (
        out["liquid"]
        & out["above_sma50"]
        & ~out["broke_today"]
        & (out["dist_to_pivot_pct"] <= MAX_DIST_TO_PIVOT_PCT)
        & (out["range10_pct"] <= MAX_RANGE_10D_PCT)
        & (out["ret20_pct"] <= MAX_PRE_20D_RETURN_PCT)
        & (out["base_low"] < pivot)
    ).fillna(False)

    _weekly_columns(out, sma50)
    return out


def _weekly_columns(out: pd.DataFrame, sma50: pd.Series) -> None:
    """The longer base: tight for three weeks under a ten-week high that is at least two weeks old."""
    close, high, low = out["close"], out["high"], out["low"]
    pivot = high.rolling(W_PIVOT_LOOKBACK, min_periods=W_PIVOT_LOOKBACK).max()
    stop = low.rolling(W_STOP_LOOKBACK, min_periods=W_STOP_LOOKBACK).min()
    # The ten-week high was not made in the last two weeks: it is a ceiling, not a spike.
    aged = high.rolling(W_PIVOT_MIN_AGE, min_periods=W_PIVOT_MIN_AGE).max() < pivot
    weekly_closes = pd.concat([close, close.shift(5), close.shift(10)], axis=1)
    spread = (weekly_closes.max(axis=1) / weekly_closes.min(axis=1) - 1.0) * 100.0
    spread = spread.where(weekly_closes.notna().all(axis=1))
    span = (high.rolling(W_STOP_LOOKBACK, min_periods=W_STOP_LOOKBACK).max() - stop) / close * 100.0
    run = (close / close.shift(W_PIVOT_LOOKBACK) - 1.0) * 100.0
    out["w_pivot"] = pivot
    out["w_stop"] = stop
    out["w_dist_pct"] = (pivot - close) / pivot * 100.0
    out["w_tight_pct"] = spread
    out["w_candidate"] = (
        out["liquid"]
        & out["above_sma50"]
        & (sma50 > sma50.shift(20))
        & aged
        & (out["w_dist_pct"] <= W_MAX_DIST_PCT)
        & (spread <= W_MAX_CLOSE_SPREAD_PCT)
        & (span <= W_MAX_RANGE_PCT)
        & (run <= W_MAX_RUN_PCT)
        & (stop < pivot)
    ).fillna(False)


def attach_cross_section(
    frame: pd.DataFrame,
    health: pd.DataFrame | None,
    heat: pd.DataFrame | None,
) -> None:
    """Fill the market-wide and industry-group columns of one stock's frame, in place."""
    dates = frame["date"]
    if health is not None and len(health):
        frame["market_breadth"] = dates.map(health["pct_above_50"]).astype(float)
        frame["market_breadth_chg"] = dates.map(health["breadth_chg"]).astype(float)
    if heat is not None and len(heat):
        frame["group_heat"] = dates.map(heat["heat"]).astype(float)
        frame["group_members"] = dates.map(heat["members"]).astype(float)
        frame["group_broke"] = dates.map(heat["broke"]).astype(float)


def _oi_build(dates: pd.Series, ret5_pct: pd.Series, oi: pd.DataFrame | None) -> pd.Series:
    """OI growth while price went nowhere. A contract roll inside the window is not growth."""
    if oi is None or oi.empty:
        return pd.Series(np.nan, index=dates.index)
    level = dates.map(oi["oi"]).astype(float)
    contract = dates.map(oi["instrument_key"])
    same_contract = contract.notna() & (contract == contract.shift(5))
    change = (level / level.shift(5).replace(0, np.nan) - 1.0) * 100.0
    change = change.where(same_contract)
    flat = ret5_pct.abs() < 3.0
    return change.where(flat, 0.0).where(change.notna()).clip(lower=-50.0, upper=50.0)


def add_forward_outcomes(
    frame: pd.DataFrame,
    horizon: int = LABEL_HORIZON,
    cost_pct: float = DEFAULT_COST_PCT,
) -> pd.DataFrame:
    """Adds what happened after each daily-list row. Looks ahead by design.

    ``label``            1 when a close within the horizon held ``LABEL_HOLD_PCT`` above the pivot.
    ``trigger_offset``   sessions until the high first crossed the pivot (1..horizon), else NaN.
    ``fill``             a stop-entry at the pivot: the pivot, or the open when it gapped over.
    ``trigger_close``    the close of the trigger day, which is where an end-of-day scan buys.
    ``fwd5_pct`` / ``fwd10_pct``  close 5 / 10 sessions after the trigger, against ``fill``.
    ``next_fill``        the fill when the pivot was crossed on the very next session.
    ``trade_ret_pct``    that trade's result under the main exit rule, after costs. This is
                         what the score is trained on: last evening's reading, today's trade.
    """
    out = frame.copy()
    n = len(out)
    opens = out["open"].to_numpy(dtype=float)
    highs = out["high"].to_numpy(dtype=float)
    lows = out["low"].to_numpy(dtype=float)
    closes = out["close"].to_numpy(dtype=float)
    pivots = out["pivot"].to_numpy(dtype=float)
    stops = out["base_low"].to_numpy(dtype=float)
    open_l, high_l, low_l, close_l = opens.tolist(), highs.tolist(), lows.tolist(), closes.tolist()

    label = np.full(n, np.nan)
    offset = np.full(n, np.nan)
    fill = np.full(n, np.nan)
    trigger_close = np.full(n, np.nan)
    fwd5 = np.full(n, np.nan)
    fwd10 = np.full(n, np.nan)
    next_fill = np.full(n, np.nan)
    trade_ret = np.full(n, np.nan)
    candidate = out["candidate"].to_numpy(dtype=bool)

    for t in np.flatnonzero(candidate):
        pivot = pivots[t]
        if not np.isfinite(pivot) or pivot <= 0:
            continue
        nxt = t + 1
        stop = stops[t]
        if nxt < n and np.isfinite(stop) and opens[nxt] > stop and highs[nxt] > pivot:
            entry = max(opens[nxt], pivot)
            next_fill[t] = entry
            result = simulate_exit(MAIN_RULE, open_l, high_l, low_l, close_l, nxt, entry, float(stop))
            if result is not None:
                trade_ret[t] = net_return_pct(entry, result[0], cost_pct)
        end = t + horizon
        if end >= n:
            continue  # the horizon is not complete yet, so the row has no label
        window_close = closes[t + 1 : end + 1]
        label[t] = 1.0 if window_close.max() >= pivot * (1.0 + LABEL_HOLD_PCT / 100.0) else 0.0
        crossed = np.flatnonzero(highs[t + 1 : end + 1] > pivot)
        if crossed.size == 0:
            continue
        j = t + 1 + int(crossed[0])
        offset[t] = j - t
        fill[t] = max(opens[j], pivot)
        trigger_close[t] = closes[j]
        if j + 5 < n:
            fwd5[t] = (closes[j + 5] / fill[t] - 1.0) * 100.0
        if j + 10 < n:
            fwd10[t] = (closes[j + 10] / fill[t] - 1.0) * 100.0

    out["label"] = label
    out["trigger_offset"] = offset
    out["fill"] = fill
    out["trigger_close"] = trigger_close
    out["fwd5_pct"] = fwd5
    out["fwd10_pct"] = fwd10
    out["next_fill"] = next_fill
    out["trade_ret_pct"] = trade_ret
    return out


def sector_acceleration(closes_long: pd.DataFrame) -> dict[str, pd.Series]:
    """Per sector: (sector 10-day return minus market 10-day return), change over 10 sessions.

    ``closes_long`` has ``date, ticker, sector, close`` sorted by ticker then date.
    Equal weight, so one large name does not stand in for the sector.
    """
    if closes_long.empty:
        return {}
    frame = closes_long[["date", "ticker", "sector", "close"]].copy()
    frame["ret10"] = frame.groupby("ticker")["close"].transform(lambda s: (s / s.shift(10) - 1.0) * 100.0)
    frame = frame.dropna(subset=["ret10"])
    if frame.empty:
        return {}
    market = frame.groupby("date")["ret10"].mean()
    result: dict[str, pd.Series] = {}
    for sector, group in frame.dropna(subset=["sector"]).groupby("sector"):
        if group["ticker"].nunique() < 4:
            continue
        relative = (group.groupby("date")["ret10"].mean() - market).dropna().sort_index()
        result[str(sector)] = (relative - relative.shift(10)).dropna()
    return result
