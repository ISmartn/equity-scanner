"""Day-T quality gates that reject dominant momentum fakeout modes.

Calibrated from forward-return winner/loser analysis on historical ``pattern_signals``
(see ``data/scanner_analysis/failure_pattern_analysis.json``,
``july_20d_exhaustion_report.json``, and related scripts).

Dominant failure modes addressed:
- Weak close on trigger day (close_position < 0.65)
- Climactic volume without a decisive close (volume_z >= 3.5 and close < 0.75)
- Deep VCP bases (> 25%)
- Prior 20d run-up exhaustion (July study: cliff at 20–25%; hard cap 18%)
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .indicators import (
    close_position_in_range,
    relative_volume,
    rsi,
    sma,
    upper_wick_ratio,
    volume_zscore,
)

# Trigger-day close quality (dominant separator in pocket_pivot cohort).
MIN_TRIGGER_CLOSE_POSITION = 0.65

# Climactic volume without conviction close → exhaustion / distribution.
CLIMACTIC_VOLUME_Z = 3.5
MIN_CLOSE_WITH_CLIMACTIC_VOL = 0.75

# Pocket pivot scoring hints (used by patterns.py; not hard-rejected here).
MIN_RVOL_POCKET = 1.15
MAX_VOLUME_Z_POCKET = 4.5

# Wick rejection (shooting-star style) on weak close — secondary tell.
UPPER_WICK_EXHAUSTION = 0.45
MIN_CLOSE_WITH_UPPER_WICK = 0.70

# Prior 20-session run-up exhaustion (July 2026 study: cliff at 20–25%).
MAX_20D_RUNUP_PCT = 18.0
MAX_20D_RUNUP_WITH_HIGHER_LOW_PCT = 25.0
ALLOW_EXTENDED_WITH_HIGHER_LOW = True


def _quality_overrides() -> dict[str, Any]:
    """Optional knobs from data/scanner_score_weights.json → quality."""
    from .scoring import _load_weight_file

    block = _load_weight_file().get("quality") or {}
    return block if isinstance(block, dict) else {}


def resolved_max_20d_runup_pct() -> float:
    raw = _quality_overrides().get("max_20d_runup_pct")
    try:
        return float(raw) if raw is not None else MAX_20D_RUNUP_PCT
    except (TypeError, ValueError):
        return MAX_20D_RUNUP_PCT


def resolved_max_20d_runup_with_higher_low_pct() -> float:
    raw = _quality_overrides().get("max_20d_runup_with_higher_low_pct")
    try:
        return float(raw) if raw is not None else MAX_20D_RUNUP_WITH_HIGHER_LOW_PCT
    except (TypeError, ValueError):
        return MAX_20D_RUNUP_WITH_HIGHER_LOW_PCT


def resolved_allow_extended_with_higher_low() -> bool:
    raw = _quality_overrides().get("allow_extended_with_higher_low")
    if raw is None:
        return ALLOW_EXTENDED_WITH_HIGHER_LOW
    return bool(raw)


def has_higher_low_structure(df: pd.DataFrame, *, lookback: int = 10) -> bool | None:
    """True when the last ``lookback`` lows sit above the prior ``lookback`` lows."""
    need = lookback * 2
    if len(df) < need:
        return None
    recent = float(df["low"].iloc[-lookback:].min())
    prior = float(df["low"].iloc[-need:-lookback].min())
    return recent > prior


def compute_quality_metrics(df: pd.DataFrame) -> dict[str, Any]:
    """Compute Day-T quality features from bars ending on the scan date."""
    if len(df) < 21:
        return {
            "close_position": None,
            "upper_wick_ratio": None,
            "volume_z50": None,
            "rvol20": None,
            "rsi14": None,
            "pct_above_sma50": None,
            "higher_low_10d": None,
        }

    last = df.iloc[-1]
    close = float(last["close"])
    vol_z = volume_zscore(df["volume"], window=50)
    last_vol_z = float(vol_z.iloc[-1]) if pd.notna(vol_z.iloc[-1]) else None
    rvol = relative_volume(df["volume"], window=20)
    rsi14 = rsi(df["close"], window=14)
    sma50 = sma(df["close"], 50)
    pct50 = None
    if len(df) >= 50 and pd.notna(sma50.iloc[-1]) and float(sma50.iloc[-1]) > 0:
        pct50 = (close / float(sma50.iloc[-1]) - 1.0) * 100.0

    return {
        "close_position": round(close_position_in_range(last), 3),
        "upper_wick_ratio": (
            round(float(upper_wick_ratio(last)), 3)
            if upper_wick_ratio(last) is not None
            else None
        ),
        "volume_z50": round(last_vol_z, 3) if last_vol_z is not None else None,
        "rvol20": round(float(rvol), 3) if rvol is not None else None,
        "rsi14": round(float(rsi14), 2) if rsi14 is not None else None,
        "pct_above_sma50": round(pct50, 3) if pct50 is not None else None,
        "higher_low_10d": has_higher_low_structure(df, lookback=10),
    }


def passes_quality_gates(
    *,
    pattern_type: str,
    triggered_today: bool,
    metrics: dict[str, Any],
    details: dict[str, Any] | None = None,
    max_20d_runup_pct: float | None = None,
    allow_extended_with_higher_low: bool | None = None,
) -> tuple[bool, str | None]:
    """
    Return (keep, reject_reason).

    Setup-only alerts are mostly preserved; hard gates focus on trigger-day fakeouts
    and prior-20d exhaustion.
    """
    details = details or {}
    close_pos = metrics.get("close_position")
    if close_pos is None and details.get("close_position") is not None:
        close_pos = float(details["close_position"])
    wick = metrics.get("upper_wick_ratio")
    vol_z = metrics.get("volume_z50")
    if vol_z is None and details.get("volume_zscore") is not None:
        vol_z = float(details["volume_zscore"])
    higher_low = metrics.get("higher_low_10d")
    if higher_low is None and details.get("higher_low_10d") is not None:
        higher_low = bool(details["higher_low_10d"])

    runup_cap = (
        resolved_max_20d_runup_pct()
        if max_20d_runup_pct is None
        else float(max_20d_runup_pct)
    )
    allow_hl = (
        resolved_allow_extended_with_higher_low()
        if allow_extended_with_higher_low is None
        else bool(allow_extended_with_higher_low)
    )
    hl_ceiling = resolved_max_20d_runup_with_higher_low_pct()

    if pattern_type == "vcp":
        depth = details.get("base_depth_pct")
        if depth is not None and float(depth) > 25.0:
            return False, "vcp_deep_base"

    if not triggered_today:
        return True, None

    if close_pos is None or float(close_pos) < MIN_TRIGGER_CLOSE_POSITION:
        return False, "weak_trigger_close"

    if (
        wick is not None
        and float(wick) >= UPPER_WICK_EXHAUSTION
        and float(close_pos) < MIN_CLOSE_WITH_UPPER_WICK
    ):
        return False, "upper_wick_exhaustion"

    if (
        vol_z is not None
        and float(vol_z) >= CLIMACTIC_VOLUME_Z
        and float(close_pos) < MIN_CLOSE_WITH_CLIMACTIC_VOL
    ):
        return False, "climactic_volume_weak_close"

    pre_20d = details.get("pre_20d_return_pct")
    if pre_20d is not None:
        pre_20d = float(pre_20d)
        if pre_20d > runup_cap:
            if allow_hl and higher_low is True and pre_20d <= hl_ceiling:
                pass
            else:
                return False, "max_20d_runup"

    return True, None
