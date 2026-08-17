from __future__ import annotations

import asyncio
import csv
import io
import json
import time
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote

import aiohttp

from ..cache import get_cached, set_cache
from ..config import (
    EQUITY_ISIN_BY_SYMBOL,
    EQUITY_SERIES_BY_SYMBOL,
    NIFTY50_FALLBACK,
    NSE_ARCHIVE_BASE,
    NSE_BASE,
    NSE_EQUITY_LIST_URL,
    NSE_FO_MKTLOTS_URL,
    normalize_symbol,
)

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/get-quotes/equity",
}

_nse_session_cookies = ""
_nse_session_expiry = 0.0
_nse_session_lock = asyncio.Lock()


class NseSessionError(RuntimeError):
    """NSE returned HTML or rejected the request (session/rate limit)."""


def _invalidate_nse_session() -> None:
    global _nse_session_cookies, _nse_session_expiry
    _nse_session_cookies = ""
    _nse_session_expiry = 0.0

# Index underlyings in the F&O lot file (not individual equity symbols).
FO_INDEX_SYMBOLS = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"})

# EQ = regular; BE = trade-to-trade (B group); BZ = Z group — all tradeable on NSE CM.
TRADEABLE_EQUITY_SERIES = frozenset({"EQ", "BE", "BZ"})
SERIES_PRIORITY = {"EQ": 0, "BE": 1, "BZ": 2}


