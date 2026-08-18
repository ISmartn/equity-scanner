from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..cache import delete_cache_prefix, get_cached
from ..config import get_access_token
from ..db.store import get_store
from ..services import market_info_sync
from ..services.market_calendar import trading_days_in_month_through, trading_days_prior_to
from ..services.scanner.engine import DEFAULT_SCANNER_CONCURRENCY, run_scanner
from ..services.scanner.fo_enrich import enrich_scanner_results
from ..services.scanner.fo_sync import load_fno_symbol_set_sync
from ..services.scanner.timing import enrich_signal_timing, passes_timing_filters

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scanner", tags=["scanner"])

PATTERN_TYPES = (
    "vcp",
    "high_tight_flag",
    "pocket_pivot",
    "pocket_pivot_setup",
    "inside_bar_cluster",
    "power_gap",
    "tight_range_near_pivot",
    "darvas_pre_setup",
)

ScannerBatchMode = Literal["single", "month", "last_7"]

_scanner_status: dict = {
    "running": False,
    "total": 0,
    "processed": 0,
    "alerts_count": 0,
    "current_ticker": None,
    "trade_date": None,
    "batch_mode": None,
    "batch_dates": None,
    "batch_day_index": 0,
    "batch_day_total": 0,
    "last_result": None,
}


class ScannerRunRequest(BaseModel):
    trade_date: str | None = Field(None, description="Scan as of this date (YYYY-MM-DD)")
    batch: ScannerBatchMode = Field(
        "single",
        description="single | month (weekdays in selected month through date) | last_7 (7 prior weekdays)",
    )


class EnsureDerivativesRequest(BaseModel):
    trade_date: str = Field(..., description="Trade date YYYY-MM-DD")
    tickers: list[str] = Field(..., min_length=1, max_length=100)


class PatternSignalRow(BaseModel):
    ticker: str
    company_name: str | None
    sector: str | None
    trade_date: str
    pattern_type: str
    macro_pass: bool
    score: float
    triggered_today: bool
    setup_ready: bool
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None
    daily_return_pct: float | None = None
    details: dict


class ScannerResultsResponse(BaseModel):
    trade_date: str
    total: int
    limit: int
    offset: int
    scan_alerts_count: int | None = None
    results: list[PatternSignalRow]


def _scanner_progress_callback(update: dict) -> None:
    _scanner_status.update(update)


def _reset_scanner_status_for_run(
    *,
    trade_date: str | None,
    batch_mode: ScannerBatchMode,
    batch_dates: list[str] | None = None,
) -> None:
    _scanner_status.update(
        {
            "running": True,
            "total": 0,
            "processed": 0,
            "alerts_count": 0,
            "current_ticker": None,
            "trade_date": trade_date,
            "batch_mode": batch_mode if batch_mode != "single" else None,
            "batch_dates": batch_dates,
            "batch_day_index": 0,
            "batch_day_total": len(batch_dates) if batch_dates else 0,
        }
    )


def _batch_dates_for_mode(batch: ScannerBatchMode, trade_date: str) -> list[str]:
    anchor = date.fromisoformat(trade_date)
    if batch == "month":
        return trading_days_in_month_through(anchor)
    if batch == "last_7":
        return trading_days_prior_to(anchor, 7)
    return [trade_date]


def _clear_batch_fields() -> None:
    _scanner_status["batch_mode"] = None
    _scanner_status["batch_dates"] = None
    _scanner_status["batch_day_index"] = 0
    _scanner_status["batch_day_total"] = 0


async def _run_scanner_job(trade_date: str | None) -> None:
    _reset_scanner_status_for_run(trade_date=trade_date, batch_mode="single")
    try:
        result = run_scanner(
            trade_date=trade_date,
            on_progress=_scanner_progress_callback,
            concurrency=DEFAULT_SCANNER_CONCURRENCY,
        )
        _scanner_status["last_result"] = result
    except Exception as exc:
        logger.exception("Scanner run failed")
        _scanner_status["last_result"] = {"error": str(exc), "status": "failed"}
    finally:
        _scanner_status["running"] = False
        _scanner_status["current_ticker"] = None
        _clear_batch_fields()


