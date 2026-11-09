"""OHLCV indicators for the Grimes engine. Missing/zero volume is handled as NaN features."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ...scanner.indicators import atr, ema, sma


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def bollinger(close: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.DataFrame:
    mid = sma(close, window)
    std = close.rolling(window, min_periods=window).std()
    return pd.DataFrame(
        {
            "bb_mid": mid,
            "bb_upper": mid + n_std * std,
            "bb_lower": mid - n_std * std,
            "bb_width": (2.0 * n_std * std) / mid.replace(0, np.nan),
        }
    )


def keltner(
    df: pd.DataFrame,
    window: int = 20,
    atr_mult: float = 1.5,
    atr_window: int | None = None,
) -> pd.DataFrame:
    period = atr_window or window
    mid = ema(df["close"], window)
    a = atr(df, window=period)
    return pd.DataFrame(
        {
            "kc_mid": mid,
            "kc_upper": mid + atr_mult * a,
            "kc_lower": mid - atr_mult * a,
        }
    )


def bar_range(df: pd.DataFrame) -> pd.Series:
    return (df["high"] - df["low"]).clip(lower=0)


def nr7_mask(df: pd.DataFrame, window: int = 7) -> pd.Series:
    rng = bar_range(df)
    rolling_min = rng.rolling(window, min_periods=window).min()
    return (rng > 0) & (rng <= rolling_min + 1e-12) & rng.notna() & rolling_min.notna()


def inside_day_mask(df: pd.DataFrame) -> pd.Series:
    prev_high = df["high"].shift(1)
    prev_low = df["low"].shift(1)
    return (df["high"] < prev_high) & (df["low"] > prev_low)


def consecutive_inside(inside: pd.Series) -> pd.Series:
    """Count of consecutive True bars ending at each index (0 if not inside)."""
    vals = inside.fillna(False).astype(bool).to_numpy()
    out = np.zeros(len(vals), dtype=int)
    run = 0
    for i, flag in enumerate(vals):
        if flag:
            run += 1
        else:
            run = 0
        out[i] = run
    return pd.Series(out, index=inside.index)


def volume_zscore(volume: pd.Series, window: int = 50) -> pd.Series:
    vol = volume.astype(float).replace(0, np.nan)
    mean = vol.rolling(window, min_periods=max(10, window // 2)).mean()
    std = vol.rolling(window, min_periods=max(10, window // 2)).std()
    return (vol - mean) / std.replace(0, np.nan)


def atr_percentile(atr_series: pd.Series, close: pd.Series, window: int = 100) -> pd.Series:
    ratio = atr_series / close.replace(0, np.nan)
    return ratio.rolling(window, min_periods=max(20, window // 5)).rank(pct=True) * 100.0


def attach_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with indicator columns. Requires open/high/low/close; volume optional."""
    out = df.copy()
    if "volume" not in out.columns:
        out["volume"] = np.nan
    out["volume"] = pd.to_numeric(out["volume"], errors="coerce")
    for col in ("open", "high", "low", "close"):
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out["ema20"] = ema(out["close"], 20)
    out["sma50"] = sma(out["close"], 50)
    out["atr14"] = atr(out, 14)
    out["atr20"] = atr(out, 20)
    out["range"] = bar_range(out)
    out["nr7"] = nr7_mask(out)
    out["inside"] = inside_day_mask(out)
    out["inside_run"] = consecutive_inside(out["inside"])
    bb = bollinger(out["close"])
    kc = keltner(out, atr_mult=1.5)
    kc_wide = keltner(out, atr_mult=2.25)
    out = out.join(bb).join(kc)
    out["kc_wide_upper"] = kc_wide["kc_upper"]
    out["kc_wide_lower"] = kc_wide["kc_lower"]
    squeeze = (
        out["bb_upper"].notna()
        & out["kc_upper"].notna()
        & (out["bb_upper"] <= out["kc_upper"])
        & (out["bb_lower"] >= out["kc_lower"])
    )
    out["bb_kc_squeeze"] = squeeze
    macd_df = macd(out["close"])
    out = out.join(macd_df)
    out["vol_z"] = volume_zscore(out["volume"])
    out["atr_pctile"] = atr_percentile(out["atr14"], out["close"])
    prev_ema = out["ema20"].shift(1)
    out["ema20_slope"] = out["ema20"] - prev_ema
    return out


def weekly_ema_rising(df: pd.DataFrame, span: int = 20) -> bool | None:
    """True if last weekly 20-EMA is rising (close-based weekly bars)."""
    if df is None or len(df) < span * 5:
        return None
    close = df["close"].copy()
    if not isinstance(close.index, pd.DatetimeIndex):
        return None
    weekly = close.resample("W-FRI").last().dropna()
    if len(weekly) < span + 2:
        return None
    w_ema = weekly.ewm(span=span, adjust=False, min_periods=span).mean()
    if pd.isna(w_ema.iloc[-1]) or pd.isna(w_ema.iloc[-2]):
        return None
    return bool(w_ema.iloc[-1] > w_ema.iloc[-2])
