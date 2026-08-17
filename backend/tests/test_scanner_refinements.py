"""Tests for scanner refinements from 1-month forward-path analysis."""

from __future__ import annotations

import pandas as pd

from app.services.scanner.filters import MIN_AVG_TURNOVER_INR, evaluate_liquidity
from app.services.scanner.patterns import score_vcp


def _make_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_liquidity_passes_with_sufficient_turnover() -> None:
    rows = []
    for _ in range(25):
        rows.append({"close": 100.0, "high": 101.0, "low": 99.0, "open": 100.0, "volume": 1_000_000})
    result = evaluate_liquidity(_make_df(rows))
    assert result["pass"] is True
    assert result["avg_turnover_inr"] >= MIN_AVG_TURNOVER_INR


def test_liquidity_rejects_thin_names() -> None:
    rows = []
    for _ in range(25):
        rows.append({"close": 50.0, "high": 51.0, "low": 49.0, "open": 50.0, "volume": 10_000})
    result = evaluate_liquidity(_make_df(rows))
    assert result["pass"] is False


def test_vcp_rejects_when_far_below_pivot() -> None:
    """Contraction alone is not enough — must be near pivot or breakout (two-stage)."""
    rows = []
    for i in range(280):
        price = 80.0
        rows.append(
            {
                "date": f"2024-01-{i % 28 + 1:02d}",
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price,
                "volume": 800_000 if i >= 260 else 1_200_000,
            }
        )
    rows[-12]["high"] = 120.0
    df = _make_df(rows)
    assert score_vcp(df) is None
