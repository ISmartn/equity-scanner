from __future__ import annotations

import asyncio
import logging
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal, TextIO

import aiohttp

from ..config import ROOT_DIR, get_access_token, normalize_symbol
from ..db.store import TimelineStore, get_store
from . import nse_client, upstox_client
from .market_data import _transform_upstox_candles

logger = logging.getLogger(__name__)

SourcePreference = Literal["auto", "upstox", "nse"]
IngestProgressCallback = Callable[[dict[str, Any]], None]
CancelChecker = Callable[[], bool]

DEFAULT_REQUEST_DELAY_SEC = 0.35
DEFAULT_CONCURRENCY = 3
DEFAULT_DAILY_DAYS = 7
DEFAULT_BOOTSTRAP_DAYS = 30
MAX_RETRIES = 5
CHUNK_DAYS = 364
DEFAULT_ERROR_LOG = ROOT_DIR / "data" / "candle_ingest_errors.log"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_ingest_error(
    handle: TextIO | None,
    ticker: str,
    message: str,
    *,
    kind: str = "error",
) -> None:
    line = f"{_utc_now_iso()}\t{kind}\t{ticker}\t{message}\n"
    if handle is not None:
        handle.write(line)
        handle.flush()
    logger.warning("[%s] %s: %s", kind, ticker, message)


def parse_ingest_error_log(log_path: Path | str) -> dict[str, Any]:
    path = Path(log_path)
    errors: set[str] = set()
    error_counts: dict[str, int] = {}
    if not path.is_file():
        return {"error": errors, "error_counts": error_counts}

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", 3)
        if len(parts) < 4:
            continue
        kind = parts[1].strip().lower()
        ticker = parts[2].strip().upper()
        if kind == "error" and ticker:
            errors.add(ticker)
            error_counts[ticker] = error_counts.get(ticker, 0) + 1
    return {"error": errors, "error_counts": error_counts}


def _is_transient_ingest_error(message: str) -> bool:
    text = message.lower()
    if "nse returned html" in text or "session expired or rate limited" in text:
        return True
    if "unable to establish nse session" in text:
        return True
    return False


def _ingest_skip_reason(message: str) -> str:
    text = message.lower()
    if "invalid instrument key" in text or "udapi100011" in text:
        return "upstox_invalid_instrument"
    if "unexpected mimetype: text/html" in text:
        return "nse_blocked_or_delisted"
    return "ingest_repeat_failure"


def _should_auto_skip(message: str, prior_error_count: int) -> bool:
    """Mark profile ingest_skip after repeat failures or clearly permanent errors."""
    if _is_transient_ingest_error(message):
        return False
    if prior_error_count >= 1:
        return True
    text = message.lower()
    if "invalid instrument key" in text or "udapi100011" in text:
        return True
    return False


def resolve_profile_from_date(
    last_trade_date: str | None,
    to_date: date,
    *,
    since_last: bool,
    days: int | None,
    years: int,
    bootstrap_days: int = DEFAULT_BOOTSTRAP_DAYS,
) -> date | None:
    """Return the fetch start date for one symbol, or None if already current."""
    if since_last:
        if last_trade_date is None:
            window = days if days is not None else bootstrap_days
            return to_date - timedelta(days=window)
        last = date.fromisoformat(last_trade_date)
        if last >= to_date:
            return None
        return last + timedelta(days=1)

    if days is not None:
        return to_date - timedelta(days=days)
    return to_date - timedelta(days=years * 365)


def calc_daily_return_pct(open_price: float, close_price: float) -> float | None:
    if not open_price:
        return None
    return round((close_price - open_price) / open_price * 100, 4)


