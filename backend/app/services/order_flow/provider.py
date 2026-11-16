"""Order Flow's data, from the lab's own Upstox client and database.

Implements the standalone provider contract (server/providers/types.mjs):

- ``expiries(u)``              live option expiries, from Upstox option contracts
- ``option_chain(u, expiry)``  Upstox put/call chain; spot from the chain, previous close from the lab's daily candles
- ``futures(u, session)``      the near-month future: 1-minute candles (with OI) from Upstox,
                               previous close and OI from Upstox daily candles

The near-month future's instrument key comes from ``futures_oi_daily``, the
lab's stored F&O snapshot. Only one future month is stored, so the board gets
one month per underlying. Index futures (NIFTY, BANKNIFTY) are not stored, so
those indices show their spot move until the board has a future for them.

Every Upstox call goes through one token bucket (``MAX_PER_SECOND``).
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import date, datetime, timedelta
from typing import Any

from ...config import INDEX_INSTRUMENT_KEYS, get_access_token, normalize_symbol, resolve_instrument_key
from ...db.store import get_store
from ..upstox_client import (
    extract_option_expiries,
    get_historical_candles,
    get_intra_day_candles,
    get_option_contracts,
    get_put_call_option_chain,
)
from .market_file import _finite
from .session import latest_trading_session_date, market_parts

MAX_PER_SECOND = 10
_HISTORY_DAYS = 15


class _TokenBucket:
    """At most ``per_second`` calls in any second, shared by every caller."""

    def __init__(self, per_second: int) -> None:
        self.per_second = per_second
        self._stamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._stamps and now - self._stamps[0] >= 1:
                    self._stamps.popleft()
                if len(self._stamps) < self.per_second:
                    self._stamps.append(now)
                    return
                await asyncio.sleep(1 - (now - self._stamps[0]) + 0.005)


def _num(value: Any) -> float | None:
    return float(value) if _finite(value) else None


def _positive(value: Any) -> float | None:
    number = _num(value)
    return number if number is not None and number > 0 else None


def _rows(payload: Any) -> list[dict[str, Any]]:
    """The list of rows inside an Upstox answer, under ``data`` (possibly nested once)."""
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        data = data["data"]
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _leg(side: dict[str, Any] | None) -> dict[str, Any] | None:
    """One Upstox option side as the contract's leg; None when the side is not listed."""
    if not isinstance(side, dict) or not isinstance(side.get("market_data"), dict):
        return None
    market = side["market_data"]
    greeks = side.get("option_greeks") if isinstance(side.get("option_greeks"), dict) else {}
    ltp = _num(market.get("ltp")) or 0.0
    return {
        "ltp": ltp,
        "prevClose": _positive(market.get("close_price")),
        "oi": _num(market.get("oi")) or 0.0,
        "prevOi": _num(market.get("prev_oi")),
        "volume": _num(market.get("volume")) or 0.0,
        "prevVolume": None,
        "avgPrice": ltp,  # the chain carries no average price
        "iv": _num(greeks.get("iv")),
        "bid": _num(market.get("bid_price")) or 0.0,
        "ask": _num(market.get("ask_price")) or 0.0,
        "bidQty": _num(market.get("bid_qty")) or 0.0,
        "askQty": _num(market.get("ask_qty")) or 0.0,
        "dayHigh": None,
        "dayLow": None,
        "lastTradeAt": None,
        "delta": _num(greeks.get("delta")),
    }


def parse_option_chain(payload: Any, *, expiry: str, at: float, prev_close: float | None) -> dict[str, Any]:
    """Upstox's put/call chain as the contract's OptionChain. Spot is the chain's own underlying price."""
    rows = _rows(payload)
    spot = next((_num(row.get("underlying_spot_price")) for row in rows if _num(row.get("underlying_spot_price"))), None)
    strikes = []
    for row in rows:
        strike = _num(row.get("strike_price"))
        if strike is None:
            continue
        strikes.append({"strike": strike, "call": _leg(row.get("call_options")), "put": _leg(row.get("put_options"))})
    strikes.sort(key=lambda item: item["strike"])
    return {"expiry": expiry, "at": at, "spot": spot or 0.0, "prevClose": prev_close, "atm": None, "strikes": strikes}


def parse_candles(payload: Any) -> list[dict[str, Any]]:
    """Upstox candles ``[time, open, high, low, close, volume, oi]`` as ``{at, close, oi}``, ascending."""
    candles = None
    if isinstance(payload, dict):
        candles = payload.get("candles") or (payload.get("data") or {}).get("candles")
    out = []
    for candle in candles or []:
        if not isinstance(candle, (list, tuple)) or len(candle) < 7:
            continue
        try:
            at = datetime.fromisoformat(str(candle[0]).replace("Z", "+00:00")).timestamp() * 1000
        except ValueError:
            continue
        close = _num(candle[4])
        oi = _num(candle[6])
        if close is not None and close > 0 and oi is not None:
            out.append({"at": at, "close": close, "oi": oi})
    out.sort(key=lambda c: c["at"])
    return out


