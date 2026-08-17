from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable

import upstox_client
from upstox_client import MarketDataStreamerV3

from .models import ensure_ist, parse_epoch_to_ist

logger = logging.getLogger(__name__)

TickHandler = Callable[[float, datetime], None]


def _dig(mapping: dict[str, Any], *keys: str) -> Any:
    cur: Any = mapping
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def parse_ltpc_tick(feed: dict[str, Any]) -> tuple[float, datetime] | None:
    """Extract (ltp, timestamp) from an Upstox V3 feed payload."""
    ltpc = feed.get("ltpc")
    if not isinstance(ltpc, dict):
        index_ff = _dig(feed, "fullFeed", "indexFF") or _dig(feed, "fullFeed", "indexFf")
        if isinstance(index_ff, dict):
            ltpc = index_ff.get("ltpc")
    if not isinstance(ltpc, dict):
        return None

    ltp = ltpc.get("ltp")
    if ltp is None:
        return None
    price = float(ltp)
    if price <= 0:
        return None

    ltt = ltpc.get("ltt")
    if ltt is not None:
        ts = parse_epoch_to_ist(ltt)
    else:
        ts = ensure_ist(datetime.now().astimezone())
    return price, ts


class MarketDataFeed:
    """Upstox Market Data Feeder V3 with exponential-backoff reconnect."""

    def __init__(
        self,
        access_token: str,
        instrument_key: str,
        on_tick: TickHandler,
        *,
        mode: str = "ltpc",
        max_backoff_sec: float = 60.0,
    ) -> None:
        self._token = access_token
        self._instrument_key = instrument_key
        self._on_tick = on_tick
        self._mode = mode
        self._max_backoff = max_backoff_sec

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._streamer: MarketDataStreamerV3 | None = None
        self._lock = threading.Lock()
        self.status = "stopped"
        self.last_error: str | None = None
        self.reconnect_attempts = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="mtf-rsi-ws",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.status = "stopped"
        streamer = None
        with self._lock:
            streamer = self._streamer
            self._streamer = None
        if streamer is not None:
            try:
                streamer.disconnect()
            except Exception as exc:
                logger.warning("Disconnect error: %s", exc)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._connect_once()
                backoff = 1.0
                self.reconnect_attempts = 0
            except Exception as exc:
                self.last_error = str(exc)
                self.status = "error"
                logger.exception("WebSocket session failed: %s", exc)

            if self._stop.is_set():
                break

            self.reconnect_attempts += 1
            sleep_for = min(backoff, self._max_backoff)
            logger.warning(
                "Reconnecting in %.1fs (attempt %d)",
                sleep_for,
                self.reconnect_attempts,
            )
            self.status = "reconnecting"
            self._stop.wait(sleep_for)
            backoff = min(backoff * 2.0, self._max_backoff)

    def _connect_once(self) -> None:
        configuration = upstox_client.Configuration()
        configuration.access_token = self._token
        api_client = upstox_client.ApiClient(configuration)
        streamer = MarketDataStreamerV3(
            api_client,
            instrumentKeys=[self._instrument_key],
            mode=self._mode,
        )

        session_done = threading.Event()

        def on_open(*_args: Any) -> None:
            self.status = "connected"
            self.last_error = None
            logger.info("WebSocket connected; subscribed to %s", self._instrument_key)

        def on_message(msg: dict[str, Any], *_args: Any) -> None:
            self._handle_message(msg)

        def on_error(err: Any, *_args: Any) -> None:
            self.last_error = str(err)
            self.status = "error"
            logger.warning("WebSocket error: %s", err)

        def on_close(*args: Any) -> None:
            code = args[0] if args else None
            reason = args[1] if len(args) > 1 else None
            if not self._stop.is_set():
                self.status = "disconnected"
                self.last_error = f"closed: {code} {reason}"
                logger.warning("WebSocket closed: %s %s", code, reason)
            session_done.set()

        streamer.on("open", on_open)
        streamer.on("message", on_message)
        streamer.on("error", on_error)
        streamer.on("close", on_close)
        # SDK reconnect helps for brief blips; outer loop covers hard failures.
        streamer.auto_reconnect(True, interval=2, retry_count=5)

        with self._lock:
            self._streamer = streamer

        self.status = "connecting"
        try:
            streamer.connect()
            while not self._stop.is_set() and not session_done.is_set():
                if self.status in ("error", "disconnected", "stopped"):
                    break
                time.sleep(0.5)
        finally:
            try:
                streamer.disconnect()
            except Exception:
                pass
            with self._lock:
                if self._streamer is streamer:
                    self._streamer = None

    def _handle_message(self, msg: dict[str, Any]) -> None:
        feeds = msg.get("feeds")
        if not isinstance(feeds, dict):
            return
        feed = feeds.get(self._instrument_key)
        if not isinstance(feed, dict):
            # Some payloads key by encoded form; scan values.
            for value in feeds.values():
                if isinstance(value, dict):
                    parsed = parse_ltpc_tick(value)
                    if parsed is not None:
                        self._on_tick(*parsed)
                        return
            return
        parsed = parse_ltpc_tick(feed)
        if parsed is not None:
            self._on_tick(*parsed)
