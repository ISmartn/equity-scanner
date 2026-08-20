from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from ..config import ROOT_DIR, get_access_token
from ..db.store import get_store
from . import upstox_client

logger = logging.getLogger(__name__)

# Delay between tickers (8 sequential Upstox calls each).
REQUEST_DELAY_SEC = 1.5
SECTION_DELAY_SEC = 0.4
DEFAULT_ERROR_LOG = ROOT_DIR / "data" / "fundamentals_sync_errors.log"
MAX_RETRIES = 6
INITIAL_BACKOFF_SEC = 3.0
MAX_BACKOFF_SEC = 120.0

REQUIRED_SECTIONS = (
    "profile",
    "balance_sheet",
    "cash_flow",
    "income_statement",
    "share_holdings",
    "key_ratios",
    "corporate_actions",
)

FundamentalsProgressCallback = Callable[[dict[str, Any]], None]
SectionFetcher = Callable[[], Awaitable[dict[str, Any]]]


def _extract_data(response: dict[str, Any] | None) -> Any:
    if not response:
        return None
    if "data" in response:
        return response["data"]
    return response


def _statement_has_numeric_history(section: Any, *, kind: str) -> bool:
    """True when income/cash/balance payloads include usable period values."""
    if not isinstance(section, dict):
        return False
    full = section.get("full_statement")
    if isinstance(full, list) and full:
        return True
    if kind == "balance":
        hist = section.get("history")
        return isinstance(hist, list) and bool(hist)

    rows_key = "income_statement" if kind == "income" else "cash_flow"
    rows = section.get(rows_key)
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        hist = row.get("history")
        if isinstance(hist, list) and hist:
            return True
    return False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_rate_limited(exc: BaseException) -> bool:
    text = str(exc)
    return "429" in text or "UDAPI10005" in text or "Too Many Request" in text


def parse_error_log(log_path: Path | str) -> dict[str, set[str]]:
    """Read tickers with error/partial entries from an existing log file."""
    path = Path(log_path)
    errors: set[str] = set()
    partials: set[str] = set()
    if not path.is_file():
        return {"error": errors, "partial": partials}

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", 3)
        if len(parts) < 4:
            continue
        kind = parts[1].strip().lower()
        ticker = parts[2].strip().upper()
        if not ticker:
            continue
        if kind == "error":
            errors.add(ticker)
        elif kind == "partial":
            partials.add(ticker)
    return {"error": errors, "partial": partials}


def _log_error(
    handle: TextIO | None,
    ticker: str,
    message: str,
    *,
    kind: str = "error",
    terminal: bool = False,
) -> None:
    line = f"{_utc_now_iso()}\t{kind}\t{ticker}\t{message}\n"
    if handle is not None:
        handle.write(line)
        handle.flush()
    if terminal:
        logger.error("[%s] %s: %s", kind, ticker, message)
    else:
        logger.debug("[%s] %s: %s", kind, ticker, message)


async def _fetch_with_retry(
    factory: SectionFetcher,
    *,
    section_delay_sec: float,
) -> dict[str, Any]:
    backoff = INITIAL_BACKOFF_SEC
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            return await factory()
        except Exception as exc:
            last_exc = exc
            if _is_rate_limited(exc) and attempt < MAX_RETRIES - 1:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SEC)
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("fetch failed without exception")


