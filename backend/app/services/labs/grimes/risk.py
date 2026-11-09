"""Position sizing, R-multiples, trailing stops, time stops."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

Side = Literal["long", "short"]
TrailMethod = Literal["SWING_PIVOT", "EMA_TRAIL", "ATR_CHANDELIER"]


def calculate_position_size(
    account_size: float,
    risk_percentage: float,
    entry_price: float,
    stop_loss_price: float,
) -> dict[str, Any]:
    equity = float(account_size)
    f = float(risk_percentage)
    entry = float(entry_price)
    stop = float(stop_loss_price)
    r_distance = abs(entry - stop)
    valid = equity > 0 and 0 < f <= 0.2 and entry > 0 and r_distance > 0
    if not valid:
        return {
            "shares": 0,
            "notional": 0.0,
            "risk_amount": 0.0,
            "r_distance": round(r_distance, 6) if r_distance == r_distance else None,
            "valid": False,
        }
    risk_amount = equity * f
    shares = int(risk_amount // r_distance)
    notional = shares * entry
    return {
        "shares": shares,
        "notional": round(notional, 2),
        "risk_amount": round(min(risk_amount, shares * r_distance), 2),
        "r_distance": round(r_distance, 6),
        "valid": shares > 0,
    }


def calculate_r_multiples(
    entry: float,
    stop_loss: float,
    targets: list[float] | None = None,
    side: Side = "long",
) -> dict[str, Any]:
    tlist = targets if targets is not None else [1.0, 2.0, 3.0]
    entry_f = float(entry)
    stop_f = float(stop_loss)
    r = abs(entry_f - stop_f)
    prices: dict[str, float] = {}
    if r <= 0:
        return {"r": 0.0, "prices": prices, "side": side}
    sign = 1.0 if side == "long" else -1.0
    for t in tlist:
        prices[str(t)] = round(entry_f + sign * float(t) * r, 6)
    return {"r": round(r, 6), "prices": prices, "side": side}


def hybrid_stop(
    *,
    side: Side,
    entry: float,
    swing_stop: float | None,
    atr_value: float,
    k_atr: float = 1.8,
    min_atr: float = 1.0,
    max_atr: float = 2.0,
    buffer_atr: float = 0.15,
) -> float:
    """Closer of structural (buffered) and 2×ATR, never tighter than 1×ATR."""
    atr_v = float(atr_value) if atr_value and np.isfinite(atr_value) else 0.0
    if atr_v <= 0:
        atr_v = abs(entry) * 0.02
    vol_wide = k_atr * atr_v
    vol_max = max_atr * atr_v
    vol_min = min_atr * atr_v
    if side == "long":
        vol_stop = entry - min(vol_wide, vol_max)
        if swing_stop is not None and np.isfinite(swing_stop):
            struct = float(swing_stop) - buffer_atr * atr_v
            candidate = max(struct, vol_stop) if struct < entry else vol_stop
            # "closer" to entry among valid stops below entry
            stops = [s for s in (candidate, vol_stop) if s < entry]
            stop = max(stops) if stops else vol_stop
        else:
            stop = vol_stop
        floor = entry - vol_min
        # never tighter than 1 ATR (stop not above entry - 1 ATR)
        if stop > floor:
            stop = floor
        return float(stop)
    vol_stop = entry + min(vol_wide, vol_max)
    if swing_stop is not None and np.isfinite(swing_stop):
        struct = float(swing_stop) + buffer_atr * atr_v
        candidate = min(struct, vol_stop) if struct > entry else vol_stop
        stops = [s for s in (candidate, vol_stop) if s > entry]
        stop = min(stops) if stops else vol_stop
    else:
        stop = vol_stop
    ceiling = entry + vol_min
    if stop < ceiling:
        stop = ceiling
    return float(stop)


def evaluate_trailing_stop(
    ohlcv: pd.DataFrame,
    trade_direction: Side,
    method: TrailMethod = "SWING_PIVOT",
    entry_index: int = 0,
    chandelier_mult: float = 3.0,
    swing_pivots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if ohlcv is None or ohlcv.empty:
        return {"price": None, "method": method}
    last_i = len(ohlcv) - 1
    entry_index = max(0, min(int(entry_index), last_i))
    window = ohlcv.iloc[entry_index:]
    atr_col = "atr14" if "atr14" in ohlcv.columns else None
    last_atr = float(ohlcv[atr_col].iloc[-1]) if atr_col else float("nan")
    if not np.isfinite(last_atr) or last_atr <= 0:
        last_atr = float((ohlcv["high"] - ohlcv["low"]).iloc[-20:].mean() or 0) or abs(
            float(ohlcv["close"].iloc[-1])
        ) * 0.02

    price: float | None = None
    if method == "EMA_TRAIL":
        if "ema20" in ohlcv.columns and pd.notna(ohlcv["ema20"].iloc[-1]):
            price = float(ohlcv["ema20"].iloc[-1])
        else:
            price = float(ohlcv["close"].ewm(span=20, adjust=False).mean().iloc[-1])
    elif method == "ATR_CHANDELIER":
        if trade_direction == "long":
            hh = float(window["high"].max())
            price = hh - chandelier_mult * last_atr
        else:
            ll = float(window["low"].min())
            price = ll + chandelier_mult * last_atr
    else:
        pivots = swing_pivots or []
        if trade_direction == "long":
            lows = [p for p in pivots if p.get("kind") == "low" and int(p["index"]) <= last_i]
            price = float(lows[-1]["price"]) if lows else float(window["low"].min())
        else:
            highs = [p for p in pivots if p.get("kind") == "high" and int(p["index"]) <= last_i]
            price = float(highs[-1]["price"]) if highs else float(window["high"].max())

    return {"price": round(float(price), 6) if price is not None else None, "method": method}


def evaluate_time_stop(
    entry_bar_index: int,
    current_bar_index: int,
    max_hold_bars: int = 8,
    current_r: float = 0.0,
    min_r: float = 0.5,
) -> dict[str, Any]:
    held = int(current_bar_index) - int(entry_bar_index)
    if held < int(max_hold_bars):
        return {"kill": False, "reason": None, "bars_held": held}
    if current_r < float(min_r):
        return {
            "kill": True,
            "reason": f"momentum stall: {held} bars with R={current_r:.2f} < {min_r}",
            "bars_held": held,
        }
    return {"kill": False, "reason": None, "bars_held": held}


def r_multiple_now(entry: float, stop: float, price: float, side: Side) -> float:
    r = abs(float(entry) - float(stop))
    if r <= 0:
        return 0.0
    if side == "long":
        return (float(price) - float(entry)) / r
    return (float(entry) - float(price)) / r
