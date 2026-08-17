from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import normalize_symbol
from ..db.store import get_store
from ..services.news.config import telegram_channels
from ..services.news.event_study import aggregate_ticker_impact, compute_and_store_reactions, event_session_date
from ..services.news.extract import process_unprocessed_messages
from ..services.news.gemini_client import (
    build_outlook,
    classify_company_news_sentiment,
    gemini_enabled,
)
from ..services.news.ingest import sync_configured_channels
from ..services.news.live_manager import get_live_manager
from ..services.news.monitors import monitor_topics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])

_sync_status: dict[str, Any] = {
    "running": False,
    "mode": None,
    "last_result": None,
    "error": None,
}


class SyncRequest(BaseModel):
    backfill: bool = False
    limit: int | None = Field(500, ge=1, le=5000)
    process: bool = True


class PatchEventRequest(BaseModel):
    ticker: str | None = None
    status: Literal["linked", "dismissed", "unmatched", "skipped"] | None = None
    sentiment: Literal["bullish", "bearish", "neutral", "unknown"] | None = None
    company_name_matched: str | None = None


class ClassifySentimentRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)


def _horizon_sort_key(horizon: str) -> tuple[int, str]:
    order = {"t_m2": 0, "t_m1": 1, "t0": 2, "t1": 3, "t2": 4, "t3": 5, "t4": 6, "t5": 7}
    return (order.get(horizon, 99), horizon)


