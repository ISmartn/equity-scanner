from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path

import upstox_client
from upstox_client.rest import ApiException

from .models import Candle, parse_upstox_candle_row

logger = logging.getLogger(__name__)


def _safe_key(instrument_key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", instrument_key)


def cache_path(cache_dir: Path, instrument_key: str, timeframe: int, day: date | None = None) -> Path:
    day = day or date.today()
    return cache_dir / day.isoformat() / f"{_safe_key(instrument_key)}_{timeframe}m.json"


def load_cached_candles(
    cache_dir: Path,
    instrument_key: str,
    timeframe: int,
    *,
    day: date | None = None,
) -> list[Candle] | None:
    path = cache_path(cache_dir, instrument_key, timeframe, day)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("candles") if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or not rows:
            return None
        candles = [Candle.from_dict(row) for row in rows]
        logger.info(
            "Using cached %dm seed (%d candles) from %s",
            timeframe,
            len(candles),
            path,
        )
        return candles
    except Exception as exc:
        logger.warning("Failed reading cache %s: %s", path, exc)
        return None


def save_cached_candles(
    cache_dir: Path,
    instrument_key: str,
    timeframe: int,
    candles: list[Candle],
    *,
    day: date | None = None,
) -> Path:
    path = cache_path(cache_dir, instrument_key, timeframe, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "instrument_key": instrument_key,
        "timeframe": timeframe,
        "saved_at": datetime.now().isoformat(),
        "candles": [c.as_dict() for c in candles],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _history_api(access_token: str) -> upstox_client.HistoryV3Api:
    configuration = upstox_client.Configuration()
    configuration.access_token = access_token
    return upstox_client.HistoryV3Api(upstox_client.ApiClient(configuration))


def fetch_intraday_candles(
    access_token: str,
    instrument_key: str,
    timeframe: int,
    *,
    limit: int = 100,
) -> list[Candle]:
    api = _history_api(access_token)
    try:
        response = api.get_intra_day_candle_data(
            instrument_key,
            "minutes",
            int(timeframe),
        )
    except ApiException as exc:
        raise RuntimeError(
            f"Upstox intraday fetch failed for {timeframe}m "
            f"[{getattr(exc, 'status', '?')}]: {getattr(exc, 'body', exc)}"
        ) from exc

    data = getattr(response, "data", None)
    raw_candles = getattr(data, "candles", None) if data is not None else None
    if raw_candles is None and isinstance(response, dict):
        raw_candles = (response.get("data") or {}).get("candles")

    candles: list[Candle] = []
    for row in raw_candles or []:
        parsed = parse_upstox_candle_row(row)
        if parsed is not None:
            candles.append(parsed)

    candles.sort(key=lambda c: c.ts)
    if limit > 0 and len(candles) > limit:
        candles = candles[-limit:]
    logger.info(
        "Fetched %dm intraday seed: %d candles for %s",
        timeframe,
        len(candles),
        instrument_key,
    )
    return candles


def seed_timeframe_candles(
    access_token: str,
    instrument_key: str,
    timeframe: int,
    cache_dir: Path,
    *,
    limit: int = 100,
    force_refresh: bool = False,
) -> list[Candle]:
    """Return historical candles, using disk cache when available."""
    if not force_refresh:
        cached = load_cached_candles(cache_dir, instrument_key, timeframe)
        if cached is not None:
            if limit > 0 and len(cached) > limit:
                return cached[-limit:]
            return cached

    candles = fetch_intraday_candles(
        access_token,
        instrument_key,
        timeframe,
        limit=limit,
    )
    if candles:
        save_cached_candles(cache_dir, instrument_key, timeframe, candles)
    return candles


def seed_all_timeframes(
    access_token: str,
    instrument_key: str,
    timeframes: list[int],
    cache_dir: Path,
    *,
    limit: int = 100,
    force_refresh: bool = False,
) -> dict[int, list[Candle]]:
    out: dict[int, list[Candle]] = {}
    for tf in timeframes:
        out[tf] = seed_timeframe_candles(
            access_token,
            instrument_key,
            tf,
            cache_dir,
            limit=limit,
            force_refresh=force_refresh,
        )
    return out
