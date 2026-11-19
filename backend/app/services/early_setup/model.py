"""Setup score: the expected result of the trade, from the leading features.

The score answers one question: if this stock crosses its pivot tomorrow and
the stop-entry order fills, how does that trade tend to turn out? It is not a
forecast of whether the pivot will be crossed. How close a stock sits to its
pivot predicts a cross even on random prices, so a score trained on crossing
mostly learns closeness. Distance to the pivot is shown on its own instead.

The shipped weights are hand-set priors. ``fit`` replaces them with weights
learned from the candle database: a ridge regression of each trade's net result
on the features, fitted on the earlier sessions and measured on the latest
ones, which it never saw. A score of 50 is an average setup.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from ...config import ROOT_DIR
from .features import FEATURES

WEIGHTS_PATH = ROOT_DIR / "data" / "early_setup_weights.json"
TARGET = "trade_ret_pct"
MIN_ROWS = 500
MIN_SESSIONS = 60

# name: (typical value, typical spread, weight). Negative weight: lower is better.
#
# These starting values come from NSE data, February 2025 to November 2026: 73,000
# stock-days on the daily list and the 13,000 trades that followed. The typical
# value and spread are what those rows showed. A reading has a weight only if it
# pointed the same way in both halves of that period; four did, and fourteen
# flipped, including base tightness, volume dry-up and relative strength. The
# weights use all of that data, so they have not been tested on anything later.
# ``fit`` re-derives them from the local database and tests them on unseen sessions.
_DEFAULTS: dict[str, tuple[float, float, float]] = {
    "dist_to_pivot_pct": (3.17, 1.51, 0.0),
    "tightness_pctile": (0.306, 0.239, 0.0),
    "atr_ratio": (0.973, 0.195, 0.0),
    "vol_dryup": (0.901, 0.488, 0.0),
    "updown_vol_log": (0.509, 0.534, 0.0),
    "rs_pctile": (0.767, 0.227, 0.0),
    "rs_new_high": (0.101, 0.301, 0.0),
    "close_tight_pct": (1.23, 0.66, 0.0),
    "ret20_pct": (6.0, 5.87, 0.0),
    "higher_lows": (0.926, 0.262, 0.0),
    "pct_from_52w_high": (15.8, 12.1, -0.38),
    "sector_accel": (0.075, 3.21, -0.21),
    "oi_build": (0.0, 5.0, 0.0),
    "deliv_pct_5d": (49.5, 9.37, 0.0),
    "deliv_trend": (0.593, 5.58, 0.0),
    "group_heat": (1.35, 10.5, 0.25),
    "market_breadth": (58.9, 17.8, 0.25),
    "market_breadth_chg": (1.19, 14.5, 0.0),
}
_DEFAULT_SPREAD = 0.468
# Makes the logistic curve track the normal one, so the score reads as a percentile.
_PROBIT = 1.702

_cache: dict[str, Any] | None = None
_cache_mtime: float | None = None


def default_weights() -> dict[str, Any]:
    return {
        "fitted": False,
        "intercept": 0.0,
        "center": 0.0,
        "spread": _DEFAULT_SPREAD,
        "features": {
            name: {"mean": mean, "std": std, "weight": weight}
            for name, (mean, std, weight) in _DEFAULTS.items()
        },
        "metrics": None,
    }


def load_weights(path: Path | None = None) -> dict[str, Any]:
    """Fitted weights when the file exists and is well formed, otherwise the priors.

    A feature the file does not know (added after it was fitted) counts for nothing
    until the next fit, rather than throwing the whole file away.
    """
    global _cache, _cache_mtime
    target = path or WEIGHTS_PATH
    try:
        mtime = target.stat().st_mtime
    except OSError:
        return default_weights()
    if path is None and _cache is not None and _cache_mtime == mtime:
        return _cache
    try:
        payload = json.loads(target.read_text())
        stored = payload["features"]
        features = {}
        for name in FEATURES:
            if name in stored:
                features[name] = {
                    "mean": float(stored[name]["mean"]),
                    "std": float(stored[name]["std"]) or 1.0,
                    "weight": float(stored[name]["weight"]),
                }
            else:
                features[name] = {"mean": _DEFAULTS[name][0], "std": _DEFAULTS[name][1], "weight": 0.0}
        weights = {
            "fitted": bool(payload.get("fitted", True)),
            "intercept": float(payload["intercept"]),
            "center": float(payload["center"]),
            "spread": float(payload["spread"]) or 1.0,
            "features": features,
            "metrics": payload.get("metrics"),
            "fitted_at": payload.get("fitted_at"),
        }
    except (OSError, ValueError, KeyError, TypeError):
        return default_weights()
    if path is None:
        _cache, _cache_mtime = weights, mtime
    return weights


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1.0 + exp)


def score_row(row: Mapping[str, Any], weights: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Score 0–100 and each feature's push on it. A missing feature counts as average."""
    use = weights or load_weights()
    total = float(use["intercept"])
    parts: dict[str, float] = {}
    for name in FEATURES:
        spec = use["features"][name]
        value = row.get(name)
        try:
            number = float(value) if value is not None else math.nan
        except (TypeError, ValueError):
            number = math.nan
        if math.isnan(number):
            parts[name] = 0.0
            continue
        z = max(-3.0, min(3.0, (number - spec["mean"]) / (spec["std"] or 1.0)))
        parts[name] = spec["weight"] * z
        total += parts[name]
    spread = float(use["spread"]) or 1.0
    return {
        "score": round(_sigmoid(_PROBIT * (total - float(use["center"])) / spread) * 100.0, 1),
        "contributions": {name: round(value / spread, 3) for name, value in parts.items()},
    }