def candles_to_rows(
    instrument_token: str,
    candles: list[dict[str, Any]],
    source: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candle in candles:
        open_price = float(candle["open"])
        close_price = float(candle["close"])
        rows.append(
            {
                "trade_date": candle["date"],
                "instrument_token": instrument_token,
                "open_price": open_price,
                "high_price": float(candle["high"]),
                "low_price": float(candle["low"]),
                "close_price": close_price,
                "volume": int(float(candle.get("volume") or 0)),
                "daily_return_pct": calc_daily_return_pct(open_price, close_price),
                "source": source,
            }
        )
    return rows


async def _fetch_upstox_range(
    session: aiohttp.ClientSession,
    instrument_token: str,
    from_date: date,
    to_date: date,
    access_token: str | None,
) -> list[dict[str, Any]]:
    del session  # Upstox SDK is sync; kept for signature parity with NSE fetch.
    merged: dict[str, dict[str, Any]] = {}
    chunk_start = from_date
    while chunk_start <= to_date:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), to_date)
        raw = await upstox_client.get_historical_candles(
            access_token,
            instrument_token,
            "days",
            "1",
            chunk_end.strftime("%Y-%m-%d"),
            chunk_start.strftime("%Y-%m-%d"),
        )
        for candle in _transform_upstox_candles(raw):
            merged[candle["date"]] = candle
        chunk_start = chunk_end + timedelta(days=1)
    return [merged[key] for key in sorted(merged)]


async def _fetch_nse_range(
    session: aiohttp.ClientSession,
    ticker: str,
    from_date: date,
    to_date: date,
) -> list[dict[str, Any]]:
    return await nse_client.fetch_equity_historical_range(
        session,
        ticker,
        from_date,
        to_date,
        chunk_days=CHUNK_DAYS,
    )


def _upstox_invalid_instrument(exc: Exception) -> bool:
    text = str(exc)
    return "Invalid Instrument key" in text or "UDAPI100011" in text


async def fetch_candles_for_profile(
    session: aiohttp.ClientSession,
    profile: dict[str, Any],
    from_date: date,
    to_date: date,
    access_token: str | None,
    source_preference: SourcePreference = "auto",
) -> tuple[list[dict[str, Any]], str]:
    instrument_token = profile["instrument_token"]
    ticker = profile["ticker"]

    if source_preference == "nse":
        candles = await _fetch_nse_range(session, ticker, from_date, to_date)
        return candles, "nse"

    if source_preference == "upstox":
        candles = await _fetch_upstox_range(session, instrument_token, from_date, to_date, access_token)
        return candles, "upstox"

    try:
        candles = await _fetch_upstox_range(session, instrument_token, from_date, to_date, access_token)
        return candles, "upstox"
    except Exception as exc:
        if _upstox_invalid_instrument(exc):
            logger.info("Upstox invalid instrument for %s, falling back to NSE", ticker)
            candles = await _fetch_nse_range(session, ticker, from_date, to_date)
            return candles, "nse"
        logger.debug("Upstox failed for %s, falling back to NSE: %s", ticker, exc)
        candles = await _fetch_nse_range(session, ticker, from_date, to_date)
        return candles, "nse"


def _is_non_retryable_ingest_error(exc: Exception) -> bool:
    text = str(exc)
    if isinstance(exc, nse_client.NseSessionError):
        return False
    if "unexpected mimetype: text/html" in text:
        return True
    return False


