"""Setup watchlist: stocks still inside a base, before the breakout."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..services.early_setup import breadth, filings, market_data, preopen, repo
from ..services.early_setup.features import FEATURE_LABELS
from ..services.early_setup.filings import CATEGORY_LABELS, get_filings_poller
from ..services.early_setup.live import send_telegram, telegram_configured
from ..services.early_setup.model import load_weights
from ..services.early_setup.report import watchlist_report
from ..services.early_setup.sizing import describe
from ..services.early_setup.watchlist import SPECS, update_watchlist
from ..services.live_scan.clocks import IST
from ..services.live_scan.hub import get_live_scan_hub

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/early-setup", tags=["early-setup"])

_STATUSES = {"active", "triggered", "failed", "expired", "all"}
_LISTS = {"daily", "weekly", "all"}
_FLAG_LABELS = {"asm_long": "Surveillance", "asm_short": "Surveillance", "fo_ban": "F&O ban"}
_build_lock = asyncio.Lock()


def _iso(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{name} must be YYYY-MM-DD") from exc


def _which(value: str) -> str | None:
    if value not in _LISTS:
        raise HTTPException(status_code=400, detail="list must be daily, weekly, or all")
    return None if value == "all" else value


def _model_summary() -> dict[str, Any]:
    weights = load_weights()
    return {
        "fitted": bool(weights.get("fitted")),
        "fitted_at": weights.get("fitted_at"),
        "metrics": weights.get("metrics"),
        "features": [
            {"name": name, "label": FEATURE_LABELS.get(name, name), "weight": round(spec["weight"], 4)}
            for name, spec in weights["features"].items()
        ],
    }


def _filing_row(row: dict[str, Any]) -> dict[str, Any]:
    size = None
    if row.get("size_json"):
        try:
            size = json.loads(row["size_json"])
        except ValueError:
            size = None
    public = {key: value for key, value in row.items() if key != "size_json"}
    return {
        **public,
        "category_label": CATEGORY_LABELS.get(str(row["category"]), "Filing"),
        "size": size,
        "size_text": describe(size),
    }


def _health() -> dict[str, Any] | None:
    latest = repo.latest_health()
    if latest is None:
        return None
    return {**latest, "label": breadth.STATE_LABELS.get(str(latest["state"]), "")}


def _watchlist(status: str, limit: int, timeframe: str | None) -> dict[str, Any]:
    entries = repo.list_entries(status=None if status == "all" else status, limit=limit, timeframe=timeframe)
    rows = [entry.public() for entry in entries]
    now = datetime.now(IST)
    today = now.date()
    tickers = sorted({row["ticker"] for row in rows if row["status"] == "active"})
    # Newest first, so the first one kept per ticker is its latest filing.
    latest: dict[str, dict[str, Any]] = {}
    for filing in repo.list_filings(since=(now - timedelta(hours=24)).isoformat(), tickers=tickers, limit=2000):
        latest.setdefault(filing["ticker"], _filing_row(filing))
    events = repo.upcoming_events(today.isoformat(), (today + timedelta(days=5)).isoformat())
    flags = repo.load_flags()
    buys = repo.one_sided_buys((today - timedelta(days=10)).isoformat())
    auction = repo.load_preopen(today.isoformat())
    for row in rows:
        if row["status"] != "active":
            continue
        ticker = row["ticker"]
        row["filing"] = latest.get(ticker)
        row["event"] = events.get(ticker)
        row["flags"] = [
            {"flag": flag["flag"], "label": _FLAG_LABELS.get(flag["flag"], flag["flag"]), "detail": flag.get("detail")}
            for flag in flags.get(ticker, [])
        ]
        row["large_buy"] = buys[ticker][0] if ticker in buys else None
        row["preopen"] = auction.get((ticker, row["timeframe"]))
    return {
        "status": status,
        "processed_through": repo.get_meta("processed_through"),
        "counts": repo.status_counts(timeframe=timeframe),
        "counts_by_list": {name: repo.status_counts(timeframe=name) for name in SPECS},
        "rows": rows,
        "model": _model_summary(),
        "health": _health(),
    }


def _filings(hours: int, watchlist_only: bool, limit: int) -> dict[str, Any]:
    watching = {entry.ticker for entry in repo.list_entries(status="active", limit=10_000)}
    since = (datetime.now(IST) - timedelta(hours=hours)).isoformat()
    rows = repo.list_filings(since=since, tickers=sorted(watching) if watchlist_only else None, limit=limit)
    return {
        "rows": [{**_filing_row(row), "on_watchlist": row["ticker"] in watching} for row in rows],
        "poller": get_filings_poller().status(),
        "telegram_configured": telegram_configured(),
        "typical_moves": filings.load_impact(),
        "min_cases": filings.MIN_CASES,
    }


@router.get("/filings")
async def early_setup_filings(
    hours: int = Query(24, ge=1, le=240, description="How far back to list"),
    watchlist_only: bool = Query(False),
    limit: int = Query(300, ge=1, le=1000),
) -> dict[str, Any]:
    """Price-moving NSE filings, newest first, read from the exchange as they are published."""
    return await asyncio.to_thread(_filings, hours, watchlist_only, limit)


@router.post("/filings/poll")
async def early_setup_filings_poll() -> dict[str, Any]:
    """Read NSE once now. The background poller does this every minute while it runs."""
    try:
        return await asyncio.to_thread(get_filings_poller().poll_once)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE did not answer: {type(exc).__name__}: {exc}"[:300]) from exc


@router.post("/filings/poller")
async def early_setup_filings_poller(run: bool = Query(..., description="true to start, false to stop")) -> dict[str, Any]:
    poller = get_filings_poller()
    if run:
        poller.start()
    else:
        await asyncio.to_thread(poller.stop)
    return poller.status()


@router.post("/filings/typical-moves")
async def early_setup_filings_typical_moves() -> dict[str, Any]:
    """Re-measure what stocks did after each kind of filing, from the filings and candles on record."""
    return await asyncio.to_thread(filings.rebuild_impact)


@router.get("/watchlist")
async def early_setup_watchlist(
    status: str = Query("active", description="active, triggered, failed, expired, or all"),
    limit: int = Query(250, ge=1, le=1000),
    which: str = Query("all", alias="list", description="daily, weekly, or all"),
) -> dict[str, Any]:
    if status not in _STATUSES:
        raise HTTPException(status_code=400, detail="status must be active, triggered, failed, expired, or all")
    timeframe = _which(which)
    return await asyncio.to_thread(_watchlist, status, limit, timeframe)


@router.post("/build")
async def early_setup_build(
    through: str | None = Query(None, description="YYYY-MM-DD, default the latest candle date"),
    from_date: str | None = Query(None, description="Replay from this date (with rebuild)"),
    rebuild: bool = Query(False, description="Clear the list and replay from from_date"),
    refresh: bool = Query(True, description="First top up delivery, deals, flags and corporate actions from NSE"),
) -> dict[str, Any]:
    through = _iso(through, "through")
    from_date = _iso(from_date, "from_date")
    if rebuild and not from_date:
        raise HTTPException(status_code=400, detail="rebuild needs from_date")
    if _build_lock.locked():
        raise HTTPException(status_code=409, detail="A watchlist build is already running")
    async with _build_lock:
        try:
            result = await asyncio.to_thread(
                update_watchlist, through=through, from_date=from_date, rebuild=rebuild, refresh_data=refresh
            )
        except Exception as exc:
            logger.exception("Setup watchlist build failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if result.get("status") == "updated":
            # Fresh candles change what followed recent filings, so re-measure the typical moves.
            try:
                await asyncio.to_thread(filings.rebuild_impact)
            except Exception:
                logger.exception("Typical filing moves were not re-measured")
        return result


@router.post("/market-data")
async def early_setup_market_data() -> dict[str, Any]:
    """Top up delivery, large deals, surveillance flags, corporate actions and industries from NSE."""
    return await asyncio.to_thread(market_data.refresh)


@router.get("/live")
async def early_setup_live() -> dict[str, Any]:
    """Watchlist names on the live feed. Empty rows when the live scan is not running."""
    return get_live_scan_hub().setup_watch()


@router.get("/preopen")
async def early_setup_preopen() -> dict[str, Any]:
    """Today's opening-auction reading for watchlist stocks. Empty until 9:08 on a trading day."""
    today = datetime.now(IST).date().isoformat()
    rows = await asyncio.to_thread(repo.load_preopen, today)
    return {"session_date": today, "rows": list(rows.values()), "labels": preopen.LABELS}