def _linear(frame: pd.DataFrame, weights: Mapping[str, Any]) -> np.ndarray:
    total = np.full(len(frame), float(weights["intercept"]))
    for name in FEATURES:
        spec = weights["features"][name]
        if not spec["weight"]:
            continue
        z = (frame[name].to_numpy(dtype=float) - spec["mean"]) / (spec["std"] or 1.0)
        total += spec["weight"] * np.clip(np.nan_to_num(z, nan=0.0), -3.0, 3.0)
    return total


def score_frame(frame: pd.DataFrame, weights: Mapping[str, Any] | None = None) -> pd.Series:
    use = weights or load_weights()
    z = _PROBIT * (_linear(frame, use) - float(use["center"])) / (float(use["spread"]) or 1.0)
    return pd.Series(100.0 / (1.0 + np.exp(-np.clip(z, -40, 40))), index=frame.index)


# ------------------------------------------------------------------ fitting


def _summary(returns: np.ndarray) -> dict[str, Any]:
    if len(returns) == 0:
        return {"trades": 0}
    return {
        "trades": int(len(returns)),
        "avg_pct": round(float(returns.mean()), 2),
        "median_pct": round(float(np.median(returns)), 2),
        "win_rate_pct": round(float((returns > 0).mean()) * 100.0, 1),
    }


def _spread_interval(dates: np.ndarray, top: np.ndarray, returns: np.ndarray, draws: int = 1000) -> tuple[float, float] | None:
    """90% interval for (top-group average minus the rest), resampling whole days.

    Trades on the same day rise and fall together, so they are not independent
    evidence. Resampling days, not trades, keeps the interval honest about that.
    """
    days, day_index = np.unique(dates, return_inverse=True)
    if len(days) < 10:
        return None
    k = len(days)
    top_sum = np.bincount(day_index, weights=np.where(top, returns, 0.0), minlength=k)
    top_n = np.bincount(day_index, weights=top.astype(float), minlength=k)
    rest_sum = np.bincount(day_index, weights=np.where(top, 0.0, returns), minlength=k)
    rest_n = np.bincount(day_index, weights=(~top).astype(float), minlength=k)
    rng = np.random.default_rng(0)
    picks = rng.integers(0, k, size=(draws, k))
    ts, tn = top_sum[picks].sum(axis=1), top_n[picks].sum(axis=1)
    rs, rn = rest_sum[picks].sum(axis=1), rest_n[picks].sum(axis=1)
    usable = (tn > 0) & (rn > 0)
    if usable.sum() < draws * 0.5:
        return None
    spreads = ts[usable] / tn[usable] - rs[usable] / rn[usable]
    return float(np.percentile(spreads, 5)), float(np.percentile(spreads, 95))


def evaluate(test: pd.DataFrame, scores: np.ndarray) -> dict[str, Any]:
    """How trades ranked by ``scores`` did: everything, the top fifth, and the rest."""
    returns = test[TARGET].to_numpy(dtype=float)
    if len(returns) < 20:
        return {"all": _summary(returns), "verdict": "too_few_trades"}
    cutoff = float(np.quantile(scores, 0.8))
    top = scores >= cutoff
    result: dict[str, Any] = {
        "all": _summary(returns),
        "top_fifth": _summary(returns[top]),
        "rest": _summary(returns[~top]),
        # Spearman by hand (ranks, then Pearson): pandas needs scipy for it, which is not a dependency.
        "rank_correlation": round(float(pd.Series(scores).rank().corr(pd.Series(returns).rank())), 3),
    }
    spread = float(returns[top].mean() - returns[~top].mean()) if top.any() and (~top).any() else None
    result["spread_pct"] = round(spread, 2) if spread is not None else None
    interval = _spread_interval(test["date"].to_numpy(), top, returns)
    if interval is None or spread is None:
        result["verdict"] = "too_few_days"
    else:
        result["spread_low_pct"], result["spread_high_pct"] = round(interval[0], 2), round(interval[1], 2)
        # The score earns its place only when the top fifth beats the rest beyond chance.
        result["verdict"] = "ranks" if interval[0] > 0 else "no_evidence"
    return result


