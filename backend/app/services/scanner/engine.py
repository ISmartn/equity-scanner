from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from threading import Lock
from typing import Any, Callable

import pandas as pd

from ...config import get_access_token
from ...db.store import TimelineStore, get_store
from .context import (
    compute_context_adjustment,
    compute_market_score_delta,
    evaluate_fundamental_gate,
    load_market_context,
)
from .filters import evaluate_liquidity
from .fo_overlay import evaluate_fo_overlay
from .fo_sync import (
    ensure_and_finalize_scanner_signals,
    finalize_signals_with_fo_data,
    run_coro_sync,
)
from .patterns import scan_symbol_patterns
from .quality import compute_quality_metrics, passes_quality_gates
from .scoring import compose_signal_scores, passes_hard_extension_gate
from .timing import build_timing_details
from .trend_template import evaluate_trend_template

logger = logging.getLogger(__name__)

ScanProgressCallback = Callable[[dict[str, Any]], None]
MIN_BARS = 250
HISTORY_BARS = 280
DEFAULT_SCANNER_CONCURRENCY = 3
# Bumped when darvas_pre_setup shipped; calendar accents dates rescanned on this engine.
SCANNER_ENGINE_VERSION = "darvas_v1"


@dataclass
class _TickerScanResult:
    ticker: str
    signals: list[dict[str, Any]]
    skipped_illiquid: int = 0
    skipped_fo_reject: int = 0
    skipped_no_data: int = 0


def _default_trade_date(store: TimelineStore) -> str:
    stats = store.stats()
    return stats["max_trade_date"] or date.today().isoformat()


def _scan_ticker(
    meta: dict[str, Any],
    *,
    scan_date: str,
    run_id: int,
    db: TimelineStore,
    fundamentals_index: dict[str, Any],
    market_ctx: Any,
) -> _TickerScanResult:
    ticker = meta["ticker"]
    rows = db.get_recent_candles_for_scan(
        ticker,
        limit=HISTORY_BARS,
        as_of_date=scan_date,
    )
    if len(rows) < MIN_BARS or str(rows[-1]["date"]) != scan_date:
        return _TickerScanResult(ticker=ticker, signals=[], skipped_no_data=1)

    group = pd.DataFrame(rows)
    liquidity = evaluate_liquidity(group)
    if not liquidity["pass"]:
        return _TickerScanResult(ticker=ticker, signals=[], skipped_illiquid=1)

    macro_pass, trend_details = evaluate_trend_template(group)
    hits = scan_symbol_patterns(group, macro_pass)

    fundamental = evaluate_fundamental_gate(fundamentals_index.get(ticker))
    market_delta, market_details = compute_market_score_delta(market_ctx, ticker)
    context_adjustment = compute_context_adjustment(fundamental, market_delta)
    daily_return_pct = rows[-1].get("daily_return_pct")
    if daily_return_pct is not None:
        daily_return_pct = float(daily_return_pct)

    fo_metrics = market_ctx.derivatives.get(ticker.upper())
    fo_result = evaluate_fo_overlay(
        daily_return_pct=daily_return_pct,
        metrics=fo_metrics,
    )

    signals: list[dict[str, Any]] = []
    skipped_fo_reject = 0
    quality_metrics = compute_quality_metrics(group)
    for hit in hits:
        if fo_result.action == "REJECT":
            skipped_fo_reject += 1
            continue

        timing = build_timing_details(
            group,
            daily_return_pct=daily_return_pct,
            setup_ready=hit.setup_ready,
            triggered_today=hit.triggered_today,
        )
        pre_20d = timing.get("pre_20d_return_pct")
        if not passes_hard_extension_gate(
            pattern_type=hit.pattern_type,
            pre_20d_return_pct=pre_20d,
            details=hit.details,
        ):
            continue

        keep_quality, reject_reason = passes_quality_gates(
            pattern_type=hit.pattern_type,
            triggered_today=hit.triggered_today,
            metrics=quality_metrics,
            details={**hit.details, **timing},
        )
        if not keep_quality:
            continue

        score_parts = compose_signal_scores(
            pattern_score=hit.score,
            context_adjustment=context_adjustment,
            fo_multiplier=fo_result.multiplier,
            macro_pass=macro_pass,
            setup_ready=hit.setup_ready,
            triggered_today=hit.triggered_today,
            pre_20d_return_pct=pre_20d,
            apply_trigger_penalty=True,
        )
        signals.append(
            {
                "run_id": run_id,
                "trade_date": scan_date,
                "ticker": ticker,
                "pattern_type": hit.pattern_type,
                "macro_pass": macro_pass,
                "score": hit.score,
                "triggered_today": hit.triggered_today,
                "setup_ready": hit.setup_ready,
                "details": {
                    **hit.details,
                    **timing,
                    "trend": trend_details if macro_pass else {},
                    "fundamental": fundamental,
                    "market": market_details,
                    "liquidity": liquidity,
                    "quality": {
                        **quality_metrics,
                        "reject_reason": reject_reason,
                    },
                    "pattern_score": hit.score,
                    "context_adjustment": context_adjustment,
                    "daily_return_pct": daily_return_pct,
                    "fo_overlay": fo_result.details,
                    "fo_multiplier": fo_result.multiplier,
                    "macro_bonus": score_parts["macro_bonus"],
                    "extension_penalty": score_parts["extension_penalty"],
                    "trigger_penalty": score_parts["trigger_penalty"],
                    "adjusted_context": score_parts["adjusted_context"],
                    "composite_score": score_parts["composite_score"],
                    "efficiency_score": score_parts["efficiency_score"],
                },
            }
        )

    return _TickerScanResult(
        ticker=ticker,
        signals=signals,
        skipped_fo_reject=skipped_fo_reject,
    )


