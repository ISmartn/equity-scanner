"""Market regime classifier (Wyckoff–Grimes phases as tradable states)."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

from .pivots import last_swings

Regime = Literal[
    "TREND_BULL",
    "TREND_BEAR",
    "VOLATILITY_COMPRESSION",
    "TRADING_RANGE",
    "CLIMACTIC_EXHAUSTION",
]


def _swing_trend(pivots: list[dict[str, Any]]) -> str | None:
    highs = last_swings(pivots, "high", 2)
    lows = last_swings(pivots, "low", 2)
    if len(highs) < 2 or len(lows) < 2:
        return None
    hh = highs[-1]["price"] > highs[-2]["price"]
    hl = lows[-1]["price"] > lows[-2]["price"]
    lh = highs[-1]["price"] < highs[-2]["price"]
    ll = lows[-1]["price"] < lows[-2]["price"]
    if hh and hl:
        return "bull"
    if lh and ll:
        return "bear"
    return "range"


def classify_regime(
    df: pd.DataFrame,
    pivots: list[dict[str, Any]],
    weekly_ema_up: bool | None = None,
) -> dict[str, Any]:
    """
    Classify the last bar. Compression and climax override generic trend/range
    when their signatures are present on the close.
    """
    empty = {
        "regime": "TRADING_RANGE",
        "swing_trend": None,
        "ma_stack": "flat",
        "weekly_aligned": None,
        "climax": False,
        "squeeze": False,
    }
    if df is None or len(df) < 30:
        return empty

    row = df.iloc[-1]
    close = float(row["close"])
    ema20 = row.get("ema20")
    sma50 = row.get("sma50")
    atr_v = row.get("atr14")
    rng = row.get("range")
    vol_z = row.get("vol_z")

    ma_stack = "flat"
    if pd.notna(ema20) and pd.notna(sma50):
        if close > float(ema20) > float(sma50):
            ma_stack = "bull"
        elif close < float(ema20) < float(sma50):
            ma_stack = "bear"

    swing = _swing_trend(pivots)
    squeeze = bool(row.get("nr7") or row.get("bb_kc_squeeze") or (row.get("inside_run") or 0) >= 2)

    climax = False
    if pd.notna(atr_v) and float(atr_v) > 0 and pd.notna(rng) and pd.notna(ema20):
        ext = abs(close - float(ema20)) / float(atr_v)
        range_x = float(rng) / float(atr_v)
        vol_ok = pd.isna(vol_z) or float(vol_z) >= 1.8
        climax = range_x >= 2.5 and ext >= 2.0 and vol_ok

    if climax:
        regime: Regime = "CLIMACTIC_EXHAUSTION"
    elif squeeze:
        regime = "VOLATILITY_COMPRESSION"
    elif swing == "bull" or (swing is None and ma_stack == "bull"):
        regime = "TREND_BULL"
    elif swing == "bear" or (swing is None and ma_stack == "bear"):
        regime = "TREND_BEAR"
    else:
        regime = "TRADING_RANGE"

    weekly_aligned: bool | None
    if weekly_ema_up is None:
        weekly_aligned = None
    elif regime == "TREND_BULL":
        weekly_aligned = bool(weekly_ema_up)
    elif regime == "TREND_BEAR":
        weekly_aligned = not bool(weekly_ema_up)
    else:
        weekly_aligned = bool(weekly_ema_up) if ma_stack == "bull" else (
            (not weekly_ema_up) if ma_stack == "bear" else None
        )

    return {
        "regime": regime,
        "swing_trend": swing,
        "ma_stack": ma_stack,
        "weekly_aligned": weekly_aligned,
        "weekly_ema_up": weekly_ema_up,
        "climax": climax,
        "squeeze": squeeze,
    }