@router.post("/preopen")
async def early_setup_preopen_run() -> dict[str, Any]:
    """Read the opening auction now. It is used only if NSE's reading is from today's auction."""
    try:
        return await asyncio.to_thread(preopen.run)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE did not answer: {type(exc).__name__}: {exc}"[:300]) from exc


@router.get("/alerts")
async def early_setup_alerts(
    session_date: str | None = Query(None, description="YYYY-MM-DD, default all sessions"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    session_date = _iso(session_date, "session_date")
    rows = await asyncio.to_thread(lambda: repo.list_alerts(session_date=session_date, limit=limit))
    return {"rows": rows, "telegram_configured": telegram_configured()}


@router.post("/alerts/test")
async def early_setup_alert_test() -> dict[str, Any]:
    """Send one test message to the configured Telegram chat."""
    if not telegram_configured():
        raise HTTPException(
            status_code=400,
            detail="Set TELEGRAM_BOT_TOKEN and TELEGRAM_ALERT_CHAT_ID in .env, then restart the backend",
        )
    delivered = await asyncio.to_thread(send_telegram, "Equity Scan Lab: setup alerts are connected.")
    if not delivered:
        raise HTTPException(status_code=502, detail="Telegram refused the message. Check the token and chat id")
    return {"delivered": True}


@router.get("/report")
async def early_setup_report(
    since: str | None = Query(None, description="Only setups first listed on or after YYYY-MM-DD"),
    which: str = Query("daily", alias="list", description="daily or weekly"),
    max_positions: int = Query(10, ge=1, le=100, description="Most positions held at once in the account view"),
) -> dict[str, Any]:
    since = _iso(since, "since")
    if which not in SPECS:
        raise HTTPException(status_code=400, detail="list must be daily or weekly")
    return await asyncio.to_thread(
        lambda: watchlist_report(since=since, timeframe=which, max_positions=max_positions)
    )


@router.get("/model")
async def early_setup_model() -> dict[str, Any]:
    return _model_summary()
