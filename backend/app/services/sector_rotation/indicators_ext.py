"""Vectorized extras for sector rotation (ADX, OBV, CMF, regression slope)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..scanner.indicators import atr, ema, sma


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff().fillna(0.0))
    return (direction * volume.fillna(0.0)).cumsum()


def cmf(df: pd.DataFrame, window: int = 20) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"].fillna(0.0)
    span = (high - low).replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / span
    mfv = mfm.fillna(0.0) * volume
    return mfv.rolling(window, min_periods=window).sum() / volume.rolling(
        window, min_periods=window
    ).sum().replace(0, np.nan)


def adx(df: pd.DataFrame, window: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (ADX, +DI, -DI) Wilder-smoothed."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(
        np.where((up > down) & (up > 0), up, 0.0),
        index=df.index,
    )
    minus_dm = pd.Series(
        np.where((down > up) & (down > 0), down, 0.0),
        index=df.index,
    )
    tr = atr(df, window=1)
    atr_n = tr.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    plus_di = 100.0 * (
        plus_dm.ewm(alpha=1 / window, adjust=False, min_periods=window).mean() / atr_n.replace(0, np.nan)
    )
    minus_di = 100.0 * (
        minus_dm.ewm(alpha=1 / window, adjust=False, min_periods=window).mean() / atr_n.replace(0, np.nan)
    )
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_s = dx.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    return adx_s, plus_di, minus_di


def linreg_slope(series: pd.Series, window: int = 10) -> pd.Series:
    """Rolling OLS slope of ``series`` vs 0..window-1 (vectorized via rolling cov)."""
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()
    if x_var <= 0:
        return pd.Series(np.nan, index=series.index)

    def _slope(y: np.ndarray) -> float:
        if np.any(~np.isfinite(y)):
            return float("nan")
        y_mean = y.mean()
        return float(((x - x_mean) * (y - y_mean)).sum() / x_var)

    return series.rolling(window, min_periods=window).apply(_slope, raw=True)


def ensure_ohlcv_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names; keep chronological order (do not reverse)."""
    out = df.copy()
    rename = {}
    for col in list(out.columns):
        low = str(col).lower()
        if low in {"open", "high", "low", "close", "volume", "date", "ts"}:
            rename[col] = "date" if low in {"date", "ts"} else low
    if rename:
        out = out.rename(columns=rename)
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"])
        out = out.sort_values("date", kind="mergesort").drop_duplicates("date", keep="last")
        out = out.set_index("date")
    out = out.sort_index(kind="mergesort")
    for col in ("open", "high", "low", "close"):
        if col not in out.columns:
            raise ValueError(f"missing column {col}")
    if "volume" not in out.columns:
        out["volume"] = 0.0
    return out[["open", "high", "low", "close", "volume"]].astype(float)


__all__ = [
    "adx",
    "atr",
    "cmf",
    "ema",
    "ensure_ohlcv_frame",
    "linreg_slope",
    "obv",
    "sma",
]
