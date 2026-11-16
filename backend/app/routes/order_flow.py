"""API: Order Flow, the standalone board's contract served from the lab's Upstox feed.

Routes (the same shapes the Order Flow page reads):

  GET /api/order-flow/status                     provider, clock, last build
  GET /api/order-flow/market                     the market file (every underlying's nearest-expiry chain)
  GET /api/order-flow/market/{date}/{HHMM}       an earlier minute of today (15m / 1h windows)
  GET /api/order-flow/futures/{symbol}?session=  the near-month future and its 1-minute candles
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response

from ..services.order_flow import get_collector
from ..services.order_flow.session import latest_trading_session_date

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/order-flow", tags=["order-flow"])

_SYMBOL = re.compile(r"^[A-Za-z0-9&._-]{1,40}$")
_MINUTE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@router.get("/status")
async def status() -> dict[str, Any]:
    return get_collector().status()


@router.get("/market")
async def market() -> Response:
    collector = get_collector()
    if not collector.latest_json:
        message = (collector.last_error or {}).get("message", "The first market file is still being built.")
        return JSONResponse({"error": message}, status_code=503, headers={"Retry-After": "5"})
    return Response(content=collector.latest_json, media_type="application/json")


@router.get("/market/{date}/{hhmm}")
async def market_minute(date: str, hhmm: str) -> FileResponse:
    if not _MINUTE.match(date) or not re.match(r"^\d{4}$", hhmm):
        raise HTTPException(status_code=400, detail="Bad request.")
    path = get_collector().scan_dir / date / f"{hhmm}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No such minute.")
    return FileResponse(path, media_type="application/json")


@router.get("/futures/{symbol}")
async def futures(symbol: str, session: str | None = Query(None)) -> dict[str, Any]:
    collector = get_collector()
    if not _SYMBOL.match(symbol):
        raise HTTPException(status_code=400, detail="Bad request.")
    symbol = symbol.upper()
    if symbol not in collector.by_symbol:
        raise HTTPException(status_code=404, detail="Unknown underlying.")
    current = latest_trading_session_date(collector.now_ms())
    wanted = session or current
    # Only the current session is served: the page never asks for another, and history is not the board's to spend quota on.
    if wanted != current:
        raise HTTPException(status_code=400, detail=f"Only the current session ({current}) is served.")
    try:
        return await collector.futures_for(symbol, wanted)
    except Exception as error:
        logger.error("order flow futures %s failed: %s", symbol, error)
        raise HTTPException(status_code=502, detail="The data provider did not answer for this underlying.") from error
