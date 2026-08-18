from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Literal

import aiohttp
import pandas as pd

from ..cache import get_cached, set_cache
from ..config import normalize_symbol, resolve_instrument_key
from . import upstox_client

Interval = Literal["daily", "weekly", "monthly"]

LOOKBACK_YEARS = 5
LOOKBACK_DAYS = LOOKBACK_YEARS * 365  # ~5 years of daily data for all intervals

INTERVAL_HORIZON: dict[Interval, int] = {
    "daily": 20,
    "weekly": 12,
    "monthly": 6,
}


def default_horizon(interval: Interval) -> int:
    return INTERVAL_HORIZON[interval]


def _transform_upstox_candles(raw: dict[str, Any]) -> list[dict[str, Any]]:
    candles_raw = (raw.get("data") or {}).get("candles") or []
    candles: list[dict[str, Any]] = []
    for row in candles_raw:
        if not row or len(row) < 5:
            continue
        ts_raw = row[0]
        if isinstance(ts_raw, str):
            ts = ts_raw.split("T")[0].split(" ")[0]
        else:
            ts = datetime.utcfromtimestamp(float(ts_raw)).strftime("%Y-%m-%d")
        candles.append(
            {
                "date": ts,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]) if len(row) > 5 else 0.0,
            }
        )
    candles.sort(key=lambda item: item["date"])
    return candles


def _resample_candles(candles: list[dict[str, Any]], interval: Interval) -> list[dict[str, Any]]:
    if interval == "daily" or not candles:
        return candles

    frame = pd.DataFrame(candles)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date").sort_index()

    rule = "W-FRI" if interval == "weekly" else "ME"
    grouped = frame.resample(rule).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    grouped = grouped.dropna(subset=["close"])

    result: list[dict[str, Any]] = []
    for idx, row in grouped.iterrows():
        result.append(
            {
                "date": idx.strftime("%Y-%m-%d"),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
        )
    return result


async def _fetch_upstox_daily(
    session: aiohttp.ClientSession,
    symbol: str,
    from_date: date,
    to_date: date,
    access_token: str | None,
) -> list[dict[str, Any]]:
    instrument_key = resolve_instrument_key(symbol)
    if not instrument_key:
        raise RuntimeError(f"No Upstox instrument key for {symbol}")

    cache_key = f"upstox:daily:{instrument_key}:{from_date}:{to_date}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    raw = await upstox_client.get_historical_candles(
        access_token,
        instrument_key,
        "days",
        "1",
        to_date.strftime("%Y-%m-%d"),
        from_date.strftime("%Y-%m-%d"),
    )
    candles = _transform_upstox_candles(raw)
    if not candles:
        raise RuntimeError("Upstox returned empty candle data")

    set_cache(cache_key, candles, 900)
    return candles


async def fetch_candles(
    session: aiohttp.ClientSession,
    symbol: str,
    interval: Interval,
    access_token: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    normalized = normalize_symbol(symbol)
    to_date = date.today()
    from_date = to_date - timedelta(days=LOOKBACK_DAYS)

    # Upstox only — do not fall back to NSE (session/HTML failures pollute ingest).
    daily = await _fetch_upstox_daily(session, normalized, from_date, to_date, access_token)
    source = "upstox"

    candles = _resample_candles(daily, interval)
    if len(candles) < 32:
        raise RuntimeError(f"Insufficient history for {symbol}: need at least 32 {interval} points")

    return candles, source


def annotate_pct_changes(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add pct_change vs previous bar close (first bar has null pct_change)."""
    result: list[dict[str, Any]] = []
    prev_close: float | None = None
    for candle in candles:
        row = dict(candle)
        close = float(candle["close"])
        if prev_close is not None and prev_close != 0:
            row["pct_change"] = round((close - prev_close) / prev_close * 100, 4)
        else:
            row["pct_change"] = None
        result.append(row)
        prev_close = close
    return result