def _attach_reactions(event: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    reactions = store.get_news_reactions(int(event["id"]))
    reactions.sort(key=lambda r: _horizon_sort_key(r["horizon"]))
    event = dict(event)
    event["reactions"] = reactions
    return event


@router.get("/stats")
async def news_stats() -> dict[str, Any]:
    store = get_store()
    stats = store.news_stats()
    stats["channels"] = telegram_channels()
    stats["gemini_enabled"] = gemini_enabled()
    channel_meta = []
    for key in telegram_channels():
        row = store.get_news_channel(key)
        if row:
            channel_meta.append(row)
    stats["channel_meta"] = channel_meta
    stats["sync"] = {
        "running": _sync_status["running"],
        "mode": _sync_status["mode"],
        "error": _sync_status["error"],
    }
    stats["live"] = get_live_manager().snapshot()
    stats["monitors"] = [
        {"key": t.key, "label": t.label, "keywords": list(t.keywords)} for t in monitor_topics()
    ]
    return stats


class LiveToggleRequest(BaseModel):
    catch_up: bool = True
    process: bool = True


@router.get("/live/status")
async def live_status() -> dict[str, Any]:
    return get_live_manager().snapshot()


@router.post("/live/start")
async def live_start(body: LiveToggleRequest | None = None) -> dict[str, Any]:
    mgr = get_live_manager()
    try:
        opts = body or LiveToggleRequest()
        return await mgr.start(catch_up=opts.catch_up, process=opts.process)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to start live feed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/live/stop")
async def live_stop() -> dict[str, Any]:
    return await get_live_manager().stop()


@router.get("/messages")
async def list_messages(
    channel: str | None = None,
    topic: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """All recent Telegram posts stored in DB (linked or not)."""
    store = get_store()
    rows, total = store.list_telegram_messages(
        channel_key=channel,
        topic=topic,
        limit=limit,
        offset=offset,
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "topic": topic,
        "results": rows,
    }


@router.post("/sync")
async def sync_news(body: SyncRequest) -> dict[str, Any]:
    if _sync_status["running"]:
        raise HTTPException(status_code=409, detail="News sync already running")
    _sync_status["running"] = True
    _sync_status["mode"] = "backfill" if body.backfill else "incremental"
    _sync_status["error"] = None
    try:
        result = await sync_configured_channels(
            backfill=body.backfill,
            backfill_limit=body.limit if body.backfill else None,
            process=body.process,
        )
        _sync_status["last_result"] = result
        return result
    except RuntimeError as exc:
        _sync_status["error"] = str(exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("News sync failed")
        _sync_status["error"] = str(exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        _sync_status["running"] = False


@router.post("/process")
async def process_queue(limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
    return await process_unprocessed_messages(limit=limit, build_reactions=True)


@router.post("/classify-sentiment")
async def classify_sentiment(body: ClassifySentimentRequest) -> dict[str, Any]:
    """7-tier company news sentiment: Good…Bad (Gemini or heuristic)."""
    return await classify_company_news_sentiment(body.text)


@router.post("/reactions/rebuild")
async def rebuild_reactions(limit: int = Query(500, ge=1, le=5000)) -> dict[str, Any]:
    return compute_and_store_reactions(limit=limit)


@router.get("/events")
async def list_events(
    ticker: str | None = None,
    sentiment: str | None = None,
    status: str | None = "linked",
    from_date: str | None = None,
    to_date: str | None = None,
    channel: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    store = get_store()
    rows, total = store.list_news_events(
        ticker=normalize_symbol(ticker) if ticker else None,
        sentiment=sentiment,
        status=status,
        from_date=from_date,
        to_date=to_date,
        channel_key=channel,
        limit=limit,
        offset=offset,
    )
    events = [_attach_reactions(r) for r in rows]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": events,
    }


@router.get("/events/{event_id}")
async def get_event(event_id: int) -> dict[str, Any]:
    store = get_store()
    event = store.get_news_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return _attach_reactions(event)


@router.patch("/events/{event_id}")
async def patch_event(event_id: int, body: PatchEventRequest) -> dict[str, Any]:
    store = get_store()
    event = store.get_news_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    fields: dict[str, Any] = {}
    if body.ticker is not None:
        ticker = normalize_symbol(body.ticker)
        profile = store.get_profile_by_ticker(ticker)
        if not profile:
            raise HTTPException(status_code=400, detail=f"Unknown ticker {ticker}")
        fields["ticker"] = ticker
        fields["company_name_matched"] = body.company_name_matched or profile.get("company_name")
        fields["match_confidence"] = 100.0
        fields["status"] = "linked"
        if not event.get("event_date") and event.get("posted_at"):
            fields["event_date"] = event_session_date(event["posted_at"])
    if body.status is not None:
        fields["status"] = body.status
    if body.sentiment is not None:
        fields["sentiment"] = body.sentiment
    if body.company_name_matched is not None and "company_name_matched" not in fields:
        fields["company_name_matched"] = body.company_name_matched

    updated = store.update_news_event(event_id, **fields)
    if updated and updated.get("status") == "linked" and updated.get("ticker"):
        compute_and_store_reactions(store, event_ids=[event_id])
    return _attach_reactions(store.get_news_event(event_id) or updated or {})


@router.post("/events/{event_id}/outlook")
async def event_outlook(event_id: int) -> dict[str, Any]:
    if not gemini_enabled():
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY is not set")
    store = get_store()
    event = store.get_news_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    similar = store.list_similar_news_events(
        ticker=event.get("ticker"),
        themes=event.get("themes") or [],
        exclude_event_id=event_id,
        limit=10,
    )
    try:
        outlook = await build_outlook(
            message_text=event.get("message_text") or "",
            ticker=event.get("ticker"),
            sentiment=event.get("sentiment"),
            themes=event.get("themes") or [],
            similar_events=similar,
        )
    except Exception as exc:
        logger.exception("Outlook failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    store.update_news_event(event_id, outlook_json=outlook)
    updated = store.get_news_event(event_id)
    return _attach_reactions(updated or event)


@router.get("/ticker/{ticker}/impact")
async def ticker_impact(
    ticker: str,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    store = get_store()
    symbol = normalize_symbol(ticker)
    rows, total = store.list_news_events(ticker=symbol, status="linked", limit=limit, offset=0)
    events = [_attach_reactions(r) for r in rows]
    aggregates = aggregate_ticker_impact(events)
    markers = [
        {
            "event_id": e["id"],
            "date": e.get("event_date"),
            "sentiment": e.get("sentiment"),
            "summary": e.get("summary"),
            "t1": next((r.get("return_pct") for r in e["reactions"] if r["horizon"] == "t1"), None),
            "t3": next((r.get("return_pct") for r in e["reactions"] if r["horizon"] == "t3"), None),
        }
        for e in events
        if e.get("event_date")
    ]
    profile = store.get_profile_by_ticker(symbol)
    return {
        "ticker": symbol,
        "company_name": profile.get("company_name") if profile else None,
        "total": total,
        "events": events,
        "aggregates": aggregates,
        "markers": markers,
    }
