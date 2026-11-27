"""API: Order Flow, the standalone board's contract served from the lab's Upstox feed.

Routes (the same shapes the Order Flow page reads):

  GET /api/order-flow/status                     provider, clock, last build
  GET /api/order-flow/market                     the market file (every underlying's nearest-expiry chain)
  GET /api/order-flow/market/{date}/{HHMM}       an earlier minute of today (15m / 1h windows)
  GET /api/order-flow/futures/{symbol}?session=  the near-month future and its 1-minute candles

The trigger log, kept for backtests (see services/order_flow/signal_log.py):

  POST /api/order-flow/signals                    record or update the board's buy / sell / stale triggers
  PUT  /api/order-flow/signals/{date}/candles/{symbol}  the 1-minute candles of an underlying that triggered
  GET  /api/order-flow/signals/dates              sessions with a log, newest first
  GET  /api/order-flow/signals/{date}?candles=1   one session's triggers (and their candles)
"""

from __future__ import annotations

import logging
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from ..services.order_flow import get_collector
from ..services.order_flow.session import latest_trading_session_date
from ..services.order_flow.signal_log import get_signal_log, valid_date, valid_symbol

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


class SignalRecord(BaseModel):
    """One trigger as the board raised it; the reading that raised it rides along in ``context``."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1, max_length=80)
    symbol: str = Field(pattern=r"^[A-Za-z0-9&._-]{1,40}$")
    kind: Literal["buy", "sell"]
    state: Literal["active", "stale"]
    outcome: Literal["target", "stop", "side", "zone", "replaced", "aged"] | None = None
    decision: Literal["closed", "continued", "missed"] | None = None
    triggeredAt: float
    entryLow: float
    entryHigh: float
    stop: float


class SignalBatch(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    signals: list[SignalRecord] = Field(max_length=500)


class CandleBatch(BaseModel):
    """[epoch_ms, close, open interest] per minute."""

    candles: list[Annotated[list[float], Field(min_length=3, max_length=3)]] = Field(max_length=2000)


@router.post("/signals")
async def record_signals(batch: SignalBatch) -> dict[str, int]:
    return get_signal_log().upsert(batch.date, [row.model_dump() for row in batch.signals])


@router.put("/signals/{date}/candles/{symbol}")
async def record_candles(date: str, symbol: str, batch: CandleBatch) -> dict[str, int]:
    if not valid_date(date) or not valid_symbol(symbol):
        raise HTTPException(status_code=400, detail="Bad request.")
    get_signal_log().put_candles(date, symbol.upper(), batch.candles)
    return {"candles": len(batch.candles)}


@router.get("/signals/dates")
async def signal_dates() -> list[dict[str, Any]]:
    return get_signal_log().dates()


@router.get("/signals/{date}")
async def signals_for(date: str, candles: bool = Query(False)) -> dict[str, Any]:
    if not valid_date(date):
        raise HTTPException(status_code=400, detail="Bad request.")
    return get_signal_log().read(date, with_candles=candles)


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