def parse_candles_daily(payload: Any) -> list[dict[str, Any]]:
    """Daily candles, newest first, as ``{at, close, oi}``."""
    return parse_candles(payload)[::-1]


def _is_index_key(key: str) -> bool:
    return key.startswith(("NSE_INDEX|", "BSE_INDEX|"))


class UpstoxOrderFlowProvider:
    id = "upstox"
    label = "Upstox"
    alwaysLive = False

    def __init__(self) -> None:
        self._bucket = _TokenBucket(MAX_PER_SECOND)
        self._daily: dict[tuple[str, str], dict[str, Any] | None] = {}

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _token() -> str:
        token = get_access_token()
        if not token:
            raise RuntimeError("Set UPSTOX_ACCESS_TOKEN in .env (the day's access token from the Upstox login).")
        return token

    @staticmethod
    def _underlying_key(symbol: str) -> str:
        key = INDEX_INSTRUMENT_KEYS.get(normalize_symbol(symbol)) or resolve_instrument_key(symbol)
        if not key:
            raise RuntimeError(f"No Upstox instrument for {symbol}.")
        return key

    @staticmethod
    def _previous_close(key: str, session: str) -> float | None:
        """The underlying's close on the last stored session before ``session``."""
        with get_store().connection() as conn:
            if _is_index_key(key):
                row = conn.execute(
                    "SELECT close_price FROM index_candles WHERE instrument_token = ? AND timeframe = 'daily' AND ts < ? "
                    "ORDER BY ts DESC LIMIT 1",
                    (key, session),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT close_price FROM daily_candles WHERE instrument_token = ? AND trade_date < ? "
                    "ORDER BY trade_date DESC LIMIT 1",
                    (key, session),
                ).fetchone()
        return _positive(row["close_price"]) if row else None

    @staticmethod
    def _front_future(symbol: str, session: str) -> tuple[str, str] | None:
        """(instrument key, expiry) of the nearest future on or after ``session``, from the latest stored snapshot."""
        internal = normalize_symbol(symbol)
        with get_store().connection() as conn:
            row = conn.execute(
                "SELECT instrument_key, expiry FROM futures_oi_daily "
                "WHERE symbol = ? AND trade_date = (SELECT MAX(trade_date) FROM futures_oi_daily WHERE symbol = ?) "
                "AND expiry >= ? ORDER BY expiry LIMIT 1",
                (internal, internal, session),
            ).fetchone()
        return (row["instrument_key"], row["expiry"]) if row else None

    async def _call(self, fn, *args):
        await self._bucket.wait()
        return await fn(*args)

    # ── Contract ───────────────────────────────────────────────────────────

    async def expiries(self, u: dict[str, Any]) -> list[str]:
        key = self._underlying_key(u["symbol"])
        payload = await self._call(get_option_contracts, self._token(), key)
        return sorted(extract_option_expiries(payload))

    async def _last_daily(self, key: str, session: str) -> dict[str, Any] | None:
        """The last Upstox daily candle before ``session`` (``{at, close, oi}``), read once per session."""
        cache_key = (key, session)
        if cache_key not in self._daily:
            before = (date.fromisoformat(session) - timedelta(days=1)).isoformat()
            from_day = (date.fromisoformat(session) - timedelta(days=_HISTORY_DAYS)).isoformat()
            daily = await self._call(get_historical_candles, self._token(), key, "days", "1", before, from_day)
            candles = parse_candles_daily(daily)
            self._daily[cache_key] = candles[0] if candles else None
        return self._daily[cache_key]

    async def option_chain(self, u: dict[str, Any], expiry: str) -> dict[str, Any]:
        key = self._underlying_key(u["symbol"])
        session = latest_trading_session_date(time.time() * 1000)
        payload = await self._call(get_put_call_option_chain, self._token(), key, expiry)
        prev_close = self._previous_close(key, session)
        if prev_close is None:
            # Bank Nifty and other indices without stored daily candles: Upstox's own daily history.
            last = await self._last_daily(key, session)
            prev_close = last["close"] if last else None
        return parse_option_chain(payload, expiry=expiry, at=time.time() * 1000, prev_close=prev_close)

    async def futures(self, u: dict[str, Any], session: str) -> list[dict[str, Any]]:
        found = self._front_future(u["symbol"], session)
        if not found:
            return []
        key, expiry = found
        token = self._token()
        last = await self._last_daily(key, session)
        prev_close = last["close"] if last else None
        prev_oi = last["oi"] if last else None

        if market_parts(time.time() * 1000)[0] == session:
            minute = await self._call(get_intra_day_candles, token, key, "minutes", 1)
        else:
            minute = await self._call(get_historical_candles, token, key, "minutes", "1", session, session)
        return [{"date": expiry, "prevClose": prev_close, "prevOi": prev_oi, "candles": parse_candles(minute)}]

