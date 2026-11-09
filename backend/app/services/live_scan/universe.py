"""F&O cash keys plus the front-month stock future for each name."""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import aiohttp

from ...config import ROOT_DIR, normalize_symbol
from ...db.store import get_store
from ..nse_client import fetch_fno_symbols
from .clocks import IST

logger = logging.getLogger(__name__)

INSTRUMENT_URLS = (
    "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz",
    "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz",
)
CACHE_PATH = ROOT_DIR / "data" / "cache" / "upstox_equity_futures.json"
CACHE_MAX_AGE_SEC = 12 * 60 * 60


@dataclass(frozen=True)
class FutureContract:
    symbol: str
    instrument_key: str
    expiry: str
    underlying_key: str | None = None


@dataclass(frozen=True)
class UniverseSymbol:
    symbol: str
    company_name: str | None
    sector: str | None
    cash_key: str
    future_key: str | None
    future_expiry: str | None
    kind: str = "equity"
    segment: str = "fno"


# Same session-call path as cash names. Keys are the Upstox full-mode instruments.
LIVE_INDEXES: tuple[UniverseSymbol, ...] = (
    UniverseSymbol(
        symbol="NIFTY",
        company_name="Nifty 50",
        sector="Index",
        cash_key="NSE_INDEX|Nifty 50",
        future_key=None,
        future_expiry=None,
        kind="index",
        segment="index",
    ),
    UniverseSymbol(
        symbol="SENSEX",
        company_name="Sensex",
        sector="Index",
        cash_key="BSE_INDEX|SENSEX",
        future_key=None,
        future_expiry=None,
        kind="index",
        segment="index",
    ),
)

# Full mode alone allows 2,000 keys. Stay under that so a reconnect or an
# index add cannot trip the websocket cap. Non-F&O names are one cash key each.
FULL_MODE_KEY_LIMIT = 1900
MIN_CASH_HISTORY_BARS = 10


def parse_expiry(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        return datetime.fromtimestamp(timestamp, IST).date()
    text = str(value).strip()
    if text.isdigit():
        return parse_expiry(int(text))
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _as_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
    return []


def select_front_futures(
    rows: list[dict[str, Any]],
    symbols: set[str],
    as_of: date,
) -> dict[str, FutureContract]:
    """Nearest NSE stock future on or after ``as_of`` for each requested symbol."""
    chosen: dict[str, tuple[date, FutureContract]] = {}
    for row in rows:
        if str(row.get("instrument_type") or "").upper() not in {"FUT", "FUTSTK"}:
            continue
        segment = str(row.get("segment") or "")
        instrument_key = str(row.get("instrument_key") or "")
        if segment != "NSE_FO" and not instrument_key.startswith("NSE_FO|"):
            continue
        if row.get("weekly") is True:
            continue
        underlying_type = str(row.get("underlying_type") or row.get("asset_type") or "").upper()
        if underlying_type and underlying_type not in {"EQUITY", "EQ"}:
            continue
        raw_symbol = row.get("underlying_symbol") or row.get("asset_symbol") or ""
        symbol = normalize_symbol(str(raw_symbol))
        if symbol not in symbols:
            continue
        expiry = parse_expiry(row.get("expiry"))
        if expiry is None or expiry < as_of or not instrument_key:
            continue
        contract = FutureContract(
            symbol=symbol,
            instrument_key=instrument_key,
            expiry=expiry.isoformat(),
            underlying_key=str(row.get("underlying_key") or row.get("asset_key") or "") or None,
        )
        current = chosen.get(symbol)
        if current is None or expiry < current[0]:
            chosen[symbol] = (expiry, contract)
    return {symbol: contract for symbol, (_expiry, contract) in chosen.items()}


def _load_cached_rows(now_ts: float) -> list[dict[str, Any]] | None:
    if not CACHE_PATH.exists():
        return None
    age = now_ts - CACHE_PATH.stat().st_mtime
    if age > CACHE_MAX_AGE_SEC:
        return None
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable futures cache: %s", exc)
        return None
    rows = _as_list(payload)
    return rows or None


def _write_cache(rows: list[dict[str, Any]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(rows), encoding="utf-8")


def _download_instrument_rows() -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for url in INSTRUMENT_URLS:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "equity-scan-lab"})
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            payload = json.loads(raw)
            rows = _as_list(payload)
            if rows:
                logger.info("Loaded %d Upstox instruments from %s", len(rows), url)
                return rows
        except Exception as exc:
            last_error = exc
            logger.warning("Instrument dump failed for %s: %s", url, exc)
    raise RuntimeError(f"Upstox instrument dump unavailable: {last_error}")


