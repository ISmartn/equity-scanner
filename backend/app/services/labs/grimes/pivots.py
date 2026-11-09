"""N-bar fractal swing pivots and HH/HL/LH/LL labeling."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

PivotKind = Literal["high", "low"]
StructureLabel = Literal["HH", "HL", "LH", "LL"]


def fractal_pivots(df: pd.DataFrame, n: int = 2) -> list[dict[str, Any]]:
    """
    Confirmed N-bar fractals. A high at i is a pivot if high[i] is the unique max
    on [i-n, i+n]; lows analogously. Pivots at the unconfirmed right edge are omitted.
    """
    if df is None or len(df) < 2 * n + 3:
        return []
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n_bars = len(df)
    timestamps = [str(x)[:10] for x in df.index.astype(str)]
    pivots: list[dict[str, Any]] = []

    for i in range(n, n_bars - n):
        window_h = high[i - n : i + n + 1]
        window_l = low[i - n : i + n + 1]
        h = high[i]
        l = low[i]
        if not np.isfinite(h) or not np.isfinite(l):
            continue
        is_high = np.isfinite(h) and h >= np.nanmax(window_h) - 1e-12
        is_low = np.isfinite(l) and l <= np.nanmin(window_l) + 1e-12
        # If both (doji range), skip — ambiguous
        if is_high and is_low:
            continue
        if is_high:
            pivots.append(
                {
                    "index": int(i),
                    "timestamp": timestamps[i],
                    "price": round(float(h), 4),
                    "kind": "high",
                    "label": None,
                }
            )
        elif is_low:
            pivots.append(
                {
                    "index": int(i),
                    "timestamp": timestamps[i],
                    "price": round(float(l), 4),
                    "kind": "low",
                    "label": None,
                }
            )

    pivots.sort(key=lambda p: p["index"])
    return label_structure(pivots)


def label_structure(pivots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    last_high: float | None = None
    last_low: float | None = None
    out: list[dict[str, Any]] = []
    for p in pivots:
        q = dict(p)
        if q["kind"] == "high":
            if last_high is None:
                q["label"] = "HH"
            else:
                q["label"] = "HH" if q["price"] > last_high else "LH"
            last_high = float(q["price"])
        else:
            if last_low is None:
                q["label"] = "HL"
            else:
                q["label"] = "HL" if q["price"] > last_low else "LL"
            last_low = float(q["price"])
        out.append(q)
    return out


def last_swings(pivots: list[dict[str, Any]], kind: PivotKind, count: int = 3) -> list[dict[str, Any]]:
    subset = [p for p in pivots if p["kind"] == kind]
    return subset[-count:]


def recent_sr_zones(pivots: list[dict[str, Any]], last_close: float, limit: int = 8) -> list[dict[str, Any]]:
    """Static swing levels with polarity vs last close."""
    zones: list[dict[str, Any]] = []
    seen: set[float] = set()
    for p in reversed(pivots):
        price = round(float(p["price"]), 4)
        key = round(price, 2)
        if key in seen:
            continue
        seen.add(key)
        if p["kind"] == "high":
            role = "resistance" if price >= last_close else "flipped_support"
        else:
            role = "support" if price <= last_close else "flipped_resistance"
        zones.append(
            {
                "price": price,
                "kind": p["kind"],
                "label": p.get("label"),
                "timestamp": p["timestamp"],
                "index": p["index"],
                "role": role,
            }
        )
        if len(zones) >= limit:
            break
    zones.reverse()
    return zones
