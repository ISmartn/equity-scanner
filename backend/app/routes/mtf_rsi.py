from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.mtf_rsi_manager import get_mtf_rsi_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mtf-rsi", tags=["mtf-rsi"])


class StreamStartRequest(BaseModel):
    rsi_period: int = Field(14, ge=1, le=200)
    force_refresh: bool = False


class RsiPeriodRequest(BaseModel):
    rsi_period: int = Field(..., ge=1, le=200)


@router.get("/status")
async def mtf_rsi_status() -> dict[str, Any]:
    return get_mtf_rsi_manager().status()


@router.get("/snapshot")
async def mtf_rsi_snapshot() -> dict[str, Any]:
    return get_mtf_rsi_manager().snapshot()


@router.get("/chart")
async def mtf_rsi_chart(
    timeframe: int | None = Query(None, description="Optional single TF minutes filter"),
) -> dict[str, Any]:
    return get_mtf_rsi_manager().chart(timeframe)


@router.post("/seed")
async def mtf_rsi_seed(
    body: StreamStartRequest | None = None,
    x_upstox_access_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Seed historical buffers without WebSocket (useful when market is closed)."""
    payload = body or StreamStartRequest()
    try:
        return get_mtf_rsi_manager().seed_only(
            x_upstox_access_token,
            rsi_period=payload.rsi_period,
            force_refresh=payload.force_refresh,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("MTF RSI seed failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/stream/start")
async def mtf_rsi_stream_start(
    body: StreamStartRequest | None = None,
    x_upstox_access_token: str | None = Header(default=None),
) -> dict[str, Any]:
    payload = body or StreamStartRequest()
    try:
        return get_mtf_rsi_manager().start(
            x_upstox_access_token,
            rsi_period=payload.rsi_period,
            force_refresh=payload.force_refresh,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("MTF RSI stream start failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/stream/stop")
async def mtf_rsi_stream_stop() -> dict[str, Any]:
    return get_mtf_rsi_manager().stop()


@router.post("/rsi-period")
async def mtf_rsi_set_period(body: RsiPeriodRequest) -> dict[str, Any]:
    try:
        return get_mtf_rsi_manager().set_rsi_period(body.rsi_period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/config")
async def mtf_rsi_config(
    rsi_period: int = Query(14, ge=1, le=200),
) -> dict[str, Any]:
    mgr = get_mtf_rsi_manager()
    status = mgr.status()
    return {
        "default_rsi_period": rsi_period,
        "active_rsi_period": status["rsi_period"],
        "timeframes": status["timeframes"],
        "instrument_key": status["instrument_key"],
        "instrument_label": status["instrument_label"],
        "market": status.get("market"),
        "mode_note": status.get("mode_note"),
    }
