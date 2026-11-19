"""Daily candles as the watchlist reads them: split-adjusted, with a market benchmark.

NSE's own price files are raw: on the day a 1:1 bonus takes effect the price
halves. Read as it stands, that looks like a crash, breaks every stop and
ruins the averages. ``adjust_for_actions`` scales the prices before each split
or bonus so the series is continuous. It checks the price jump first, so a
database whose candles are already adjusted is left alone.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from ...db.store import TimelineStore, get_store
from . import repo

# How far the ex-day open may sit from the expected ratio and still count as that action.
_ACTION_TOLERANCE = 0.20
# An open this far from the previous close is not a market move. NSE's price bands stop
# ordinary stocks at 20% a day, so a jump of this size is a demerger, a split the actions
# list missed, or a relisting.
_BREAK_BELOW = 0.70
_BREAK_ABOVE = 1.45


def adjust_for_actions(candles: pd.DataFrame, actions: list[dict[str, Any]]) -> tuple[pd.DataFrame, int]:
    """Scale the bars before each split or bonus by its factor. Returns the frame and how many applied.

    ``candles`` is sorted by ticker then date. An action is applied only when the
    ex-day open against the previous close is closer to the action's factor than
    to 1.0: adjusted data shows no jump there, raw data shows the factor.
    """
    wanted: dict[str, list[tuple[str, float]]] = {}
    for action in actions:
        factor = action.get("factor")
        if factor and factor > 0 and abs(factor - 1.0) > 1e-6:
            wanted.setdefault(str(action["ticker"]), []).append((str(action["ex_date"]), float(factor)))
    if candles.empty or not wanted:
        return candles, 0

    positions = candles.groupby("ticker", sort=False).indices
    dates = candles["date"].to_numpy()
    prices = {name: candles[name].to_numpy(dtype=float, copy=True) for name in ("open", "high", "low", "close")}
    volume = candles["volume"].to_numpy(dtype=float, copy=True)
    applied = 0
    for ticker, items in wanted.items():
        index = positions.get(ticker)
        if index is None or len(index) < 2:
            continue
        ticker_dates = dates[index]
        for ex_date, factor in items:
            at = int(np.searchsorted(ticker_dates, ex_date))
            if at <= 0 or at >= len(index):
                continue
            before = prices["close"][index[at - 1]]
            first = prices["open"][index[at]]
            if before <= 0 or first <= 0:
                continue
            as_raw = abs(math.log(first / before / factor))
            as_adjusted = abs(math.log(first / before))
            if as_raw >= as_adjusted or as_raw > _ACTION_TOLERANCE:
                continue
            earlier = index[:at]
            for series in prices.values():
                series[earlier] *= factor
            volume[earlier] /= factor
            applied += 1
    if not applied:
        return candles, 0
    adjusted = candles.copy()
    for name, series in prices.items():
        adjusted[name] = series
    adjusted["volume"] = volume
    return adjusted, applied


def heal_breaks(candles: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Close the price breaks that are still there after the known actions were applied.

    Where a stock opens more than 30% under or 45% over its previous close, the
    bars before that day are scaled by the same ratio. Returns that follow are
    then measured on one continuous series instead of across a cliff.
    """
    if candles.empty:
        return candles, 0
    previous = candles.groupby("ticker", sort=False)["close"].shift(1)
    ratio = (candles["open"] / previous).to_numpy(dtype=float)
    breaks = np.isfinite(ratio) & ((ratio < _BREAK_BELOW) | (ratio > _BREAK_ABOVE))
    if not breaks.any():
        return candles, 0
    factor = pd.Series(np.where(breaks, ratio, 1.0), index=candles.index)
    affected = candles["ticker"].isin(candles.loc[breaks, "ticker"].unique())
    healed = candles.copy()
    # For each bar: the product of every break ratio that comes after it.
    scale = (
        factor[affected]
        .groupby(candles.loc[affected, "ticker"], sort=False)
        .transform(lambda column: column[::-1].cumprod()[::-1].shift(-1).fillna(1.0))
    )
    for name in ("open", "high", "low", "close"):
        healed.loc[affected, name] = candles.loc[affected, name] * scale
    healed.loc[affected, "volume"] = candles.loc[affected, "volume"] / scale
    return healed, int(breaks.sum())


