"""API: Grimes market-structure lab (local DB only)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query

from ..db.store import get_store
from ..services.labs.grimes.engine import (
    ENGINE_VERSION,
    get_chart_payload,
    get_or_run_grimes_scan,
    knowledge_payload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/labs/grimes", tags=["labs-grimes"])


@router.get("/knowledge")
async def grimes_knowledge() -> dict[str, Any]:
    return knowledge_payload()


@router.get("/dates")
async def grimes_dates(limit: int = Query(365, ge=1, le=365)) -> dict[str, Any]:
    store = get_store()
    dates = store.list_grimes_dates(limit=limit, engine_version=ENGINE_VERSION)
    latest = store.max_daily_trade_date()
    return {
        "dates": dates,
        "count": len(dates),
        "engine_version": ENGINE_VERSION,
        "latest_data_date": latest,
        "latest_with_scan": dates[0] if dates else None,
    }


@router.get("/summary")
async def grimes_summary(
    trade_date: str | None = Query(None, description="Session date YYYY-MM-DD"),
    refresh: bool = Query(
        False,
        description="Recompute and overwrite the stored scan for the selected date",
    ),
) -> dict[str, Any]:
    try:
        return get_or_run_grimes_scan(trade_date=trade_date, refresh=refresh)
    except Exception as exc:
        logger.exception("Grimes summary failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/chart/{instrument_key:path}")
async def grimes_chart(
    instrument_key: str,
    trade_date: str | None = Query(None, description="Analyze bars through this session date"),
    account_size: float = Query(1_000_000, ge=1_000, le=1e12),
    risk_pct: float = Query(0.01, ge=0.001, le=0.05),
    n_simulations: int = Query(400, ge=50, le=2000),
) -> dict[str, Any]:
    key = unquote(instrument_key).strip()
    if not key:
        raise HTTPException(status_code=400, detail="instrument_key required")
    try:
        return get_chart_payload(
            key,
            as_of=trade_date,
            account_size=account_size,
            risk_pct=risk_pct,
            n_simulations=n_simulations,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Grimes chart failed for %s", key)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
