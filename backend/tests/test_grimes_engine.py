"""Unit tests for the Grimes quantitative engine."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.services.labs.grimes.diagnostics import (
    calculate_expectancy,
    calculate_mae_mfe,
    run_monte_carlo_control,
)
from app.services.labs.grimes.indicators import attach_indicators, nr7_mask
from app.services.labs.grimes.pivots import fractal_pivots
from app.services.labs.grimes.regime import classify_regime
from app.services.labs.grimes.risk import (
    calculate_position_size,
    calculate_r_multiples,
    evaluate_time_stop,
    hybrid_stop,
)


def _trending_df(*, n: int = 160, bull: bool = True) -> pd.DataFrame:
    rows: list[dict] = []
    d = date(2025, 1, 2)
    price = 100.0
    i = 0
    while len(rows) < n:
        if d.weekday() < 5:
            drift = 0.35 if bull else -0.35
            # Mild pullback every 8th bar
            step = -0.55 if i % 8 == 7 else drift
            o = price
            c = price + step
            h = max(o, c) + 0.4
            l = min(o, c) - 0.35
            rows.append(
                {
                    "date": d.isoformat(),
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": 1_000_000 + (i % 5) * 50_000,
                }
            )
            price = c
            i += 1
        d += timedelta(days=1)
    df = pd.DataFrame(rows)
    df["_dt"] = pd.to_datetime(df["date"])
    return df.set_index("_dt")


def test_position_size_one_percent():
    out = calculate_position_size(100_000, 0.01, 100.0, 95.0)
    assert out["valid"] is True
    assert out["shares"] == 200  # 1000 / 5
    assert out["risk_amount"] == 1000.0


def test_r_multiples_long_and_short():
    long_t = calculate_r_multiples(100, 95, [1, 2, 3], "long")
    assert long_t["prices"]["1"] == 105.0
    assert long_t["prices"]["2"] == 110.0
    short_t = calculate_r_multiples(100, 105, [1, 2], "short")
    assert short_t["prices"]["1"] == 95.0


def test_hybrid_stop_never_tighter_than_1atr():
    stop = hybrid_stop(side="long", entry=100.0, swing_stop=99.8, atr_value=2.0)
    assert stop <= 100.0 - 2.0  # 1 ATR floor
    wide = hybrid_stop(side="long", entry=100.0, swing_stop=90.0, atr_value=2.0)
    assert wide >= 100.0 - 2.0 * 2.0 - 1e-9


def test_expectancy_classic_example():
    trades = [{"r": 2.0}] * 4 + [{"r": -1.0}] * 6
    stats = calculate_expectancy(trades)
    assert stats["n"] == 10
    assert abs(stats["expectancy"] - 0.2) < 1e-9
    assert abs(stats["win_rate"] - 0.4) < 1e-9


def test_mae_mfe_long():
    path = pd.DataFrame({"high": [102, 108], "low": [97, 99]})
    out = calculate_mae_mfe(100, 95, "long", path)
    assert out["mae_r"] == 0.6  # (100-97)/5
    assert out["mfe_r"] == 1.6  # (108-100)/5


def test_time_stop_kills_stalled_trade():
    stalled = evaluate_time_stop(0, 10, max_hold_bars=8, current_r=0.1, min_r=0.5)
    assert stalled["kill"] is True
    ok = evaluate_time_stop(0, 10, max_hold_bars=8, current_r=1.2, min_r=0.5)
    assert ok["kill"] is False


def test_nr7_is_narrowest_of_seven():
    df = _trending_df()
    df.iloc[-1, df.columns.get_loc("high")] = df.iloc[-1]["low"] + 0.01
    mask = nr7_mask(df)
    assert bool(mask.iloc[-1]) is True


def test_fractal_pivots_on_oscillation():
    n = 80
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    t = np.arange(n)
    close = 100 + 4 * np.sin(t / 4.5)
    df = pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 0.8,
            "low": close - 0.8,
            "close": close,
            "volume": 1_000_000,
        },
        index=idx,
    )
    pivots = fractal_pivots(df, n=2)
    assert len(pivots) >= 5
    labels = {p["label"] for p in pivots}
    assert labels & {"HH", "HL", "LH", "LL"}


def test_bull_trend_regime_on_synthetic_uptrend():
    raw = _trending_df(bull=True)
    df = attach_indicators(raw)
    pivots = fractal_pivots(df, n=3)
    info = classify_regime(df, pivots, weekly_ema_up=True)
    assert info["regime"] in {"TREND_BULL", "VOLATILITY_COMPRESSION", "TRADING_RANGE"}
    assert info["ma_stack"] == "bull"


def test_monte_carlo_returns_pvalue_on_enough_events():
    df = attach_indicators(_trending_df(n=180))
    idxs = list(range(40, 160, 8))
    mc = run_monte_carlo_control(idxs, df, n_simulations=80, horizon=5, rng=np.random.default_rng(1))
    assert mc["n_patterns"] >= 5
    assert mc["p_value"] is not None
    assert 0 < mc["p_value"] <= 1