async def fetch_fundamentals_for_ticker(
    ticker: str,
    access_token: str | None,
    *,
    force: bool = False,
    section_delay_sec: float = SECTION_DELAY_SEC,
) -> dict[str, Any]:
    store = get_store()
    ticker_norm = ticker.strip().upper()
    token = get_access_token(access_token)
    if not token:
        raise RuntimeError("Upstox access token required for fundamentals sync")

    if not force:
        cached = store.get_fundamentals(ticker_norm)
        if cached:
            return cached

    profile_row = store.get_profile_by_ticker(ticker_norm)
    if not profile_row:
        raise ValueError(f"No security profile for {ticker_norm}. Run profile sync first.")
    isin = profile_row.get("isin")
    if not isin:
        raise ValueError(f"No ISIN for {ticker_norm}. Run profile sync first.")
    instrument_key = profile_row.get("instrument_token")

    fetchers: list[tuple[str, SectionFetcher | None]] = [
        ("profile", lambda: upstox_client.get_company_profile(token, isin)),
        ("balance_sheet", lambda: upstox_client.get_balance_sheet(token, isin)),
        ("cash_flow", lambda: upstox_client.get_cash_flow(token, isin)),
        ("income_statement", lambda: upstox_client.get_income_statement(token, isin)),
        ("share_holdings", lambda: upstox_client.get_share_holdings(token, isin)),
        ("key_ratios", lambda: upstox_client.get_key_ratios(token, isin)),
        ("corporate_actions", lambda: upstox_client.get_corporate_actions(token, isin)),
        (
            "competitors",
            (lambda: upstox_client.get_competitors(token, instrument_key))
            if instrument_key
            else None,
        ),
    ]

    payload: dict[str, Any] = {}
    errors: list[str] = []

    for key, factory in fetchers:
        if factory is None:
            continue
        try:
            response = await _fetch_with_retry(
                factory,
                section_delay_sec=section_delay_sec,
            )
            payload[key] = _extract_data(response)
        except Exception as exc:
            errors.append(f"{key}: {exc}")
            logger.debug("Fundamentals %s fetch failed for %s: %s", key, ticker_norm, exc)
        await asyncio.sleep(section_delay_sec)

    # Many NSE names (e.g. IRFC) publish usable statements only as standalone.
    # Consolidated responses can be empty shells — fall back when histories are blank.
    statement_kinds = (
        ("balance_sheet", "balance", upstox_client.get_balance_sheet),
        ("cash_flow", "cash", upstox_client.get_cash_flow),
        ("income_statement", "income", upstox_client.get_income_statement),
    )
    for key, kind, fetcher in statement_kinds:
        if _statement_has_numeric_history(payload.get(key), kind=kind):
            continue
        try:
            response = await _fetch_with_retry(
                lambda f=fetcher: f(token, isin, type="standalone"),
                section_delay_sec=section_delay_sec,
            )
            standalone = _extract_data(response)
            if _statement_has_numeric_history(standalone, kind=kind):
                payload[key] = standalone
                payload.setdefault("_meta", {})
                if isinstance(payload["_meta"], dict):
                    payload["_meta"][f"{key}_type"] = "standalone"
                logger.info(
                    "Fundamentals %s for %s: using standalone (consolidated empty)",
                    key,
                    ticker_norm,
                )
        except Exception as exc:
            errors.append(f"{key}_standalone: {exc}")
            logger.debug(
                "Fundamentals %s standalone fallback failed for %s: %s",
                key,
                ticker_norm,
                exc,
            )
        await asyncio.sleep(section_delay_sec)

    # Quarterly income for QoQ / YoY momentum (prefer same filing type as yearly).
    income_type = "consolidated"
    meta = payload.get("_meta")
    if isinstance(meta, dict) and meta.get("income_statement_type") == "standalone":
        income_type = "standalone"
    elif isinstance(payload.get("income_statement"), dict):
        # Heuristic: if yearly only filled after standalone fallback, meta is set;
        # otherwise try consolidated first then standalone.
        pass

    quarterly_types = [income_type]
    if "standalone" not in quarterly_types:
        quarterly_types.append("standalone")
    if "consolidated" not in quarterly_types:
        quarterly_types.append("consolidated")

    quarterly_data: Any = None
    for qtype in quarterly_types:
        try:
            response = await _fetch_with_retry(
                lambda t=qtype: upstox_client.get_income_statement(
                    token,
                    isin,
                    type=t,
                    time_period="quarterly",
                ),
                section_delay_sec=section_delay_sec,
            )
            candidate = _extract_data(response)
            if _statement_has_numeric_history(candidate, kind="income"):
                quarterly_data = candidate
                payload.setdefault("_meta", {})
                if isinstance(payload["_meta"], dict):
                    payload["_meta"]["income_statement_quarterly_type"] = qtype
                logger.info(
                    "Fundamentals income_statement_quarterly for %s: type=%s",
                    ticker_norm,
                    qtype,
                )
                break
            if quarterly_data is None:
                quarterly_data = candidate
        except Exception as exc:
            errors.append(f"income_statement_quarterly_{qtype}: {exc}")
            logger.debug(
                "Fundamentals quarterly income (%s) failed for %s: %s",
                qtype,
                ticker_norm,
                exc,
            )
        await asyncio.sleep(section_delay_sec)

    if quarterly_data is not None:
        payload["income_statement_quarterly"] = quarterly_data

    if not instrument_key:
        errors.append("competitors: no instrument_key in profile")

    if not any(payload.get(section) is not None for section in REQUIRED_SECTIONS):
        raise RuntimeError(f"All fundamentals fetches failed for {ticker_norm}: {'; '.join(errors)}")

    store.upsert_fundamentals(ticker_norm, isin, payload)
    result = store.get_fundamentals(ticker_norm)
    if result is None:
        raise RuntimeError(f"Failed to persist fundamentals for {ticker_norm}")
    if errors:
        result["partial_errors"] = errors
    return result


