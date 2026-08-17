from __future__ import annotations

from typing import Any, Literal

import pandas as pd

TimingClass = Literal["early", "confirmation", "extended"]

EXTENDED_PRE_20D_THRESHOLD_PCT = 18.0
PRE_20D_LOOKBACK_SESSIONS = 20


def compute_pre_20d_return_pct(df: pd.DataFrame) -> float | None:
    """Return % change from close 20 sessions ago to latest close."""
    if len(df) < PRE_20D_LOOKBACK_SESSIONS + 1:
        return None

    current_close = float(df["close"].iloc[-1])
    prior_close = float(df["close"].iloc[-(PRE_20D_LOOKBACK_SESSIONS + 1)])
    if current_close <= 0 or prior_close <= 0:
        return None

    return round((current_close - prior_close) / prior_close * 100, 4)


def compute_signal_day_return_pct(
    df: pd.DataFrame,
    *,
    daily_return_pct: float | None = None,
) -> float | None:
    """Return % move on the signal session (prefer stored daily_return_pct)."""
    if daily_return_pct is not None:
        return round(float(daily_return_pct), 4)

    if len(df) < 2:
        return None

    current_close = float(df["close"].iloc[-1])
    prior_close = float(df["close"].iloc[-2])
    if current_close <= 0 or prior_close <= 0:
        return None

    return round((current_close - prior_close) / prior_close * 100, 4)


def classify_timing_class(
    *,
    pre_20d_return_pct: float | None,
    setup_ready: bool,
    triggered_today: bool,
    extended_threshold_pct: float = EXTENDED_PRE_20D_THRESHOLD_PCT,
) -> TimingClass:
    if pre_20d_return_pct is not None and pre_20d_return_pct > extended_threshold_pct:
        return "extended"
    if setup_ready and not triggered_today:
        return "early"
    return "confirmation"


def build_timing_details(
    df: pd.DataFrame,
    *,
    daily_return_pct: float | None,
    setup_ready: bool,
    triggered_today: bool,
) -> dict[str, Any]:
    pre_20d_return_pct = compute_pre_20d_return_pct(df)
    signal_day_return_pct = compute_signal_day_return_pct(df, daily_return_pct=daily_return_pct)
    timing_class = classify_timing_class(
        pre_20d_return_pct=pre_20d_return_pct,
        setup_ready=setup_ready,
        triggered_today=triggered_today,
    )
    return {
        "pre_20d_return_pct": pre_20d_return_pct,
        "signal_day_return_pct": signal_day_return_pct,
        "timing_class": timing_class,
    }


def enrich_signal_timing(
    signal: dict[str, Any],
    df: pd.DataFrame,
) -> dict[str, Any]:
    """Fill timing fields on a stored signal (for scans before timing metrics existed)."""
    details = dict(signal.get("details") or {})
    if details.get("pre_20d_return_pct") is not None and details.get("timing_class"):
        return signal

    daily_return_pct = details.get("daily_return_pct")
    if daily_return_pct is not None:
        daily_return_pct = float(daily_return_pct)

    timing = build_timing_details(
        df,
        daily_return_pct=daily_return_pct,
        setup_ready=bool(signal.get("setup_ready")),
        triggered_today=bool(signal.get("triggered_today")),
    )
    details.update(timing)
    signal["details"] = details
    return signal


def passes_timing_filters(
    signal: dict[str, Any],
    *,
    max_pre_20d_return: float | None,
    max_signal_day_return: float | None,
) -> bool:
    details = signal.get("details") or {}
    pre_20d = details.get("pre_20d_return_pct")
    signal_day = details.get("signal_day_return_pct")

    if max_pre_20d_return is not None:
        if pre_20d is None or float(pre_20d) > max_pre_20d_return:
            return False
    if max_signal_day_return is not None:
        if signal_day is None or float(signal_day) > max_signal_day_return:
            return False
    return True
