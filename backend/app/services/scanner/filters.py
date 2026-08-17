from __future__ import annotations

from typing import Any

import pandas as pd

# ₹5 Cr average daily turnover (close × volume)
MIN_AVG_TURNOVER_INR = 50_000_000
TURNOVER_WINDOW = 20


def evaluate_liquidity(df: pd.DataFrame, *, window: int = TURNOVER_WINDOW) -> dict[str, Any]:
    """Require 20-day average turnover >= ₹5 Cr to reduce illiquid noise."""
    if len(df) < window:
        return {
            "pass": False,
            "avg_turnover_inr": None,
            "signal_turnover_inr": None,
            "min_avg_turnover_inr": MIN_AVG_TURNOVER_INR,
            "window": window,
        }

    turnover = df["close"] * df["volume"]
    avg_turnover = float(turnover.iloc[-window:].mean())
    signal_turnover = float(turnover.iloc[-1])
    passed = avg_turnover >= MIN_AVG_TURNOVER_INR

    return {
        "pass": passed,
        "avg_turnover_inr": round(avg_turnover, 2),
        "signal_turnover_inr": round(signal_turnover, 2),
        "min_avg_turnover_inr": MIN_AVG_TURNOVER_INR,
        "window": window,
    }
