"""DB-backed Nifty candle seed for MTF RSI (``index_candles`` table).

First run pulls ~3y history into SQLite. Later runs only fetch from the last
stored bar forward, upsert, then load candles from the DB into the engine.
"""

from __future__ import annotations

import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..db.store import TimelineStore, get_store

# Ensure ``mtf_rsi`` package imports resolve.
_backend_dir = str(Path(__file__).resolve().parents[2])
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from mtf_rsi.history import (  # noqa: E402
    HISTORY_LOOKBACK_DAYS,
    HISTORY_LOOKBACK_YEARS,
    fetch_historical_candles,
    fetch_intraday_candles,
    load_cached_candles,
    _merge_candles,
)
from mtf_rsi.models import Candle, ensure_ist  # noqa: E402

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
SOURCE = "mtf_rsi"
# Treat fewer than this many bars as "not seeded yet" → full lookback fetch.
MIN_BARS_FOR_INCREMENTAL = 1000


def _tf_key(minutes: int) -> str:
    return f"{int(minutes)}m"


def _as_ist_date(ts: datetime) -> date:
    return ensure_ist(ts).date()


def _parse_db_ts(raw: str) -> datetime:
    text = (raw or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        # Older rows may be naive IST wall times.
        dt = dt.replace(tzinfo=IST)
    return ensure_ist(dt)


def _candle_to_row(instrument_key: str, timeframe: str, candle: Candle) -> dict[str, Any]:
    return {
        "instrument_token": instrument_key,
        "timeframe": timeframe,
        "ts": ensure_ist(candle.ts).astimezone(timezone.utc).isoformat(),
        "open_price": float(candle.open),
        "high_price": float(candle.high),
        "low_price": float(candle.low),
        "close_price": float(candle.close),
        "volume": int(candle.volume or 0),
        "oi": None,
        "source": SOURCE,
    }


def _row_to_candle(row: dict[str, Any]) -> Candle:
    return Candle(
        ts=_parse_db_ts(str(row["ts"])),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row.get("volume") or 0.0),
    )


def _db_stats(
    store: TimelineStore,
    instrument_key: str,
    timeframe: str,
) -> dict[str, Any] | None:
    rows = store.index_candle_stats(instrument_key, timeframe=timeframe)
    return rows[0] if rows else None


def _lookback_from_ts(lookback_days: int) -> str:
    today = datetime.now(tz=IST).date()
    earliest = today - timedelta(days=max(1, lookback_days) - 1)
    # Compare as UTC midnight-ish ISO so lexicographic ts filter works.
    start = datetime(earliest.year, earliest.month, earliest.day, tzinfo=IST).astimezone(
        timezone.utc
    )
    return start.isoformat()


def load_candles_from_db(
    store: TimelineStore,
    instrument_key: str,
    timeframe_minutes: int,
    *,
    lookback_days: int = HISTORY_LOOKBACK_DAYS,
) -> list[Candle]:
    tf = _tf_key(timeframe_minutes)
    rows = store.get_index_candles(
        instrument_key,
        tf,
        from_ts=_lookback_from_ts(lookback_days),
    )
    candles = [_row_to_candle(r) for r in rows]
    candles.sort(key=lambda c: c.ts)
    return candles


def _upsert_candles(
    store: TimelineStore,
    instrument_key: str,
    timeframe_minutes: int,
    candles: list[Candle],
) -> int:
    if not candles:
        return 0
    tf = _tf_key(timeframe_minutes)
    rows = [_candle_to_row(instrument_key, tf, c) for c in candles]
    return store.upsert_index_candles(rows)


def _maybe_import_json_cache(
    store: TimelineStore,
    instrument_key: str,
    timeframe_minutes: int,
    cache_dir: Path,
) -> int:
    """One-time bridge: if DB is empty but JSON cache exists, import it."""
    tf = _tf_key(timeframe_minutes)
    stats = _db_stats(store, instrument_key, tf)
    if stats and int(stats.get("count") or 0) >= MIN_BARS_FOR_INCREMENTAL:
        return 0
    cached = load_cached_candles(cache_dir, instrument_key, timeframe_minutes)
    if not cached:
        return 0
    n = _upsert_candles(store, instrument_key, timeframe_minutes, cached)
    logger.info(
        "Imported %d %s candles from JSON cache into index_candles",
        n,
        tf,
    )
    return n