async def _run_scanner_batch_job(batch: ScannerBatchMode, trade_date: str, dates: list[str]) -> None:
    _reset_scanner_status_for_run(trade_date=dates[0], batch_mode=batch, batch_dates=dates)
    run_results: list[dict] = []
    total_alerts = 0
    completed_dates: list[str] = []
    try:
        for day_index, scan_date in enumerate(dates, start=1):
            _scanner_status["batch_day_index"] = day_index
            _scanner_status["trade_date"] = scan_date
            _scanner_status["processed"] = 0
            _scanner_status["total"] = 0
            _scanner_status["current_ticker"] = None

            def on_progress(update: dict, *, _scan_date: str = scan_date) -> None:
                _scanner_progress_callback(update)
                _scanner_status["trade_date"] = _scan_date

            result = run_scanner(
                trade_date=scan_date,
                on_progress=on_progress,
                concurrency=DEFAULT_SCANNER_CONCURRENCY,
            )
            run_results.append(result)
            completed_dates.append(scan_date)
            total_alerts += int(result.get("alerts_count") or 0)
            _scanner_status["alerts_count"] = total_alerts

        _scanner_status["last_result"] = {
            "status": "completed",
            "batch": batch,
            "anchor_date": trade_date,
            "dates_scanned": dates,
            "days_scanned": len(dates),
            "total_alerts": total_alerts,
            "runs": run_results,
        }
        _scanner_status["trade_date"] = dates[-1]
    except Exception as exc:
        logger.exception("Scanner batch run failed")
        _scanner_status["last_result"] = {
            "error": str(exc),
            "status": "failed",
            "batch": batch,
            "anchor_date": trade_date,
            "dates_scanned": completed_dates,
        }
    finally:
        _scanner_status["running"] = False
        _scanner_status["current_ticker"] = None
        _clear_batch_fields()


@router.get("/dates")
async def scanner_dates(limit: int = Query(90, ge=1, le=365)) -> dict:
    from ..services.scanner.engine import SCANNER_ENGINE_VERSION

    store = get_store()
    dates = store.list_scanner_dates(limit=limit)
    refined_dates = store.list_refined_scanner_dates(
        engine_version=SCANNER_ENGINE_VERSION,
        limit=limit,
    )
    stats = store.stats()
    return {
        "dates": dates,
        "refined_dates": refined_dates,
        "engine_version": SCANNER_ENGINE_VERSION,
        "count": len(dates),
        "latest_data_date": stats.get("max_trade_date"),
        "latest_with_alerts": store.latest_scanner_date_with_alerts(),
    }


@router.post("/run")
async def scanner_run(
    body: ScannerRunRequest,
    background: BackgroundTasks,
    background_run: bool = Query(True),
) -> dict:
    if _scanner_status.get("running"):
        raise HTTPException(status_code=409, detail="Scanner already running")

    batch = body.batch
    if batch != "single":
        if not body.trade_date:
            raise HTTPException(status_code=400, detail="trade_date required for batch scan")
        dates = _batch_dates_for_mode(batch, body.trade_date)
        if not dates:
            raise HTTPException(status_code=400, detail="No trading days in scan range")

        if not background_run:
            raise HTTPException(status_code=400, detail="Batch scan requires background_run=true")

        background.add_task(_run_scanner_batch_job, batch, body.trade_date, dates)
        _reset_scanner_status_for_run(
            trade_date=dates[0],
            batch_mode=batch,
            batch_dates=dates,
        )
        label = "month" if batch == "month" else "last 7 days"
        return {
            "status": "started",
            "message": f"Batch scan started ({label}, {len(dates)} sessions)",
            "batch": batch,
            "dates": dates,
        }

    if background_run:
        background.add_task(_run_scanner_job, body.trade_date)
        _reset_scanner_status_for_run(trade_date=body.trade_date, batch_mode="single")
        return {"status": "started", "message": "Scanner started in background"}

    try:
        result = run_scanner(trade_date=body.trade_date, on_progress=_scanner_progress_callback)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _scanner_status["last_result"] = result
    return result


