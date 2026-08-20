from __future__ import annotations

import logging
from datetime import date
from typing import Any

import aiohttp
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..cache import delete_cache, get_cached, set_cache
from ..db.store import get_store
from ..services import candle_ingestion, fundamentals_sync, profile_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


class MoverRow(BaseModel):
    ticker: str
    company_name: str | None
    sector: str | None
    industry: str | None
    trade_date: str
    open_price: float | None
    high_price: float | None
    low_price: float | None
    close_price: float | None
    volume: int | None
    daily_return_pct: float | None
    source: str | None


class MoversResponse(BaseModel):
    trade_date: str
    sector: str | None
    min_move_pct: float
    direction: str
    total: int
    limit: int
    offset: int
    results: list[MoverRow]


class IngestRequest(BaseModel):
    years: int = Field(2, ge=1, le=10)
    days: int | None = Field(None, ge=1, le=3650)
    limit: int | None = Field(None, ge=1, le=5000)
    tickers: list[str] | None = None
    refresh_all: bool = False
    since_last: bool = False
    bootstrap_days: int = Field(30, ge=1, le=365)
    source: str = Field("auto", pattern="^(auto|upstox|nse)$")
    concurrency: int = Field(3, ge=1, le=8)
    request_delay_sec: float = Field(0.35, ge=0.0, le=5.0)


_ingest_status: dict[str, Any] = {
    "running": False,
    "mode": None,
    "total": 0,
    "processed": 0,
    "success": 0,
    "failed": 0,
    "skipped": 0,
    "empty": 0,
    "total_bars": 0,
    "current_ticker": None,
    "last_result": None,
    "cancel_requested": False,
    "recent_errors": [],
}

_ingest_cancel_requested = False


def _reset_ingest_progress(*, mode: str) -> None:
    global _ingest_cancel_requested
    _ingest_cancel_requested = False
    _ingest_status.update(
        {
            "running": True,
            "mode": mode,
            "total": 0,
            "processed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "empty": 0,
            "total_bars": 0,
            "current_ticker": None,
            "cancel_requested": False,
        }
    )


def _ingest_should_cancel() -> bool:
    return _ingest_cancel_requested


def _ingest_progress_callback(update: dict[str, Any]) -> None:
    _ingest_status.update(update)


@router.get("/stats")
async def timeline_stats() -> dict:
    return get_store().stats()


@router.get("/sectors")
async def timeline_sectors() -> dict:
    sectors = get_store().list_sectors()
    return {"sectors": sectors, "count": len(sectors)}


@router.get("/dates")
async def timeline_dates(limit: int = Query(365, ge=1, le=2000)) -> dict:
    dates = get_store().list_trade_dates(limit=limit)
    return {"dates": dates, "count": len(dates)}


