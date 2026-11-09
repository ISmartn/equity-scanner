from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response

from ..db.store import get_store
from ..services.live_scan.backtest import (
    BacktestParams,
    cached_backtest,
    journal_scorecard,
    last_completed_session,
)
from ..services.live_scan.hub import LiveScanConflict, get_live_scan_hub

logger = logging.getLogger(__name__)

_DEFAULTS = BacktestParams(start="2000-01-01", end="2000-01-01")

router = APIRouter(prefix="/api/live-scan", tags=["live-scan"])


@router.get("/status")
async def live_scan_status() -> dict[str, Any]:
    return get_live_scan_hub().status_payload()


@router.get("/snapshot")
async def live_scan_snapshot(
    board: str = Query("all", description="momentum, breakout, oi, calls, or all"),
    limit: int = Query(50, ge=1, le=500),
    segment: str = Query("fno", description="fno or cash"),
) -> Response:
    # Pre-encoded bytes: skips jsonable_encoder walking four boards on the event loop.
    try:
        body = get_live_scan_hub().snapshot_json(board, limit, segment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=body, media_type="application/json")


@router.post("/start")
async def live_scan_start(
    x_upstox_access_token: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        return await get_live_scan_hub().start(x_upstox_access_token)
    except LiveScanConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        message = str(exc)
        status = 401 if "access token" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message) from exc
    except Exception as exc:
        logger.exception("Live scan start failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/stop")
async def live_scan_stop() -> dict[str, Any]:
    return await asyncio.to_thread(get_live_scan_hub().stop)


@router.get("/backtest")
async def live_scan_backtest(
    start: str | None = Query(None, description="YYYY-MM-DD, default one year before end"),
    end: str | None = Query(None, description="YYYY-MM-DD, default the last completed session"),
    segment: str = Query("all", description="fno, cash, or all"),
    side: str = Query("both", description="buy, sell, or both"),
    reward_r: float = Query(_DEFAULTS.reward_r),
    swing_r: float = Query(_DEFAULTS.swing_r),
    entry_window_r: float = Query(_DEFAULTS.entry_window_r),
    min_efficiency: float = Query(_DEFAULTS.min_efficiency),
    risk_min_atr: float = Query(_DEFAULTS.risk_min_atr),
    risk_max_atr: float = Query(_DEFAULTS.risk_max_atr),
    max_swing_days: int = Query(_DEFAULTS.max_swing_days),
    cost_pct: float = Query(_DEFAULTS.cost_pct, description="Round-trip cost, percent of the fill"),
    trades_limit: int = Query(200, ge=0, le=500),
) -> dict[str, Any]:
    """Replay the Session Call rules on daily candles. Cached for ten minutes per parameter set."""
    end_date = end or last_completed_session()
    try:
        start_date = start or (date.fromisoformat(end_date) - timedelta(days=365)).isoformat()
        params = BacktestParams(
            start=start_date,
            end=end_date,
            segment=segment,
            side=side,
            reward_r=reward_r,
            swing_r=swing_r,
            entry_window_r=entry_window_r,
            min_efficiency=min_efficiency,
            risk_min_atr=risk_min_atr,
            risk_max_atr=risk_max_atr,
            max_swing_days=max_swing_days,
            cost_pct=cost_pct,
        ).checked()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await asyncio.to_thread(cached_backtest, params, trades_limit=trades_limit)


@router.get("/journal-stats")
async def live_scan_journal_stats(
    start: str | None = Query(None),
    end: str | None = Query(None),
    segment: str = Query("all", description="fno, cash, or all"),
    cost_pct: float = Query(_DEFAULTS.cost_pct),
) -> dict[str, Any]:
    """Score every saved live plan across sessions, in R after costs."""
    if segment not in {"fno", "cash", "all"}:
        raise HTTPException(status_code=400, detail="segment must be fno, cash, or all")
    rows = await asyncio.to_thread(get_store().list_live_call_journal_range, start, end)
    return journal_scorecard(rows, cost_pct=cost_pct, segment=segment)
