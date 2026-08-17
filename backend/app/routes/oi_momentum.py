from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.oi_momentum.alert_log import ALERT_LOG_PATH, read_alert_records
from ..services.oi_momentum.service import (
    API_MIN_WINDOW_SEC,
    DEFAULT_SYMBOLS,
    DEFAULT_WINDOW_SEC,
    MAX_WINDOW_SEC,
    evaluate_momentum,
)
from ..services.oi_momentum.ws_feed import get_stream_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/oi-momentum", tags=["oi-momentum"])


class StreamStartRequest(BaseModel):
    symbol: str = Field("NIFTY", min_length=1, max_length=32)


@router.get("/symbols")
async def list_symbols() -> dict[str, Any]:
    return {
        "default_symbols": list(DEFAULT_SYMBOLS),
        "description": "Index underlyings supported out of the box; F&O stocks need security_profiles.",
    }


@router.get("/stream/status")
async def stream_status(
    symbol: str | None = Query(None, max_length=32),
) -> dict[str, Any]:
    return get_stream_manager().status(symbol)


@router.post("/stream/start")
async def stream_start(
    body: StreamStartRequest,
    x_upstox_access_token: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        return await get_stream_manager().start(x_upstox_access_token, body.symbol)
    except RuntimeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("OI stream start failed for %s", body.symbol)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/stream/stop")
async def stream_stop(
    symbol: str = Query("NIFTY", min_length=1, max_length=32),
) -> dict[str, Any]:
    return get_stream_manager().stop(symbol)


@router.get("/alerts")
async def list_oi_momentum_alerts(
    symbol: str | None = Query(None, max_length=32),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    records = read_alert_records(symbol=symbol, limit=limit)
    return {"count": len(records), "records": records}


@router.get("/alerts/export")
async def export_oi_momentum_alerts(
    symbol: str | None = Query(None, max_length=32),
    limit: int = Query(500, ge=1, le=500),
) -> dict[str, Any]:
    records = read_alert_records(symbol=symbol, limit=limit)
    return {
        "path": str(ALERT_LOG_PATH),
        "count": len(records),
        "records": records,
    }


@router.get("/evaluate")
async def evaluate_oi_momentum(
    symbol: str = Query("NIFTY", min_length=1, max_length=32),
    window_sec: int = Query(DEFAULT_WINDOW_SEC, ge=API_MIN_WINDOW_SEC, le=MAX_WINDOW_SEC),
    expiry: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    source: str = Query("auto", pattern="^(auto|rest|websocket)$"),
    x_upstox_access_token: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        return await evaluate_momentum(
            x_upstox_access_token,
            symbol,
            window_sec=window_sec,
            expiry=expiry,
            source=source,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("OI momentum evaluation failed for %s", symbol)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
