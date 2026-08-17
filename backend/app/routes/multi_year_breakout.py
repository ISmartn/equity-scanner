"""API routes for multi-year breakout / ATH pullback screener."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from ..db.store import get_store
from ..services.multi_year_breakout.detector import DEFAULT_ATH_PULLBACK_PCT
from ..services.multi_year_breakout.engine import (
    DEFAULT_LOOKBACK_YEARS,
    run_multi_year_breakout_scan,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/multi-year-breakout", tags=["multi-year-breakout"])

StrategyLiteral = Literal["multi_year_breakout", "ath_pullback", "custom"]
TrendLiteral = Literal["all", "uptrend", "downtrend"]
MatchLiteral = Literal["at_least", "at_most", "band"]

_status: dict[str, Any] = {
    "running": False,
    "trade_date": None,
    "strategy": None,
    "lookback_years": None,
    "processed": 0,
    "total": 0,
    "alerts_count": 0,
    "current_ticker": None,
    "last_result": None,
}


class MybRunRequest(BaseModel):
    trade_date: str | None = None
    strategy: StrategyLiteral = "multi_year_breakout"
    lookback_years: int = Field(default=DEFAULT_LOOKBACK_YEARS, ge=2, le=5)
    pullback_pct: float = Field(default=DEFAULT_ATH_PULLBACK_PCT, ge=5.0, le=90.0)
    match_mode: MatchLiteral = "at_least"
    band_width_pct: float = Field(default=5.0, ge=0.0, le=40.0)
    trend_filter: TrendLiteral = "all"
    short_ma_period: int = Field(default=50, ge=5, le=100)
    long_ma_period: int = Field(default=200, ge=20, le=300)
    ma_type: Literal["sma", "ema"] = "sma"
    include_multi_year: bool = True
    include_ath_pullback: bool = True
    sector: str | None = None
    size_tier: Literal["all", "large", "mid", "small"] | None = "all"
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    min_rvol: float | None = Field(default=None, ge=0)
    concurrency: int = Field(default=4, ge=1, le=12)


def _filters_from_body(body: MybRunRequest) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if body.sector:
        out["sector"] = body.sector
    if body.size_tier and body.size_tier != "all":
        out["size_tier"] = body.size_tier
    if body.min_price is not None:
        out["min_price"] = body.min_price
    if body.max_price is not None:
        out["max_price"] = body.max_price
    if body.min_rvol is not None:
        out["min_rvol"] = body.min_rvol
    return out


def _run_kwargs(body: MybRunRequest) -> dict[str, Any]:
    return {
        "trade_date": body.trade_date,
        "strategy": body.strategy,
        "lookback_years": body.lookback_years,
        "pullback_pct": body.pullback_pct,
        "match_mode": body.match_mode,
        "band_width_pct": body.band_width_pct,
        "trend_filter": body.trend_filter,
        "short_ma_period": body.short_ma_period,
        "long_ma_period": body.long_ma_period,
        "ma_type": body.ma_type,
        "custom_flags": {
            "include_multi_year": body.include_multi_year,
            "include_ath_pullback": body.include_ath_pullback,
        },
        "filters": _filters_from_body(body),
        "concurrency": body.concurrency,
    }


def _run_job(body: MybRunRequest) -> None:
    def on_progress(update: dict[str, Any]) -> None:
        _status["processed"] = int(update.get("processed") or 0)
        _status["total"] = int(update.get("total") or 0)
        _status["alerts_count"] = int(update.get("alerts_count") or 0)
        _status["current_ticker"] = update.get("current_ticker")
        _status["trade_date"] = update.get("trade_date")
        _status["lookback_years"] = update.get("lookback_years")
        _status["strategy"] = update.get("strategy")

    try:
        result = run_multi_year_breakout_scan(**_run_kwargs(body), on_progress=on_progress)
        _status["last_result"] = result
    except Exception as exc:
        logger.exception("Multi-year breakout scan failed")
        _status["last_result"] = {"status": "failed", "error": str(exc)}
    finally:
        _status["running"] = False
        _status["current_ticker"] = None


@router.get("/strategies")
async def myb_strategies() -> dict:
    return {
        "strategies": [
            {
                "id": "multi_year_breakout",
                "label": "Multi-Year Breakout",
                "description": "Fresh or near break of a dormant multi-year high with volume confirmation.",
            },
            {
                "id": "ath_pullback",
                "label": "Pullback from ATH",
                "description": "Stocks down at least X% from ATH, with optional uptrend/downtrend filter.",
            },
            {
                "id": "custom",
                "label": "Custom Filters",
                "description": "Combine multi-year and ATH pullback conditions with shared global filters.",
            },
        ]
    }


@router.get("/dates")
async def myb_dates(
    limit: int = Query(90, ge=1, le=365),
    strategy: str | None = Query(None),
) -> dict:
    store = get_store()
    dates = store.list_myb_dates(limit=limit, strategy=strategy)
    stats = store.stats()
    return {
        "dates": dates,
        "count": len(dates),
        "latest_data_date": stats.get("max_trade_date"),
    }


@router.get("/status")
async def myb_status() -> dict:
    return dict(_status)


@router.post("/run")
async def myb_run(
    body: MybRunRequest,
    background: BackgroundTasks,
    background_run: bool = Query(True),
) -> dict:
    if _status.get("running"):
        raise HTTPException(status_code=409, detail="Multi-year breakout scan already running")

    if background_run:
        _status.update(
            {
                "running": True,
                "trade_date": body.trade_date,
                "strategy": body.strategy,
                "lookback_years": body.lookback_years,
                "processed": 0,
                "total": 0,
                "alerts_count": 0,
                "current_ticker": None,
                "last_result": None,
            }
        )
        background.add_task(_run_job, body)
        return {
            "status": "started",
            "background": True,
            "strategy": body.strategy,
            "lookback_years": body.lookback_years,
            "pullback_pct": body.pullback_pct,
            "match_mode": body.match_mode,
            "trend_filter": body.trend_filter,
        }

    result = run_multi_year_breakout_scan(**_run_kwargs(body))
    _status["last_result"] = result
    return result


@router.get("/results")
async def myb_results(
    trade_date: str = Query(...),
    strategy: str | None = Query(None),
    lookback_years: int | None = Query(None, ge=0, le=5),
    status: str | None = Query(None, pattern="^(breakout|near|pullback)$"),
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    sector: str | None = Query(None),
    size_tier: str | None = Query(None),
    trend: str | None = Query(None, pattern="^(all|uptrend|downtrend)$"),
    min_price: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    min_rvol: float | None = Query(None, ge=0),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    store = get_store()
    lb = lookback_years
    if strategy == "ath_pullback" and lb is None:
        lb = 0
    rows, total = store.query_myb_signals(
        trade_date,
        strategy=strategy,
        lookback_years=lb,
        status=status,
        min_score=min_score,
        sector=sector,
        size_tier=size_tier,
        trend=trend,
        min_price=min_price,
        max_price=max_price,
        min_rvol=min_rvol,
        limit=limit,
        offset=offset,
    )
    run = store.get_latest_myb_run(trade_date, strategy=strategy, lookback_years=lb)
    return {
        "trade_date": trade_date,
        "strategy": strategy or (run or {}).get("strategy"),
        "lookback_years": lb if lb is not None else (run or {}).get("lookback_years"),
        "params": (run or {}).get("params") or {},
        "total": total,
        "count": len(rows),
        "offset": offset,
        "limit": limit,
        "scan_alerts_count": (run or {}).get("alerts_count"),
        "results": rows,
    }
