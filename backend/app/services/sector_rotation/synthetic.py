"""Build equal-weight synthetic sector OHLCV from constituent daily bars."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .indicators_ext import ensure_ohlcv_frame


def build_synthetic_ohlcv(
    constituent_frames: dict[str, pd.DataFrame],
    *,
    base: float = 100.0,
) -> pd.DataFrame | None:
    """
    Equal-weight synthetic index from constituent OHLCV frames.

    - Align on chronological date index (no reverse sorts).
    - Mean of daily % returns across available names each day.
    - Cumulative product from ``base``.
    - Volume = sum of constituent volumes.
    - High/Low from close * (1 ± mean high/low excursion vs close).
    """
    closes: dict[str, pd.Series] = {}
    volumes: dict[str, pd.Series] = {}
    highs: dict[str, pd.Series] = {}
    lows: dict[str, pd.Series] = {}

    for ticker, raw in constituent_frames.items():
        if raw is None or raw.empty:
            continue
        try:
            frame = ensure_ohlcv_frame(raw)
        except ValueError:
            continue
        if len(frame) < 30:
            continue
        closes[ticker] = frame["close"]
        volumes[ticker] = frame["volume"]
        highs[ticker] = frame["high"]
        lows[ticker] = frame["low"]

    if len(closes) < 2:
        return None

    close_df = pd.DataFrame(closes).sort_index(kind="mergesort")
    # Prefer days with at least 2 live constituents; forward-fill short histories.
    close_df = close_df.ffill(limit=5)
    rets = close_df.pct_change()
    # Ignore first-day NaNs from IPO joins without polluting the mean.
    mean_ret = rets.mean(axis=1, skipna=True)
    mean_ret = mean_ret.dropna()
    if len(mean_ret) < 60:
        return None

    synth_close = (1.0 + mean_ret).cumprod() * base
    vol_df = pd.DataFrame(volumes).reindex(synth_close.index).fillna(0.0)
    synth_vol = vol_df.sum(axis=1)

    high_exc = ((pd.DataFrame(highs).reindex(synth_close.index) / close_df.reindex(synth_close.index)) - 1.0).mean(
        axis=1, skipna=True
    )
    low_exc = ((pd.DataFrame(lows).reindex(synth_close.index) / close_df.reindex(synth_close.index)) - 1.0).mean(
        axis=1, skipna=True
    )
    high_exc = high_exc.fillna(0.0).clip(lower=0.0)
    low_exc = low_exc.fillna(0.0).clip(upper=0.0)

    synth_high = synth_close * (1.0 + high_exc)
    synth_low = synth_close * (1.0 + low_exc)
    synth_open = synth_close.shift(1).fillna(synth_close.iloc[0])

    out = pd.DataFrame(
        {
            "open": synth_open,
            "high": np.maximum(synth_high, np.maximum(synth_open, synth_close)),
            "low": np.minimum(synth_low, np.minimum(synth_open, synth_close)),
            "close": synth_close,
            "volume": synth_vol,
        },
        index=synth_close.index,
    )
    return out


def constituent_day_returns(
    constituent_frames: dict[str, pd.DataFrame],
    as_of: pd.Timestamp,
) -> list[dict[str, Any]]:
    """Latest session % change per constituent for summary badges."""
    rows: list[dict[str, Any]] = []
    for ticker, raw in constituent_frames.items():
        if raw is None or raw.empty:
            continue
        try:
            frame = ensure_ohlcv_frame(raw)
        except ValueError:
            continue
        sub = frame.loc[:as_of]
        if len(sub) < 2:
            continue
        last = sub.iloc[-1]
        prev = sub.iloc[-2]
        if float(prev["close"]) <= 0:
            continue
        chg = (float(last["close"]) / float(prev["close"]) - 1.0) * 100.0
        rows.append({"ticker": ticker, "change_pct": round(chg, 2), "close": float(last["close"])})
    return rows
