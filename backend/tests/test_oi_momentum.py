from __future__ import annotations

import time

from app.services.oi_momentum.engine import (
    evaluate_support_momentum,
    momentum_thresholds,
    parse_option_chain_rows,
    smooth_atm_strike,
)
from app.services.oi_momentum.snapshot_store import ChainSnapshot, StrikeSnapshot


def _sample_chain_payload(spot: float = 22025.0) -> dict:
    return {
        "data": [
            {
                "strike_price": 22000.0,
                "underlying_spot_price": spot,
                "call_options": {"market_data": {"oi": 500_000, "volume": 100_000}},
                "put_options": {"market_data": {"oi": 800_000, "volume": 200_000}},
            },
            {
                "strike_price": 21950.0,
                "underlying_spot_price": spot,
                "call_options": {"market_data": {"oi": 300_000, "volume": 80_000}},
                "put_options": {"market_data": {"oi": 600_000, "volume": 150_000}},
            },
            {
                "strike_price": 22050.0,
                "underlying_spot_price": spot,
                "call_options": {"market_data": {"oi": 400_000, "volume": 90_000}},
                "put_options": {"market_data": {"oi": 700_000, "volume": 180_000}},
            },
        ]
    }


def test_atm_hysteresis_prevents_flicker():
    step = 50
    assert smooth_atm_strike(22024.0, step, 22000.0) == 22000.0
    assert smooth_atm_strike(22010.0, step, 22000.0) == 22000.0
    assert smooth_atm_strike(22040.0, step, 22000.0) == 22050.0


def test_strong_alert_on_put_surge_call_unwind_and_volume():
    base = parse_option_chain_rows(_sample_chain_payload(), symbol="NIFTY")
    now = time.time()
    prev_rows = []
    for row in base.rows:
        if row.strike_price == 22000.0:
            prev_rows.append(
                StrikeSnapshot(
                    row.strike_price,
                    row.call_oi,
                    row.put_oi - 25_000,
                    row.call_volume,
                    row.put_volume - 500_000,
                )
            )
        elif row.strike_price == 21950.0:
            prev_rows.append(
                StrikeSnapshot(
                    row.strike_price,
                    row.call_oi + 10_000,
                    row.put_oi - 5_000,
                    row.call_volume,
                    row.put_volume - 100_000,
                )
            )
        else:
            prev_rows.append(row)
    previous = ChainSnapshot(now - 180, base.spot, base.smoothed_atm, base.strike_step, tuple(prev_rows))
    current = ChainSnapshot(now, base.spot + 5, base.smoothed_atm, base.strike_step, base.rows)

    result = evaluate_support_momentum(current, previous, window_sec=180.0, baseline_mode="full")
    assert result.alert == "strong"
    assert result.metrics.volume_confirmed is True
    assert result.signal_quality["notify_eligible"] is True
    assert result.metrics.pcr_momentum is not None
    assert result.metrics.pcr_momentum >= 2.0


def test_partial_baseline_shows_strike_deltas():
    base = parse_option_chain_rows(_sample_chain_payload(), symbol="NIFTY")
    now = time.time()
    previous = ChainSnapshot(now - 55, base.spot, base.smoothed_atm, base.strike_step, base.rows)
    curr_rows = list(base.rows)
    current = ChainSnapshot(now, base.spot, base.smoothed_atm, base.strike_step, tuple(curr_rows))

    result = evaluate_support_momentum(
        current,
        previous,
        window_sec=55.0,
        target_window_sec=180.0,
        baseline_mode="partial",
    )
    assert result.strike_details
    assert result.strike_details[0]["put_oi_delta"] is not None
    assert result.baseline_mode == "partial"
    assert result.alert == "warming"


def test_partial_early_signal_when_surge_and_volume():
    base = parse_option_chain_rows(_sample_chain_payload(), symbol="NIFTY")
    now = time.time()
    prev_rows = []
    for row in base.rows:
        if row.strike_price == 22000.0:
            prev_rows.append(
                StrikeSnapshot(
                    row.strike_price,
                    row.call_oi,
                    row.put_oi - 20_000,
                    row.call_volume,
                    row.put_volume - 400_000,
                )
            )
        else:
            prev_rows.append(row)
    previous = ChainSnapshot(now - 45, base.spot, base.smoothed_atm, base.strike_step, tuple(prev_rows))
    current = ChainSnapshot(now, base.spot + 2, base.smoothed_atm, base.strike_step, base.rows)

    result = evaluate_support_momentum(
        current,
        previous,
        window_sec=45.0,
        target_window_sec=180.0,
        baseline_mode="partial",
    )
    assert result.alert == "mild"
    assert result.metrics.volume_confirmed is True
    assert result.metrics.rapid_put_surge is True
    assert result.signal_quality["notify_eligible"] is True


def test_strike_rotation_suppresses_notify():
    base = parse_option_chain_rows(_sample_chain_payload(), symbol="NIFTY")
    now = time.time()
    prev_rows = []
    for row in base.rows:
        if row.strike_price == 22000.0:
            prev_rows.append(StrikeSnapshot(row.strike_price, row.call_oi, row.put_oi - 30_000, row.call_volume, row.put_volume - 600_000))
        elif row.strike_price == 21950.0:
            prev_rows.append(StrikeSnapshot(row.strike_price, row.call_oi, row.put_oi + 5_000, row.call_volume, row.put_volume - 200_000))
        else:
            prev_rows.append(row)
    previous = ChainSnapshot(now - 180, base.spot, base.smoothed_atm, base.strike_step, tuple(prev_rows))
    current = ChainSnapshot(now, base.spot + 3, base.smoothed_atm, base.strike_step, base.rows)
    result = evaluate_support_momentum(current, previous, window_sec=180.0, baseline_mode="full")
    assert result.signal_quality["strike_rotation"] is True
    assert result.signal_quality["notify_eligible"] is False
    assert result.alert == "warming"


def test_momentum_thresholds_scale_for_scalp_window():
    surge, volume = momentum_thresholds(30.0)
    assert surge == 0.01
    assert volume == 250

    surge_60, volume_60 = momentum_thresholds(60.0)
    assert surge_60 == 0.02
    assert volume_60 == 500

    surge_180, volume_180 = momentum_thresholds(180.0)
    assert surge_180 == 0.02
    assert volume_180 == 500
