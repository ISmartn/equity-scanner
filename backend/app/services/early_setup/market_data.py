"""Keeps the watchlist's extra market data current.

``refresh`` is the small daily top-up: recent delivery files, the latest large
deals, the surveillance and ban lists, and corporate actions around today. It
is best effort by design. Each part fails on its own, a refusal from NSE stops
the rest, and the whole thing has a time budget, because it runs before the
watchlist update and must never hold that up for long.

``backfill`` loads history, one file per trading day, for fitting and testing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable

import aiohttp

from ...db.store import TimelineStore
from ..live_scan.clocks import IST
from . import nse, repo

logger = logging.getLogger(__name__)

_INDUSTRY_MAX_AGE_DAYS = 7
_ACTION_LABELS = {"bonus": "Ex-bonus", "split": "Ex-split", "dividend": "Ex-dividend", "other": "Corporate action"}
# A weekday with no file this many days later was a holiday. Remember it and stop asking.
_HOLIDAY_AFTER_DAYS = 3


def _today() -> date:
    return datetime.now(IST).date()


def _weekdays(start: date, end: date) -> list[date]:
    days = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _no_data_days(db: TimelineStore) -> set[str]:
    try:
        return set(json.loads(repo.get_meta("delivery_no_data", db) or "[]"))
    except ValueError:
        return set()


def _remember_no_data(db: TimelineStore, days: set[str]) -> None:
    repo.set_meta("delivery_no_data", json.dumps(sorted(days)[-400:]), db)


async def _patiently(make: Callable[[], Awaitable[Any]], attempts: int = 4) -> Any:
    """Retry a request that timed out or dropped. A refusal is not retried."""
    for attempt in range(attempts):
        try:
            return await make()
        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            if attempt == attempts - 1:
                raise
            logger.info("NSE request failed (%s); retrying", type(exc).__name__)
            await asyncio.sleep(2.0 * (attempt + 1))


async def _load_day(
    client: nse.NseClient,
    day: date,
    db: TimelineStore,
    *,
    candles: bool,
    index: bool,
) -> dict[str, int] | None:
    """One trading day's file into the database. None when NSE has no file for that day."""
    text = await client.text(nse.bhavcopy_url(day))
    if not nse.is_data(text):
        return None
    file_day, rows = nse.parse_bhavcopy(text or "")
    # A request for a non-trading day is answered with the previous session's file.
    if file_day != day.isoformat() or not rows:
        return None
    counts = {"delivery": repo.save_delivery(rows, db), "candles": 0, "index": 0}
    if candles:
        counts["candles"] = repo.fill_missing_candles(rows, db)
    if index:
        index_text = await client.text(nse.index_close_url(day))
        bar = nse.parse_index_close(index_text or "") if nse.is_data(index_text) else None
        if bar and bar["trade_date"] == day.isoformat():
            counts["index"] = repo.fill_missing_index(bar, db)
    return counts


async def _sync_industries(client: nse.NseClient, db: TimelineStore, *, force: bool = False) -> str:
    synced = repo.get_meta("industries_synced", db)
    if not force and synced and (_today() - date.fromisoformat(synced)).days < _INDUSTRY_MAX_AGE_DAYS:
        return "current"
    text = await client.text(nse.INDUSTRY_URL)
    rows = nse.parse_industries(text or "") if nse.is_data(text) else []
    if not rows:
        return "no data"
    repo.save_industries(rows, db)
    repo.set_meta("industries_synced", _today().isoformat(), db)
    return f"{len(rows)} stocks"


async def _sync_delivery(client: nse.NseClient, db: TimelineStore, through: date, days: int) -> str:
    have = repo.delivery_days(db)
    holidays = _no_data_days(db)
    wanted = [d for d in _weekdays(through - timedelta(days=int(days * 1.6) + 3), through)][-days:]
    loaded = 0
    for day in wanted:
        key = day.isoformat()
        if key in have or key in holidays:
            continue
        if await _load_day(client, day, db, candles=False, index=False):
            loaded += 1
        elif (_today() - day).days >= _HOLIDAY_AFTER_DAYS:
            holidays.add(key)
        await asyncio.sleep(0.3)
    _remember_no_data(db, holidays)
    return f"{loaded} new days"


async def _sync_deals(client: nse.NseClient, db: TimelineStore) -> str:
    deals: list[dict[str, Any]] = []
    for url, kind in ((nse.BULK_URL, "bulk"), (nse.BLOCK_URL, "block")):
        text = await client.text(url)
        if nse.is_data(text):
            deals.extend(nse.parse_deals(text or "", kind))
    if not deals:
        return "no deals"
    nse.mark_churn(deals)
    repo.save_deals(deals, db)
    return f"{len(deals)} deals, {sum(1 for d in deals if not d['churn'] and d['side'] == 'BUY')} one-sided buys"


async def _sync_flags(client: nse.NseClient, db: TimelineStore) -> str:
    parts = []
    ban_text = await client.text(nse.BAN_URL)
    if nse.is_data(ban_text):
        banned = nse.parse_ban(ban_text or "")
        repo.replace_flags(["fo_ban"], banned, db)
        parts.append(f"{len(banned)} in F&O ban")
    surveillance = nse.parse_asm(await client.json(nse.ASM_URL))
    if surveillance:  # an empty answer is more likely a failed read than an empty list
        repo.replace_flags(["asm_long", "asm_short"], surveillance, db)
        parts.append(f"{len(surveillance)} under surveillance")
    return ", ".join(parts) or "no data"


