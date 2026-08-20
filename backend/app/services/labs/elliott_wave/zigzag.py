"""ATR-scaled ZigZag / monowave pivot extractor.

Preserves chronological order — never reverse-sorts the input frame.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

from ...scanner.indicators import atr

PivotType = Literal["PEAK", "TROUGH"]


def extract_pivots(
    df: pd.DataFrame,
    *,
    atr_mult: float = 2.5,
    atr_period: int = 14,
) -> list[dict[str, Any]]:
    """
    Dynamic ZigZag pivots using threshold = ATR(period) * atr_mult.

    Each node: {index, timestamp, price, type: PEAK|TROUGH}.
    ``index`` is the integer position in the chronological OHLCV frame.
    """
    if df is None or len(df) < atr_period + 5:
        return []

    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    atr_s = atr(df, window=atr_period).to_numpy(dtype=float)
    n = len(df)
    timestamps = [str(x)[:10] for x in df.index.astype(str)]

    pivots: list[dict[str, Any]] = []

    # Seed with first usable bar as provisional trough/peak from close vs mid
    i0 = atr_period
    last_pivot_i = i0
    last_pivot_price = float(close[i0])
    # Start looking for a peak if first swing is up from the low of seed bar
    direction = 1  # 1 = seeking peak, -1 = seeking trough
    extreme_i = i0
    extreme_price = float(high[i0]) if direction == 1 else float(low[i0])

    for i in range(i0 + 1, n):
        thr = float(atr_s[i]) * atr_mult if np.isfinite(atr_s[i]) else float("nan")
        if not np.isfinite(thr) or thr <= 0:
            thr = abs(float(close[i])) * 0.02

        if direction == 1:
            if high[i] >= extreme_price:
                extreme_i = i
                extreme_price = float(high[i])
            elif extreme_price - low[i] >= thr:
                # Confirm peak, reverse to seeking trough
                pivots.append(
                    {
                        "index": int(extreme_i),
                        "timestamp": timestamps[extreme_i],
                        "price": round(extreme_price, 4),
                        "type": "PEAK",
                    }
                )
                last_pivot_i = extreme_i
                last_pivot_price = extreme_price
                direction = -1
                extreme_i = i
                extreme_price = float(low[i])
        else:
            if low[i] <= extreme_price:
                extreme_i = i
                extreme_price = float(low[i])
            elif high[i] - extreme_price >= thr:
                pivots.append(
                    {
                        "index": int(extreme_i),
                        "timestamp": timestamps[extreme_i],
                        "price": round(extreme_price, 4),
                        "type": "TROUGH",
                    }
                )
                last_pivot_i = extreme_i
                last_pivot_price = extreme_price
                direction = 1
                extreme_i = i
                extreme_price = float(high[i])

    # Append active extreme as provisional last pivot if far enough from prior
    if pivots and extreme_i > last_pivot_i:
        thr_last = float(atr_s[-1]) * atr_mult if np.isfinite(atr_s[-1]) else abs(last_pivot_price) * 0.02
        move = abs(extreme_price - last_pivot_price)
        if move >= thr_last * 0.5:
            pivots.append(
                {
                    "index": int(extreme_i),
                    "timestamp": timestamps[extreme_i],
                    "price": round(extreme_price, 4),
                    "type": "PEAK" if direction == 1 else "TROUGH",
                }
            )

    # Ensure alternating types
    cleaned: list[dict[str, Any]] = []
    for p in pivots:
        if cleaned and cleaned[-1]["type"] == p["type"]:
            # Keep more extreme of the same type
            if p["type"] == "PEAK" and p["price"] >= cleaned[-1]["price"]:
                cleaned[-1] = p
            elif p["type"] == "TROUGH" and p["price"] <= cleaned[-1]["price"]:
                cleaned[-1] = p
        else:
            cleaned.append(p)

    return cleaned
