"""Grimes pattern / setup detectors."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

from .pivots import last_swings

SetupType = Literal[
    "TREND_PULLBACK",
    "COMPLEX_PULLBACK",
    "VOL_SQUEEZE",
    "FAILED_BREAKOUT",
    "CLIMACTIC_EXHAUSTION",
    "ABSORPTION",
]

SETUP_GROUP: dict[str, str] = {
    "TREND_PULLBACK": "Trend Continuation",
    "COMPLEX_PULLBACK": "Trend Continuation",
    "VOL_SQUEEZE": "Squeeze Breakout",
    "FAILED_BREAKOUT": "Mean Reversion",
    "CLIMACTIC_EXHAUSTION": "Mean Reversion",
    "ABSORPTION": "Mean Reversion",
}


def _safe_float(val: Any) -> float | None:
    if val is None or (isinstance(val, float) and not np.isfinite(val)):
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _near(price: float, level: float, atr_v: float, k: float = 0.6) -> bool:
    if atr_v <= 0:
        return abs(price - level) / max(abs(level), 1e-9) < 0.01
    return abs(price - level) <= k * atr_v


def detect_trend_pullback(df: pd.DataFrame, pivots: list[dict[str, Any]], i: int) -> dict[str, Any] | None:
    if i < 50 or i >= len(df):
        return None
    row = df.iloc[i]
    close = _safe_float(row["close"])
    ema20 = _safe_float(row.get("ema20"))
    sma50 = _safe_float(row.get("sma50"))
    atr_v = _safe_float(row.get("atr14")) or 0.0
    if close is None or ema20 is None or sma50 is None or atr_v <= 0:
        return None

    highs = last_swings([p for p in pivots if p["index"] <= i], "high", 3)
    lows = last_swings([p for p in pivots if p["index"] <= i], "low", 3)
    if len(highs) < 2 or len(lows) < 2:
        return None

    bull = highs[-1]["price"] > highs[-2]["price"] and lows[-1]["price"] > lows[-2]["price"]
    bear = highs[-1]["price"] < highs[-2]["price"] and lows[-1]["price"] < lows[-2]["price"]
    if not bull and not bear:
        return None
    if bull and not (close > sma50 and ema20 > sma50):
        return None
    if bear and not (close < sma50 and ema20 < sma50):
        return None

    magnet = ema20 if _near(close, ema20, atr_v, 0.85) else (
        sma50 if _near(close, sma50, atr_v, 0.85) else None
    )
    if magnet is None:
        return None

    # Range contraction vs prior 8 bars
    rng = _safe_float(row.get("range")) or 0.0
    prior_rng = float(df["range"].iloc[max(0, i - 8) : i].mean() or 0)
    if prior_rng > 0 and rng > 0.95 * prior_rng:
        return None

    vol_declining = True
    vol = df["volume"].iloc[max(0, i - 15) : i + 1]
    if vol.notna().sum() >= 10 and float(vol.iloc[-5:].mean() or 0) > 0:
        impulse = float(vol.iloc[-15:-5].mean() or 0)
        pull = float(vol.iloc[-5:].mean() or 0)
        if impulse > 0:
            vol_declining = pull <= impulse * 1.05

    side = "long" if bull else "short"
    last_struct = lows[-1]["price"] if bull else highs[-1]["price"]
    return {
        "type": "TREND_PULLBACK",
        "side": side,
        "index": i,
        "timestamp": str(df.index[i])[:10],
        "magnet": "ema20" if magnet == ema20 else "sma50",
        "volume_declining": vol_declining,
        "swing_stop": last_struct,
        "quality_hint": 70 if vol_declining else 55,
    }


def detect_complex_pullback(df: pd.DataFrame, pivots: list[dict[str, Any]], i: int) -> dict[str, Any] | None:
    if i < 50 or i >= len(df):
        return None
    eligible = [p for p in pivots if p["index"] <= i]
    if len(eligible) < 6:
        return None
    last = eligible[-4:]
    kinds = [p["kind"] for p in last]
    close = float(df["close"].iloc[i])
    sma50 = df["sma50"].iloc[i]
    if pd.isna(sma50):
        return None

    # Bull ABC: high, low, high, low with 2nd high < 1st high
    if kinds == ["high", "low", "high", "low"]:
        h1, l1, h2, l2 = last
        if h2["price"] < h1["price"] and close > float(sma50):
            return {
                "type": "COMPLEX_PULLBACK",
                "side": "long",
                "index": i,
                "timestamp": str(df.index[i])[:10],
                "abc": {
                    "a": l1["price"],
                    "b": h2["price"],
                    "c": l2["price"],
                },
                "swing_stop": min(l1["price"], l2["price"]),
                "quality_hint": 62,
            }
    if kinds == ["low", "high", "low", "high"]:
        l1, h1, l2, h2 = last
        if l2["price"] > l1["price"] and close < float(sma50):
            return {
                "type": "COMPLEX_PULLBACK",
                "side": "short",
                "index": i,
                "timestamp": str(df.index[i])[:10],
                "abc": {
                    "a": h1["price"],
                    "b": l2["price"],
                    "c": h2["price"],
                },
                "swing_stop": max(h1["price"], h2["price"]),
                "quality_hint": 62,
            }
    return None


def detect_volatility_squeeze(df: pd.DataFrame, i: int) -> dict[str, Any] | None:
    if i < 20 or i >= len(df):
        return None
    row = df.iloc[i]
    flags: list[str] = []
    if bool(row.get("nr7")):
        flags.append("NR7")
    run = int(row.get("inside_run") or 0)
    if run >= 1:
        flags.append(f"INSIDE_x{run}")
    if bool(row.get("bb_kc_squeeze")):
        flags.append("BB_KC")
    if not flags:
        return None
    close = float(row["close"])
    ema20 = row.get("ema20")
    side = "long"
    if pd.notna(ema20):
        side = "long" if close >= float(ema20) else "short"
    return {
        "type": "VOL_SQUEEZE",
        "side": side,
        "index": i,
        "timestamp": str(df.index[i])[:10],
        "flags": flags,
        "swing_stop": None,
        "quality_hint": 58 + min(20, 5 * len(flags) + 3 * max(0, run - 1)),
    }


def detect_failed_breakout(df: pd.DataFrame, pivots: list[dict[str, Any]], i: int) -> dict[str, Any] | None:
    if i < 10 or i >= len(df):
        return None
    eligible = [p for p in pivots if p["index"] < i]
    if not eligible:
        return None
    row = df.iloc[i]
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])
    atr_v = _safe_float(row.get("atr14")) or 0.0
    last_high = last_swings(eligible, "high", 1)
    last_low = last_swings(eligible, "low", 1)

    # Upthrust: pierce last swing high, close back below
    if last_high:
        lvl = float(last_high[-1]["price"])
        if high > lvl and close < lvl and (atr_v <= 0 or (high - lvl) >= 0.15 * atr_v):
            return {
                "type": "FAILED_BREAKOUT",
                "side": "short",
                "index": i,
                "timestamp": str(df.index[i])[:10],
                "variant": "upthrust",
                "level": lvl,
                "swing_stop": high,
                "quality_hint": 68,
            }
    if last_low:
        lvl = float(last_low[-1]["price"])
        if low < lvl and close > lvl and (atr_v <= 0 or (lvl - low) >= 0.15 * atr_v):
            return {
                "type": "FAILED_BREAKOUT",
                "side": "long",
                "index": i,
                "timestamp": str(df.index[i])[:10],
                "variant": "spring",
                "level": lvl,
                "swing_stop": low,
                "quality_hint": 68,
            }
    return None


def detect_climactic_exhaustion(df: pd.DataFrame, i: int) -> dict[str, Any] | None:
    if i < 30 or i >= len(df):
        return None
    row = df.iloc[i]
    atr_v = _safe_float(row.get("atr14"))
    rng = _safe_float(row.get("range"))
    close = _safe_float(row["close"])
    ema20 = _safe_float(row.get("ema20"))
    vol_z = _safe_float(row.get("vol_z"))
    if atr_v is None or atr_v <= 0 or rng is None or close is None or ema20 is None:
        return None
    if rng / atr_v < 2.5:
        return None
    if abs(close - ema20) / atr_v < 2.0:
        return None
    if vol_z is not None and vol_z < 1.5:
        return None
    side = "short" if close > ema20 else "long"
    return {
        "type": "CLIMACTIC_EXHAUSTION",
        "side": side,
        "index": i,
        "timestamp": str(df.index[i])[:10],
        "range_atr": round(rng / atr_v, 2),
        "extension_atr": round(abs(close - ema20) / atr_v, 2),
        "vol_z": None if vol_z is None else round(vol_z, 2),
        "swing_stop": float(row["high"]) if side == "short" else float(row["low"]),
        "quality_hint": 60,
    }


def detect_absorption(df: pd.DataFrame, pivots: list[dict[str, Any]], i: int) -> dict[str, Any] | None:
    if i < 50 or i >= len(df):
        return None
    row = df.iloc[i]
    vol_z = _safe_float(row.get("vol_z"))
    atr_v = _safe_float(row.get("atr14"))
    rng = _safe_float(row.get("range"))
    close = _safe_float(row["close"])
    if vol_z is None or atr_v is None or atr_v <= 0 or rng is None or close is None:
        return None
    if vol_z < 1.5 or rng / atr_v > 0.65:
        return None
    eligible = [p for p in pivots if p["index"] <= i][-8:]
    near = None
    for p in eligible:
        if _near(close, float(p["price"]), atr_v, 0.45):
            near = p
            break
    ema20 = _safe_float(row.get("ema20"))
    sma50 = _safe_float(row.get("sma50"))
    if near is None:
        for lvl, name in ((ema20, "ema20"), (sma50, "sma50")):
            if lvl is not None and _near(close, lvl, atr_v, 0.4):
                near = {"kind": "ma", "label": name, "price": lvl}
                break
    if near is None:
        return None
    side = "long" if near.get("kind") == "low" or close >= (ema20 or close) else "short"
    if near.get("kind") == "high":
        side = "short"
    return {
        "type": "ABSORPTION",
        "side": side,
        "index": i,
        "timestamp": str(df.index[i])[:10],
        "at": near.get("label") or near.get("kind"),
        "level": float(near["price"]),
        "vol_z": round(vol_z, 2),
        "swing_stop": float(row["low"]) if side == "long" else float(row["high"]),
        "quality_hint": 57,
    }


def detect_all_on_bar(df: pd.DataFrame, pivots: list[dict[str, Any]], i: int) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for fn in (
        detect_climactic_exhaustion,
        lambda d, i: detect_volatility_squeeze(d, i),
        lambda d, i: detect_failed_breakout(d, pivots, i),
        lambda d, i: detect_complex_pullback(d, pivots, i),
        lambda d, i: detect_trend_pullback(d, pivots, i),
        lambda d, i: detect_absorption(d, pivots, i),
    ):
        if fn is detect_climactic_exhaustion:
            hit = fn(df, i)
        else:
            hit = fn(df, i)  # type: ignore[misc]
        if hit:
            hit["group"] = SETUP_GROUP.get(str(hit["type"]), "Other")
            found.append(hit)
    return found


def scan_history(df: pd.DataFrame, pivots: list[dict[str, Any]], lookback: int = 180) -> list[dict[str, Any]]:
    if df is None or len(df) < 55:
        return []
    start = max(54, len(df) - lookback)
    setups: list[dict[str, Any]] = []
    for i in range(start, len(df)):
        setups.extend(detect_all_on_bar(df, pivots, i))
    return setups
