"""Centralized momentum scanner scoring weights and composite formulas.

Pattern detectors in ``patterns.py`` produce structure scores; this module applies
MIN_SCORES, extension/trigger penalties, context/FO composition, and efficiency ranking.
Optional overrides: ``data/scanner_score_weights.json`` (merged over defaults).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ...config import ROOT_DIR

logger = logging.getLogger(__name__)

# Calibrated from forward-path analysis (plan_action Phase 2).
DEFAULT_MIN_SCORES: dict[str, float] = {
    "vcp": 85.0,
    "high_tight_flag": 95.0,
    "pocket_pivot": 95.0,
    "pocket_pivot_setup": 85.0,
    "inside_bar_cluster": 90.0,
    "power_gap": 85.0,
    "tight_range_near_pivot": 80.0,
}

# Pattern quality gates (Phase 3 + failure-pattern recalibration).
# Deep VCP bases (>25%) showed ~28% 5d win rate in loser analysis — hard-reject.
MAX_VCP_BASE_DEPTH_PCT = 25.0
PREFERRED_VCP_BASE_DEPTH_PCT = 20.0
VCP_DEEP_BASE_PENALTY = -10.0
HARD_EXTENSION_PRE_20D_PCT = 25.0
HTF_EXTENSION_EXCEPTION_FLAG_DEPTH_PCT = 10.0
MIN_VOLUME_Z_POCKET = 1.0
MIN_VOLUME_Z_POWER_GAP = 1.5
# Pocket pivot: require decisive close (was 0.5); soft-reward stronger closes in detector.
MIN_CLOSE_POSITION_POCKET = 0.65
# July exhaustion study — soft score overlay still uses 15/25 tiers below.
VCP_BREAKOUT_LOOKBACK = 10
VCP_NEAR_PIVOT_PCT = 3.0  # setup when within this % below pivot
TIGHT_RANGE_MAX_PCT = 5.0
TIGHT_RANGE_NEAR_PIVOT_PCT = 5.0

# Composite / ranking overlays (Phase 2).
EXTENSION_SOFT_THRESHOLD_PCT = 12.0
EXTENSION_HARD_SOFT_THRESHOLD_PCT = 18.0
EXTENSION_PENALTY_SOFT = -5.0
EXTENSION_PENALTY_HARD = -15.0
TRIGGER_PENALTY = -3.0
MACRO_PASS_BONUS = 5.0
SETUP_READY_EFFICIENCY_BONUS = 8.0
FUNDAMENTAL_SCORE_BONUS = 3.0

WEIGHTS_PATH = ROOT_DIR / "data" / "scanner_score_weights.json"

_weights_cache: dict[str, Any] | None = None


def _load_weight_file() -> dict[str, Any]:
    global _weights_cache
    if _weights_cache is not None:
        return _weights_cache
    if not WEIGHTS_PATH.is_file():
        _weights_cache = {}
        return _weights_cache
    try:
        _weights_cache = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
        if not isinstance(_weights_cache, dict):
            _weights_cache = {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load scanner score weights from %s: %s", WEIGHTS_PATH, exc)
        _weights_cache = {}
    return _weights_cache


def reload_weights() -> None:
    """Clear cached overrides (tests / after editing weights file)."""
    global _weights_cache
    _weights_cache = None


def min_scores() -> dict[str, float]:
    overrides = _load_weight_file().get("min_scores") or {}
    merged = dict(DEFAULT_MIN_SCORES)
    for key, value in overrides.items():
        try:
            merged[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return merged


def min_score_for(pattern_type: str) -> float:
    scores = min_scores()
    return float(scores.get(pattern_type, 80.0))


# Back-compat alias used by patterns / tests
MIN_SCORES = DEFAULT_MIN_SCORES


def extension_penalty(pre_20d_return_pct: float | None) -> float:
    if pre_20d_return_pct is None:
        return 0.0
    if pre_20d_return_pct > EXTENSION_HARD_SOFT_THRESHOLD_PCT:
        return EXTENSION_PENALTY_HARD
    if pre_20d_return_pct > EXTENSION_SOFT_THRESHOLD_PCT:
        return EXTENSION_PENALTY_SOFT
    return 0.0


def trigger_penalty(*, triggered_today: bool, apply: bool = True) -> float:
    if apply and triggered_today:
        return TRIGGER_PENALTY
    return 0.0


def passes_hard_extension_gate(
    *,
    pattern_type: str,
    pre_20d_return_pct: float | None,
    details: dict[str, Any] | None = None,
) -> bool:
    """Reject chase setups; HTF with shallow flag may pass."""
    if pre_20d_return_pct is None or pre_20d_return_pct <= HARD_EXTENSION_PRE_20D_PCT:
        return True
    if pattern_type == "high_tight_flag":
        flag_depth = (details or {}).get("flag_depth_pct")
        if flag_depth is not None and float(flag_depth) <= HTF_EXTENSION_EXCEPTION_FLAG_DEPTH_PCT:
            return True
    return False


def vcp_base_depth_adjustment(
    depth_pct: float | None,
    *,
    pre_20d_return_pct: float | None = None,
) -> tuple[bool, float]:
    """
    Return (keep_signal, score_delta).

    Deep bases (> preferred) are penalized; deep + already extended are rejected.
    """
    if depth_pct is None:
        return True, 0.0
    if depth_pct > MAX_VCP_BASE_DEPTH_PCT:
        return False, 0.0
    if depth_pct > PREFERRED_VCP_BASE_DEPTH_PCT:
        if pre_20d_return_pct is not None and pre_20d_return_pct > 20.0:
            return False, 0.0
        return True, VCP_DEEP_BASE_PENALTY
    return True, 0.0


def apply_fo_multiplier(
    pattern_score: float,
    context_adjustment: float,
    fo_multiplier: float,
) -> float:
    """Composite score: (pattern + context) × F&O multiplier, capped at 100."""
    raw = (pattern_score + context_adjustment) * fo_multiplier
    return round(min(100.0, max(0.0, raw)), 1)


def efficiency_score(
    *,
    composite_score: float,
    setup_ready: bool,
    triggered_today: bool,
    pre_20d_return_pct: float | None,
) -> float:
    """
    Ranking proxy favoring early/setup entries over extended chase.

    Starts from composite, adds setup bonus, subtracts extension and trigger penalties.
    """
    score = float(composite_score)
    if setup_ready and not triggered_today:
        score += SETUP_READY_EFFICIENCY_BONUS
    score += extension_penalty(pre_20d_return_pct)
    score += trigger_penalty(triggered_today=triggered_today, apply=True)
    return round(min(100.0, max(0.0, score)), 1)


def compose_signal_scores(
    *,
    pattern_score: float,
    context_adjustment: float,
    fo_multiplier: float,
    macro_pass: bool,
    setup_ready: bool,
    triggered_today: bool,
    pre_20d_return_pct: float | None,
    apply_trigger_penalty: bool = True,
) -> dict[str, float]:
    """Build composite + efficiency scores and expose intermediate penalties."""
    macro_bonus = MACRO_PASS_BONUS if macro_pass else 0.0
    ext_pen = extension_penalty(pre_20d_return_pct)
    trig_pen = trigger_penalty(triggered_today=triggered_today, apply=apply_trigger_penalty)
    adjusted_context = round(context_adjustment + macro_bonus + ext_pen + trig_pen, 1)
    composite = apply_fo_multiplier(pattern_score, adjusted_context, fo_multiplier)
    efficiency = efficiency_score(
        composite_score=composite,
        setup_ready=setup_ready,
        triggered_today=triggered_today,
        pre_20d_return_pct=pre_20d_return_pct,
    )
    return {
        "macro_bonus": macro_bonus,
        "extension_penalty": ext_pen,
        "trigger_penalty": trig_pen,
        "adjusted_context": adjusted_context,
        "composite_score": composite,
        "efficiency_score": efficiency,
    }


def passes_posthoc_quality_filters(signal: dict[str, Any]) -> bool:
    """
    Apply refined quality gates to a stored signal (comparison / outcomes report).

    Uses fields already present on the row / details_json — does not re-run detectors.
    """
    from .quality import passes_quality_gates

    details = signal.get("details") or {}
    pattern_type = str(signal.get("pattern_type") or "")
    pre_20d = details.get("pre_20d_return_pct")
    if pre_20d is not None:
        pre_20d = float(pre_20d)
    if not passes_hard_extension_gate(
        pattern_type=pattern_type,
        pre_20d_return_pct=pre_20d,
        details=details,
    ):
        return False

    if pattern_type == "vcp":
        depth = details.get("base_depth_pct")
        keep, _ = vcp_base_depth_adjustment(
            float(depth) if depth is not None else None,
            pre_20d_return_pct=pre_20d,
        )
        if not keep:
            return False

    min_required = min_score_for(pattern_type)
    score = float(signal.get("score") or 0)
    if score < min_required:
        return False

    quality = details.get("quality") or {}
    metrics = {
        "close_position": quality.get("close_position", details.get("close_position")),
        "upper_wick_ratio": quality.get("upper_wick_ratio"),
        "volume_z50": quality.get("volume_z50", details.get("volume_zscore")),
        "rvol20": quality.get("rvol20"),
        "rsi14": quality.get("rsi14"),
        "pct_above_sma50": quality.get("pct_above_sma50"),
    }
    keep_q, _ = passes_quality_gates(
        pattern_type=pattern_type,
        triggered_today=bool(signal.get("triggered_today")),
        metrics=metrics,
        details=details,
    )
    return keep_q


def write_default_weights_template(path: Path | None = None) -> Path:
    """Write a starter weights file if missing (does not overwrite)."""
    target = path or WEIGHTS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        return target
    payload = {
        "schema_version": "1.0",
        "description": "Optional overrides merged over scoring.DEFAULT_MIN_SCORES",
        "min_scores": dict(DEFAULT_MIN_SCORES),
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target