async def _sync_actions(client: nse.NseClient, db: TimelineStore, start: date, end: date) -> str:
    actions = nse.parse_actions(await client.json(nse.actions_url(start, end)))
    if not actions:
        return "no actions"
    repo.save_actions(actions, db)
    today = _today().isoformat()
    upcoming = [
        {
            "ticker": action["ticker"],
            "event_date": action["ex_date"],
            "purpose": _ACTION_LABELS.get(action["kind"], "Corporate action"),
            "detail": action["subject"],
        }
        for action in actions
        if action["ex_date"] >= today
    ]
    if upcoming:
        repo.save_events(upcoming, db)
    return f"{len(actions)} actions, {len(upcoming)} upcoming"


async def _refresh(db: TimelineStore, through: date, delivery_days: int, budget_sec: float) -> dict[str, Any]:
    deadline = time.monotonic() + budget_sec
    result: dict[str, Any] = {}
    today = _today()
    async with nse.NseClient() as client:
        steps: list[tuple[str, Callable[[], Awaitable[str]]]] = [
            ("delivery", lambda: _sync_delivery(client, db, through, delivery_days)),
            ("deals", lambda: _sync_deals(client, db)),
            ("flags", lambda: _sync_flags(client, db)),
            ("actions", lambda: _sync_actions(client, db, today - timedelta(days=45), today + timedelta(days=30))),
            ("industries", lambda: _sync_industries(client, db)),
        ]
        refused = False
        for name, step in steps:
            if refused:
                result[name] = "skipped: NSE refused an earlier request"
            elif time.monotonic() > deadline:
                result[name] = "skipped: out of time"
            else:
                try:
                    result[name] = await step()
                except nse.NseRefused:
                    refused = True
                    result[name] = "refused by NSE"
                except Exception as exc:  # one part failing must not stop the others
                    logger.warning("Market data refresh, %s failed: %s", name, exc)
                    result[name] = f"failed: {type(exc).__name__}"
    return result


def refresh(
    *,
    through: str | None = None,
    delivery_days: int = 10,
    budget_sec: float = 75.0,
    store: TimelineStore | None = None,
) -> dict[str, Any]:
    """Top up delivery, deals, flags, corporate actions and industries. Never raises."""
    db = repo.ensure_schema(store)
    day = date.fromisoformat(through) if through else _today()
    try:
        return nse.run(_refresh(db, min(day, _today()), delivery_days, budget_sec))
    except Exception as exc:  # no network, or NSE down before the first request
        logger.warning("Market data refresh did not start: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}


async def _backfill(
    db: TimelineStore,
    days: int,
    *,
    candles: bool,
    index: bool,
    pause: float,
    on_progress: Callable[[dict[str, Any]], None] | None,
) -> dict[str, Any]:
    today = _today()
    wanted = _weekdays(today - timedelta(days=int(days * 1.5) + 10), today)[-days:]
    have = repo.delivery_days(db)
    have_candles = repo.candle_days(db) if candles else set()
    have_index = repo.index_days(db) if index else set()
    holidays = _no_data_days(db)
    totals = {"days_loaded": 0, "days_skipped": 0, "no_file": 0, "delivery_rows": 0, "candles_added": 0, "index_added": 0}
    result: dict[str, Any] = {"from": wanted[0].isoformat() if wanted else None, "to": today.isoformat()}
    async with nse.NseClient() as client:
        try:
            result["industries"] = await _sync_industries(client, db, force=True)
            # The actions list answers a few months at a time.
            chunks = 0
            cursor = wanted[0] if wanted else today
            while cursor <= today + timedelta(days=30):
                upto = min(cursor + timedelta(days=80), today + timedelta(days=30))
                await _sync_actions(client, db, cursor, upto)
                chunks += 1
                cursor = upto + timedelta(days=1)
                await asyncio.sleep(pause)
            result["action_chunks"] = chunks
            for position, day in enumerate(reversed(wanted), start=1):
                key = day.isoformat()
                complete = key in have and (not candles or key in have_candles) and (not index or key in have_index)
                if key in holidays or complete:
                    totals["days_skipped"] += 1
                    continue
                counts = await _patiently(lambda day=day: _load_day(client, day, db, candles=candles, index=index))
                if counts is None:
                    totals["no_file"] += 1
                    if (today - day).days >= _HOLIDAY_AFTER_DAYS:
                        holidays.add(key)
                else:
                    totals["days_loaded"] += 1
                    totals["delivery_rows"] += counts["delivery"]
                    totals["candles_added"] += counts["candles"]
                    totals["index_added"] += counts["index"]
                if on_progress:
                    on_progress({"day": key, "position": position, "total": len(wanted), **totals})
                await asyncio.sleep(pause)
        except nse.NseRefused as exc:
            result["stopped"] = str(exc)
        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            result["stopped"] = f"NSE stopped answering ({type(exc).__name__}). Run it again to continue."
        finally:
            _remember_no_data(db, holidays)
    return {**result, **totals}


def backfill(
    days: int,
    *,
    candles: bool = False,
    index: bool = False,
    pause: float = 0.4,
    store: TimelineStore | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Load ``days`` trading days of history, newest first. Safe to stop and rerun."""
    db = repo.ensure_schema(store)
    return nse.run(_backfill(db, max(1, int(days)), candles=candles, index=index, pause=pause, on_progress=on_progress))
