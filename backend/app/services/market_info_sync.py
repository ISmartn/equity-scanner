from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

import aiohttp

from ..config import INDEX_INSTRUMENT_KEYS, get_access_token, normalize_symbol
from ..db.store import get_store
from . import nse_client, upstox_client

logger = logging.getLogger(__name__)

REQUEST_DELAY_SEC = 0.5
MAX_RETRIES = 5
INITIAL_BACKOFF_SEC = 2.0
MAX_BACKOFF_SEC = 60.0
DEFAULT_BUCKET_INTERVAL = 60
DEFAULT_CHANGE_OI_INTERVAL = "5"
DEFAULT_FLOW_LOOKBACK_DAYS = 90

FII_DATA_TYPES = (
    "NSE_EQ|CASH",
    "NSE_FO|INDEX_FUTURES",
    "NSE_FO|STOCK_FUTURES",
    "NSE_FO|INDEX_OPTIONS",
    "NSE_FO|STOCK_OPTIONS",
)

DII_DATA_TYPES = ("NSE_EQ|CASH",)

DEFAULT_INDEX_WATCHLIST: list[dict[str, Any]] = [
    {"symbol": "NIFTY", "instrument_key": INDEX_INSTRUMENT_KEYS["NIFTY"], "index": True},
    {"symbol": "BANKNIFTY", "instrument_key": INDEX_INSTRUMENT_KEYS["BANKNIFTY"], "index": True},
]

DEFAULT_STOCK_FO_WATCHLIST = (
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "INFY",
    "ICICIBANK",
)

MarketInfoProgressCallback = Callable[[dict[str, Any]], None]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_rate_limited(exc: BaseException) -> bool:
    text = str(exc)
    return "429" in text or "UDAPI10005" in text or "Too Many Request" in text


def _extract_data(response: dict[str, Any] | None) -> Any:
    if not response:
        return None
    if "data" in response:
        return response["data"]
    return response


async def _fetch_with_retry(factory: Callable[[], Any]) -> dict[str, Any]:
    backoff = INITIAL_BACKOFF_SEC
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            result = await factory()
            if isinstance(result, dict):
                return result
            return {"data": result}
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


