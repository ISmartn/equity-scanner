"""News desk routes: stored RSS stories and extractive blurbs."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..cache import delete_cache_prefix, get_cached, set_cache
from ..config import normalize_symbol
from ..db.store import get_store
from ..services.newsdesk.service import build_board, refresh_feeds, summary_for_link

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/newsdesk", tags=["newsdesk"])
CACHE_TTL_SEC = 60


@router.get("")
async def newsdesk(
    days: int = Query(3, ge=1, le=30),
    limit: int = Query(120, ge=1, le=400),
    refresh: bool = Query(False),
) -> dict[str, Any]:
    cache_key = f"newsdesk:board:{days}:{limit}"
    if refresh:
        try:
            await refresh_feeds(get_store())
        except Exception as exc:
            logger.exception("Newsdesk refresh failed")
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        delete_cache_prefix("newsdesk:board:")
    else:
        cached = get_cached(cache_key)
        if cached:
            return cached
    payload = build_board(get_store(), days=days, limit=limit)
    set_cache(cache_key, payload, CACHE_TTL_SEC)
    return payload


@router.get("/summary")
async def newsdesk_summary(link: str = Query(..., min_length=8, max_length=2000)) -> dict[str, Any]:
    payload = summary_for_link(get_store(), link)
    if payload is None:
        raise HTTPException(status_code=404, detail="Article is not in the desk archive")
    return payload


@router.get("/companies")
async def newsdesk_companies(symbol: str = Query(..., min_length=1, max_length=32)) -> dict[str, Any]:
    ticker = normalize_symbol(symbol)
    board = build_board(get_store(), days=30, limit=400)
    stories = [story for story in board["stories"] if ticker in story["companies"]]
    return {"symbol": ticker, "count": len(stories), "stories": stories[:40]}