def seed_timeframe_to_db(
    access_token: str,
    instrument_key: str,
    timeframe_minutes: int,
    *,
    store: TimelineStore | None = None,
    cache_dir: Path | None = None,
    force_refresh: bool = False,
    lookback_days: int = HISTORY_LOOKBACK_DAYS,
) -> list[Candle]:
    """Fetch → upsert into ``index_candles`` → return candles for the engine."""
    store = store or get_store()
    tf = _tf_key(timeframe_minutes)
    today = datetime.now(tz=IST).date()
    from_d_full = today - timedelta(days=max(1, lookback_days) - 1)

    if cache_dir is not None:
        _maybe_import_json_cache(store, instrument_key, timeframe_minutes, cache_dir)

    stats = _db_stats(store, instrument_key, tf)
    db_count = int(stats.get("count") or 0) if stats else 0
    max_ts_raw = stats.get("max_ts") if stats else None

    if force_refresh or db_count < MIN_BARS_FOR_INCREMENTAL:
        logger.info(
            "Full %s seed into DB (force=%s, existing=%d) %s→%s",
            tf,
            force_refresh,
            db_count,
            from_d_full,
            today,
        )
        historical = fetch_historical_candles(
            access_token,
            instrument_key,
            timeframe_minutes,
            from_date=from_d_full,
            to_date=today,
        )
        try:
            intraday = fetch_intraday_candles(access_token, instrument_key, timeframe_minutes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Intraday fetch failed during full DB seed: %s", exc)
            intraday = []
        merged = _merge_candles(historical, intraday)
        upserted = _upsert_candles(store, instrument_key, timeframe_minutes, merged)
        logger.info("Upserted %d %s candles into index_candles", upserted, tf)
    else:
        assert max_ts_raw is not None
        last_ts = _parse_db_ts(str(max_ts_raw))
        last_day = _as_ist_date(last_ts)
        logger.info(
            "Incremental %s DB seed from last bar %s (day %s)",
            tf,
            last_ts.isoformat(),
            last_day,
        )
        incremental: list[Candle] = []
        if last_day <= today:
            try:
                incremental = fetch_historical_candles(
                    access_token,
                    instrument_key,
                    timeframe_minutes,
                    from_date=last_day,
                    to_date=today,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Incremental historical fetch failed for %s (%s→%s): %s",
                    tf,
                    last_day,
                    today,
                    exc,
                )
        try:
            intraday = fetch_intraday_candles(access_token, instrument_key, timeframe_minutes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Intraday fetch failed during incremental DB seed: %s", exc)
            intraday = []
        # Only keep bars at/after last day (upsert overwrites the partial day).
        fresh = [
            c
            for c in _merge_candles(incremental, intraday)
            if _as_ist_date(c.ts) >= last_day
        ]
        upserted = _upsert_candles(store, instrument_key, timeframe_minutes, fresh)
        logger.info(
            "Incremental %s upserted %d bars (hist=%d intra=%d)",
            tf,
            upserted,
            len(incremental),
            len(intraday),
        )

    candles = load_candles_from_db(
        store,
        instrument_key,
        timeframe_minutes,
        lookback_days=lookback_days,
    )
    logger.info(
        "Loaded %d %s candles from index_candles for engine (~%dy window)",
        len(candles),
        tf,
        HISTORY_LOOKBACK_YEARS,
    )
    return candles


def seed_all_timeframes_to_db(
    access_token: str,
    instrument_key: str,
    timeframes: list[int],
    *,
    store: TimelineStore | None = None,
    cache_dir: Path | None = None,
    force_refresh: bool = False,
    lookback_days: int = HISTORY_LOOKBACK_DAYS,
) -> dict[int, list[Candle]]:
    store = store or get_store()
    out: dict[int, list[Candle]] = {}
    workers = min(3, max(1, len(timeframes)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                seed_timeframe_to_db,
                access_token,
                instrument_key,
                tf,
                store=store,
                cache_dir=cache_dir,
                force_refresh=force_refresh,
                lookback_days=lookback_days,
            ): tf
            for tf in timeframes
        }
        for fut in as_completed(futures):
            tf = futures[fut]
            out[tf] = fut.result()
    return out