def _flow_rows_from_payload(
    flow_type: str,
    data_type: str,
    interval_code: str,
    payload: Any,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not payload:
        return rows

    if isinstance(payload, dict):
        for key, records in payload.items():
            segment = str(key)
            if not isinstance(records, list):
                continue
            for record in records:
                if not isinstance(record, dict):
                    continue
                ts = record.get("time_stamp") or record.get("timestamp")
                if ts is None:
                    continue
                buy = record.get("buy_amount")
                sell = record.get("sell_amount")
                net = None
                if buy is not None and sell is not None:
                    net = float(buy) - float(sell)
                rows.append(
                    {
                        "flow_type": flow_type,
                        "data_type": segment if segment != data_type else data_type,
                        "interval_code": interval_code,
                        "record_ts": int(ts),
                        "buy_amount": buy,
                        "sell_amount": sell,
                        "net_amount": net,
                        "buy_contracts": record.get("buy_contracts"),
                        "sell_contracts": record.get("sell_contracts"),
                        "oi_contracts": record.get("oi_contracts"),
                        "oi_amount": record.get("oi_amount"),
                        "payload": record,
                    }
                )
        return rows

    if isinstance(payload, list):
        for record in payload:
            if not isinstance(record, dict):
                continue
            ts = record.get("time_stamp") or record.get("timestamp")
            if ts is None:
                continue
            buy = record.get("buy_amount")
            sell = record.get("sell_amount")
            net = None
            if buy is not None and sell is not None:
                net = float(buy) - float(sell)
            rows.append(
                {
                    "flow_type": flow_type,
                    "data_type": data_type,
                    "interval_code": interval_code,
                    "record_ts": int(ts),
                    "buy_amount": buy,
                    "sell_amount": sell,
                    "net_amount": net,
                    "buy_contracts": record.get("buy_contracts"),
                    "sell_contracts": record.get("sell_contracts"),
                    "oi_contracts": record.get("oi_contracts"),
                    "oi_amount": record.get("oi_amount"),
                    "payload": record,
                }
            )
    return rows


def _parse_max_pain_strike(payload: dict[str, Any] | None) -> float | None:
    if not payload:
        return None
    for key in ("max_pain_strike", "max_pain", "strike_price"):
        val = payload.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    insights = payload.get("insights")
    if isinstance(insights, list) and insights:
        last = insights[-1]
        if isinstance(last, dict):
            for key in ("max_pain_strike", "max_pain", "strike_price"):
                val = last.get(key)
                if val is not None:
                    try:
                        return float(val)
                    except (TypeError, ValueError):
                        pass
    return None


def _parse_pcr(payload: dict[str, Any] | None) -> float | None:
    if not payload:
        return None
    val = payload.get("pcr")
    if val is not None:
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
    return None


def resolve_derivative_watchlist(
    *,
    symbols: list[str] | None = None,
    include_indices: bool = True,
    include_stocks: bool = True,
    stock_limit: int = 5,
) -> list[dict[str, Any]]:
    store = get_store()
    watchlist: list[dict[str, Any]] = []

    if include_indices:
        watchlist.extend(DEFAULT_INDEX_WATCHLIST)

    if include_stocks:
        tickers = symbols or list(DEFAULT_STOCK_FO_WATCHLIST[:stock_limit])
        for raw in tickers:
            ticker = normalize_symbol(raw)
            profile = store.get_profile_by_ticker(ticker)
            if profile:
                watchlist.append(
                    {
                        "symbol": ticker,
                        "instrument_key": profile["instrument_token"],
                        "index": False,
                    }
                )
            elif ticker in INDEX_INSTRUMENT_KEYS:
                watchlist.append(
                    {
                        "symbol": ticker,
                        "instrument_key": INDEX_INSTRUMENT_KEYS[ticker],
                        "index": True,
                    }
                )
    return watchlist


async def sync_institutional_flows(
    access_token: str | None,
    *,
    interval: str = "1D",
    from_date: date | None = None,
    request_delay_sec: float = REQUEST_DELAY_SEC,
) -> dict[str, Any]:
    token = get_access_token(access_token)
    if not token:
        raise RuntimeError("Upstox access token required for market info sync")

    store = get_store()
    from_iso = (from_date or date.today() - timedelta(days=DEFAULT_FLOW_LOOKBACK_DAYS)).isoformat()
    all_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    async def pull_fii(data_type: str) -> None:
        resp = await _fetch_with_retry(
            lambda: upstox_client.get_fii_data(token, data_type, interval, from_iso)
        )
        rows = _flow_rows_from_payload("FII", data_type, interval, _extract_data(resp))
        all_rows.extend(rows)

    async def pull_dii(data_type: str) -> None:
        resp = await _fetch_with_retry(
            lambda: upstox_client.get_dii_data(token, data_type, interval, from_iso)
        )
        rows = _flow_rows_from_payload("DII", data_type, interval, _extract_data(resp))
        all_rows.extend(rows)

    for data_type in FII_DATA_TYPES:
        try:
            await pull_fii(data_type)
        except Exception as exc:
            errors.append(f"FII {data_type}: {exc}")
            logger.warning("FII sync failed for %s: %s", data_type, exc)
        await asyncio.sleep(request_delay_sec)

    for data_type in DII_DATA_TYPES:
        try:
            await pull_dii(data_type)
        except Exception as exc:
            errors.append(f"DII {data_type}: {exc}")
            logger.warning("DII sync failed for %s: %s", data_type, exc)
        await asyncio.sleep(request_delay_sec)

    inserted = store.upsert_institutional_flows(all_rows)
    return {
        "flow_rows": inserted,
        "from_date": from_iso,
        "interval": interval,
        "errors": errors,
    }


async def sync_derivative_snapshot_for_underlying(
    session: aiohttp.ClientSession,
    access_token: str | None,
    underlying: dict[str, Any],
    trade_date: date,
    *,
    expiry: str | None = None,
    bucket_interval: int = DEFAULT_BUCKET_INTERVAL,
    change_oi_interval: str = DEFAULT_CHANGE_OI_INTERVAL,
    request_delay_sec: float = REQUEST_DELAY_SEC,
) -> dict[str, Any]:
    token = get_access_token(access_token)
    if not token:
        raise RuntimeError("Upstox access token required for market info sync")

    symbol = underlying["symbol"]
    instrument_key = underlying["instrument_key"]

    if not expiry:
        try:
            expiry = await upstox_client.resolve_nearest_option_expiry(
                token,
                instrument_key,
                trade_date,
            )
        except Exception as exc:
            raise RuntimeError(f"No option expiry for {symbol}: {exc}") from exc
    if not expiry:
        raise ValueError(f"No option expiry found for {symbol}")

    trade_iso = trade_date.isoformat()
    oi_resp = await _fetch_with_retry(
        lambda: upstox_client.get_oi_data(token, instrument_key, expiry, trade_iso)
    )
    await asyncio.sleep(request_delay_sec)

    change_oi_resp = await _fetch_with_retry(
        lambda: upstox_client.get_change_oi_data(
            token, instrument_key, expiry, trade_iso, change_oi_interval
        )
    )
    await asyncio.sleep(request_delay_sec)

    pcr_resp = await _fetch_with_retry(
        lambda: upstox_client.get_pcr_data(
            token, instrument_key, expiry, trade_iso, bucket_interval
        )
    )
    await asyncio.sleep(request_delay_sec)

    max_pain_resp = await _fetch_with_retry(
        lambda: upstox_client.get_max_pain_data(
            token, instrument_key, expiry, trade_iso, bucket_interval
        )
    )

    oi_data = _extract_data(oi_resp) or {}
    pcr_data = _extract_data(pcr_resp) or {}
    max_pain_data = _extract_data(max_pain_resp) or {}

    row = {
        "instrument_key": instrument_key,
        "symbol": symbol,
        "expiry": expiry,
        "trade_date": trade_iso,
        "total_call_oi": oi_data.get("total_calls"),
        "total_put_oi": oi_data.get("total_puts"),
        "spot_close": oi_data.get("spot_closing_price") or pcr_data.get("spot_closing_price"),
        "pcr": _parse_pcr(pcr_data),
        "max_pain_strike": _parse_max_pain_strike(max_pain_data),
        "oi_payload": oi_data if isinstance(oi_data, dict) else {},
        "change_oi_payload": _extract_data(change_oi_resp) or {},
        "pcr_payload": pcr_data if isinstance(pcr_data, dict) else {},
        "max_pain_payload": max_pain_data if isinstance(max_pain_data, dict) else {},
    }
    get_store().upsert_derivative_snapshot(row)
    return row


async def ensure_derivative_snapshots(
    access_token: str | None,
    *,
    trade_date: date,
    symbols: list[str],
    request_delay_sec: float = REQUEST_DELAY_SEC,
) -> dict[str, Any]:
    """Fetch Upstox derivative snapshots only for symbols missing on trade_date."""
    token = get_access_token(access_token)
    if not token:
        raise RuntimeError("Upstox access token required for derivative sync")

    store = get_store()
    trade_iso = trade_date.isoformat()
    normalized = sorted({normalize_symbol(s) for s in symbols if s and s.strip()})
    missing = store.symbols_missing_derivatives(normalized, trade_iso)
    already_present = [s for s in normalized if s not in missing]

    if not missing:
        return {
            "trade_date": trade_iso,
            "requested": len(normalized),
            "already_present": already_present,
            "synced": [],
            "failed": [],
            "skipped_no_profile": [],
        }

    synced: list[str] = []
    failed: list[dict[str, str]] = []
    skipped_no_profile: list[str] = []

    async with aiohttp.ClientSession() as session:
        for index, symbol in enumerate(missing):
            watchlist = resolve_derivative_watchlist(
                symbols=[symbol],
                include_indices=False,
                include_stocks=True,
                stock_limit=1,
            )
            if not watchlist:
                skipped_no_profile.append(symbol)
                continue
            try:
                await sync_derivative_snapshot_for_underlying(
                    session,
                    token,
                    watchlist[0],
                    trade_date,
                    request_delay_sec=request_delay_sec,
                )
                synced.append(symbol)
            except Exception as exc:
                logger.warning("Ensure derivative sync failed for %s: %s", symbol, exc)
                failed.append({"symbol": symbol, "error": str(exc)})
            if index + 1 < len(missing):
                await asyncio.sleep(request_delay_sec)

    return {
        "trade_date": trade_iso,
        "requested": len(normalized),
        "already_present": already_present,
        "synced": synced,
        "failed": failed,
        "skipped_no_profile": skipped_no_profile,
    }


async def sync_derivatives(
    access_token: str | None,
    *,
    trade_date: date | None = None,
    expiry: str | None = None,
    symbols: list[str] | None = None,
    include_indices: bool = True,
    include_stocks: bool = True,
    stock_limit: int = 5,
    all_fno_stocks: bool = False,
    bucket_interval: int = DEFAULT_BUCKET_INTERVAL,
    change_oi_interval: str = DEFAULT_CHANGE_OI_INTERVAL,
    request_delay_sec: float = REQUEST_DELAY_SEC,
    on_progress: MarketInfoProgressCallback | None = None,
) -> dict[str, Any]:
    token = get_access_token(access_token)
    if not token:
        raise RuntimeError("Upstox access token required for market info sync")

    as_of = trade_date or date.today()

    async with aiohttp.ClientSession() as session:
        resolved_symbols = symbols
        if all_fno_stocks and include_stocks and not resolved_symbols:
            fno_list = await nse_client.fetch_fno_symbols(session)
            resolved_symbols = [
                normalize_symbol(sym)
                for sym in fno_list
                if normalize_symbol(sym) not in INDEX_INSTRUMENT_KEYS
            ]

        watchlist = resolve_derivative_watchlist(
            symbols=resolved_symbols,
            include_indices=include_indices,
            include_stocks=include_stocks,
            stock_limit=stock_limit,
            all_fno_stocks=all_fno_stocks,
            request_delay_sec=request_delay_sec,
        )
        if not watchlist:
            return {"processed": 0, "success": 0, "failed": 0, "results": [], "message": "No underlyings"}

        results: list[dict[str, Any]] = []
        success = 0
        failed = 0
        total = len(watchlist)

        def emit(current: str | None = None) -> None:
            if on_progress:
                on_progress(
                    {
                        "total": total,
                        "processed": success + failed,
                        "success": success,
                        "failed": failed,
                        "current_symbol": current,
                    }
                )

        emit()

        for index, underlying in enumerate(watchlist):
            symbol = underlying["symbol"]
            emit(symbol)
            try:
                row = await sync_derivative_snapshot_for_underlying(
                    session,
                    token,
                    underlying,
                    as_of,
                    expiry=expiry,
                    bucket_interval=bucket_interval,
                    change_oi_interval=change_oi_interval,
                    request_delay_sec=request_delay_sec,
                )
                results.append({"symbol": symbol, "status": "ok", **row})
                success += 1
            except Exception as exc:
                logger.warning("Derivative sync failed for %s: %s", symbol, exc)
                results.append({"symbol": symbol, "status": "error", "error": str(exc)})
                failed += 1
            if index + 1 < len(watchlist):
                await asyncio.sleep(request_delay_sec)

        emit(None)
        return {
            "processed": total,
            "success": success,
            "failed": failed,
            "trade_date": as_of.isoformat(),
            "all_fno_stocks": all_fno_stocks,
            "results": results,
        }


async def sync_market_info(
    access_token: str | None,
    *,
    trade_date: date | None = None,
    expiry: str | None = None,
    symbols: list[str] | None = None,
    flows: bool = True,
    derivatives: bool = True,
    flow_interval: str = "1D",
    flow_from_date: date | None = None,
    include_indices: bool = True,
    include_stocks: bool = True,
    stock_limit: int = 5,
    all_fno_stocks: bool = False,
    request_delay_sec: float = REQUEST_DELAY_SEC,
    on_progress: MarketInfoProgressCallback | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"synced_at": _utc_now_iso()}
    if flows:
        out["flows"] = await sync_institutional_flows(
            access_token,
            interval=flow_interval,
            from_date=flow_from_date,
            request_delay_sec=request_delay_sec,
        )
    if derivatives:
        out["derivatives"] = await sync_derivatives(
            access_token,
            trade_date=trade_date,
            expiry=expiry,
            symbols=symbols,
            include_indices=include_indices,
            include_stocks=include_stocks,
            stock_limit=stock_limit,
            all_fno_stocks=all_fno_stocks,
            request_delay_sec=request_delay_sec,
            on_progress=on_progress,
        )
    return out