@router.get("/movers", response_model=MoversResponse)
async def timeline_movers(
    trade_date: date = Query(..., description="Trading date (YYYY-MM-DD)"),
    sector: str | None = Query(None),
    ticker: str | None = Query(None, min_length=1, max_length=32),
    min_move_pct: float = Query(0.0, ge=0),
    direction: str = Query("both", pattern="^(both|up|down)$"),
    limit: int = Query(100, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> MoversResponse:
    ticker_norm = ticker.strip().upper() if ticker else None
    cache_key = (
        f"timeline:movers:{trade_date}:{sector}:{ticker_norm}:{min_move_pct}:"
        f"{direction}:{limit}:{offset}"
    )
    cached = get_cached(cache_key)
    if cached:
        return MoversResponse(**cached)

    date_str = trade_date.isoformat()
    rows, total = get_store().query_movers(
        date_str,
        sector=sector,
        ticker=ticker_norm,
        min_move_pct=min_move_pct,
        direction=direction,
        limit=limit,
        offset=offset,
    )

    payload = MoversResponse(
        trade_date=date_str,
        sector=sector,
        min_move_pct=min_move_pct,
        direction=direction,
        total=total,
        limit=limit,
        offset=offset,
        results=[MoverRow(**row) for row in rows],
    )
    set_cache(cache_key, payload.model_dump(), 3600)
    return payload


class TimelineCandlePoint(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    daily_return_pct: float | None = None
    source: str | None = None


class TimelineCandlesResponse(BaseModel):
    symbol: str
    source: str
    history_bars: int
    from_date: str | None
    to_date: str | None
    history: list[TimelineCandlePoint]


@router.get("/candles", response_model=TimelineCandlesResponse)
async def timeline_candles(
    symbol: str = Query(..., min_length=1),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
) -> TimelineCandlesResponse:
    from_str = from_date.isoformat() if from_date else None
    to_str = to_date.isoformat() if to_date else None
    rows = get_store().get_candles_for_ticker(
        symbol.upper(),
        from_date=from_str,
        to_date=to_str,
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No local candle history for {symbol.upper()}. Ingest this symbol first.",
        )

    history = [TimelineCandlePoint(**row) for row in rows]
    sources = {row.get("source") for row in rows if row.get("source")}
    source = "+".join(sorted(sources)) if sources else "local"

    return TimelineCandlesResponse(
        symbol=symbol.upper(),
        source=source,
        history_bars=len(history),
        from_date=history[0].date if history else None,
        to_date=history[-1].date if history else None,
        history=history,
    )


@router.post("/sync-profiles")
async def sync_profiles() -> dict:
    async with aiohttp.ClientSession() as session:
        try:
            result = await profile_sync.sync_security_profiles(session)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result


@router.post("/reprofile-stale")
async def reprofile_stale() -> dict:
    async with aiohttp.ClientSession() as session:
        try:
            result = await profile_sync.reprofile_stale_profiles(session)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result


async def _run_ingest(
    years: int,
    days: int | None,
    limit: int | None,
    tickers: list[str] | None,
    refresh_all: bool,
    since_last: bool,
    bootstrap_days: int,
    source: str,
    concurrency: int,
    request_delay_sec: float,
    access_token: str | None,
) -> None:
    global _ingest_status
    mode = "upto_date" if since_last else "ingest"
    _reset_ingest_progress(mode=mode)
    try:
        result = await candle_ingestion.ingest_candles(
            years=years,
            days=days,
            limit=limit,
            tickers=tickers,
            refresh_all=refresh_all,
            since_last=since_last,
            bootstrap_days=bootstrap_days,
            source_preference=source,  # type: ignore[arg-type]
            concurrency=concurrency,
            request_delay_sec=request_delay_sec,
            access_token=access_token,
            on_progress=_ingest_progress_callback,
            should_cancel=_ingest_should_cancel,
        )
        _ingest_status["last_result"] = result
    except Exception as exc:
        logger.exception("Background ingest failed")
        _ingest_status["last_result"] = {"error": str(exc)}
    finally:
        _ingest_status["running"] = False
        _ingest_status["current_ticker"] = None


def _recent_ingest_errors(last_result: Any, limit: int = 25) -> list[dict[str, str]]:
    if not isinstance(last_result, dict):
        return []
    errors = last_result.get("errors")
    if isinstance(errors, dict) and errors:
        return [
            {"ticker": ticker, "error": message}
            for ticker, message in list(errors.items())[:limit]
        ]
    results = last_result.get("results")
    if not isinstance(results, list):
        return []
    out: list[dict[str, str]] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        if row.get("status") != "error":
            continue
        ticker = str(row.get("ticker") or "")
        err = str(row.get("error") or "unknown error")
        if ticker:
            out.append({"ticker": ticker, "error": err})
        if len(out) >= limit:
            break
    return out


@router.post("/ingest")
async def ingest_candles_endpoint(
    body: IngestRequest,
    background: BackgroundTasks,
    x_upstox_access_token: str | None = Header(default=None),
    background_run: bool = Query(True, description="Run ingestion in background"),
) -> dict:
    if _ingest_status.get("running"):
        raise HTTPException(status_code=409, detail="Ingestion already running")

    use_background = background_run and (
        body.since_last or body.refresh_all or (body.limit is not None and body.limit > 20)
    )

    if use_background:
        background.add_task(
            _run_ingest,
            body.years,
            body.days,
            body.limit,
            body.tickers,
            body.refresh_all or body.since_last,
            body.since_last,
            body.bootstrap_days,
            body.source,
            body.concurrency,
            body.request_delay_sec,
            x_upstox_access_token,
        )
        mode = "upto_date" if body.since_last else "ingest"
        _reset_ingest_progress(mode=mode)
        return {
            "status": "started",
            "mode": mode,
            "message": "Ingestion started in background",
        }

    mode = "upto_date" if body.since_last else "ingest"
    _reset_ingest_progress(mode=mode)
    try:
        result = await candle_ingestion.ingest_candles(
            years=body.years,
            days=body.days,
            limit=body.limit,
            tickers=body.tickers,
            refresh_all=body.refresh_all or body.since_last,
            since_last=body.since_last,
            bootstrap_days=body.bootstrap_days,
            source_preference=body.source,  # type: ignore[arg-type]
            concurrency=body.concurrency,
            request_delay_sec=body.request_delay_sec,
            access_token=x_upstox_access_token,
            on_progress=_ingest_progress_callback,
            should_cancel=_ingest_should_cancel,
        )
    except Exception as exc:
        _ingest_status["running"] = False
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _ingest_status["last_result"] = result
    _ingest_status["running"] = False
    _ingest_status["current_ticker"] = None
    return result


@router.post("/ingest/cancel")
async def cancel_ingest() -> dict:
    global _ingest_cancel_requested
    if not _ingest_status.get("running"):
        return {"status": "idle", "message": "No ingestion running"}
    _ingest_cancel_requested = True
    _ingest_status["cancel_requested"] = True
    return {"status": "cancelling", "message": "Stop requested; finishing current symbol…"}


@router.get("/ingest/status")
async def ingest_status() -> dict:
    last_result = _ingest_status.get("last_result")
    live_errors = _ingest_status.get("recent_errors")
    return {
        "running": bool(_ingest_status.get("running")),
        "mode": _ingest_status.get("mode"),
        "total": int(_ingest_status.get("total") or 0),
        "processed": int(_ingest_status.get("processed") or 0),
        "success": int(_ingest_status.get("success") or 0),
        "failed": int(_ingest_status.get("failed") or 0),
        "skipped": int(_ingest_status.get("skipped") or 0),
        "empty": int(_ingest_status.get("empty") or 0),
        "total_bars": int(_ingest_status.get("total_bars") or 0),
        "cancel_requested": bool(_ingest_status.get("cancel_requested")),
        "current_ticker": _ingest_status.get("current_ticker"),
        "last_result": last_result,
        "recent_errors": live_errors if live_errors else _recent_ingest_errors(last_result),
        "error_log": (
            last_result.get("error_log")
            if isinstance(last_result, dict) and last_result.get("error_log")
            else candle_ingestion.DEFAULT_ERROR_LOG.as_posix()
        ),
    }


class FundamentalsResponse(BaseModel):
    ticker: str
    isin: str | None = None
    updated_at: str
    cached: bool = True
    profile: dict[str, Any] | list[Any] | None = None
    balance_sheet: dict[str, Any] | list[Any] | None = None
    cash_flow: dict[str, Any] | list[Any] | None = None
    income_statement: dict[str, Any] | list[Any] | None = None
    income_statement_quarterly: dict[str, Any] | list[Any] | None = None
    share_holdings: dict[str, Any] | list[Any] | None = None
    key_ratios: dict[str, Any] | list[Any] | None = None
    corporate_actions: dict[str, Any] | list[Any] | None = None
    competitors: dict[str, Any] | list[Any] | None = None
    partial_errors: list[str] | None = None
    quality_verdict: dict[str, Any] | None = None
    momentum_verdict: dict[str, Any] | None = None


class SyncFundamentalsRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1, max_length=50)
    force: bool = False


def _attach_quality_verdict(payload: FundamentalsResponse) -> FundamentalsResponse:
    from ..services.fundamentals_momentum import evaluate_earnings_momentum
    from ..services.fundamentals_quality import evaluate_fundamentally_strong

    data = payload.model_dump()
    data["quality_verdict"] = evaluate_fundamentally_strong(data)
    data["momentum_verdict"] = evaluate_earnings_momentum(data)
    return FundamentalsResponse(**data)


@router.get("/fundamentals", response_model=FundamentalsResponse)
async def get_fundamentals(
    ticker: str = Query(..., min_length=1, max_length=32),
    fetch_if_missing: bool = Query(True, description="Fetch from Upstox when not cached"),
    x_upstox_access_token: str | None = Header(default=None),
) -> FundamentalsResponse:
    ticker_norm = ticker.strip().upper()
    cache_key = f"fundamentals:{ticker_norm}"
    cached_mem = get_cached(cache_key)
    if cached_mem:
        return _attach_quality_verdict(FundamentalsResponse(**cached_mem))

    store = get_store()
    row = store.get_fundamentals(ticker_norm)
    if row:
        payload = FundamentalsResponse(cached=True, **row)
        set_cache(cache_key, payload.model_dump(), 3600)
        return _attach_quality_verdict(payload)

    if not fetch_if_missing:
        raise HTTPException(
            status_code=404,
            detail=f"No cached fundamentals for {ticker_norm}. Use sync-fundamentals to fetch.",
        )

    try:
        row = await fundamentals_sync.fetch_fundamentals_for_ticker(
            ticker_norm,
            x_upstox_access_token,
            force=False,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    payload = FundamentalsResponse(cached=False, **row)
    set_cache(cache_key, payload.model_dump(), 3600)
    return _attach_quality_verdict(payload)

@router.get("/fundamentals/strong")
async def list_fundamentally_strong() -> dict:
    """Tickers that pass the fundamentally-strong baseline over cached financials."""
    from ..services.fundamentals_quality import (
        DEFAULT_STRONG_THRESHOLDS,
        list_fundamentally_strong_tickers,
    )
    from dataclasses import asdict

    store = get_store()
    index = store.load_fundamentals_index()
    symbols = list_fundamentally_strong_tickers(index)
    return {
        "symbols": symbols,
        "count": len(symbols),
        "evaluated": len(index),
        "thresholds": asdict(DEFAULT_STRONG_THRESHOLDS),
    }


@router.post("/sync-fundamentals")
async def sync_fundamentals_endpoint(
    body: SyncFundamentalsRequest,
    x_upstox_access_token: str | None = Header(default=None),
) -> dict:
    tickers = [t.strip().upper() for t in body.tickers if t.strip()]
    if not tickers:
        raise HTTPException(status_code=400, detail="No valid tickers provided")
    try:
        result = await fundamentals_sync.sync_fundamentals_tickers(
            tickers,
            x_upstox_access_token,
            force=body.force,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    for ticker in result.get("tickers_synced", []):
        delete_cache(f"fundamentals:{ticker}")

    if result["success"] == 0 and result["failed"] > 0:
        first_error = next(iter(result["errors"].values()), "Sync failed")
        raise HTTPException(status_code=502, detail=first_error)
    return result