def _ridge(design: np.ndarray, raw: np.ndarray, l2: float) -> np.ndarray:
    # A handful of extreme trades should not set the weights.
    low, high = np.percentile(raw, [1, 99])
    target = np.clip(raw, low, high)
    n, k = design.shape
    return np.linalg.solve(design.T @ design + l2 * n * np.eye(k), design.T @ (target - target.mean()))


def fit(
    dataset: pd.DataFrame,
    *,
    test_share: float = 0.3,
    l2: float = 0.05,
    min_weight: float = 0.03,
) -> dict[str, Any]:
    """Fit on the earlier sessions, measure on the later ones.

    ``dataset`` has one row per (stock, day) in a base with ``date``, the features
    and ``trade_ret_pct``; rows whose pivot was not crossed the next session have
    no trade and are ignored. Rows are split by date, never at random: a random
    split puts the same base in both halves and flatters the result.

    A reading keeps a weight only if it pointed the same way in both halves of
    the fitting period. Most readings flip between periods; a weight fitted to
    one stretch of the market then works against you in the next. On NSE data
    from 2025–26 a plain fit did not rank unseen sessions, and this one did.
    """
    data = dataset.dropna(subset=[TARGET]).sort_values("date")
    if len(data) < MIN_ROWS:
        raise ValueError(f"Only {len(data)} completed trades. At least {MIN_ROWS} are needed to fit.")
    dates = sorted(data["date"].unique())
    if len(dates) < MIN_SESSIONS:
        raise ValueError(f"Only {len(dates)} sessions of data. At least {MIN_SESSIONS} are needed to fit.")
    cut = dates[int(len(dates) * (1.0 - test_share))]
    train = data[data["date"] < cut]
    test = data[data["date"] >= cut]
    train_dates = sorted(train["date"].unique())
    middle = train_dates[len(train_dates) // 2]

    stats: dict[str, tuple[float, float]] = {}
    for name in FEATURES:
        column = train[name].astype(float)
        mean = float(column.mean()) if column.notna().any() else _DEFAULTS[name][0]
        std = float(column.std(ddof=0)) if column.notna().sum() > 1 else 0.0
        stats[name] = (mean, std if std > 1e-9 else _DEFAULTS[name][1])

    def design(frame: pd.DataFrame) -> np.ndarray:
        return np.column_stack(
            [
                np.clip(np.nan_to_num((frame[name].to_numpy(dtype=float) - stats[name][0]) / stats[name][1], nan=0.0), -3, 3)
                for name in FEATURES
            ]
        )

    halves = (train[train["date"] < middle], train[train["date"] >= middle])
    first, second = (_ridge(design(half), half[TARGET].to_numpy(dtype=float), l2) for half in halves)
    agree = (first * second > 0) & (np.minimum(np.abs(first), np.abs(second)) >= min_weight)
    coefficients = np.where(agree, (first + second) / 2.0, 0.0)
    raw = train[TARGET].to_numpy(dtype=float)
    low, high = np.percentile(raw, [1, 99])

    weights: dict[str, Any] = {
        "fitted": True,
        "intercept": float(np.clip(raw, low, high).mean()),
        "center": 0.0,
        "spread": 1.0,
        "features": {
            name: {"mean": stats[name][0], "std": stats[name][1], "weight": float(coefficients[i])}
            for i, name in enumerate(FEATURES)
        },
    }
    fitted = _linear(train, weights)
    weights["center"] = float(fitted.mean())
    weights["spread"] = float(fitted.std()) or 1.0

    priors = default_weights()
    weights["metrics"] = {
        "target": "Net % result of a stop-entry at the pivot, stop at the base low, sold after 10 sessions",
        "train_from": str(train["date"].min()),
        "train_to": str(train["date"].max()),
        "test_from": str(test["date"].min()) if len(test) else None,
        "test_to": str(test["date"].max()) if len(test) else None,
        "kept": [name for i, name in enumerate(FEATURES) if agree[i]],
        "dropped": [name for i, name in enumerate(FEATURES) if not agree[i]],
        "train": evaluate(train, score_frame(train, weights).to_numpy()),
        "test": evaluate(test, score_frame(test, weights).to_numpy()),
        "test_with_default_weights": evaluate(test, score_frame(test, priors).to_numpy()),
    }
    return weights


def save_weights(weights: Mapping[str, Any], fitted_at: str, path: Path | None = None) -> Path:
    global _cache, _cache_mtime
    target = path or WEIGHTS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({**weights, "fitted_at": fitted_at}, indent=2) + "\n")
    _cache, _cache_mtime = None, None
    return target