async def ingest_profile_with_retry(
    session: aiohttp.ClientSession,
    store: TimelineStore,
    profile: dict[str, Any],
    from_date: date,
    to_date: date,
    access_token: str | None,
    source_preference: SourcePreference = "auto",
    should_cancel: CancelChecker | None = None,
    error_log: TextIO | None = None,
) -> dict[str, Any]:
    ticker = profile["ticker"]
    last_error: str | None = None
    max_attempts = 2 if source_preference == "nse" else MAX_RETRIES

    for attempt in range(max_attempts):
        if should_cancel and should_cancel():
            return {"ticker": ticker, "status": "cancelled", "error": "ingest cancelled"}

        try:
            candles, source = await fetch_candles_for_profile(
                session,
                profile,
                from_date,
                to_date,
                access_token,
                source_preference,
            )
            rows = candles_to_rows(profile["instrument_token"], candles, source)
            inserted = store.upsert_candles(rows)
            return {
                "ticker": ticker,
                "status": "ok",
                "bars": inserted,
                "source": source,
                "from_date": from_date.isoformat(),
            }
        except Exception as exc:
            last_error = str(exc)
            if isinstance(exc, nse_client.NseSessionError):
                nse_client._invalidate_nse_session()
            if _is_non_retryable_ingest_error(exc):
                logger.warning("Ingest failed for %s (no retry): %s", ticker, exc)
                break

            backoff = min(2 ** attempt * 0.5 + random.uniform(0, 0.3), 30)
            logger.warning(
                "Ingest retry %d/%d for %s: %s (sleep %.1fs)",
                attempt + 1,
                max_attempts,
                ticker,
                exc,
                backoff,
            )
            slept = 0.0
            while slept < backoff:
                if should_cancel and should_cancel():
                    return {"ticker": ticker, "status": "cancelled", "error": "ingest cancelled"}
                step = min(0.25, backoff - slept)
                await asyncio.sleep(step)
                slept += step

    status = "cancelled" if should_cancel and should_cancel() else "error"
    message = last_error or "unknown error"
    if status == "error":
        _log_ingest_error(error_log, ticker, message)
    return {"ticker": ticker, "status": status, "error": message}


