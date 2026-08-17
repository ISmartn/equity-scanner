from __future__ import annotations

import logging
import threading
import time
from typing import Any

import upstox_client
from upstox_client import MarketDataStreamerV3

from ...config import INDEX_INSTRUMENT_KEYS, get_access_token, normalize_symbol
from .engine import infer_strike_step, smooth_atm_strike, support_zone_strikes
from .service import fetch_live_option_chain, resolve_underlying
from .ws_state import LiveOiBook, StreamSessionState, StrikeInstrumentMap

logger = logging.getLogger(__name__)

SAMPLE_MIN_SEC = 15
SAMPLE_MIN_SEC_STREAM = 5
SAMPLE_MIN_SEC_SCALP = 3
CHAIN_REFRESH_SEC = 300


def stream_sample_interval(window_sec: int) -> int:
    if window_sec <= 30:
        return SAMPLE_MIN_SEC_SCALP
    return SAMPLE_MIN_SEC_STREAM


def _dig(mapping: dict[str, Any], *keys: str) -> Any:
    cur: Any = mapping
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _parse_option_full_feed(feed: dict[str, Any]) -> dict[str, Any] | None:
    market = _dig(feed, "fullFeed", "marketFF")
    if market is None:
        market = _dig(feed, "fullFeed", "marketFf")
    if not isinstance(market, dict):
        return None
    ltpc = market.get("ltpc") if isinstance(market.get("ltpc"), dict) else {}
    return {
        "ltp": float(ltpc.get("ltp") or 0),
        "oi": int(float(market.get("oi") or 0)),
        "volume": int(float(market.get("vtt") or 0)),
    }


def _parse_index_ltpc(feed: dict[str, Any]) -> float | None:
    ltpc = feed.get("ltpc")
    if not isinstance(ltpc, dict):
        index_ff = _dig(feed, "fullFeed", "indexFF") or _dig(feed, "fullFeed", "indexFf")
        if isinstance(index_ff, dict):
            ltpc = index_ff.get("ltpc")
    if not isinstance(ltpc, dict):
        return None
    ltp = ltpc.get("ltp")
    return float(ltp) if ltp is not None else None


def _strike_maps_from_chain(payload: Any) -> tuple[list[StrikeInstrumentMap], float]:
    rows = payload if isinstance(payload, list) else None
    if rows is None and isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict) and isinstance(data.get("data"), list):
            rows = data["data"]
    if not rows:
        raise ValueError("Option chain has no rows for WebSocket bootstrap")

    spot = 0.0
    maps: list[StrikeInstrumentMap] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        strike = item.get("strike_price")
        if strike is None:
            continue
        if spot <= 0:
            spot_val = item.get("underlying_spot_price")
            if spot_val is not None:
                spot = float(spot_val)
        ce_key = _dig(item, "call_options", "instrument_key")
        pe_key = _dig(item, "put_options", "instrument_key")
        if ce_key and pe_key:
            maps.append(
                StrikeInstrumentMap(
                    strike_price=float(strike),
                    call_key=str(ce_key),
                    put_key=str(pe_key),
                )
            )
    if spot <= 0 or not maps:
        raise ValueError("Could not parse strike instrument keys from option chain")
    return maps, spot


def _zone_instrument_keys(
    strike_maps: list[StrikeInstrumentMap],
    zone_strikes: list[float],
) -> list[str]:
    by_strike = {m.strike_price: m for m in strike_maps}
    keys: list[str] = []
    for strike in zone_strikes:
        mapped = by_strike.get(strike) or by_strike.get(float(int(strike)))
        if not mapped:
            continue
        keys.extend([mapped.call_key, mapped.put_key])
    return keys