def _extract_set_cookie_pairs(res: aiohttp.ClientResponse) -> list[str]:
    pairs: list[str] = []
    if hasattr(res.headers, "getall"):
        raw_headers = res.headers.getall("Set-Cookie", [])
    else:
        single = res.headers.get("Set-Cookie")
        raw_headers = [single] if single else []

    for header in raw_headers:
        if not header:
            continue
        first = header.split(";")[0].strip()
        if "=" in first:
            pairs.append(first)

    for cookie in res.cookies.values():
        pairs.append(f"{cookie.key}={cookie.value}")

    seen: set[str] = set()
    unique: list[str] = []
    for pair in pairs:
        key = pair.split("=", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        unique.append(pair)
    return unique


async def _establish_nse_session(session: aiohttp.ClientSession) -> str:
    global _nse_session_cookies, _nse_session_expiry

    headers = {
        **NSE_HEADERS,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    for attempt in range(3):
        try:
            async with session.get(NSE_BASE, headers=headers, allow_redirects=True) as res:
                cookie_pairs = _extract_set_cookie_pairs(res)
                await res.read()
            if cookie_pairs:
                _nse_session_cookies = "; ".join(cookie_pairs)
                _nse_session_expiry = time.time() + 120
                return _nse_session_cookies
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        if attempt < 2:
            await asyncio.sleep(1.5 * (attempt + 1))

    _nse_session_cookies = ""
    _nse_session_expiry = 0.0
    return ""


async def get_nse_session(session: aiohttp.ClientSession) -> str:
    global _nse_session_cookies, _nse_session_expiry

    if _nse_session_cookies and time.time() < _nse_session_expiry:
        return _nse_session_cookies

    async with _nse_session_lock:
        if _nse_session_cookies and time.time() < _nse_session_expiry:
            return _nse_session_cookies
        return await _establish_nse_session(session)


def _parse_csv_symbols(text: str) -> list[str]:
    symbols: list[str] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        sym = (row.get("Symbol") or row.get("symbol") or "").strip().upper()
        if sym:
            symbols.append(sym)
    return symbols


async def fetch_nifty50_symbols(session: aiohttp.ClientSession) -> list[str]:
    cache_key = "nifty50:symbols"
    cached = get_cached(cache_key)
    if cached:
        return cached

    url = f"{NSE_ARCHIVE_BASE}/ind_nifty50list.csv"
    try:
        async with session.get(url, headers={"User-Agent": NSE_HEADERS["User-Agent"]}) as res:
            if res.ok:
                text = await res.text()
                symbols = _parse_csv_symbols(text)
                if symbols:
                    set_cache(cache_key, symbols, 3600)
                    return symbols
    except aiohttp.ClientError:
        pass

    set_cache(cache_key, NIFTY50_FALLBACK, 3600)
    return NIFTY50_FALLBACK


def _parse_fno_symbols(text: str) -> list[str]:
    reader = csv.reader(io.StringIO(text))
    next(reader, None)
    symbols: set[str] = set()
    for row in reader:
        if len(row) < 2:
            continue
        sym = row[1].strip().upper()
        if not sym or sym == "SYMBOL":
            continue
        if sym in FO_INDEX_SYMBOLS:
            continue
        symbols.add(normalize_symbol(sym))
    return sorted(symbols)


async def fetch_fno_symbols(session: aiohttp.ClientSession) -> list[str]:
    cache_key = "fno:symbols:v1"
    cached = get_cached(cache_key)
    if cached:
        return cached

    headers = {
        "User-Agent": NSE_HEADERS["User-Agent"],
        "Accept": "text/csv,text/plain,*/*",
    }
    try:
        async with session.get(
            NSE_FO_MKTLOTS_URL,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as res:
            if not res.ok:
                raise RuntimeError(f"NSE F&O list failed: HTTP {res.status}")
            text = await res.text()
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise RuntimeError(f"NSE F&O list request failed: {exc}") from exc

    symbols = _parse_fno_symbols(text)
    if not symbols:
        raise RuntimeError("NSE F&O list returned no symbols")

    set_cache(cache_key, symbols, 3600)
    return symbols


def _normalize_csv_row(row: dict[str, str | None]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        normalized[key.strip().upper()] = (value or "").strip()
    return normalized


def _parse_equity_master(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, str]] = []
    for raw_row in reader:
        row = _normalize_csv_row(raw_row)
        series = row.get("SERIES", "")
        if series not in TRADEABLE_EQUITY_SERIES:
            continue
        symbol = row.get("SYMBOL", "")
        isin = row.get("ISIN NUMBER") or row.get("ISIN") or ""
        name = row.get("NAME OF COMPANY") or row.get("NAME") or ""
        if not symbol or not isin:
            continue
        rows.append(
            {
                "symbol": normalize_symbol(symbol),
                "name": name,
                "isin": isin.upper(),
                "series": series,
            }
        )

    by_symbol: dict[str, dict[str, str]] = {}
    for row in rows:
        sym = row["symbol"]
        existing = by_symbol.get(sym)
        if existing is None:
            by_symbol[sym] = row
            continue
        new_rank = SERIES_PRIORITY.get(row["series"], 99)
        old_rank = SERIES_PRIORITY.get(existing["series"], 99)
        if new_rank < old_rank:
            by_symbol[sym] = row

    return list(by_symbol.values())


async def fetch_equity_master(session: aiohttp.ClientSession) -> list[dict[str, str]]:
    cache_key = "nse:equity:master:v2"
    cached = get_cached(cache_key)
    if cached:
        return cached

    url = NSE_EQUITY_LIST_URL
    headers = {
        "User-Agent": NSE_HEADERS["User-Agent"],
        "Accept": "text/csv,text/plain,*/*",
    }
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as res:
            if not res.ok:
                raise RuntimeError(f"NSE equity list failed: HTTP {res.status}")
            text = await res.text()
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise RuntimeError(f"NSE equity list request failed: {exc}") from exc

    rows = _parse_equity_master(text)
    if not rows:
        raise RuntimeError("NSE equity list returned no tradeable symbols")

    EQUITY_ISIN_BY_SYMBOL.clear()
    EQUITY_SERIES_BY_SYMBOL.clear()
    for row in rows:
        EQUITY_ISIN_BY_SYMBOL[row["symbol"]] = row["isin"]
        EQUITY_SERIES_BY_SYMBOL[row["symbol"]] = row["series"]

    set_cache(cache_key, rows, 86400)
    return rows


async def search_equity_symbols(
    session: aiohttp.ClientSession,
    query: str,
    limit: int = 15,
) -> list[dict[str, str]]:
    q = query.strip().upper()
    if len(q) < 1:
        return []

    master = await fetch_equity_master(session)
    matches: list[dict[str, str]] = []
    for row in master:
        symbol = row["symbol"]
        name = row["name"]
        if q in symbol or q in name.upper():
            matches.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "series": row["series"],
                    "instrument_key": f"NSE_EQ|{row['isin']}",
                }
            )
    matches.sort(key=lambda item: (0 if item["symbol"].startswith(q) else 1, item["symbol"]))
    return matches[:limit]


def _format_nse_date(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def _parse_nse_timestamp(raw: str) -> str:
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw


async def fetch_equity_historical(
    session: aiohttp.ClientSession,
    symbol: str,
    from_date: date,
    to_date: date,
    series: str = "EQ",
    *,
    _session_retry: bool = True,
) -> list[dict[str, Any]]:
    cache_key = f"nse:hist:{symbol}:{series}:{from_date}:{to_date}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    cookies = await get_nse_session(session)
    if not cookies:
        raise NseSessionError("Unable to establish NSE session")

    series_param = quote(f'["{series}"]')
    url = (
        f"{NSE_BASE}/api/historical/cm/equity"
        f"?symbol={quote(symbol)}&series={series_param}"
        f"&from={_format_nse_date(from_date)}&to={_format_nse_date(to_date)}"
    )
    headers = {**NSE_HEADERS, "Cookie": cookies}

    async with session.get(url, headers=headers) as res:
        content_type = (res.headers.get("Content-Type") or "").lower()
        if not res.ok:
            raise RuntimeError(f"NSE historical API failed: HTTP {res.status}")
        if "html" in content_type:
            body_preview = (await res.text())[:120]
            if _session_retry:
                _invalidate_nse_session()
                return await fetch_equity_historical(
                    session,
                    symbol,
                    from_date,
                    to_date,
                    series,
                    _session_retry=False,
                )
            raise NseSessionError(
                f"NSE returned HTML instead of JSON for {symbol} "
                f"(session expired or rate limited). Preview: {body_preview!r}"
            )
        try:
            payload = await res.json(content_type=None)
        except (json.JSONDecodeError, aiohttp.ContentTypeError) as exc:
            if _session_retry:
                _invalidate_nse_session()
                return await fetch_equity_historical(
                    session,
                    symbol,
                    from_date,
                    to_date,
                    series,
                    _session_retry=False,
                )
            raise NseSessionError(f"NSE historical JSON decode failed for {symbol}: {exc}") from exc

    rows = payload.get("data") or []
    candles: list[dict[str, Any]] = []
    for row in rows:
        ts = _parse_nse_timestamp(str(row.get("mTIMESTAMP") or row.get("CH_TIMESTAMP") or ""))
        candles.append(
            {
                "date": ts,
                "open": float(row.get("CH_OPENING_PRICE") or row.get("OPEN") or 0),
                "high": float(row.get("CH_TRADE_HIGH_PRICE") or row.get("HIGH") or 0),
                "low": float(row.get("CH_TRADE_LOW_PRICE") or row.get("LOW") or 0),
                "close": float(row.get("CH_CLOSING_PRICE") or row.get("CLOSE") or 0),
                "volume": float(row.get("CH_TOT_TRADED_QTY") or row.get("VOLUME") or 0),
            }
        )

    candles.sort(key=lambda item: item["date"])
    set_cache(cache_key, candles, 1800)
    return candles


async def fetch_equity_historical_range(
    session: aiohttp.ClientSession,
    symbol: str,
    from_date: date,
    to_date: date,
    chunk_days: int = 364,
) -> list[dict[str, Any]]:
    """Fetch long history by chunking NSE requests (max ~1 year per call)."""
    normalized = normalize_symbol(symbol)
    series = EQUITY_SERIES_BY_SYMBOL.get(normalized, "EQ")
    cache_key = f"nse:hist:range:{symbol}:{series}:{from_date}:{to_date}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    merged: dict[str, dict[str, Any]] = {}
    chunk_start = from_date
    while chunk_start <= to_date:
        chunk_end = min(chunk_start + timedelta(days=chunk_days), to_date)
        batch = await fetch_equity_historical(
            session, symbol, chunk_start, chunk_end, series=series,
        )
        for candle in batch:
            merged[candle["date"]] = candle
        chunk_start = chunk_end + timedelta(days=1)

    candles = [merged[key] for key in sorted(merged)]
    set_cache(cache_key, candles, 3600)
    return candles


async def fetch_index_historical_range(
    session: aiohttp.ClientSession,
    index_name: str,
    from_date: date,
    to_date: date,
    chunk_days: int = 364,
) -> list[dict[str, Any]]:
    cache_key = f"nse:index:range:{index_name}:{from_date}:{to_date}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    merged: dict[str, dict[str, Any]] = {}
    chunk_start = from_date
    while chunk_start <= to_date:
        chunk_end = min(chunk_start + timedelta(days=chunk_days), to_date)
        batch = await fetch_index_historical(session, index_name, chunk_start, chunk_end)
        for candle in batch:
            merged[candle["date"]] = candle
        chunk_start = chunk_end + timedelta(days=1)

    candles = [merged[key] for key in sorted(merged)]
    set_cache(cache_key, candles, 3600)
    return candles


async def fetch_index_historical(
    session: aiohttp.ClientSession,
    index_name: str,
    from_date: date,
    to_date: date,
) -> list[dict[str, Any]]:
    cache_key = f"nse:index:{index_name}:{from_date}:{to_date}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    cookies = await get_nse_session(session)
    if not cookies:
        raise RuntimeError("Unable to establish NSE session")

    url = (
        f"{NSE_BASE}/api/historical/indicesHistory"
        f"?indexType=NIFTY%2050&from={_format_nse_date(from_date)}&to={_format_nse_date(to_date)}"
    )
    headers = {**NSE_HEADERS, "Cookie": cookies, "Referer": "https://www.nseindia.com/reports-indices-historical-index-data"}

    async with session.get(url, headers=headers) as res:
        if not res.ok:
            raise RuntimeError(f"NSE index historical API failed: HTTP {res.status}")
        payload = await res.json()

    rows = payload.get("data", {}).get("indexCloseOnlineRecords") or payload.get("data") or []
    candles: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, str):
            try:
                row = json.loads(row)
            except json.JSONDecodeError:
                continue
        ts = _parse_nse_timestamp(str(row.get("EOD_TIMESTAMP") or row.get("TIMESTAMP") or ""))
        close = float(row.get("CLOSE_INDEX_VAL") or row.get("CLOSE") or 0)
        candles.append(
            {
                "date": ts,
                "open": float(row.get("OPEN_INDEX_VAL") or close),
                "high": float(row.get("HIGH_INDEX_VAL") or close),
                "low": float(row.get("LOW_INDEX_VAL") or close),
                "close": close,
                "volume": 0.0,
            }
        )

    candles.sort(key=lambda item: item["date"])
    set_cache(cache_key, candles, 1800)
    return candles
