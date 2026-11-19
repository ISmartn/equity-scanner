"""Readings across all stocks at once: market health and how hot each industry group is.

Both are built from each stock's own feature frame, one value per date, using
only bars up to that date. They say nothing about one stock; they say whether
conditions favour breakouts in general, and whether a stock's group is moving.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Hand-set thresholds on the share of stocks above their 50-day average.
GREEN_ABOVE = 60.0
RED_BELOW = 40.0
MIDLINE = 50.0
FALLING_FAST = -5.0
_GROUP_MIN_STOCKS = 5
_RECENT_SESSIONS = 5

STATE_LABELS = {
    "green": "Healthy: most stocks are above their 50-day average",
    "amber": "Mixed",
    "red": "Weak: most stocks are under their 50-day average",
}


def health_state(pct_above_50: float | None, change_10: float | None) -> str:
    """green, amber or red from the share of stocks above their 50-day average and its 10-session change."""
    if pct_above_50 is None or pd.isna(pct_above_50):
        return "amber"
    change = None if change_10 is None or pd.isna(change_10) else float(change_10)
    if pct_above_50 >= GREEN_ABOVE or (pct_above_50 >= MIDLINE and change is not None and change > 0):
        return "green"
    if pct_above_50 < RED_BELOW or (pct_above_50 < MIDLINE and change is not None and change < FALLING_FAST):
        return "red"
    return "amber"


def _liquid_rows(by_ticker: dict[str, pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    parts = [frame.loc[frame["liquid"], columns] for frame in by_ticker.values()]
    parts = [part for part in parts if not part.empty]
    if not parts:
        return pd.DataFrame(columns=columns)
    return pd.concat(parts, ignore_index=True)


def market_health(by_ticker: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per date, indexed by date: breadth, new 20-day highs and lows, and the state."""
    rows = _liquid_rows(by_ticker, ["date", "above_sma50", "broke_today", "low_break"])
    if rows.empty:
        return pd.DataFrame(columns=["stocks", "pct_above_50", "new_highs", "new_lows", "breadth_chg", "state"])
    grouped = rows.groupby("date")
    health = pd.DataFrame(
        {
            "stocks": grouped.size(),
            "pct_above_50": grouped["above_sma50"].mean() * 100.0,
            "new_highs": grouped["broke_today"].sum().astype(int),
            "new_lows": grouped["low_break"].sum().astype(int),
        }
    ).sort_index()
    health["breadth_chg"] = health["pct_above_50"] - health["pct_above_50"].shift(10)
    health["state"] = [health_state(pct, chg) for pct, chg in zip(health["pct_above_50"], health["breadth_chg"])]
    return health


def group_heat(by_ticker: dict[str, pd.DataFrame], groups: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Per group, indexed by date: ``heat``, ``members`` and ``broke``.

    ``broke`` counts the group's stocks that closed at a new 20-day high in the
    last five sessions. ``heat`` is that share minus the same share for the whole
    market, in percentage points, so a rally that lifts everything scores zero.
    Groups with fewer than five liquid stocks that day have no heat.
    """
    parts = []
    for ticker, frame in by_ticker.items():
        recent = frame["broke_today"].astype(float).rolling(_RECENT_SESSIONS, min_periods=1).max()
        part = pd.DataFrame({"date": frame["date"], "recent": recent, "liquid": frame["liquid"]})
        part = part[part["liquid"]]
        if part.empty:
            continue
        group = groups.get(ticker)
        part["group"] = group if isinstance(group, str) and group else None
        parts.append(part[["date", "recent", "group"]])
    if not parts:
        return {}
    rows = pd.concat(parts, ignore_index=True)
    market = rows.groupby("date")["recent"].mean()
    result: dict[str, pd.DataFrame] = {}
    for group, members in rows.dropna(subset=["group"]).groupby("group"):
        stats = members.groupby("date")["recent"].agg(["mean", "sum", "count"])
        heat = (stats["mean"] - market.reindex(stats.index)) * 100.0
        result[str(group)] = pd.DataFrame(
            {
                "heat": heat.where(stats["count"] >= _GROUP_MIN_STOCKS),
                "members": stats["count"].astype(int),
                "broke": stats["sum"].astype(int),
            }
        )
    return result