async def sync_fundamentals_tickers(
    tickers: list[str],
    access_token: str | None,
    *,
    force: bool = False,
    request_delay_sec: float = REQUEST_DELAY_SEC,
    section_delay_sec: float = SECTION_DELAY_SEC,
    retry_from_log: bool = True,
    on_progress: FundamentalsProgressCallback | None = None,
    error_log_path: Path | str | None = None,
) -> dict[str, Any]:
    return await sync_all_fundamentals(
        access_token,
        force=force,
        tickers=tickers,
        request_delay_sec=request_delay_sec,
        section_delay_sec=section_delay_sec,
        retry_from_log=retry_from_log,
        on_progress=on_progress,
        error_log_path=error_log_path,
    )


async def sync_all_fundamentals(
    access_token: str | None = None,
    *,
    force: bool = False,
    tickers: list[str] | None = None,
    limit: int | None = None,
    request_delay_sec: float = REQUEST_DELAY_SEC,
    section_delay_sec: float = SECTION_DELAY_SEC,
    retry_from_log: bool = True,
    on_progress: FundamentalsProgressCallback | None = None,
    error_log_path: Path | str | None = None,
) -> dict[str, Any]:
    store = get_store()
    token = get_access_token(access_token)
    if not token:
        raise RuntimeError("Upstox access token required. Set UPSTOX_ACCESS_TOKEN in .env")

    log_path = Path(error_log_path) if error_log_path else DEFAULT_ERROR_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)

    prior_log = parse_error_log(log_path) if retry_from_log and not force else {"error": set(), "partial": set()}
    retry_tickers = prior_log["error"] | prior_log["partial"]

    ticker_filter = [t.strip().upper() for t in tickers if t.strip()] if tickers else None
    profiles = store.list_profiles_with_isin(tickers=ticker_filter, limit=limit)
    cached_tickers = store.list_fundamentals_tickers()

    queue: list[str] = []
    skipped_ok = 0
    for profile in profiles:
        ticker = profile["ticker"]
        if force:
            queue.append(ticker)
            continue
        if ticker in cached_tickers and ticker not in retry_tickers:
            skipped_ok += 1
            continue
        queue.append(ticker)

    total = len(queue)
    success: list[str] = []
    failed: dict[str, str] = {}
    partial: dict[str, list[str]] = {}

    def emit(current_ticker: str | None = None) -> None:
        if on_progress:
            on_progress(
                {
                    "total": total,
                    "processed": len(success) + len(failed),
                    "success": len(success),
                    "failed": len(failed),
                    "skipped": skipped_ok,
                    "skipped_retry_queued": len(retry_tickers & cached_tickers),
                    "current_ticker": current_ticker,
                    "error_log": str(log_path),
                }
            )

    emit()

    log_mode = "a" if log_path.exists() and log_path.stat().st_size > 0 else "w"
    with log_path.open(log_mode, encoding="utf-8") as error_log:
        error_log.write(f"\n# fundamentals bulk sync started {_utc_now_iso()}\n")
        error_log.write(f"# force={force} queued={total} skipped_ok={skipped_ok}\n")
        error_log.flush()

        for ticker in queue:
            emit(ticker)
            try:
                result = await fetch_fundamentals_for_ticker(
                    ticker,
                    token,
                    force=True,
                    section_delay_sec=section_delay_sec,
                )
                success.append(ticker)
                partial_errors = result.get("partial_errors") or []
                if partial_errors:
                    partial[ticker] = partial_errors
                    _log_error(
                        error_log,
                        ticker,
                        "; ".join(partial_errors),
                        kind="partial",
                    )
            except Exception as exc:
                failed[ticker] = str(exc)
                _log_error(error_log, ticker, str(exc), kind="error")
            await asyncio.sleep(request_delay_sec)

        emit(None)

        error_log.write(
            f"# completed {_utc_now_iso()}: "
            f"{len(success)} ok, {len(failed)} failed, {len(partial)} partial, "
            f"{skipped_ok} skipped (cached, no log errors)\n"
        )
        error_log.flush()

    return {
        "profiles_with_isin": len(profiles),
        "queued": total,
        "skipped_cached_ok": skipped_ok,
        "skipped_cached": skipped_ok,
        "retry_from_log": sorted(retry_tickers) if retry_tickers else [],
        "success": len(success),
        "failed": len(failed),
        "partial": len(partial),
        "tickers_synced": success,
        "errors": failed,
        "partial_errors": partial,
        "error_log": str(log_path),
    }
