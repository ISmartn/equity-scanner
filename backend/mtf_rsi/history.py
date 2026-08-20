from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import upstox_client
from upstox_client.rest import ApiException

from .models import Candle, parse_upstox_candle_row

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# Calendar-day lookback for historical seed (≈3 years).
HISTORY_LOOKBACK_YEARS = 3
HISTORY_LOOKBACK_DAYS = 365 * HISTORY_LOOKBACK_YEARS

# Upstox historical request chunk size by TF minutes.
CHUNK_DAYS_BY_TF: dict[int, int] = {
    1: 7,
    3: 14,
    5: 30,
    10: 30,
    15: 30,
}

# Soft cap on points returned to the UI (engine still keeps full seed for RSI).
CHART_MAX_POINTS = 100_000

CACHE_VERSION = "hist_3y_v1"


def _safe_key(instrument_key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", instrument_key)


def cache_path(cache_dir: Path, instrument_key: str, timeframe: int) -> Path:
    return (
        cache_dir
        / CACHE_VERSION
        / f"{_safe_key(instrument_key)}_{timeframe}m.json"
    )


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


def load_cached_candles(
    cache_dir: Path,
    instrument_key: str,
    timeframe: int,
) -> list[Candle] | None:
    path = cache_path(cache_dir, instrument_key, timeframe)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("candles") if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or not rows:
            return None
        candles = [Candle.from_dict(row) for row in rows]
        lookback = (
            int(payload.get("lookback_days", 0))
            if isinstance(payload, dict)
            else 0
        )
        if lookback and lookback < HISTORY_LOOKBACK_DAYS // 2:
            logger.info(
                "Ignoring short cache for %dm (%d lookback days) at %s",
                timeframe,
                lookback,
                path,
            )
            return None
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
    from_date: date | None = None,
    to_date: date | None = None,
) -> Path:
    path = cache_path(cache_dir, instrument_key, timeframe)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "instrument_key": instrument_key,
        "timeframe": timeframe,
        "lookback_days": HISTORY_LOOKBACK_DAYS,
        "lookback_years": HISTORY_LOOKBACK_YEARS,
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": to_date.isoformat() if to_date else None,
        "saved_at": datetime.now(tz=IST).isoformat(),
        "candles": [c.as_dict() for c in candles],
    }
    # Compact JSON — multi-year seeds are large.
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    logger.info("Saved %dm seed cache (%d candles) → %s", timeframe, len(candles), path)
    return path


def _history_api(access_token: str) -> upstox_client.HistoryV3Api:
    configuration = upstox_client.Configuration()
    configuration.access_token = access_token
    return upstox_client.HistoryV3Api(upstox_client.ApiClient(configuration))


def _parse_raw_candles(raw_candles: list | None) -> list[Candle]:
    candles: list[Candle] = []
    for row in raw_candles or []:
        parsed = parse_upstox_candle_row(row)
        if parsed is not None:
            candles.append(parsed)
    return candles