async def ingest_candles(
    *,
    years: int = 2,
    days: int | None = None,
    limit: int | None = None,
    tickers: list[str] | None = None,
    refresh_all: bool = False,
    since_last: bool = False,
    bootstrap_days: int = DEFAULT_BOOTSTRAP_DAYS,
    source_preference: SourcePreference = "auto",
    request_delay_sec: float = DEFAULT_REQUEST_DELAY_SEC,
    concurrency: int = DEFAULT_CONCURRENCY,
    error_log_path: str | Path | None = None,
    access_token: str | None = None,
    store: TimelineStore | None = None,
    on_progress: IngestProgressCallback | None = None,
    should_cancel: CancelChecker | None = None,
) -> dict[str, Any]:
    db = store or get_store()
    token = get_access_token(access_token)
    to_date = date.today()
    default_from_date = resolve_profile_from_date(
        None,
        to_date,
        since_last=False,
        days=days,
        years=years,
        bootstrap_days=bootstrap_days,
    )
    assert default_from_date is not None

    if tickers:
        profiles = []
        for raw in tickers:
            profile = db.get_profile_by_ticker(normalize_symbol(raw))
            if profile:
                profiles.append(profile)
    elif refresh_all:
        profiles = db.list_profiles(limit=limit)
    else:
        profiles = db.profiles_missing_candles(limit=limit)
        if not profiles and limit:
            profiles = db.list_profiles(limit=limit)

    ingest_skip_count = 0
    if not tickers:
        ingest_skipped = [p for p in profiles if p.get("ingest_skip")]
        profiles = [p for p in profiles if not p.get("ingest_skip")]
        ingest_skip_count = len(ingest_skipped)

    if not profiles:
        if ingest_skip_count:
            return {
                "processed": ingest_skip_count,
                "success": 0,
                "failed": 0,
                "skipped": ingest_skip_count,
                "total_bars": 0,
                "message": "All remaining profiles are marked ingest-skip (delisted / not in NSE master).",
            }
        hint = "Use --upto-date for daily updates when all symbols already have history."
        return {
            "processed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "total_bars": 0,
            "message": f"No profiles to ingest. Run profile sync first. {hint}",
        }

    last_dates = db.get_last_trade_dates() if since_last else {}

    success = 0
    failed = 0
    skipped = ingest_skip_count
    empty = 0
    total_bars = 0
    cancelled = False
    results: list[dict[str, Any]] = []
    error_map: dict[str, str] = {}
    total_profiles = len(profiles)
    workers = max(1, concurrency)
    progress_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(workers)

    def emit_progress(current_ticker: str | None = None) -> None:
        if not on_progress:
            return
        on_progress(
            {
                "total": total_profiles,
                "processed": success + failed + skipped + empty,
                "success": success,
                "failed": failed,
                "skipped": skipped,
                "empty": empty,
                "total_bars": total_bars,
                "current_ticker": current_ticker,
                "recent_errors": [
                    {"ticker": ticker, "error": message}
                    for ticker, message in list(error_map.items())[-12:]
                ],
            }
        )

    async def record_result(result: dict[str, Any]) -> None:
        nonlocal success, failed, skipped, empty, total_bars, cancelled
        async with progress_lock:
            results.append(result)
            status = result.get("status")
            ticker = str(result.get("ticker") or "")
            if status == "ok":
                bars = int(result.get("bars") or 0)
                if bars == 0:
                    empty += 1
                else:
                    success += 1
                    total_bars += bars
            elif status == "cancelled":
                cancelled = True
            elif status == "skipped":
                skipped += 1
            else:
                failed += 1
                err = result.get("error")
                if ticker and err:
                    error_map[ticker] = str(err)
            emit_progress(ticker or None)

    emit_progress()

    log_path = Path(error_log_path) if error_log_path else DEFAULT_ERROR_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    prior_error_counts = parse_ingest_error_log(log_path).get("error_counts", {})
    ingest_skip_marked = 0

    async with aiohttp.ClientSession() as session:
        await nse_client.fetch_equity_master(session)

        with log_path.open("a", encoding="utf-8") as error_log:
            error_log.write(
                f"\n# ingest started {_utc_now_iso()} since_last={since_last} "
                f"concurrency={workers} profiles={total_profiles}\n"
            )
            error_log.flush()

            async def process_profile(profile: dict[str, Any]) -> None:
                nonlocal cancelled, ingest_skip_marked
                if cancelled:
                    return
                if should_cancel and should_cancel():
                    cancelled = True
                    return

                ticker = profile["ticker"]
                instrument_token = profile["instrument_token"]
                async with progress_lock:
                    emit_progress(ticker)

                if since_last:
                    profile_from_date = resolve_profile_from_date(
                        last_dates.get(instrument_token),
                        to_date,
                        since_last=True,
                        days=days,
                        years=years,
                        bootstrap_days=bootstrap_days,
                    )
                    if profile_from_date is None:
                        await record_result(
                            {
                                "ticker": ticker,
                                "status": "skipped",
                                "reason": "up_to_date",
                                "last_date": last_dates.get(instrument_token),
                            }
                        )
                        return
                else:
                    profile_from_date = default_from_date

                async with semaphore:
                    if should_cancel and should_cancel():
                        cancelled = True
                        return
                    result = await ingest_profile_with_retry(
                        session,
                        db,
                        profile,
                        profile_from_date,
                        to_date,
                        token,
                        source_preference,
                        should_cancel=should_cancel,
                        error_log=error_log,
                    )
                    if result.get("status") == "ok" and profile.get("ingest_skip"):
                        db.set_ingest_skip(ticker, False, None)
                    elif result.get("status") == "error":
                        err_msg = str(result.get("error") or "")
                        prior = int(prior_error_counts.get(ticker.upper(), 0))
                        if _should_auto_skip(err_msg, prior):
                            reason = _ingest_skip_reason(err_msg)
                            if db.set_ingest_skip(ticker, True, reason):
                                ingest_skip_marked += 1
                                _log_ingest_error(
                                    error_log,
                                    ticker,
                                    f"marked ingest_skip ({reason})",
                                    kind="skip",
                                )
                    await record_result(result)
                    if result.get("status") == "cancelled":
                        cancelled = True
                        return
                    if request_delay_sec > 0:
                        await asyncio.sleep(request_delay_sec)

            await asyncio.gather(*(process_profile(profile) for profile in profiles))

    emit_progress(None)

    processed = success + failed + skipped + empty
    return {
        "processed": processed,
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "empty": empty,
        "total_bars": total_bars,
        "cancelled": cancelled,
        "from_date": default_from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "days": days,
        "years": years if days is None and not since_last else None,
        "refresh_all": refresh_all,
        "since_last": since_last,
        "concurrency": workers,
        "error_log": str(log_path),
        "ingest_skip_marked": ingest_skip_marked,
        "errors": error_map,
        "results": results,
    }