class OiMomentumStreamManager:
    """One Upstox MarketDataStreamerV3 session per symbol (zone strikes + index spot)."""

    def __init__(self) -> None:
        self._sessions: dict[str, StreamSessionState] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._streamers: dict[str, MarketDataStreamerV3] = {}
        self._global_lock = threading.Lock()

    def get_session(self, symbol: str) -> StreamSessionState | None:
        return self._sessions.get(normalize_symbol(symbol))

    def status(self, symbol: str | None = None) -> dict[str, Any]:
        if symbol:
            session = self.get_session(symbol)
            return session.snapshot_status() if session else {"symbol": normalize_symbol(symbol), "status": "stopped"}
        return {
            "sessions": [s.snapshot_status() for s in self._sessions.values()],
        }

    def stop(self, symbol: str) -> dict[str, Any]:
        sym = normalize_symbol(symbol)
        with self._global_lock:
            streamer = self._streamers.pop(sym, None)
            session = self._sessions.get(sym)
            if session:
                session.status = "stopped"
            thread = self._threads.pop(sym, None)
        if streamer:
            try:
                streamer.disconnect()
            except Exception as exc:
                logger.warning("Stream disconnect for %s: %s", sym, exc)
        if thread and thread.is_alive():
            thread.join(timeout=3)
        return self.status(sym)

    async def start(self, access_token: str | None, symbol: str) -> dict[str, Any]:
        token = get_access_token(access_token)
        if not token:
            raise RuntimeError("Upstox access token required for WebSocket stream")

        sym = normalize_symbol(symbol)
        self.stop(sym)

        underlying = await resolve_underlying(sym)
        chain_payload, expiry = await fetch_live_option_chain(token, sym)
        strike_maps, spot = _strike_maps_from_chain(chain_payload)
        strikes = [m.strike_price for m in strike_maps]
        step = infer_strike_step(strikes, spot, 50 if sym == "NIFTY" else 100)
        smoothed = smooth_atm_strike(spot, step, None)
        zone = support_zone_strikes(smoothed, step)
        option_keys = _zone_instrument_keys(strike_maps, zone)

        index_key = underlying["instrument_key"]
        if sym in INDEX_INSTRUMENT_KEYS:
            index_key = INDEX_INSTRUMENT_KEYS[sym]

        book = LiveOiBook(symbol=sym, expiry=expiry, spot=spot, strike_step=step, zone_strikes=zone)
        book.smoothed_atm = smoothed
        for mapped in strike_maps:
            if mapped.strike_price in zone:
                book.key_side[mapped.call_key] = (mapped.strike_price, "CE")
                book.key_side[mapped.put_key] = (mapped.strike_price, "PE")

        session = StreamSessionState(
            symbol=sym,
            expiry=expiry,
            status="connecting",
            index_key=index_key,
            subscribed_keys=[index_key, *option_keys],
            zone_strikes=zone,
            strike_maps=strike_maps,
            started_at=time.time(),
            chain_bootstrapped_at=time.time(),
            book=book,
        )

        with self._global_lock:
            self._sessions[sym] = session

        thread = threading.Thread(
            target=self._run_stream,
            args=(sym, token, index_key, option_keys),
            name=f"oi-momentum-ws-{sym}",
            daemon=True,
        )
        with self._global_lock:
            self._threads[sym] = thread
        thread.start()
        return session.snapshot_status()

    def _run_stream(
        self,
        symbol: str,
        token: str,
        index_key: str,
        option_keys: list[str],
    ) -> None:
        session = self._sessions[symbol]
        configuration = upstox_client.Configuration()
        configuration.access_token = token
        api_client = upstox_client.ApiClient(configuration)
        streamer = MarketDataStreamerV3(api_client, instrumentKeys=[index_key], mode="ltpc")

        def on_open(*_args: Any) -> None:
            session.status = "connected"
            session.error = None
            if option_keys:
                try:
                    streamer.subscribe(option_keys, "full")
                except Exception as exc:
                    session.status = "error"
                    session.error = f"Subscribe failed: {exc}"
                    logger.exception("OI stream subscribe failed for %s", symbol)

        def on_message(msg: dict[str, Any], *_args: Any) -> None:
            self._handle_message(session, msg)

        def on_error(err: Any, *_args: Any) -> None:
            session.status = "error"
            session.error = str(err)
            logger.warning("OI stream error %s: %s", symbol, err)

        def on_close(*args: Any) -> None:
            code = args[0] if args else None
            reason = args[1] if len(args) > 1 else None
            if session.status != "stopped":
                session.status = "error" if code not in (1000, None) else "stopped"
                session.error = f"closed: {code} {reason}"

        streamer.on("open", on_open)
        streamer.on("message", on_message)
        streamer.on("error", on_error)
        streamer.on("close", on_close)
        streamer.auto_reconnect(True, interval=2, retry_count=10)

        with self._global_lock:
            self._streamers[symbol] = streamer

        try:
            streamer.connect()
            while session.status in ("connecting", "connected"):
                time.sleep(1)
        except Exception as exc:
            session.status = "error"
            session.error = str(exc)
            logger.exception("OI stream thread failed for %s", symbol)

    def _handle_message(self, session: StreamSessionState, msg: dict[str, Any]) -> None:
        feeds = msg.get("feeds")
        if not isinstance(feeds, dict):
            return
        book = session.book
        if book is None:
            return
        now = time.time()

        with session._lock:
            for instrument_key, feed in feeds.items():
                if not isinstance(feed, dict):
                    continue
                if instrument_key == session.index_key:
                    ltp = _parse_index_ltpc(feed)
                    if ltp is not None and ltp > 0:
                        book.spot = ltp
                        book.spot_updated_at = now
                    continue

                side_info = book.key_side.get(instrument_key)
                if not side_info:
                    continue
                strike, side = side_info
                parsed = _parse_option_full_feed(feed)
                if not parsed:
                    continue
                if side == "CE":
                    book.apply_call_tick(
                        strike,
                        oi=parsed["oi"],
                        volume=parsed["volume"],
                        ltp=parsed["ltp"],
                        ts=now,
                    )
                else:
                    book.apply_put_tick(
                        strike,
                        oi=parsed["oi"],
                        volume=parsed["volume"],
                        ltp=parsed["ltp"],
                        ts=now,
                    )

            session.tick_count = book.tick_count
            session.last_tick_at = book.last_tick_at

            if book.spot > 0:
                prev_smoothed = book.smoothed_atm
                book.smoothed_atm = smooth_atm_strike(book.spot, book.strike_step, prev_smoothed)
                book.zone_strikes = support_zone_strikes(book.smoothed_atm, book.strike_step)
                if book.smoothed_atm != prev_smoothed:
                    self._maybe_rotate_zone(session, book)

    def _maybe_rotate_zone(self, session: StreamSessionState, book: LiveOiBook) -> None:
        """Re-subscribe when smoothed ATM moves (uses bootstrap strike map)."""
        if not session.strike_maps:
            return
        new_zone = support_zone_strikes(book.smoothed_atm, book.strike_step)
        new_keys = _zone_instrument_keys(session.strike_maps, new_zone)
        old_keys = [k for k in session.subscribed_keys if k != session.index_key]
        if set(new_keys) == set(old_keys):
            book.zone_strikes = new_zone
            return
        streamer = self._streamers.get(session.symbol)
        if not streamer:
            return
        try:
            if old_keys:
                streamer.unsubscribe(old_keys)
            if new_keys:
                streamer.subscribe(new_keys, "full")
            book.key_side = {}
            for mapped in session.strike_maps:
                if mapped.strike_price in new_zone:
                    book.key_side[mapped.call_key] = (mapped.strike_price, "CE")
                    book.key_side[mapped.put_key] = (mapped.strike_price, "PE")
            session.subscribed_keys = [session.index_key, *new_keys]
            session.zone_strikes = new_zone
            book.zone_strikes = new_zone
            logger.info("Rotated OI stream zone for %s -> %s", session.symbol, new_zone)
        except Exception as exc:
            logger.warning("Zone rotation failed for %s: %s", session.symbol, exc)


_manager = OiMomentumStreamManager()


def get_stream_manager() -> OiMomentumStreamManager:
    return _manager
