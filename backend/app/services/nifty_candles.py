"""Nifty 50 multi-timeframe candle sync into index_candles."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from ..config import INDEX_INSTRUMENT_KEYS, get_access_token
from ..db.store import TimelineStore, get_store
from . import upstox_client

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

NIFTY_INSTRUMENT = INDEX_INSTRUMENT_KEYS["NIFTY"]
TIMEFRAMES = ("1m", "3m", "5m", "10m", "daily")

# Default lookback windows (calendar days)
DEFAULT_LOOKBACK_DAYS: dict[str, int] = {
    "1m": 7,
    "3m": 20,
    "5m": 20,
    "10m": 20,
    "daily": 365 * 5,
}

# Max days per Upstox historical request chunk
CHUNK_DAYS: dict[str, int] = {
    "1m": 7,
    "3m": 14,
    "5m": 30,
    "10m": 30,
    "daily": 364,
}


def _tf_unit_interval(timeframe: str) -> tuple[str, str]:
    if timeframe == "daily":
        return "days", "1"
    if timeframe.endswith("m") and timeframe[:-1].isdigit():
        return "minutes", timeframe[:-1]
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def _parse_ts(raw: Any, *, daily: bool) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        dt = datetime.fromtimestamp(float(raw), tz=timezone.utc)
    elif isinstance(raw, str):
        text = raw.strip()
        if daily:
            return text.split("T")[0].split(" ")[0]
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    if daily:
        return dt.astimezone(IST).date().isoformat()
    return dt.astimezone(timezone.utc).isoformat()


def _rows_from_upstox(
    raw: dict[str, Any],
    *,
    instrument_token: str,
    timeframe: str,
    source: str,
) -> list[dict[str, Any]]:
    candles_raw = (raw.get("data") or {}).get("candles") or []
    daily = timeframe == "daily"
    out: list[dict[str, Any]] = []
    for row in candles_raw:
        if not row or len(row) < 5:
            continue
        ts = _parse_ts(row[0], daily=daily)
        if not ts:
            continue
        out.append(
            {
                "instrument_token": instrument_token,
                "timeframe": timeframe,
                "ts": ts,
                "open_price": float(row[1]),
                "high_price": float(row[2]),
                "low_price": float(row[3]),
                "close_price": float(row[4]),
                "volume": int(float(row[5])) if len(row) > 5 and row[5] is not None else 0,
                "oi": int(float(row[6])) if len(row) > 6 and row[6] is not None else None,
                "source": source,
            }
        )
    out.sort(key=lambda c: c["ts"])
    return out


def _daterange_chunks(from_d: date, to_d: date, chunk_days: int) -> list[tuple[date, date]]:
    if from_d > to_d:
        return []
    chunks: list[tuple[date, date]] = []
    cur = from_d
    delta = timedelta(days=max(1, chunk_days))
    while cur <= to_d:
        end = min(cur + delta - timedelta(days=1), to_d)
        chunks.append((cur, end))
        cur = end + timedelta(days=1)
    return chunks


def normalize_timeframes(raw: Iterable[str] | None) -> list[str]:
    if not raw:
        return list(TIMEFRAMES)
    out: list[str] = []
    for item in raw:
        tf = str(item).strip().lower()
        if tf in ("1", "3", "5", "10"):
            tf = f"{tf}m"
        if tf == "day":
            tf = "daily"
        if tf not in TIMEFRAMES:
            raise ValueError(f"Unsupported timeframe '{item}'. Use one of: {', '.join(TIMEFRAMES)}")
        if tf not in out:
            out.append(tf)
    return out


async def sync_timeframe(
    timeframe: str,
    *,
    access_token: str | None = None,
    store: TimelineStore | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    instrument_token: str = NIFTY_INSTRUMENT,
    refresh_intraday: bool = True,
) -> dict[str, Any]:
    token = get_access_token(access_token)
    if not token:
        raise RuntimeError("UPSTOX_ACCESS_TOKEN not configured")

    store = store or get_store()
    today = datetime.now(tz=IST).date()
    to_d = to_date or today
    lookback = DEFAULT_LOOKBACK_DAYS[timeframe]
    from_d = from_date or (to_d - timedelta(days=lookback - 1))

    unit, interval = _tf_unit_interval(timeframe)
    chunk_days = CHUNK_DAYS[timeframe]
    upserted = 0
    chunks_ok = 0
    errors: list[str] = []

    for chunk_from, chunk_to in _daterange_chunks(from_d, to_d, chunk_days):
        try:
            raw = await upstox_client.get_historical_candles(
                token,
                instrument_token,
                unit,
                interval,
                chunk_to.isoformat(),
                chunk_from.isoformat(),
            )
            rows = _rows_from_upstox(
                raw,
                instrument_token=instrument_token,
                timeframe=timeframe,
                source="upstox",
            )
            upserted += store.upsert_index_candles(rows)
            chunks_ok += 1
        except Exception as exc:  # noqa: BLE001
            msg = f"{chunk_from}→{chunk_to}: {exc}"
            errors.append(msg)
            logger.warning("Nifty %s historical chunk failed: %s", timeframe, msg)

    intraday_upserted = 0
    if refresh_intraday and timeframe != "daily" and to_d >= today:
        try:
            raw_intra = await upstox_client.get_intra_day_candles(
                token,
                instrument_token,
                "minutes",
                interval,
            )
            rows = _rows_from_upstox(
                raw_intra,
                instrument_token=instrument_token,
                timeframe=timeframe,
                source="upstox_intraday",
            )
            intraday_upserted = store.upsert_index_candles(rows)
            upserted += intraday_upserted
        except Exception as exc:  # noqa: BLE001
            msg = f"intraday: {exc}"
            errors.append(msg)
            logger.warning("Nifty %s intraday refresh failed: %s", timeframe, msg)

    coverage = store.index_candle_stats(instrument_token, timeframe=timeframe)
    stats = coverage[0] if coverage else {"timeframe": timeframe, "count": 0, "min_ts": None, "max_ts": None}
    return {
        "timeframe": timeframe,
        "instrument_token": instrument_token,
        "from_date": from_d.isoformat(),
        "to_date": to_d.isoformat(),
        "chunks_ok": chunks_ok,
        "upserted": upserted,
        "intraday_upserted": intraday_upserted,
        "coverage": stats,
        "errors": errors,
    }


async def sync_nifty(
    *,
    timeframes: Iterable[str] | None = None,
    access_token: str | None = None,
    store: TimelineStore | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    instrument_token: str = NIFTY_INSTRUMENT,
) -> dict[str, Any]:
    tfs = normalize_timeframes(timeframes)
    store = store or get_store()
    results = []
    for tf in tfs:
        # Per-TF default lookback when caller didn't pass an explicit from_date.
        tf_from = from_date
        if tf_from is None and to_date is None:
            results.append(
                await sync_timeframe(
                    tf,
                    access_token=access_token,
                    store=store,
                    instrument_token=instrument_token,
                )
            )
        else:
            results.append(
                await sync_timeframe(
                    tf,
                    access_token=access_token,
                    store=store,
                    from_date=tf_from,
                    to_date=to_date,
                    instrument_token=instrument_token,
                )
            )
    return {
        "instrument_token": instrument_token,
        "timeframes": tfs,
        "results": results,
        "total_upserted": sum(int(r.get("upserted") or 0) for r in results),
    }


def nifty_status(
    *,
    store: TimelineStore | None = None,
    instrument_token: str = NIFTY_INSTRUMENT,
) -> dict[str, Any]:
    store = store or get_store()
    coverage = store.index_candle_stats(instrument_token)
    by_tf = {row["timeframe"]: row for row in coverage}
    return {
        "instrument_token": instrument_token,
        "instrument_label": "Nifty 50",
        "timeframes": TIMEFRAMES,
        "coverage": [
            by_tf.get(
                tf,
                {"timeframe": tf, "count": 0, "min_ts": None, "max_ts": None},
            )
            for tf in TIMEFRAMES
        ],
    }


def nifty_candles(
    timeframe: str,
    *,
    from_ts: str | None = None,
    to_ts: str | None = None,
    limit: int | None = 5000,
    store: TimelineStore | None = None,
    instrument_token: str = NIFTY_INSTRUMENT,
) -> dict[str, Any]:
    tfs = normalize_timeframes([timeframe])
    tf = tfs[0]
    store = store or get_store()
    candles = store.get_index_candles(
        instrument_token,
        tf,
        from_ts=from_ts,
        to_ts=to_ts,
        limit=limit,
    )
    stats: dict[str, Any] = {
        "count": len(candles),
        "first_ts": candles[0]["ts"] if candles else None,
        "last_ts": candles[-1]["ts"] if candles else None,
    }
    if candles:
        first_close = float(candles[0]["close"] or 0)
        last_close = float(candles[-1]["close"] or 0)
        highs = [float(c["high"]) for c in candles if c.get("high") is not None]
        lows = [float(c["low"]) for c in candles if c.get("low") is not None]
        stats["last_close"] = last_close
        stats["period_high"] = max(highs) if highs else None
        stats["period_low"] = min(lows) if lows else None
        if first_close:
            stats["range_return_pct"] = ((last_close - first_close) / first_close) * 100.0
        else:
            stats["range_return_pct"] = None
    return {
        "instrument_token": instrument_token,
        "instrument_label": "Nifty 50",
        "timeframe": tf,
        "candles": candles,
        "stats": stats,
    }
