"""Tests for F&O scanner overlay (option OI quadrants + multipliers)."""

from __future__ import annotations

from app.services.scanner.fo_overlay import (
    apply_fo_multiplier,
    evaluate_fo_overlay,
)


def test_short_buildup_rejects() -> None:
    result = evaluate_fo_overlay(
        daily_return_pct=-1.0,
        metrics={"oi_change_pct": 8.0, "pcr": 0.9, "pcr_change_pct": 2.0, "total_oi": 1000},
    )
    assert result.action == "REJECT"
    assert result.details["quadrant"] == "short_buildup"


def test_long_buildup_boosts_multiplier() -> None:
    result = evaluate_fo_overlay(
        daily_return_pct=2.0,
        metrics={"oi_change_pct": 10.0, "pcr": 0.8, "pcr_change_pct": 5.0, "total_oi": 2000},
    )
    assert result.action == "PROCEED"
    assert result.details["quadrant"] == "long_buildup"
    assert result.multiplier == 1.15


def test_short_covering_penalizes() -> None:
    result = evaluate_fo_overlay(
        daily_return_pct=1.5,
        metrics={"oi_change_pct": -8.0, "pcr": 0.7, "pcr_change_pct": 0.0, "total_oi": 1500},
    )
    assert result.action == "PROCEED"
    assert result.details["quadrant"] == "short_covering"
    assert result.multiplier == 0.85


def test_pcr_spike_adds_support_multiplier() -> None:
    result = evaluate_fo_overlay(
        daily_return_pct=2.0,
        metrics={"oi_change_pct": 10.0, "pcr": 1.0, "pcr_change_pct": 20.0, "total_oi": 3000},
    )
    assert result.multiplier == round(1.15 * 1.05, 4)


def test_no_metrics_proceeds_neutral() -> None:
    result = evaluate_fo_overlay(daily_return_pct=3.0, metrics=None)
    assert result.action == "PROCEED"
    assert result.multiplier == 1.0
    assert result.details["available"] is False


def test_apply_fo_multiplier_caps_at_100() -> None:
    assert apply_fo_multiplier(95.0, 3.0, 1.15) == 100.0
