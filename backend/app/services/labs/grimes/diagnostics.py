"""Expectancy, MAE/MFE, Monte Carlo random-entry control."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

from .risk import r_multiple_now

Side = Literal["long", "short"]


def calculate_expectancy(trades: list[dict[str, Any]]) -> dict[str, Any]:
    rs: list[float] = []
    for t in trades:
        r = t.get("r")
        if r is None:
            continue
        try:
            rs.append(float(r))
        except (TypeError, ValueError):
            continue
    if not rs:
        return {
            "n": 0,
            "win_rate": None,
            "loss_rate": None,
            "profit_factor": None,
            "expectancy": None,
            "avg_win_r": None,
            "avg_loss_r": None,
            "avg_r": None,
            "stdev_r": None,
            "skew": None,
            "excess_kurtosis": None,
            "histogram": [],
        }
    arr = np.asarray(rs, dtype=float)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    n = len(arr)
    win_rate = float(len(wins) / n)
    loss_rate = float(len(losses) / n)
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(np.abs(losses).mean()) if len(losses) else 0.0
    expectancy = win_rate * avg_win - loss_rate * avg_loss
    gross_win = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float(np.abs(losses).sum()) if len(losses) else 0.0
    pf = gross_win / gross_loss if gross_loss > 0 else (None if gross_win == 0 else float("inf"))
    stdev = float(arr.std(ddof=1)) if n > 1 else 0.0
    skew = float(((arr - arr.mean()) ** 3).mean() / (stdev ** 3)) if stdev > 1e-12 else 0.0
    kurt = float(((arr - arr.mean()) ** 4).mean() / (stdev ** 4) - 3.0) if stdev > 1e-12 else 0.0

    hist = [
        {"bin": "<-3R", "count": int((arr <= -3).sum())},
        {"bin": "-3 to -2", "count": int(((arr > -3) & (arr <= -2)).sum())},
        {"bin": "-2 to -1", "count": int(((arr > -2) & (arr <= -1)).sum())},
        {"bin": "-1 to 0", "count": int(((arr > -1) & (arr <= 0)).sum())},
        {"bin": "0 to 1", "count": int(((arr > 0) & (arr <= 1)).sum())},
        {"bin": "1 to 2", "count": int(((arr > 1) & (arr <= 2)).sum())},
        {"bin": "2 to 3", "count": int(((arr > 2) & (arr <= 3)).sum())},
        {"bin": ">3R", "count": int((arr > 3).sum())},
    ]

    return {
        "n": n,
        "win_rate": round(win_rate, 4),
        "loss_rate": round(loss_rate, 4),
        "profit_factor": None if pf is None else (round(pf, 4) if np.isfinite(pf) else None),
        "expectancy": round(expectancy, 4),
        "avg_win_r": round(avg_win, 4) if len(wins) else None,
        "avg_loss_r": round(avg_loss, 4) if len(losses) else None,
        "avg_r": round(float(arr.mean()), 4),
        "stdev_r": round(stdev, 4),
        "skew": round(skew, 4),
        "excess_kurtosis": round(kurt, 4),
        "histogram": hist,
    }


def calculate_mae_mfe(
    entry: float,
    stop: float,
    side: Side,
    ohlcv_during: pd.DataFrame,
) -> dict[str, Any]:
    r = abs(float(entry) - float(stop))
    if r <= 0 or ohlcv_during is None or ohlcv_during.empty:
        return {"mae_r": None, "mfe_r": None, "r": r}
    high = float(ohlcv_during["high"].max())
    low = float(ohlcv_during["low"].min())
    if side == "long":
        mae = (float(entry) - low) / r
        mfe = (high - float(entry)) / r
    else:
        mae = (high - float(entry)) / r
        mfe = (float(entry) - low) / r
    return {
        "mae_r": round(max(0.0, mae), 4),
        "mfe_r": round(max(0.0, mfe), 4),
        "r": round(r, 6),
    }


def simulate_paper_trade(
    df: pd.DataFrame,
    *,
    signal_index: int,
    side: Side,
    stop: float,
    hold_bars: int = 20,
    scale_r: float = 2.0,
) -> dict[str, Any] | None:
    """Enter next bar open after signal; exit at stop, +scale_r, or time."""
    entry_i = signal_index + 1
    if entry_i >= len(df) or signal_index < 0:
        return None
    entry = float(df["open"].iloc[entry_i])
    if entry <= 0 or abs(entry - stop) <= 0:
        return None
    end_i = min(len(df) - 1, entry_i + hold_bars)
    path = df.iloc[entry_i : end_i + 1]
    mae_mfe = calculate_mae_mfe(entry, stop, side, path)
    exit_price = float(df["close"].iloc[end_i])
    exit_reason = "time"
    for j in range(entry_i, end_i + 1):
        bar = df.iloc[j]
        if side == "long":
            if float(bar["low"]) <= stop:
                exit_price = stop
                exit_reason = "stop"
                path = df.iloc[entry_i : j + 1]
                break
            target = entry + scale_r * abs(entry - stop)
            if float(bar["high"]) >= target:
                exit_price = target
                exit_reason = "target"
                path = df.iloc[entry_i : j + 1]
                break
        else:
            if float(bar["high"]) >= stop:
                exit_price = stop
                exit_reason = "stop"
                path = df.iloc[entry_i : j + 1]
                break
            target = entry - scale_r * abs(entry - stop)
            if float(bar["low"]) <= target:
                exit_price = target
                exit_reason = "target"
                path = df.iloc[entry_i : j + 1]
                break
    mae_mfe = calculate_mae_mfe(entry, stop, side, path)
    r_final = r_multiple_now(entry, stop, exit_price, side)
    return {
        "entry_index": entry_i,
        "signal_index": signal_index,
        "side": side,
        "entry": round(entry, 4),
        "stop": round(float(stop), 4),
        "exit": round(exit_price, 4),
        "exit_reason": exit_reason,
        "r": round(r_final, 4),
        "mae_r": mae_mfe["mae_r"],
        "mfe_r": mae_mfe["mfe_r"],
        "timestamp": str(df.index[signal_index])[:10],
    }


def run_monte_carlo_control(
    pattern_indices: list[int],
    ohlcv: pd.DataFrame,
    n_simulations: int = 1000,
    horizon: int = 10,
    side: Side = "long",
    rng: np.random.Generator | None = None,
) -> dict[str, Any]:
    if ohlcv is None or len(ohlcv) <= horizon + 5:
        return {"p_value": None, "n_patterns": 0, "n_simulations": n_simulations, "horizon": horizon}

    close = ohlcv["close"].to_numpy(dtype=float)
    n = len(close)
    valid_idx = [i for i in pattern_indices if 0 <= i < n - horizon]
    if len(valid_idx) < 5:
        return {
            "p_value": None,
            "n_patterns": len(valid_idx),
            "n_simulations": n_simulations,
            "horizon": horizon,
            "note": "need >= 5 dated setups inside the series",
        }

    def fwd_mean(idxs: list[int]) -> float:
        rets = []
        for i in idxs:
            c0 = close[i]
            c1 = close[i + horizon]
            if c0 <= 0 or not np.isfinite(c0) or not np.isfinite(c1):
                continue
            r = (c1 - c0) / c0
            rets.append(r if side == "long" else -r)
        return float(np.mean(rets)) if rets else 0.0

    observed = fwd_mean(valid_idx)
    gen = rng or np.random.default_rng(7)
    lo, hi = 20, n - horizon - 1
    k = len(valid_idx)
    if hi - lo < k:
        return {"p_value": None, "n_patterns": k, "note": "series too short for control"}

    random_means = np.empty(n_simulations, dtype=float)
    for s in range(n_simulations):
        draw = gen.choice(np.arange(lo, hi + 1), size=k, replace=False)
        random_means[s] = fwd_mean(draw.tolist())

    # One-sided: fraction of random means >= observed
    p = (1.0 + float(np.sum(random_means >= observed))) / (n_simulations + 1)
    rand_mean = float(random_means.mean())
    rand_std = float(random_means.std(ddof=1)) if n_simulations > 1 else 0.0
    z = (observed - rand_mean) / rand_std if rand_std > 1e-12 else 0.0
    return {
        "p_value": round(p, 4),
        "observed_mean_fwd": round(observed, 6),
        "random_mean_fwd": round(rand_mean, 6),
        "random_std_fwd": round(rand_std, 6),
        "z_score": round(float(z), 4),
        "n_patterns": k,
        "n_simulations": n_simulations,
        "horizon": horizon,
        "side": side,
    }