def run_scanner(
    *,
    trade_date: str | None = None,
    store: TimelineStore | None = None,
    on_progress: ScanProgressCallback | None = None,
    concurrency: int = 1,
    skip_fo_sync: bool = False,
) -> dict[str, Any]:
    db = store or get_store()
    scan_date = trade_date or _default_trade_date(db)
    workers = max(1, concurrency)

    tickers_meta = db.list_scan_eligible_tickers(min_bars=MIN_BARS, as_of_date=scan_date)
    if not tickers_meta:
        return {
            "trade_date": scan_date,
            "symbols_scanned": 0,
            "alerts_count": 0,
            "message": "No candle data available for scan",
        }

    total = len(tickers_meta)
    # Replace prior run for this date so UI always reflects the latest engine.
    db.delete_scanner_data_for_date(scan_date)
    run_id = db.create_scanner_run(scan_date, engine_version=SCANNER_ENGINE_VERSION)
    db.delete_pattern_signals_for_run(run_id)

    fundamentals_index = db.load_fundamentals_index()
    market_ctx = load_market_context(db, scan_date)

    signals: list[dict[str, Any]] = []
    scanned = 0
    skipped_illiquid = 0
    skipped_fo_reject = 0
    progress_lock = Lock()

    def emit(current_ticker: str | None = None) -> None:
        if on_progress:
            on_progress(
                {
                    "total": total,
                    "processed": scanned,
                    "alerts_count": len(signals),
                    "current_ticker": current_ticker,
                    "trade_date": scan_date,
                    "concurrency": workers,
                }
            )

    emit()

    def consume_result(result: _TickerScanResult) -> None:
        nonlocal scanned, skipped_illiquid, skipped_fo_reject
        with progress_lock:
            scanned += 1
            skipped_illiquid += result.skipped_illiquid
            skipped_fo_reject += result.skipped_fo_reject
            signals.extend(result.signals)
            emit(result.ticker)

    try:
        if workers == 1:
            for meta in tickers_meta:
                consume_result(
                    _scan_ticker(
                        meta,
                        scan_date=scan_date,
                        run_id=run_id,
                        db=db,
                        fundamentals_index=fundamentals_index,
                        market_ctx=market_ctx,
                    )
                )
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(
                        _scan_ticker,
                        meta,
                        scan_date=scan_date,
                        run_id=run_id,
                        db=db,
                        fundamentals_index=fundamentals_index,
                        market_ctx=market_ctx,
                    )
                    for meta in tickers_meta
                ]
                for future in as_completed(futures):
                    consume_result(future.result())

        fo_sync_meta: dict[str, Any] = {}
        if skip_fo_sync:
            signals, skipped_after = finalize_signals_with_fo_data(db, scan_date, signals)
            skipped_fo_reject += skipped_after
            fo_sync_meta = {"skipped": True, "skipped_fo_reject_after_sync": skipped_after}
        else:
            try:
                signals, fo_sync_meta = run_coro_sync(
                    ensure_and_finalize_scanner_signals(
                        db,
                        scan_date,
                        signals,
                        access_token=get_access_token(),
                    )
                )
                skipped_fo_reject += int(fo_sync_meta.get("skipped_fo_reject_after_sync") or 0)
            except Exception as exc:
                logger.warning("F&O derivative auto-sync failed: %s", exc)
                fo_sync_meta = {"error": str(exc)}

        db.insert_pattern_signals(signals)
        db.finish_scanner_run(
            run_id,
            symbols_scanned=scanned,
            alerts_count=len(signals),
            status="completed",
            engine_version=SCANNER_ENGINE_VERSION,
        )
    except Exception:
        db.finish_scanner_run(
            run_id,
            symbols_scanned=scanned,
            alerts_count=0,
            status="failed",
            engine_version=SCANNER_ENGINE_VERSION,
        )
        raise

    emit(None)
    return {
        "run_id": run_id,
        "trade_date": scan_date,
        "symbols_scanned": scanned,
        "alerts_count": len(signals),
        "skipped_illiquid": skipped_illiquid,
        "skipped_fo_reject": skipped_fo_reject,
        "fo_derivative_sync": fo_sync_meta,
        "status": "completed",
        "concurrency": workers,
        "skip_fo_sync": skip_fo_sync,
        "engine_version": SCANNER_ENGINE_VERSION,
        "fundamentals_cached": len(fundamentals_index),
        "market_context": {
            "nifty_pcr": market_ctx.nifty_pcr,
            "fii_net_cash": market_ctx.fii_net_cash,
            "derivative_symbols": len(market_ctx.stock_pcr),
            "derivative_metrics": len(market_ctx.derivatives),
        },
    }
