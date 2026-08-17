"""Refresh F&O overlay fields on scanner signals from derivative DB state."""

from __future__ import annotations

from typing import Any

from ...db.store import TimelineStore
from .fo_overlay import evaluate_fo_overlay
from .scoring import compose_signal_scores


def _daily_return_pct(row: dict[str, Any]) -> float | None:
    raw = row.get("daily_return_pct")
    if raw is not None:
        return float(raw)
    details = row.get("details") or {}
    nested = details.get("daily_return_pct")
    return float(nested) if nested is not None else None


def apply_fo_overlay_to_signal(
    signal: dict[str, Any],
    derivatives: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Return updated signal, or None if F&O hard-reject applies."""
    ticker = str(signal["ticker"]).upper()
    details = dict(signal.get("details") or {})
    fo_result = evaluate_fo_overlay(
        daily_return_pct=_daily_return_pct(signal),
        metrics=derivatives.get(ticker),
    )
    if fo_result.action == "REJECT":
        return None

    pattern_score = float(details.get("pattern_score", signal.get("score", 0)))
    context_adjustment = float(details.get("context_adjustment") or 0)
    details["fo_overlay"] = fo_result.details
    details["fo_multiplier"] = fo_result.multiplier
    parts = compose_signal_scores(
        pattern_score=pattern_score,
        context_adjustment=context_adjustment,
        fo_multiplier=fo_result.multiplier,
        macro_pass=bool(signal.get("macro_pass")),
        setup_ready=bool(signal.get("setup_ready")),
        triggered_today=bool(signal.get("triggered_today")),
        pre_20d_return_pct=(
            float(details["pre_20d_return_pct"])
            if details.get("pre_20d_return_pct") is not None
            else None
        ),
    )
    details.update(parts)
    signal = {**signal, "details": details}
    return signal


def refresh_fo_overlay_on_row(
    row: dict[str, Any],
    derivatives: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Update F&O overlay fields without dropping the row (API read path)."""
    ticker = str(row["ticker"]).upper()
    details = dict(row.get("details") or {})
    fo_result = evaluate_fo_overlay(
        daily_return_pct=_daily_return_pct(row),
        metrics=derivatives.get(ticker),
    )
    pattern_score = float(details.get("pattern_score", row.get("score", 0)))
    context_adjustment = float(details.get("context_adjustment") or 0)
    details["fo_overlay"] = fo_result.details
    details["fo_multiplier"] = fo_result.multiplier
    if fo_result.action == "REJECT":
        details["fo_overlay"] = {**fo_result.details, "would_reject": True}
    mult = fo_result.multiplier if fo_result.action != "REJECT" else 0.0
    parts = compose_signal_scores(
        pattern_score=pattern_score,
        context_adjustment=context_adjustment,
        fo_multiplier=mult,
        macro_pass=bool(row.get("macro_pass")),
        setup_ready=bool(row.get("setup_ready")),
        triggered_today=bool(row.get("triggered_today")),
        pre_20d_return_pct=(
            float(details["pre_20d_return_pct"])
            if details.get("pre_20d_return_pct") is not None
            else None
        ),
    )
    details.update(parts)
    return {**row, "details": details}


def enrich_scanner_results(
    rows: list[dict[str, Any]],
    derivatives: dict[str, dict[str, Any]],
    *,
    fno_symbols: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Recompute F&O overlay on result rows (read path after derivative sync)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        ticker = str(row["ticker"]).upper()
        if fno_symbols is not None and ticker not in fno_symbols:
            out.append(row)
            continue
        out.append(refresh_fo_overlay_on_row(row, derivatives))
    return out
