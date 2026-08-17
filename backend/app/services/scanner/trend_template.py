from __future__ import annotations

import pandas as pd

from .indicators import rolling_max, rolling_min, sma


def evaluate_trend_template(df: pd.DataFrame) -> tuple[bool, dict]:
    """Minervini-style trend template on the last bar."""
    if len(df) < 250:
        return False, {"reason": "insufficient_history"}

    close = df["close"]
    last = df.iloc[-1]
    price = float(last["close"])

    sma50 = sma(close, 50)
    sma150 = sma(close, 150)
    sma200 = sma(close, 200)

    s50 = float(sma50.iloc[-1])
    s150 = float(sma150.iloc[-1])
    s200 = float(sma200.iloc[-1])
    s200_20d = float(sma200.iloc[-21]) if len(sma200) >= 21 and pd.notna(sma200.iloc[-21]) else s200

    high_52w = float(rolling_max(df["high"], 252).iloc[-1])
    low_52w = float(rolling_min(df["low"], 252).iloc[-1])

    stack_ok = price > s50 > s150 > s200
    slope_ok = s200 > s200_20d
    above_low_ok = price >= low_52w * 1.30 if low_52w > 0 else False
    near_high_ok = price >= high_52w * 0.75 if high_52w > 0 else False

    passed = stack_ok and slope_ok and above_low_ok and near_high_ok
    details = {
        "price": round(price, 2),
        "sma50": round(s50, 2),
        "sma150": round(s150, 2),
        "sma200": round(s200, 2),
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "stack_ok": stack_ok,
        "slope_ok": slope_ok,
        "above_low_ok": above_low_ok,
        "near_high_ok": near_high_ok,
    }
    return passed, details


def in_base_context(df: pd.DataFrame, pct_from_high: float = 0.15) -> bool:
    """Within pct of 52-week high — base / consolidation context."""
    if len(df) < 252:
        return False
    high_52w = float(rolling_max(df["high"], 252).iloc[-1])
    price = float(df["close"].iloc[-1])
    if high_52w <= 0:
        return False
    return price >= high_52w * (1 - pct_from_high)
