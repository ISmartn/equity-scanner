"""API: Experimental Elliott Wave Lab (local DB only)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query

from ..cache import get_cached, set_cache
from ..services.labs.elliott_wave import get_chart_payload, run_elliott_wave_scan

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/labs/elliott-wave", tags=["labs-elliott-wave"])


@router.get("/summary")
async def elliott_wave_summary(
    refresh: bool = Query(False, description="Bypass short-lived cache"),
) -> dict[str, Any]:
    cache_key = "labs:elliott_wave:summary:v2"
    if not refresh:
        cached = get_cached(cache_key)
        if cached:
            return cached
    try:
        payload = run_elliott_wave_scan()
    except Exception as exc:
        logger.exception("Elliott wave summary failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    set_cache(cache_key, payload, 300)
    return payload


@router.get("/chart/{instrument_key:path}")
async def elliott_wave_chart(instrument_key: str) -> dict[str, Any]:
    key = unquote(instrument_key).strip()
    if not key:
        raise HTTPException(status_code=400, detail="instrument_key required")
    try:
        return get_chart_payload(key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Elliott wave chart failed for %s", key)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
