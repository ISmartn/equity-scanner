from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..cache import delete_cache_prefix, get_cached, set_cache
from ..db.store import get_store
from ..services import market_info_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market-info", tags=["market-info"])


class SyncMarketInfoRequest(BaseModel):
    trade_date: str | None = None
    expiry: str | None = None
    symbols: list[str] | None = Field(None, max_length=20)
    flows: bool = True
    derivatives: bool = True
    flow_interval: str = Field("1D", pattern="^(1D|1M)$")
    include_indices: bool = True
    include_stocks: bool = True
    stock_limit: int = Field(5, ge=0, le=20)


@router.get("/flows")
async def get_institutional_flows(
    flow_type: str | None = Query(None, pattern="^(FII|DII)$"),
    data_type: str | None = Query(None),
    interval: str = Query("1D", pattern="^(1D|1M)$"),
    limit: int = Query(90, ge=1, le=500),
) -> dict[str, Any]:
    cache_key = f"market-info:flows:{flow_type}:{data_type}:{interval}:{limit}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    rows = get_store().list_institutional_flows(
        flow_type=flow_type,
        data_type=data_type,
        interval_code=interval,
        limit=limit,
    )
    payload = {"interval": interval, "count": len(rows), "results": rows}
    set_cache(cache_key, payload, 300)
    return payload


@router.get("/derivatives")
async def list_derivative_snapshots(
    trade_date: date | None = Query(None),
    symbol: str | None = Query(None, max_length=32),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    trade_iso = trade_date.isoformat() if trade_date else None
    cache_key = f"market-info:derivatives:{trade_iso}:{symbol}:{limit}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    rows = get_store().list_derivative_snapshots(
        trade_date=trade_iso,
        symbol=symbol,
        limit=limit,
    )
    payload = {"trade_date": trade_iso, "count": len(rows), "results": rows}
    set_cache(cache_key, payload, 300)
    return payload


@router.get("/derivatives/detail")
async def get_derivative_snapshot(
    symbol: str = Query(..., min_length=1, max_length=32),
    trade_date: date = Query(...),
    expiry: str | None = Query(None),
    fetch_if_missing: bool = Query(False),
    x_upstox_access_token: str | None = Header(default=None),
) -> dict[str, Any]:
    symbol_norm = symbol.strip().upper()
    trade_iso = trade_date.isoformat()
    cache_key = f"market-info:derivative:{symbol_norm}:{trade_iso}:{expiry}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    row = get_store().get_derivative_snapshot(symbol_norm, trade_iso, expiry=expiry)
    if row:
        set_cache(cache_key, row, 600)
        return row

    if not fetch_if_missing:
        raise HTTPException(
            status_code=404,
            detail=f"No derivative snapshot for {symbol_norm} on {trade_iso}. Run market-info sync.",
        )

    watchlist = market_info_sync.resolve_derivative_watchlist(symbols=[symbol_norm])
    if not watchlist:
        raise HTTPException(status_code=404, detail=f"Unknown underlying {symbol_norm}")

    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            row = await market_info_sync.sync_derivative_snapshot_for_underlying(
                session,
                x_upstox_access_token,
                watchlist[0],
                trade_date,
                expiry=expiry,
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    set_cache(cache_key, row, 600)
    return row


@router.post("/sync")
async def sync_market_info_endpoint(
    body: SyncMarketInfoRequest,
    x_upstox_access_token: str | None = Header(default=None),
) -> dict[str, Any]:
    trade_date = date.fromisoformat(body.trade_date) if body.trade_date else None
    try:
        result = await market_info_sync.sync_market_info(
            x_upstox_access_token,
            trade_date=trade_date,
            expiry=body.expiry,
            symbols=body.symbols,
            flows=body.flows,
            derivatives=body.derivatives,
            flow_interval=body.flow_interval,
            include_indices=body.include_indices,
            include_stocks=body.include_stocks,
            stock_limit=body.stock_limit,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Market info sync failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    delete_cache_prefix("market-info:")
    return result


@router.get("/watchlist")
async def default_watchlist() -> dict[str, Any]:
    indices = market_info_sync.DEFAULT_INDEX_WATCHLIST
    stocks = list(market_info_sync.DEFAULT_STOCK_FO_WATCHLIST)
    return {
        "indices": indices,
        "default_stocks": stocks,
        "fii_segments": list(market_info_sync.FII_DATA_TYPES),
        "dii_segments": list(market_info_sync.DII_DATA_TYPES),
    }
