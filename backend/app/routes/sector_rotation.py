"""API: institutional sector rotation & thematic scanner."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..cache import get_cached, set_cache
from ..services.sector_rotation import get_sector_constituents, run_sector_rotation_scan

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sector-rotation", tags=["sector-rotation"])


@router.get("")
async def sector_rotation(
    refresh: bool = Query(False, description="Bypass short-lived cache"),
) -> dict[str, Any]:
    cache_key = "sector_rotation:scan:v2"
    if not refresh:
        cached = get_cached(cache_key)
        if cached:
            return cached
    try:
        payload = run_sector_rotation_scan()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Sector rotation scan failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    set_cache(cache_key, payload, 300)
    return payload


@router.get("/constituents")
async def sector_rotation_constituents(
    name: str = Query(..., min_length=1, description="Sector / theme name"),
) -> dict[str, Any]:
    try:
        return get_sector_constituents(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Sector constituents failed for %s", name)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/universe")
async def sector_rotation_universe() -> dict[str, Any]:
    from ..services.sector_rotation.universe import OFFICIAL_INDICES, SYNTHETIC_THEMES

    return {
        "benchmark": "Nifty 50",
        "official": [
            {"name": i.name, "key": i.instrument_key, "tickers": list(i.tickers)}
            for i in OFFICIAL_INDICES
        ],
        "synthetic": [{"name": i.name, "tickers": list(i.tickers)} for i in SYNTHETIC_THEMES],
    }