def fetch_intraday_candles(
    access_token: str,
    instrument_key: str,
    timeframe: int,
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

    candles = _parse_raw_candles(list(raw_candles or []))
    candles.sort(key=lambda c: c.ts)
    logger.info(
        "Fetched %dm intraday: %d candles for %s",
        timeframe,
        len(candles),
        instrument_key,
    )
    return candles


def fetch_historical_candles(
    access_token: str,
    instrument_key: str,
    timeframe: int,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[Candle]:
    """Chunked Upstox historical candles for ``timeframe`` minutes."""
    api = _history_api(access_token)
    today = datetime.now(tz=IST).date()
    to_d = to_date or today
    from_d = from_date or (to_d - timedelta(days=HISTORY_LOOKBACK_DAYS - 1))
    chunk_days = CHUNK_DAYS_BY_TF.get(int(timeframe), 30)

    by_ts: dict[datetime, Candle] = {}
    errors = 0
    for chunk_from, chunk_to in _daterange_chunks(from_d, to_d, chunk_days):
        try:
            response = api.get_historical_candle_data1(
                instrument_key,
                "minutes",
                str(int(timeframe)),
                chunk_to.isoformat(),
                chunk_from.isoformat(),
            )
        except ApiException as exc:
            errors += 1
            logger.warning(
                "Historical %dm chunk %s→%s failed [%s]: %s",
                timeframe,
                chunk_from,
                chunk_to,
                getattr(exc, "status", "?"),
                getattr(exc, "body", exc),
            )
            continue

        data = getattr(response, "data", None)
        raw_candles = getattr(data, "candles", None) if data is not None else None
        if raw_candles is None and isinstance(response, dict):
            raw_candles = (response.get("data") or {}).get("candles")
        for candle in _parse_raw_candles(list(raw_candles or [])):
            by_ts[candle.ts] = candle

    candles = [by_ts[k] for k in sorted(by_ts.keys())]
    logger.info(
        "Fetched %dm historical: %d candles (%s→%s, errors=%d) for %s",
        timeframe,
        len(candles),
        from_d,
        to_d,
        errors,
        instrument_key,
    )
    return candles


def _merge_candles(*groups: list[Candle]) -> list[Candle]:
    by_ts: dict[datetime, Candle] = {}
    for group in groups:
        for candle in group:
            by_ts[candle.ts] = candle
    return [by_ts[k] for k in sorted(by_ts.keys())]


def _as_ist_date(ts: datetime) -> date:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=IST).date()
    return ts.astimezone(IST).date()


def _prune_to_lookback(candles: list[Candle], lookback_days: int) -> list[Candle]:
    if not candles or lookback_days <= 0:
        return candles
    today = datetime.now(tz=IST).date()
    earliest = today - timedelta(days=max(1, lookback_days) - 1)
    return [c for c in candles if _as_ist_date(c.ts) >= earliest]


def seed_timeframe_candles(
    access_token: str,
    instrument_key: str,
    timeframe: int,
    cache_dir: Path,
    *,
    limit: int = 0,
    force_refresh: bool = False,
    lookback_days: int = HISTORY_LOOKBACK_DAYS,
) -> list[Candle]:
    """Return multi-year candles, incrementally updating from the last cached bar.

    - First run / ``force_refresh``: full ~3y historical + intraday.
    - Later runs: keep cache, re-fetch from the last recorded day through today,
      merge, prune to lookback window, and rewrite cache.
    """
    today = datetime.now(tz=IST).date()
    from_d_full = today - timedelta(days=max(1, lookback_days) - 1)

    cached: list[Candle] | None = None
    if not force_refresh:
        cached = load_cached_candles(cache_dir, instrument_key, timeframe)

    if cached:
        last_ts = max(c.ts for c in cached)
        last_day = _as_ist_date(last_ts)
        # Drop last calendar day from cache and re-pull it so a partial session
        # can be completed, then append any newer days.
        retained = [c for c in cached if _as_ist_date(c.ts) < last_day]

        incremental: list[Candle] = []
        if last_day <= today:
            try:
                incremental = fetch_historical_candles(
                    access_token,
                    instrument_key,
                    timeframe,
                    from_date=last_day,
                    to_date=today,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Incremental historical fetch failed for %dm (%s→%s): %s",
                    timeframe,
                    last_day,
                    today,
                    exc,
                )

        try:
            intraday = fetch_intraday_candles(access_token, instrument_key, timeframe)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Intraday fetch failed during incremental seed: %s", exc)
            intraday = []

        candles = _prune_to_lookback(
            _merge_candles(retained, incremental, intraday),
            lookback_days,
        )
        logger.info(
            "Incremental %dm seed: cache=%d retained=%d hist=%d intra=%d → %d (from %s)",
            timeframe,
            len(cached),
            len(retained),
            len(incremental),
            len(intraday),
            len(candles),
            last_day,
        )
        if candles:
            save_cached_candles(
                cache_dir,
                instrument_key,
                timeframe,
                candles,
                from_date=_as_ist_date(candles[0].ts),
                to_date=_as_ist_date(candles[-1].ts),
            )
        if limit > 0 and len(candles) > limit:
            return candles[-limit:]
        return candles

    # Cold start: full lookback.
    logger.info(
        "No usable %dm cache — fetching full ~%dy history (%s→%s)",
        timeframe,
        max(1, lookback_days // 365),
        from_d_full,
        today,
    )
    historical = fetch_historical_candles(
        access_token,
        instrument_key,
        timeframe,
        from_date=from_d_full,
        to_date=today,
    )
    try:
        intraday = fetch_intraday_candles(access_token, instrument_key, timeframe)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Intraday fetch failed during seed: %s", exc)
        intraday = []

    candles = _prune_to_lookback(_merge_candles(historical, intraday), lookback_days)
    if candles:
        save_cached_candles(
            cache_dir,
            instrument_key,
            timeframe,
            candles,
            from_date=_as_ist_date(candles[0].ts),
            to_date=_as_ist_date(candles[-1].ts),
        )
    if limit > 0 and len(candles) > limit:
        return candles[-limit:]
    return candles


def seed_all_timeframes(
    access_token: str,
    instrument_key: str,
    timeframes: list[int],
    cache_dir: Path,
    *,
    limit: int = 0,
    force_refresh: bool = False,
    lookback_days: int = HISTORY_LOOKBACK_DAYS,
) -> dict[int, list[Candle]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    out: dict[int, list[Candle]] = {}
    workers = min(3, max(1, len(timeframes)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                seed_timeframe_candles,
                access_token,
                instrument_key,
                tf,
                cache_dir,
                limit=limit,
                force_refresh=force_refresh,
                lookback_days=lookback_days,
            ): tf
            for tf in timeframes
        }
        for fut in as_completed(futures):
            tf = futures[fut]
            out[tf] = fut.result()
    return out


def trim_points(points: list[dict], max_points: int = CHART_MAX_POINTS) -> list[dict]:
    if max_points > 0 and len(points) > max_points:
        return points[-max_points:]
    return points
