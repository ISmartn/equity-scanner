"""Minute candles for one stock, read live from Upstox for the Stock Research chart.

History comes from the historical-candle endpoint, today's bars from the
intraday endpoint; the two are merged by timestamp. A short in-memory cache keeps
a chart refresh from calling Upstox twice.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import get_access_token, resolve_instrument_key
from .upstox_client import get_historical_candles, get_intra_day_candles

IST = timezone(timedelta(hours=5, minutes=30))

# minutes per bar -> calendar days of history to request (Upstox caps the range per request).
INTERVAL_LOOKBACK_DAYS: dict[int, int] = {1: 7, 3: 15, 5: 20, 15: 30, 30: 60, 60: 85}
CACHE_TTL_SEC = 20.0

_cache: dict[tuple[str, int], tuple[float, list[dict[str, Any]]]] = {}


def _parse(payload: Any) -> list[dict[str, Any]]:
    candles = None
    if isinstance(payload, dict):
        candles = payload.get("candles") or (payload.get("data") or {}).get("candles")
    out: list[dict[str, Any]] = []
    for row in candles or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            at = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
            o, h, l, c = (float(row[i]) for i in range(1, 5))
            volume = int(float(row[5] or 0))
        except (TypeError, ValueError):
            continue
        if c <= 0:
            continue
        out.append(
            {
                "ts": int(at.timestamp()),
                "date": at.astimezone(IST).strftime("%Y-%m-%d %H:%M"),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": volume,
            }
        )
    return out


async def fetch_intraday_candles(
    symbol: str,
    interval: int,
    *,
    access_token: str | None = None,
) -> dict[str, Any]:
    if interval not in INTERVAL_LOOKBACK_DAYS:
        raise ValueError(f"interval must be one of {sorted(INTERVAL_LOOKBACK_DAYS)}")
    normalized = symbol.strip().upper()
    key = resolve_instrument_key(normalized)
    if not key:
        raise LookupError(f"No Upstox instrument for {normalized}.")

    cache_key = (key, interval)
    held = _cache.get(cache_key)
    if held and time.monotonic() - held[0] < CACHE_TTL_SEC:
        return {"symbol": normalized, "interval": interval, "source": "upstox", "candles": held[1]}

    token = get_access_token(access_token)
    if not token:
        raise RuntimeError("Set UPSTOX_ACCESS_TOKEN in .env to read minute candles.")

    today = datetime.now(IST).date()
    start = today - timedelta(days=INTERVAL_LOOKBACK_DAYS[interval])
    merged: dict[int, dict[str, Any]] = {}
    history = await get_historical_candles(token, key, "minutes", str(interval), today.isoformat(), start.isoformat())
    for bar in _parse(history):
        merged[bar["ts"]] = bar
    try:
        live = await get_intra_day_candles(token, key, "minutes", interval)
        for bar in _parse(live):
            merged[bar["ts"]] = bar
    except RuntimeError:
        # The intraday endpoint can refuse outside market hours; the history already holds the last session.
        pass

    candles = [merged[ts] for ts in sorted(merged)]
    _cache[cache_key] = (time.monotonic(), candles)
    return {"symbol": normalized, "interval": interval, "source": "upstox", "candles": candles}
