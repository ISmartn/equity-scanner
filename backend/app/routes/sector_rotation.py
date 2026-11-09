"""API: institutional sector rotation & thematic scanner."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from zoneinfo import ZoneInfo

from ..cache import get_cached, set_cache
from ..db.store import get_store
from ..services import nifty_candles
from ..services.sector_rotation import get_sector_constituents, run_sector_rotation_scan
from ..services.sector_rotation.universe import BENCHMARK_KEY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sector-rotation", tags=["sector-rotation"])

IST = ZoneInfo("Asia/Kolkata")

# Re-pull a few sessions before the last stored bar so late corrections land.
BENCHMARK_SYNC_OVERLAP_DAYS = 5


def _benchmark_last_daily() -> date | None:
    for row in get_store().index_candle_stats(BENCHMARK_KEY, timeframe="daily"):
        raw = row.get("max_ts")
        if raw:
            return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    return None


async def _sync_benchmark(access_token: str | None) -> dict[str, Any]:
    """Top up Nifty 50 daily index candles so RRG can reach the latest bar.

    Never raises: a failed sync should still return the recomputed scan.
    """
    last = _benchmark_last_daily()
    today = datetime.now(tz=IST).date()
    if last is not None and last >= today:
        return {"status": "current", "as_of": last.isoformat(), "upserted": 0}

    from_date = (last - timedelta(days=BENCHMARK_SYNC_OVERLAP_DAYS)) if last else None
    try:
        result = await nifty_candles.sync_nifty(
            timeframes=["daily"],
            access_token=access_token,
            from_date=from_date,
            to_date=today,
        )
    except RuntimeError as exc:
        # Missing/invalid Upstox token — surface it without failing the page.
        return {"status": "unauthorized", "detail": str(exc), "upserted": 0}
    except Exception as exc:
        logger.warning("Benchmark index sync failed: %s", exc)
        return {"status": "failed", "detail": str(exc), "upserted": 0}

    return {
        "status": "ok",
        "upserted": int(result.get("total_upserted") or 0),
        "as_of": (_benchmark_last_daily() or last or today).isoformat(),
    }


@router.get("")
async def sector_rotation(
    refresh: bool = Query(False, description="Sync benchmark candles and recompute"),
    x_upstox_access_token: str | None = Header(default=None),
) -> dict[str, Any]:
    cache_key = "sector_rotation:scan:v3"
    if not refresh:
        cached = get_cached(cache_key)
        if cached:
            return cached

    benchmark_sync = await _sync_benchmark(x_upstox_access_token) if refresh else None

    try:
        payload = run_sector_rotation_scan()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Sector rotation scan failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    set_cache(cache_key, payload, 300)
    if benchmark_sync is not None:
        payload = {**payload, "benchmark_sync": benchmark_sync}
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
