from __future__ import annotations

import logging

import numpy as np
import aiohttp
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from ..services import forecast_registry, market_data, nse_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["forecast"])


class ForecastResponse(BaseModel):
    symbol: str
    interval: str
    source: str
    model: str
    model_label: str
    horizon: int
    device: str
    context_length: int
    lookback_years: int
    history_bars: int
    history: list[dict]
    forecast_dates: list[str]
    median: list[float]
    lower: list[float]
    upper: list[float]
    latest_close: float
    spread_pct: float


@router.get("/health")
async def health() -> dict:
    from ..db.store import get_store

    stats = get_store().stats()
    return {
        "status": "ok",
        "timeline": {
            "profile_count": stats["profile_count"],
            "symbols_with_data": stats["symbols_with_data"],
            "candle_count": stats["candle_count"],
            "max_trade_date": stats["max_trade_date"],
            "target_trade_date": stats["target_trade_date"],
            "is_up_to_date": stats["is_up_to_date"],
        },
    }


@router.get("/models")
async def models() -> dict:
    return {"models": forecast_registry.list_models()}


@router.get("/nifty50")
async def nifty50() -> dict:
    async with aiohttp.ClientSession() as session:
        symbols = await nse_client.fetch_nifty50_symbols(session)
    return {"symbols": symbols, "count": len(symbols)}


@router.get("/fno")
async def fno() -> dict:
    async with aiohttp.ClientSession() as session:
        try:
            symbols = await nse_client.fetch_fno_symbols(session)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"symbols": symbols, "count": len(symbols)}


@router.get("/symbols/search")
async def symbols_search(
    q: str = Query(..., min_length=1, max_length=64),
    limit: int = Query(15, ge=1, le=50),
) -> dict:
    async with aiohttp.ClientSession() as session:
        try:
            results = await nse_client.search_equity_symbols(session, q, limit)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"query": q, "results": results, "count": len(results)}


class CandlesResponse(BaseModel):
    symbol: str
    interval: str
    source: str
    lookback_years: int
    history_bars: int
    history: list[dict]
    latest_close: float


@router.get("/candles", response_model=CandlesResponse)
async def candles(
    symbol: str = Query(..., min_length=1),
    interval: market_data.Interval = Query("daily"),
    x_upstox_access_token: str | None = Header(default=None),
) -> CandlesResponse:
    async with aiohttp.ClientSession() as session:
        try:
            raw_candles, source = await market_data.fetch_candles(
                session,
                symbol,
                interval,
                x_upstox_access_token,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    history = market_data.annotate_pct_changes(raw_candles)
    latest_close = float(history[-1]["close"])

    return CandlesResponse(
        symbol=symbol.upper(),
        interval=interval,
        source=source,
        lookback_years=market_data.LOOKBACK_YEARS,
        history_bars=len(history),
        history=history,
        latest_close=latest_close,
    )


@router.get("/forecast", response_model=ForecastResponse)
async def forecast(
    symbol: str = Query(..., min_length=1),
    interval: market_data.Interval = Query("daily"),
    model: str | None = Query(None, description="timesfm-2.5 or timesfm-fin"),
    horizon: int | None = Query(None, ge=5, le=128),
    context_length: int | None = Query(None, ge=32, le=1024),
    x_upstox_access_token: str | None = Header(default=None),
) -> ForecastResponse:
    try:
        forecast_model = forecast_registry.normalize_model(model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    forecast_horizon = horizon or market_data.default_horizon(interval)
    if forecast_model == "timesfm-fin":
        forecast_horizon = min(forecast_horizon, 128)

    logger.info(
        "Forecast request: symbol=%s interval=%s model=%s horizon=%d",
        symbol,
        interval,
        forecast_model,
        forecast_horizon,
    )

    async with aiohttp.ClientSession() as session:
        try:
            candles, source = await market_data.fetch_candles(
                session,
                symbol,
                interval,
                x_upstox_access_token,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    logger.info("Candles loaded: %d bars from %s", len(candles), source)

    closes = [float(item["close"]) for item in candles]

    try:
        logger.info("Running inference with model=%s ...", forecast_model)
        result = await forecast_registry.run_forecast(
            forecast_model,
            closes=np.array(closes),
            horizon=forecast_horizon,
            interval=interval,
            context_length=context_length,
        )
    except Exception as exc:
        logger.exception("Forecast failed for %s model=%s", symbol, forecast_model)
        raise HTTPException(status_code=500, detail=f"Forecast failed: {exc}") from exc

    logger.info(
        "Forecast complete: %s model=%s device=%s spread=%.2f%%",
        symbol,
        result.model,
        result.device,
        (sum(u - l for u, l in zip(result.upper, result.lower)) / len(result.median) / closes[-1] * 100)
        if closes[-1]
        else 0,
    )

    last_date = candles[-1]["date"]
    forecast_dates = _build_forecast_dates(last_date, interval, forecast_horizon)
    latest_close = closes[-1]
    avg_spread = sum(u - l for u, l in zip(result.upper, result.lower)) / len(result.median)
    spread_pct = (avg_spread / latest_close * 100) if latest_close else 0.0

    return ForecastResponse(
        symbol=symbol.upper(),
        interval=interval,
        source=source,
        model=result.model,
        model_label=result.model_label,
        horizon=forecast_horizon,
        device=result.device,
        context_length=result.context_length,
        lookback_years=market_data.LOOKBACK_YEARS,
        history_bars=len(candles),
        history=candles,
        forecast_dates=forecast_dates,
        median=result.median,
        lower=result.lower,
        upper=result.upper,
        latest_close=latest_close,
        spread_pct=round(spread_pct, 2),
    )


def _build_forecast_dates(last_date: str, interval: str, horizon: int) -> list[str]:
    import pandas as pd

    start = pd.Timestamp(last_date)
    freq = {"daily": "B", "weekly": "W-FRI", "monthly": "ME"}[interval]
    dates = pd.date_range(start=start, periods=horizon + 1, freq=freq)[1:]
    return [d.strftime("%Y-%m-%d") for d in dates]