@router.get("/status")
async def scanner_status() -> dict:
    return {
        "running": bool(_scanner_status.get("running")),
        "total": int(_scanner_status.get("total") or 0),
        "processed": int(_scanner_status.get("processed") or 0),
        "alerts_count": int(_scanner_status.get("alerts_count") or 0),
        "current_ticker": _scanner_status.get("current_ticker"),
        "trade_date": _scanner_status.get("trade_date"),
        "batch_mode": _scanner_status.get("batch_mode"),
        "batch_dates": _scanner_status.get("batch_dates"),
        "batch_day_index": int(_scanner_status.get("batch_day_index") or 0),
        "batch_day_total": int(_scanner_status.get("batch_day_total") or 0),
        "last_result": _scanner_status.get("last_result"),
    }


def _enrich_and_filter_timing(
    store,
    trade_iso: str,
    rows: list[dict],
    *,
    max_pre_20d_return: float | None,
    max_signal_day_return: float | None,
) -> list[dict]:
    if not rows:
        return rows

    import pandas as pd

    needs_timing = any(
        (row.get("details") or {}).get("pre_20d_return_pct") is None for row in rows
    )
    candle_cache: dict[str, pd.DataFrame] = {}
    if needs_timing:
        tickers = {row["ticker"] for row in rows}
        for ticker in tickers:
            candles = store.get_recent_candles_for_scan(
                ticker,
                limit=25,
                as_of_date=trade_iso,
            )
            if len(candles) >= 21:
                candle_cache[ticker] = pd.DataFrame(candles)

    enriched: list[dict] = []
    for row in rows:
        df = candle_cache.get(row["ticker"])
        if df is not None:
            row = enrich_signal_timing(row, df)
        if passes_timing_filters(
            row,
            max_pre_20d_return=max_pre_20d_return,
            max_signal_day_return=max_signal_day_return,
        ):
            enriched.append(row)
    return enriched


