"""Tests for Day-T quality gates that reject momentum fakeouts."""

from __future__ import annotations

import pandas as pd

from app.services.scanner.quality import (
    compute_quality_metrics,
    has_higher_low_structure,
    passes_quality_gates,
)
from app.services.scanner.scoring import passes_posthoc_quality_filters


def _bar(
    *,
    open_: float = 100.0,
    high: float = 102.0,
    low: float = 99.0,
    close: float = 101.5,
    volume: float = 1_000_000,
) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume}


def _df_with_last(**last_overrides: float) -> pd.DataFrame:
    rows = []
    for i in range(60):
        rows.append(_bar(volume=800_000 + (i % 5) * 10_000))
    last = _bar()
    last.update(last_overrides)
    # map open_ key if present
    if "open_" in last:
        last["open"] = last.pop("open_")
    rows[-1] = last
    return pd.DataFrame(rows)


def test_weak_trigger_close_rejected() -> None:
    metrics = {"close_position": 0.45, "upper_wick_ratio": 0.2, "volume_z50": 1.5, "rvol20": 1.8}
    keep, reason = passes_quality_gates(
        pattern_type="pocket_pivot",
        triggered_today=True,
        metrics=metrics,
        details={"pre_20d_return_pct": 8.0},
    )
    assert keep is False
    assert reason == "weak_trigger_close"


def test_strong_trigger_close_accepted() -> None:
    metrics = {
        "close_position": 0.82,
        "upper_wick_ratio": 0.15,
        "volume_z50": 1.4,
        "rvol20": 1.6,
        "pct_above_sma50": 8.0,
    }
    keep, reason = passes_quality_gates(
        pattern_type="pocket_pivot",
        triggered_today=True,
        metrics=metrics,
        details={"pre_20d_return_pct": 8.0},
    )
    assert keep is True
    assert reason is None


def test_climactic_volume_weak_close_rejected() -> None:
    metrics = {"close_position": 0.68, "upper_wick_ratio": 0.2, "volume_z50": 4.0, "rvol20": 3.0}
    keep, reason = passes_quality_gates(
        pattern_type="vcp",
        triggered_today=True,
        metrics=metrics,
        details={"base_depth_pct": 18.0, "pre_20d_return_pct": 10.0},
    )
    assert keep is False
    assert reason == "climactic_volume_weak_close"


def test_vcp_deep_base_rejected_even_as_setup() -> None:
    metrics = {"close_position": 0.8, "volume_z50": 1.0, "rvol20": 1.2}
    keep, reason = passes_quality_gates(
        pattern_type="vcp",
        triggered_today=False,
        metrics=metrics,
        details={"base_depth_pct": 28.0},
    )
    assert keep is False
    assert reason == "vcp_deep_base"


def test_setup_without_deep_base_passes() -> None:
    metrics = {"close_position": 0.4, "volume_z50": 0.2, "rvol20": 0.9}
    keep, reason = passes_quality_gates(
        pattern_type="pocket_pivot_setup",
        triggered_today=False,
        metrics=metrics,
        details={},
    )
    assert keep is True


def test_pocket_blowoff_volume_soft_only() -> None:
    """Extreme volume with a strong close is kept (scoring handles blow-off)."""
    metrics = {"close_position": 0.85, "volume_z50": 5.2, "rvol20": 6.0, "upper_wick_ratio": 0.1}
    keep, reason = passes_quality_gates(
        pattern_type="pocket_pivot",
        triggered_today=True,
        metrics=metrics,
        details={"pre_20d_return_pct": 5.0},
    )
    assert keep is True
    assert reason is None


def test_max_20d_runup_rejected_without_higher_low() -> None:
    metrics = {
        "close_position": 0.85,
        "volume_z50": 1.5,
        "rvol20": 1.6,
        "upper_wick_ratio": 0.1,
        "higher_low_10d": False,
    }
    keep, reason = passes_quality_gates(
        pattern_type="pocket_pivot",
        triggered_today=True,
        metrics=metrics,
        details={"pre_20d_return_pct": 22.0},
    )
    assert keep is False
    assert reason == "max_20d_runup"


def test_max_20d_runup_allowed_with_higher_low_below_ceiling() -> None:
    metrics = {
        "close_position": 0.85,
        "volume_z50": 1.5,
        "rvol20": 1.6,
        "upper_wick_ratio": 0.1,
        "higher_low_10d": True,
    }
    keep, reason = passes_quality_gates(
        pattern_type="pocket_pivot",
        triggered_today=True,
        metrics=metrics,
        details={"pre_20d_return_pct": 22.0},
    )
    assert keep is True
    assert reason is None


def test_max_20d_runup_rejected_even_with_higher_low_above_ceiling() -> None:
    metrics = {
        "close_position": 0.85,
        "volume_z50": 1.5,
        "rvol20": 1.6,
        "upper_wick_ratio": 0.1,
        "higher_low_10d": True,
    }
    keep, reason = passes_quality_gates(
        pattern_type="pocket_pivot",
        triggered_today=True,
        metrics=metrics,
        details={"pre_20d_return_pct": 28.0},
    )
    assert keep is False
    assert reason == "max_20d_runup"


def test_has_higher_low_structure() -> None:
    rows = []
    for i in range(30):
        # Prior 10 days lower lows; recent 10 days higher lows
        low = 90.0 if i < 20 else 95.0
        rows.append(
            {"open": 100.0, "high": 102.0, "low": low, "close": 101.0, "volume": 1_000_000}
        )
    assert has_higher_low_structure(pd.DataFrame(rows), lookback=10) is True


def test_compute_quality_metrics_shape() -> None:
    df = _df_with_last(high=105.0, low=100.0, open_=101.0, close=104.0, volume=2_500_000)
    metrics = compute_quality_metrics(df)
    assert metrics["close_position"] is not None
    assert metrics["close_position"] >= 0.7
    assert metrics["rvol20"] is not None
    assert metrics["rvol20"] > 1.0


def test_posthoc_uses_quality_details() -> None:
    signal = {
        "pattern_type": "pocket_pivot",
        "score": 98.0,
        "triggered_today": True,
        "details": {
            "pre_20d_return_pct": 5.0,
            "close_position": 0.4,
            "volume_zscore": 1.5,
            "quality": {"close_position": 0.4, "rvol20": 1.5, "volume_z50": 1.5},
        },
    }
    assert passes_posthoc_quality_filters(signal) is False
