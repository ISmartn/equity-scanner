from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..services import nifty_candles

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/nifty", tags=["nifty"])


class NiftySyncRequest(BaseModel):
    timeframes: list[str] | None = Field(
        default=None,
        description="Subset of 1m,3m,5m,10m,daily (default: all)",
    )
    from_date: str | None = Field(default=None, description="YYYY-MM-DD")
    to_date: str | None = Field(default=None, description="YYYY-MM-DD")


def _parse_date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field}; use YYYY-MM-DD") from exc


@router.get("/status")
async def nifty_status() -> dict[str, Any]:
    return nifty_candles.nifty_status()


@router.get("/candles")
async def get_nifty_candles(
    timeframe: str = Query("5m", description="1m | 3m | 5m | 10m | daily"),
    from_ts: str | None = Query(None, description="Inclusive lower bound (ISO or YYYY-MM-DD)"),
    to_ts: str | None = Query(None, description="Inclusive upper bound (ISO or YYYY-MM-DD)"),
    limit: int | None = Query(5000, ge=1, le=50000),
) -> dict[str, Any]:
    try:
        return nifty_candles.nifty_candles(
            timeframe,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sync")
async def sync_nifty(
    body: NiftySyncRequest | None = None,
    x_upstox_access_token: str | None = Header(default=None),
) -> dict[str, Any]:
    payload = body or NiftySyncRequest()
    try:
        return await nifty_candles.sync_nifty(
            timeframes=payload.timeframes,
            access_token=x_upstox_access_token,
            from_date=_parse_date(payload.from_date, "from_date"),
            to_date=_parse_date(payload.to_date, "to_date"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Nifty sync failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