def load_adjusted(start: str, end: str, store: TimelineStore | None = None) -> pd.DataFrame:
    """Daily bars for every profiled stock on one continuous price scale.

    Splits and bonuses on record are applied first, then any break still left is closed.
    """
    db = store or get_store()
    candles = repo.load_candles(start, end, db)
    if candles.empty:
        return candles
    actions = repo.load_actions(start, end, with_factor=True, store=db)
    adjusted, _ = adjust_for_actions(candles, actions)
    healed, _ = heal_breaks(adjusted)
    return healed


def market_proxy(candles: pd.DataFrame) -> pd.Series:
    """An equal-weight market line from the candles themselves: the median stock's daily move, compounded.

    Used as the benchmark when the Nifty 50 index has not been loaded.
    """
    if candles.empty:
        return pd.Series(dtype=float)
    previous = candles.groupby("ticker", sort=False)["close"].shift(1)
    change = (candles["close"] / previous - 1.0).clip(lower=-0.3, upper=0.3)
    daily = change.groupby(candles["date"]).median().dropna().sort_index()
    return (1.0 + daily).cumprod() * 100.0


LIQUIDITY_GROUPS = 4


def liquidity_group(candles: pd.DataFrame, groups: int = LIQUIDITY_GROUPS) -> pd.Series:
    """Each bar's liquidity group, 0 (least traded) to ``groups - 1``, from the 20 sessions before it.

    NaN where the stock has too little history. The group is known before the day starts.
    """
    turnover = candles["close"] * candles["volume"]
    trailing = turnover.groupby(candles["ticker"], sort=False).transform(
        lambda column: column.rolling(20, min_periods=10).mean().shift(1)
    )
    rank = trailing.groupby(candles["date"]).rank(pct=True)
    return np.floor(rank * groups).clip(upper=groups - 1)


Typical = tuple[float, float, float, float, float, float]
# Moves beyond this over five sessions are capped when averaging, for the stock and its peers alike.
FORWARD_CAP_PCT = 50.0


def typical_day(candles: pd.DataFrame, group: pd.Series) -> dict[tuple[str, int], Typical]:
    """Per date and liquidity group, what similar stocks did from that day.

    The value is ``(average % gap at the open, average % close to close, average %
    over the next five sessions bought at that day's open, the same bought at that
    day's close, then the medians of those two five-session moves)``. A five-session
    figure is NaN for the last five dates, which have no "after" yet.

    This is the yardstick for "did this stock do anything unusual". Three choices
    in it matter, and each was got wrong once on real data before it was right:

    * Peers are stocks of similar liquidity, because large and small stocks drift
      apart for months at a time and companies that file a lot are mostly large.
    * The five-session figure is each peer bought and held, then averaged. Chaining
      five daily averages instead overstates what thinly traded stocks return.
    * Both the average and the median are kept. Stock moves are lopsided (a few big
      gains pull the average above the middle), so an average is compared with the
      average and "did it beat its peers" with the median. Mixing them makes any
      group of stocks look good.
    """
    if candles.empty:
        return {}
    by_ticker = candles.groupby("ticker", sort=False)["close"]
    previous = by_ticker.shift(1)
    later = by_ticker.shift(-5)
    moves = pd.DataFrame(
        {
            "date": candles["date"],
            "group": group,
            "gap": ((candles["open"] / previous - 1.0) * 100.0).clip(-20.0, 20.0),
            "day": ((candles["close"] / previous - 1.0) * 100.0).clip(-20.0, 20.0),
            "from_open": ((later / candles["open"] - 1.0) * 100.0).clip(-FORWARD_CAP_PCT, FORWARD_CAP_PCT),
            "from_close": ((later / candles["close"] - 1.0) * 100.0).clip(-FORWARD_CAP_PCT, FORWARD_CAP_PCT),
        }
    ).dropna(subset=["group"])
    grouped = moves.groupby(["date", "group"])
    means = grouped[["gap", "day", "from_open", "from_close"]].mean()
    medians = grouped[["from_open", "from_close"]].median()
    return {
        (str(day), int(which)): (
            float(row.gap), float(row.day), float(row.from_open), float(row.from_close),
            float(medians.at[(day, which), "from_open"]), float(medians.at[(day, which), "from_close"]),
        )
        for (day, which), row in means.iterrows()
    }


def benchmark(candles: pd.DataFrame, start: str, end: str, store: TimelineStore | None = None) -> pd.Series:
    """Nifty 50 closes when they cover the period, otherwise the equal-weight market line."""
    nifty = repo.load_benchmark(start, end, store)
    sessions = candles["date"].nunique() if not candles.empty else 0
    if sessions and len(nifty) >= 0.8 * sessions:
        return nifty
    return market_proxy(candles)
