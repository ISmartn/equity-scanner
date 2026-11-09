"""Fill daily candles for live-scan names that are missing the last completed session."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Any, Callable

from ...db.store import get_store
from ..candle_ingestion import ingest_candles
from ..nifty_candles import sync_timeframe
from .universe import UniverseSymbol

logger = logging.getLogger(__name__)

BOOTSTRAP_DAYS = 40
INDEX_LOOKBACK_DAYS = 40
# Standard APIs allow 500 requests a minute and 2,000 in 30 minutes. Two workers
# with a half-second gap stay near 240 a minute. The window cap leaves room for
# a restart before that 2,000 budget is spent.
_CANDLE_DELAY_SEC = 0.5
_CANDLE_CONCURRENCY = 2
_CANDLE_WINDOW_SEC = 30 * 60
_CANDLE_WINDOW_BUDGET = 1600


class CandleRequestBudget:
    """How many historical-candle requests this process may start in 30 minutes."""

    def __init__(self, *, limit: int = _CANDLE_WINDOW_BUDGET, window_sec: float = _CANDLE_WINDOW_SEC) -> None:
        self.limit = limit
        self.window_sec = window_sec
        self._spent = 0
        self._started = 0.0

    def grant(self, wanted: int, now: float | None = None) -> int:
        current = time.monotonic() if now is None else now
        if self._started <= 0 or current - self._started >= self.window_sec:
            self._spent = 0
            self._started = current
        room = max(0, self.limit - self._spent)
        granted = max(0, min(int(wanted), room))
        self._spent += granted
        return granted

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self._spent)


_candle_budget = CandleRequestBudget()


async def ensure_latest_candles(
    universe: list[UniverseSymbol],
    access_token: str | None,
    *,
    session_date: str,
    should_cancel: Callable[[], bool] | None = None,
    on_found: Callable[[list[str]], None] | None = None,
) -> dict[str, Any]:
    tokens = [item.cash_key for item in universe]
    stale = await asyncio.to_thread(get_store().tickers_missing_daily_session, tokens, session_date)
    granted = _candle_budget.grant(len(stale))
    deferred = len(stale) - granted
    stale = stale[:granted]
    if on_found is not None:
        on_found(stale)
    summary: dict[str, Any] = {
        "session": session_date,
        "requested": len(stale),
        "deferred": deferred,
        "budget_remaining": _candle_budget.remaining,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "total_bars": 0,
    }
    if not stale:
        if deferred:
            logger.info("Live scan deferred %d candle updates to stay inside the Upstox rate limit", deferred)
        else:
            logger.info("Live scan history is current through %s", session_date)
        return summary

    logger.info(
        "Updating %d symbols missing the %s daily candle (%d deferred)",
        len(stale),
        session_date,
        deferred,
    )
    result = await ingest_candles(
        tickers=stale,
        since_last=True,
        bootstrap_days=BOOTSTRAP_DAYS,
        access_token=access_token,
        should_cancel=should_cancel,
        concurrency=_CANDLE_CONCURRENCY,
        request_delay_sec=_CANDLE_DELAY_SEC,
    )
    summary.update(
        {
            "success": int(result.get("success") or 0),
            "failed": int(result.get("failed") or 0),
            "skipped": int(result.get("skipped") or 0),
            "total_bars": int(result.get("total_bars") or 0),
        }
    )
    return summary


async def ensure_latest_index_candles(
    indexes: list[UniverseSymbol],
    access_token: str | None,
    *,
    session_date: str,
    should_cancel: Callable[[], bool] | None = None,
    on_found: Callable[[list[str]], None] | None = None,
) -> dict[str, Any]:
    """Top up Nifty and Sensex daily bars when the last completed session is missing."""
    store = get_store()

    def find_stale() -> list[UniverseSymbol]:
        return [item for item in indexes if (store.latest_index_daily_date(item.cash_key) or "") < session_date]

    stale = await asyncio.to_thread(find_stale)
    if on_found is not None:
        on_found([item.symbol for item in stale])
    summary: dict[str, Any] = {
        "session": session_date,
        "requested": len(stale),
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "total_bars": 0,
    }
    if not stale:
        return summary

    session = date.fromisoformat(session_date)
    from_date = session - timedelta(days=INDEX_LOOKBACK_DAYS)
    logger.info("Updating %d index candles missing %s", len(stale), session_date)
    for item in stale:
        if should_cancel is not None and should_cancel():
            break
        try:
            result = await sync_timeframe(
                "daily",
                access_token=access_token,
                instrument_token=item.cash_key,
                from_date=from_date,
                to_date=session,
                refresh_intraday=False,
            )
        except Exception as exc:
            summary["failed"] += 1
            logger.warning("Index candle update failed for %s: %s", item.symbol, exc)
            continue
        summary["total_bars"] += int(result.get("upserted") or 0)
        if result.get("errors"):
            summary["failed"] += 1
            logger.warning("Index candle update incomplete for %s: %s", item.symbol, result["errors"])
        else:
            summary["success"] += 1
    return summary