def load_equity_future_rows(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    """Download the NSE dump and keep only equity futures. Cached for 12 hours."""
    now_ts = datetime.now(IST).timestamp()
    if not force_refresh:
        cached = _load_cached_rows(now_ts)
        if cached is not None:
            return cached
    rows = _download_instrument_rows()
    futures = [
        row
        for row in rows
        if str(row.get("instrument_type") or "").upper() in {"FUT", "FUTSTK"}
        and (
            str(row.get("segment") or "") == "NSE_FO"
            or str(row.get("instrument_key") or "").startswith("NSE_FO|")
        )
    ]
    try:
        _write_cache(futures)
    except OSError as exc:
        logger.warning("Could not cache futures dump: %s", exc)
    return futures


def _profiles_for_symbols(symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    profiles: dict[str, dict[str, Any]] = {}
    store = get_store()
    chunk_size = 400
    for index in range(0, len(symbols), chunk_size):
        chunk = symbols[index : index + chunk_size]
        placeholders = ",".join("?" * len(chunk))
        with store.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT ticker, company_name, sector, instrument_token
                FROM security_profiles
                WHERE ticker IN ({placeholders})
                  AND instrument_token LIKE 'NSE_EQ|%'
                """,
                chunk,
            ).fetchall()
        for row in rows:
            profiles[row["ticker"]] = dict(row)
    return profiles


def subscription_key_count(items: list[UniverseSymbol]) -> int:
    """Cash key plus the front-month future when the name has one."""
    return sum(2 if item.future_key else 1 for item in items)


def select_cash_symbols(
    candidates: list[dict[str, Any]],
    *,
    exclude: set[str],
    room: int,
    exclude_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Most liquid non-F&O names that still fit in the full-mode key budget."""
    if room <= 0:
        return []
    used_keys = set(exclude_keys or ())
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in candidates:
        symbol = normalize_symbol(str(row.get("ticker") or ""))
        token = str(row.get("instrument_token") or "")
        if not symbol or not token or symbol in exclude or symbol in seen or token in used_keys:
            continue
        seen.add(symbol)
        used_keys.add(token)
        chosen.append(row)
        if len(chosen) >= room:
            break
    return chosen


async def build_universe(as_of: date | None = None) -> list[UniverseSymbol]:
    """F&O names that have an NSE_EQ profile, joined to the front-month future when present."""
    session_date = as_of or datetime.now(IST).date()
    async with aiohttp.ClientSession() as session:
        fno_symbols = await fetch_fno_symbols(session)
    symbols = [normalize_symbol(symbol) for symbol in fno_symbols]
    profiles, future_rows = await asyncio.gather(
        asyncio.to_thread(_profiles_for_symbols, symbols),
        asyncio.to_thread(load_equity_future_rows),
    )
    if not profiles:
        raise RuntimeError("No F&O stocks with NSE_EQ profiles. Sync security profiles first.")

    contracts = select_front_futures(future_rows, set(profiles), session_date)

    universe: list[UniverseSymbol] = []
    for symbol in sorted(profiles):
        profile = profiles[symbol]
        contract = contracts.get(symbol)
        cash_key = str(profile["instrument_token"])
        if contract and contract.underlying_key and contract.underlying_key != cash_key:
            logger.debug(
                "Future underlying key %s does not match profile %s for %s",
                contract.underlying_key,
                cash_key,
                symbol,
            )
        universe.append(
            UniverseSymbol(
                symbol=symbol,
                company_name=profile.get("company_name"),
                sector=profile.get("sector"),
                cash_key=cash_key,
                future_key=contract.instrument_key if contract else None,
                future_expiry=contract.expiry if contract else None,
                kind="equity",
                segment="fno",
            )
        )
    universe = [*LIVE_INDEXES, *universe]
    room = max(0, FULL_MODE_KEY_LIMIT - subscription_key_count(universe))
    candidates = await asyncio.to_thread(
        get_store().liquid_cash_profiles,
        session_date.isoformat(),
        MIN_CASH_HISTORY_BARS,
    )
    chosen = select_cash_symbols(
        candidates,
        exclude=set(symbols),
        room=room,
        exclude_keys={item.cash_key for item in universe},
    )
    for row in chosen:
        universe.append(
            UniverseSymbol(
                symbol=normalize_symbol(str(row["ticker"])),
                company_name=row.get("company_name"),
                sector=row.get("sector"),
                cash_key=str(row["instrument_token"]),
                future_key=None,
                future_expiry=None,
                kind="equity",
                segment="cash",
            )
        )
    logger.info(
        "Live scan universe: %d F&O, %d non-F&O, %d indexes, %d futures, %d/%d full keys, %d liquid names left out",
        sum(1 for item in universe if item.segment == "fno"),
        len(chosen),
        sum(1 for item in universe if item.kind == "index"),
        sum(1 for item in universe if item.future_key),
        subscription_key_count(universe),
        FULL_MODE_KEY_LIMIT,
        max(0, len(candidates) - len(chosen)),
    )
    return universe
