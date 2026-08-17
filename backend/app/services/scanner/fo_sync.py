"""Helpers for F&O derivative ensure during scanner runs."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from datetime import date
from typing import Any, Coroutine, TypeVar

import aiohttp

from ...cache import get_cached
from ...db.store import TimelineStore
from .. import market_info_sync, nse_client
from .fo_enrich import apply_fo_overlay_to_signal

logger = logging.getLogger(__name__)

T = TypeVar("T")


def run_coro_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine from sync code, even inside a running event loop.

    FastAPI often calls ``run_scanner`` from an async route/background task, so
    bare ``asyncio.run()`` raises RuntimeError. When a loop is already running,
    execute the coroutine on a dedicated thread with its own loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def load_fno_symbol_set() -> set[str]:
    cached = get_cached("fno:symbols:v1")
    if cached:
        return set(cached)
    try:
        async with aiohttp.ClientSession() as session:
            symbols = await nse_client.fetch_fno_symbols(session)
        return set(symbols)
    except Exception as exc:
        logger.warning("Could not load F&O symbol list: %s", exc)
        return set()


def load_fno_symbol_set_sync() -> set[str]:
    cached = get_cached("fno:symbols:v1")
    if cached:
        return set(cached)
    try:
        return run_coro_sync(load_fno_symbol_set())
    except Exception as exc:
        logger.warning("Could not load F&O symbol list (sync): %s", exc)
        return set()

async def ensure_fno_derivatives_for_signals(
    store: TimelineStore,
    trade_date: str,
    signals: list[dict[str, Any]],
    *,
    access_token: str | None = None,
) -> dict[str, Any]:
    """Sync missing derivative snapshots for F&O tickers present in scanner hits."""
    fno_set = await load_fno_symbol_set()
    if not fno_set:
        return {"synced": [], "skipped": "fno_list_unavailable"}

    fno_tickers = sorted(
        {str(s["ticker"]).upper() for s in signals if str(s["ticker"]).upper() in fno_set}
    )
    missing = store.symbols_missing_derivatives(fno_tickers, trade_date)
    if not missing:
        return {"synced": [], "already_present": fno_tickers}

    try:
        result = await market_info_sync.ensure_derivative_snapshots(
            access_token,
            trade_date=date.fromisoformat(trade_date),
            symbols=missing,
        )
        return result
    except RuntimeError as exc:
        logger.info("Skipping auto F&O derivative sync: %s", exc)
        return {"synced": [], "error": str(exc)}


def finalize_signals_with_fo_data(
    store: TimelineStore,
    trade_date: str,
    signals: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Re-apply F&O overlay after optional derivative sync; drop hard rejects."""
    derivatives = store.load_derivative_metrics_for_date(trade_date)
    finalized: list[dict[str, Any]] = []
    skipped_reject = 0
    for signal in signals:
        daily_ret = signal.get("details", {}).get("daily_return_pct")
        if daily_ret is not None:
            signal = {**signal, "daily_return_pct": daily_ret}
        updated = apply_fo_overlay_to_signal(signal, derivatives)
        if updated is None:
            skipped_reject += 1
            continue
        finalized.append(updated)
    return finalized, skipped_reject


async def ensure_and_finalize_scanner_signals(
    store: TimelineStore,
    trade_date: str,
    signals: list[dict[str, Any]],
    *,
    access_token: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ensure_meta = await ensure_fno_derivatives_for_signals(
        store,
        trade_date,
        signals,
        access_token=access_token,
    )
    finalized, skipped_reject = finalize_signals_with_fo_data(store, trade_date, signals)
    ensure_meta["skipped_fo_reject_after_sync"] = skipped_reject
    return finalized, ensure_meta