@router.get("/results", response_model=ScannerResultsResponse)
async def scanner_results(
    trade_date: date = Query(..., description="Scan trade date"),
    pattern: str | None = Query(None, description="Filter by single pattern type"),
    patterns: list[str] | None = Query(None, description="Include only these pattern types"),
    exclude_patterns: list[str] | None = Query(None, description="Exclude these pattern types"),
    min_score: float = Query(0.0, ge=0, le=100),
    sector: str | None = Query(None),
    triggered_only: bool = Query(False),
    setup_only: bool = Query(False),
    macro_pass_only: bool = Query(False),
    fundamental_pass_only: bool = Query(False),
    max_pre_20d_return: float | None = Query(None, ge=-100, le=500),
    max_signal_day_return: float | None = Query(None, ge=-100, le=100),
    sort: Literal["score", "setup_first"] = Query("score"),
    limit: int = Query(100, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> ScannerResultsResponse:
    if pattern and pattern not in PATTERN_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid pattern. Choose from: {PATTERN_TYPES}")
    if patterns:
        invalid = [p for p in patterns if p not in PATTERN_TYPES]
        if invalid:
            raise HTTPException(status_code=400, detail=f"Invalid patterns: {invalid}")
    if exclude_patterns:
        invalid = [p for p in exclude_patterns if p not in PATTERN_TYPES]
        if invalid:
            raise HTTPException(status_code=400, detail=f"Invalid exclude_patterns: {invalid}")

    store = get_store()
    trade_iso = trade_date.isoformat()
    run = store.get_latest_scanner_run(trade_iso)
    timing_filter_active = max_pre_20d_return is not None or max_signal_day_return is not None
    query_limit = 2000 if timing_filter_active else limit
    query_offset = 0 if timing_filter_active else offset
    rows, total = store.query_pattern_signals(
        trade_iso,
        pattern_type=pattern if not patterns else None,
        pattern_types=patterns,
        exclude_pattern_types=exclude_patterns,
        min_score=min_score,
        sector=sector,
        triggered_only=triggered_only,
        setup_only=setup_only,
        macro_pass_only=macro_pass_only,
        fundamental_pass_only=fundamental_pass_only,
        sort_by=sort,
        limit=query_limit,
        offset=query_offset,
    )
    if timing_filter_active:
        rows = _enrich_and_filter_timing(
            store,
            trade_iso,
            rows,
            max_pre_20d_return=max_pre_20d_return,
            max_signal_day_return=max_signal_day_return,
        )
        total = len(rows)
        rows = rows[offset : offset + limit]
    derivatives = store.load_derivative_metrics_for_date(trade_iso)
    # Always refresh fo_overlay from DB (stored signals may predate FO overlay or lack enrichment).
    rows = enrich_scanner_results(rows, derivatives)
    return ScannerResultsResponse(
        trade_date=trade_iso,
        total=total,
        limit=limit,
        offset=offset,
        scan_alerts_count=int(run["alerts_count"]) if run else None,
        results=[PatternSignalRow(**row) for row in rows],
    )


@router.get("/results/{ticker}")
async def scanner_results_ticker(
    ticker: str,
    trade_date: date = Query(...),
) -> dict:
    signals = get_store().get_pattern_signals_for_ticker(ticker.upper(), trade_date.isoformat())
    if not signals:
        raise HTTPException(status_code=404, detail=f"No scanner signals for {ticker.upper()}")
    return {"ticker": ticker.upper(), "trade_date": trade_date.isoformat(), "signals": signals}


@router.post("/ensure-derivatives")
async def scanner_ensure_derivatives(
    body: EnsureDerivativesRequest,
    x_upstox_access_token: str | None = Header(default=None),
) -> dict:
    """Ensure Upstox derivative snapshots exist for F&O tickers on the scan date."""
    store = get_store()
    trade_iso = body.trade_date
    fno_set = load_fno_symbol_set_sync()
    if not fno_set:
        cached = get_cached("fno:symbols:v1")
        if not cached:
            raise HTTPException(
                status_code=503,
                detail="F&O symbol list unavailable. Retry shortly or call GET /api/fno first.",
            )
        fno_set = set(cached)

    tickers = sorted({t.strip().upper() for t in body.tickers if t.strip()})
    fno_tickers = [t for t in tickers if t in fno_set]
    if not fno_tickers:
        return {
            "trade_date": trade_iso,
            "requested": len(tickers),
            "fno_tickers": [],
            "already_present": [],
            "synced": [],
            "failed": [],
            "skipped_not_fno": tickers,
        }

    missing = store.symbols_missing_derivatives(fno_tickers, trade_iso)
    token = get_access_token(x_upstox_access_token)
    if missing and not token:
        raise HTTPException(
            status_code=401,
            detail="Upstox access token required to fetch missing F&O derivative data",
        )

    try:
        result = await market_info_sync.ensure_derivative_snapshots(
            token,
            trade_date=date.fromisoformat(trade_iso),
            symbols=fno_tickers,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Scanner ensure-derivatives failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    delete_cache_prefix("market-info:")
    result["fno_tickers"] = fno_tickers
    result["skipped_not_fno"] = [t for t in tickers if t not in fno_set]
    return result


@router.get("/patterns")
async def scanner_patterns() -> dict:
    return {
        "patterns": [
            {"id": "vcp", "label": "VCP", "type": "macro"},
            {"id": "high_tight_flag", "label": "High Tight Flag", "type": "macro"},
            {"id": "pocket_pivot", "label": "Pocket Pivot", "type": "micro"},
            {"id": "pocket_pivot_setup", "label": "Pocket Pivot Setup", "type": "micro"},
            {"id": "inside_bar_cluster", "label": "Inside Bar Cluster", "type": "micro"},
            {"id": "power_gap", "label": "Power Gap", "type": "micro"},
            {"id": "tight_range_near_pivot", "label": "Tight Range Near Pivot", "type": "micro"},
            {"id": "darvas_pre_setup", "label": "Darvas Pre-Setup", "type": "micro"},
        ]
    }


@router.get("/outcomes/summary")
async def scanner_outcomes_summary() -> dict:
    """Forward-performance feedback for stored signals (baseline vs refined filters)."""
    from ..services.scanner.outcomes import build_baseline_vs_refined_report

    store = get_store()
    return {
        "stats": store.signal_outcomes_stats(),
        "comparison": build_baseline_vs_refined_report(store=store),
    }
