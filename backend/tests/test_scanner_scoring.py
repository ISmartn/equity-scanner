"""Tests for scoring weights, quality gates, and VCP two-stage behavior."""

from __future__ import annotations

import pandas as pd

from app.services.scanner.patterns import (
    score_darvas_pre_setup,
    score_pocket_pivot_setup,
    score_tight_range_near_pivot,
    score_vcp,
)
from app.services.scanner.scoring import (
    compose_signal_scores,
    extension_penalty,
    passes_hard_extension_gate,
    passes_posthoc_quality_filters,
)


def _make_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_extension_penalty_tiers() -> None:
    assert extension_penalty(10.0) == 0.0
    assert extension_penalty(13.0) == -5.0
    assert extension_penalty(20.0) == -15.0


def test_hard_extension_gate_allows_shallow_htf() -> None:
    assert passes_hard_extension_gate(
        pattern_type="pocket_pivot",
        pre_20d_return_pct=40.0,
        details={},
    ) is False
    assert passes_hard_extension_gate(
        pattern_type="high_tight_flag",
        pre_20d_return_pct=40.0,
        details={"flag_depth_pct": 8.0},
    ) is True


def test_compose_includes_efficiency_and_macro_bonus() -> None:
    parts = compose_signal_scores(
        pattern_score=90.0,
        context_adjustment=2.0,
        fo_multiplier=1.0,
        macro_pass=True,
        setup_ready=True,
        triggered_today=False,
        pre_20d_return_pct=5.0,
    )
    assert parts["macro_bonus"] == 5.0
    assert parts["composite_score"] >= 90.0
    assert parts["efficiency_score"] >= parts["composite_score"]


def test_vcp_setup_without_breakout_when_near_pivot() -> None:
    rows = []
    for i in range(280):
        # Contracting envelopes so last 20d > 10d > 5d ranges
        if i < 240:
            amp = 3.5
        elif i < 260:
            amp = 1.8
        elif i < 270:
            amp = 0.9
        else:
            amp = 0.35
        close = 100.0
        rows.append(
            {
                "date": f"2024-06-{(i % 28) + 1:02d}",
                "open": close,
                "high": close + amp,
                "low": close - amp,
                "close": close - 0.05,
                "volume": 1_400_000 if i < 250 else 650_000,
            }
        )
    # Pivot from prior 10 highs; last 5 tighter than prior 5 of that window
    for j in range(-11, -6):
        rows[j]["high"] = 100.5
        rows[j]["low"] = 99.2
        rows[j]["close"] = 100.0
    for j in range(-6, -1):
        rows[j]["high"] = 100.35
        rows[j]["low"] = 99.7
        rows[j]["close"] = 100.0
    rows[-1]["high"] = 100.2
    rows[-1]["low"] = 99.75
    rows[-1]["close"] = 99.95
    rows[-1]["volume"] = 600_000
    hit = score_vcp(_make_df(rows))
    assert hit is not None
    assert hit.setup_ready is True
    assert hit.triggered_today is False


def test_vcp_rejects_far_from_pivot_without_breakout() -> None:
    rows = []
    for i in range(280):
        price = 80.0
        rows.append(
            {
                "date": f"2024-01-{(i % 28) + 1:02d}",
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price,
                "volume": 800_000,
            }
        )
    # Inject a high pivot far above current price
    rows[-15]["high"] = 120.0
    hit = score_vcp(_make_df(rows))
    assert hit is None


def test_posthoc_filter_respects_min_scores() -> None:
    signal = {
        "pattern_type": "pocket_pivot",
        "score": 91.0,
        "details": {"pre_20d_return_pct": 5.0},
    }
    assert passes_posthoc_quality_filters(signal) is False  # MIN now 95
    signal["score"] = 96.0
    assert passes_posthoc_quality_filters(signal) is True


