"""Tests for scanner timing classification (Phase 1.1 / 1.3)."""

from __future__ import annotations

import pandas as pd

from app.services.scanner.timing import (
    classify_timing_class,
    compute_pre_20d_return_pct,
    compute_signal_day_return_pct,
)


def _make_df(closes: list[float]) -> pd.DataFrame:
    rows = []
    for i, close in enumerate(closes):
        rows.append(
            {
                "date": f"2026-01-{i + 1:02d}",
                "open": close,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 1_000_000,
            }
        )
    return pd.DataFrame(rows)


def test_compute_pre_20d_return_pct() -> None:
    closes = [100.0] * 20 + [120.0]
    assert compute_pre_20d_return_pct(_make_df(closes)) == 20.0


def test_compute_signal_day_return_prefers_daily_return_pct() -> None:
    df = _make_df([100.0, 101.0])
    assert compute_signal_day_return_pct(df, daily_return_pct=2.5) == 2.5


def test_classify_timing_extended_overrides_early() -> None:
    assert (
        classify_timing_class(
            pre_20d_return_pct=18.1,
            setup_ready=True,
            triggered_today=False,
        )
        == "extended"
    )


def test_classify_timing_early_setup() -> None:
    assert (
        classify_timing_class(
            pre_20d_return_pct=8.0,
            setup_ready=True,
            triggered_today=False,
        )
        == "early"
    )


def test_classify_timing_confirmation_when_triggered() -> None:
    assert (
        classify_timing_class(
            pre_20d_return_pct=8.0,
            setup_ready=True,
            triggered_today=True,
        )
        == "confirmation"
    )
