"""Persist forward performance for historical pattern_signals (feedback loop)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from ...db.store import TimelineStore, get_store
from .analysis import compute_forward_performance
from .scoring import passes_posthoc_quality_filters

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]


def _horizon_stats(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [float(r[field]) for r in rows if r.get(field) is not None]
    if not values:
        return {"count": 0, "win_rate_pct": None, "avg_return_pct": None, "median_return_pct": None}
    winners = sum(1 for v in values if v > 0)
    ordered = sorted(values)
    mid = ordered[len(ordered) // 2]
    mfe = [float(r["max_favorable_pct"]) for r in rows if r.get("max_favorable_pct") is not None]
    mae = [float(r["max_adverse_pct"]) for r in rows if r.get("max_adverse_pct") is not None]
    avg_mfe = sum(mfe) / len(mfe) if mfe else None
    avg_mae = sum(mae) / len(mae) if mae else None
    rr = None
    if avg_mfe is not None and avg_mae is not None and abs(avg_mae) > 1e-9:
        rr = round(avg_mfe / abs(avg_mae), 3)
    return {
        "count": len(values),
        "win_rate_pct": round(winners / len(values) * 100, 2),
        "avg_return_pct": round(sum(values) / len(values), 4),
        "median_return_pct": round(mid, 4),
        "avg_mfe_pct": round(avg_mfe, 4) if avg_mfe is not None else None,
        "avg_mae_pct": round(avg_mae, 4) if avg_mae is not None else None,
        "mfe_mae_ratio": rr,
    }


def evaluate_and_store_outcomes(
    *,
    store: TimelineStore | None = None,
    trade_date_from: str | None = None,
    trade_date_to: str | None = None,
    limit: int = 50_000,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Compute 1/3/5/10/20d forward metrics for stored signals and upsert signal_outcomes."""
    db = store or get_store()
    signals = db.list_pattern_signals_for_outcomes(
        trade_date_from=trade_date_from,
        trade_date_to=trade_date_to,
        limit=limit,
    )
    global_max = db.stats().get("max_trade_date")
    candle_cache: dict[str, list[dict[str, Any]]] = {}
    written = 0
    skipped_no_entry = 0
    now = datetime.now(timezone.utc).isoformat()

    for index, signal in enumerate(signals):
        if on_progress and index % 100 == 0:
            on_progress(
                {
                    "phase": "evaluate",
                    "index": index + 1,
                    "total": len(signals),
                    "ticker": signal.get("ticker"),
                }
            )

        ticker = signal["ticker"]
        trade_date = signal["trade_date"]
        entry_close = signal.get("close")
        if entry_close is None:
            skipped_no_entry += 1
            continue

        if ticker not in candle_cache:
            candle_cache[ticker] = db.get_candles_for_ticker(ticker, to_date=global_max)
        history = candle_cache[ticker]
        forward = [c for c in history if str(c["date"]) >= trade_date]
        perf = compute_forward_performance(
            forward,
            entry_date=trade_date,
            entry_close=float(entry_close),
        )
        outcome = {
            "signal_id": int(signal["signal_id"]),
            "trade_date": trade_date,
            "ticker": ticker,
            "pattern_type": signal["pattern_type"],
            "entry_close": round(float(entry_close), 4),
            "evaluated_at": now,
            **perf,
        }
        db.upsert_signal_outcome(outcome)
        written += 1

    comparison = build_baseline_vs_refined_report(store=db)
    logger.info(
        "Signal outcomes evaluated written=%s skipped_no_entry=%s signals=%s",
        written,
        skipped_no_entry,
        len(signals),
    )
    return {
        "signals_considered": len(signals),
        "outcomes_written": written,
        "skipped_no_entry": skipped_no_entry,
        "stats": db.signal_outcomes_stats(),
        "comparison": comparison,
    }


def build_baseline_vs_refined_report(
    *,
    store: TimelineStore | None = None,
) -> dict[str, Any]:
    """
    Compare all stored outcomes (baseline) vs post-hoc refined quality filters.

    Refined set applies current MIN_SCORES + extension/base-depth gates to historical rows.
    """
    db = store or get_store()
    signals = db.list_pattern_signals_for_outcomes(limit=50_000)
    outcomes = {int(o["signal_id"]): o for o in db.list_signal_outcomes(limit=50_000)}

    baseline_rows: list[dict[str, Any]] = []
    refined_rows: list[dict[str, Any]] = []

    for signal in signals:
        sid = int(signal["signal_id"])
        outcome = outcomes.get(sid)
        if not outcome or outcome.get("return_5d_pct") is None:
            continue
        merged = {**signal, **outcome}
        baseline_rows.append(merged)
        if passes_posthoc_quality_filters(signal):
            refined_rows.append(merged)

    by_pattern_base: dict[str, list[dict[str, Any]]] = {}
    by_pattern_ref: dict[str, list[dict[str, Any]]] = {}
    for row in baseline_rows:
        by_pattern_base.setdefault(row["pattern_type"], []).append(row)
    for row in refined_rows:
        by_pattern_ref.setdefault(row["pattern_type"], []).append(row)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "description": (
            "Baseline = all historical signals with 5d outcomes. "
            "Refined = same set after current quality filters / MIN_SCORES."
        ),
        "baseline": {
            "signals": len(baseline_rows),
            "horizon_1d": _horizon_stats(baseline_rows, "return_1d_pct"),
            "horizon_3d": _horizon_stats(baseline_rows, "return_3d_pct"),
            "horizon_5d": _horizon_stats(baseline_rows, "return_5d_pct"),
            "by_pattern_5d": {
                k: _horizon_stats(v, "return_5d_pct") for k, v in sorted(by_pattern_base.items())
            },
        },
        "refined": {
            "signals": len(refined_rows),
            "retention_pct": (
                round(len(refined_rows) / len(baseline_rows) * 100, 2) if baseline_rows else None
            ),
            "horizon_1d": _horizon_stats(refined_rows, "return_1d_pct"),
            "horizon_3d": _horizon_stats(refined_rows, "return_3d_pct"),
            "horizon_5d": _horizon_stats(refined_rows, "return_5d_pct"),
            "by_pattern_5d": {
                k: _horizon_stats(v, "return_5d_pct") for k, v in sorted(by_pattern_ref.items())
            },
        },
        "delta_5d": _delta_block(
            _horizon_stats(baseline_rows, "return_5d_pct"),
            _horizon_stats(refined_rows, "return_5d_pct"),
        ),
    }


def _delta_block(base: dict[str, Any], refined: dict[str, Any]) -> dict[str, Any]:
    def diff(key: str) -> float | None:
        a, b = base.get(key), refined.get(key)
        if a is None or b is None:
            return None
        return round(float(b) - float(a), 4)

    return {
        "win_rate_pct": diff("win_rate_pct"),
        "avg_return_pct": diff("avg_return_pct"),
        "median_return_pct": diff("median_return_pct"),
        "mfe_mae_ratio": diff("mfe_mae_ratio"),
        "signal_count": (refined.get("count") or 0) - (base.get("count") or 0),
    }
