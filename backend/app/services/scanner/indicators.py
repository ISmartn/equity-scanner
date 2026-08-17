from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def atr(df: pd.DataFrame, window: int = 10) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window, min_periods=window).mean()


def rolling_max(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).max()


def rolling_min(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).min()


def range_pct(high: pd.Series, low: pd.Series, ref: pd.Series) -> pd.Series:
    return (high - low) / ref.replace(0, np.nan)


def close_position_in_range(row: pd.Series) -> float:
    span = row["high"] - row["low"]
    if span <= 0:
        return 0.5
    return float((row["close"] - row["low"]) / span)


def volume_zscore(volume: pd.Series, window: int = 50) -> pd.Series:
    mean = volume.rolling(window, min_periods=window).mean()
    std = volume.rolling(window, min_periods=window).std()
    return (volume - mean) / std.replace(0, np.nan)


def relative_volume(volume: pd.Series, window: int = 20) -> float | None:
    """Today's volume / prior ``window``-session average volume (excludes today)."""
    if len(volume) < window + 1:
        return None
    avg = float(volume.iloc[-(window + 1) : -1].mean())
    if avg <= 0:
        return None
    return float(volume.iloc[-1]) / avg


def upper_wick_ratio(row: pd.Series) -> float | None:
    """Upper wick as a fraction of the full bar range (0 = no wick, 1 = doji at lows)."""
    high = float(row["high"])
    low = float(row["low"])
    open_ = float(row["open"])
    close = float(row["close"])
    span = high - low
    if span <= 0:
        return None
    body_top = max(open_, close)
    return (high - body_top) / span


def rsi(close: pd.Series, window: int = 14) -> float | None:
    if len(close) < window + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    last_gain = float(gain.iloc[-1]) if pd.notna(gain.iloc[-1]) else None
    last_loss = float(loss.iloc[-1]) if pd.notna(loss.iloc[-1]) else None
    if last_gain is None or last_loss is None:
        return None
    if last_loss == 0:
        return 100.0
    rs = last_gain / last_loss
    return 100.0 - (100.0 / (1.0 + rs))


def base_depth_pct(df: pd.DataFrame, window: int = 40) -> float | None:
    if len(df) < window:
        return None
    segment = df.iloc[-window:]
    base_low = float(segment["low"].min())
    if base_low <= 0:
        return None
    base_high = float(segment["high"].max())
    return (base_high - base_low) / base_low * 100.0