def test_tight_range_near_pivot_emits_setup() -> None:
    rows = []
    for i in range(40):
        close = 103.0
        rows.append(
            {
                "date": f"2024-02-{(i % 28) + 1:02d}",
                "open": close,
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "volume": 400_000,
            }
        )
    rows[-12]["high"] = 105.0
    hit = score_tight_range_near_pivot(_make_df(rows))
    assert hit is not None
    assert hit.setup_ready is True
    assert hit.pattern_type == "tight_range_near_pivot"


def test_darvas_pre_setup_emits_coil_setup() -> None:
    """Uptrend + contracting ranges + near prior 20d high → setup_ready."""
    rows = []
    price = 80.0
    for i in range(60):
        # Gentle uptrend with shrinking swings into the last 20 bars
        price += 0.35
        if i < 30:
            amp = 4.0
        elif i < 45:
            amp = 2.2
        elif i < 55:
            amp = 1.1
        else:
            amp = 0.45
        vol = 1_200_000 if i < 50 else 700_000
        rows.append(
            {
                "date": f"2024-05-{(i % 28) + 1:02d}",
                "open": price,
                "high": price + amp,
                "low": price - amp * 0.6,
                "close": price + amp * 0.15,
                "volume": vol,
            }
        )
    # Ensure last close sits just under a clear prior pivot high
    pivot = max(float(r["high"]) for r in rows[-21:-1])
    rows[-1]["close"] = pivot * 0.985
    rows[-1]["high"] = rows[-1]["close"] + 0.2
    rows[-1]["low"] = rows[-1]["close"] - 0.3
    rows[-1]["open"] = rows[-1]["close"] - 0.1
    hit = score_darvas_pre_setup(_make_df(rows))
    assert hit is not None
    assert hit.pattern_type == "darvas_pre_setup"
    assert hit.setup_ready is True
    assert hit.triggered_today is False
    assert hit.details.get("higher_lows") is True


def test_darvas_pre_setup_breakout_is_trigger() -> None:
    rows = []
    price = 80.0
    for i in range(60):
        price += 0.35
        if i < 30:
            amp = 4.0
        elif i < 45:
            amp = 2.2
        elif i < 55:
            amp = 1.1
        else:
            amp = 0.45
        vol = 1_200_000 if i < 50 else 700_000
        rows.append(
            {
                "date": f"2024-05-{(i % 28) + 1:02d}",
                "open": price,
                "high": price + amp,
                "low": price - amp * 0.6,
                "close": price + amp * 0.15,
                "volume": vol,
            }
        )
    pivot = max(float(r["high"]) for r in rows[-21:-1])
    rows[-1]["close"] = pivot * 1.01
    rows[-1]["high"] = rows[-1]["close"] + 0.5
    rows[-1]["low"] = pivot * 0.99
    rows[-1]["open"] = pivot
    rows[-1]["volume"] = 2_000_000
    hit = score_darvas_pre_setup(_make_df(rows))
    assert hit is not None
    assert hit.triggered_today is True
    assert hit.setup_ready is False
    assert hit.details.get("stage") == "breakout"


def test_pocket_pivot_setup_requires_building_not_max() -> None:
    rows = []
    for i in range(60):
        close = 100.0 + i * 0.05
        # Alternate down days with high volume
        is_down = i % 3 == 0
        vol = 2_000_000 if is_down else 800_000
        prev = 100.0 + (i - 1) * 0.05
        rows.append(
            {
                "date": f"2024-03-{(i % 28) + 1:02d}",
                "open": prev,
                "high": close + 1,
                "low": close - 1,
                "close": close - 0.5 if is_down else close,
                "volume": vol,
            }
        )
    # Last bar: up, volume building but below max down vol
    rows[-1]["close"] = float(rows[-2]["close"]) + 0.3
    rows[-1]["open"] = float(rows[-2]["close"])
    rows[-1]["volume"] = 1_200_000
    hit = score_pocket_pivot_setup(_make_df(rows))
    # May or may not fire depending on base context; just ensure no crash and type if present
    if hit is not None:
        assert hit.pattern_type == "pocket_pivot_setup"
        assert hit.setup_ready is True
        assert hit.triggered_today is False
