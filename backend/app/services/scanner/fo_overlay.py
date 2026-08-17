"""F&O structural overlay for momentum scanner signals.

Uses end-of-day option-chain OI and PCR from ``derivative_snapshots`` (Upstox).
Futures OI bhavcopy, cost-of-carry, IV rank, and rollover are **not** applied —
those require ingestion paths that do not exist yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .scoring import apply_fo_multiplier

PRICE_UP_THRESHOLD_PCT = 0.5
OI_UP_THRESHOLD_PCT = 5.0
OI_DOWN_THRESHOLD_PCT = -5.0
PCR_CHANGE_BULLISH_PCT = 15.0

MULT_LONG_BUILDUP = 1.15
MULT_SHORT_COVERING = 0.85
MULT_PCR_SUPPORT = 1.05

QUADRANT_LABELS = {
    "long_buildup": "Long build-up (price ↑, OI ↑)",
    "short_covering": "Short covering (price ↑, OI ↓)",
    "short_buildup": "Short build-up (price ↓, OI ↑)",
    "long_unwinding": "Long unwinding (price ↓, OI ↓)",
    "neutral": "Neutral OI / price mix",
}


@dataclass(frozen=True)
class FoOverlayResult:
    action: str  # PROCEED | REJECT
    multiplier: float
    details: dict[str, Any]


def _classify_quadrant(
    *,
    price_up: bool,
    oi_up: bool,
    oi_down: bool,
) -> str:
    if price_up and oi_up:
        return "long_buildup"
    if price_up and oi_down:
        return "short_covering"
    if (not price_up) and oi_up:
        return "short_buildup"
    if (not price_up) and oi_down:
        return "long_unwinding"
    return "neutral"


def evaluate_fo_overlay(
    *,
    daily_return_pct: float | None,
    metrics: dict[str, Any] | None,
) -> FoOverlayResult:
    """Apply F&O quadrant filters and multipliers when derivative metrics exist."""
    base_details: dict[str, Any] = {
        "available": False,
        "oi_source": "options_chain",
        "unsupported": ["cost_of_carry", "iv_rank", "rollover"],
    }

    if not metrics:
        base_details["reason"] = "no_derivative_snapshot"
        return FoOverlayResult(action="PROCEED", multiplier=1.0, details=base_details)

    oi_change_pct = metrics.get("oi_change_pct")
    pcr_change_pct = metrics.get("pcr_change_pct")

    base_details.update(
        {
            "available": True,
            "pcr": metrics.get("pcr"),
            "pcr_change_pct": pcr_change_pct,
            "oi_change_pct": oi_change_pct,
            "total_oi": metrics.get("total_oi"),
            "prior_trade_date": metrics.get("prior_trade_date"),
            "max_pain_strike": metrics.get("max_pain_strike"),
        }
    )

    if daily_return_pct is None or oi_change_pct is None:
        base_details["reason"] = "missing_price_or_oi_delta"
        return FoOverlayResult(action="PROCEED", multiplier=1.0, details=base_details)

    price_up = float(daily_return_pct) > PRICE_UP_THRESHOLD_PCT
    oi_up = float(oi_change_pct) > OI_UP_THRESHOLD_PCT
    oi_down = float(oi_change_pct) < OI_DOWN_THRESHOLD_PCT

    quadrant = _classify_quadrant(price_up=price_up, oi_up=oi_up, oi_down=oi_down)
    base_details["quadrant"] = quadrant
    base_details["quadrant_label"] = QUADRANT_LABELS.get(quadrant, quadrant)

    if quadrant == "short_buildup":
        base_details["reject_reason"] = "institutional_short_buildup"
        return FoOverlayResult(action="REJECT", multiplier=0.0, details=base_details)

    multiplier = 1.0
    if quadrant == "long_buildup":
        multiplier *= MULT_LONG_BUILDUP
    elif quadrant == "short_covering":
        multiplier *= MULT_SHORT_COVERING

    if pcr_change_pct is not None and float(pcr_change_pct) > PCR_CHANGE_BULLISH_PCT:
        multiplier *= MULT_PCR_SUPPORT
        base_details["pcr_support"] = True

    base_details["multiplier"] = round(multiplier, 4)
    return FoOverlayResult(action="PROCEED", multiplier=multiplier, details=base_details)
