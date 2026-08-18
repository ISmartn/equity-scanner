from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..services import indicator_analysis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/indicator-analysis", tags=["indicator-analysis"])


@router.get("/catalog")
async def catalog() -> dict[str, Any]:
    return {
        "source": "kyalashish_own_400 indicator mention ranking",
        "indicators": indicator_analysis.INDICATOR_CATALOG,
    }


@router.get("")
async def analyze(
    symbol: str = Query("NIFTY", description="NIFTY or equity ticker (e.g. RELIANCE)"),
    timeframe: str = Query("daily", description="For NIFTY: 1m|3m|5m|10m|daily; stocks always daily"),
    limit: int = Query(300, ge=50, le=2000),
    rsi_period: int = Query(14, ge=2, le=100),
) -> dict[str, Any]:
    try:
        return indicator_analysis.analyze_symbol(
            symbol,
            timeframe=timeframe,
            limit=limit,
            rsi_period=rsi_period,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Indicator analysis failed for %s", symbol)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
