"""One full-mode Upstox V3 connection for the F&O cash and front-month futures universe.

Thread layout
-------------
``live-scan-ws``       owns the connection lifecycle and reconnect backoff.
SDK socket thread      ``run_forever``. Appends raw binary frames to a deque and
                       returns. It never decodes, never locks, never waits.
``live-scan-ingest``   the only writer of the book. Decodes protobuf directly,
                       applies frames, seals minutes on the clock, closes
                       journal path windows, hands bars to the writer.
``live-scan-ranker``   1 Hz on a fixed schedule. Reads the book's published
                       view, ranks, advances the journal, pre-encodes JSON.
``live-scan-writer``   SQLite, one transaction per drain.

Each connection gets an epoch. Frames and callbacks from an older epoch are
ignored, so a half-closed socket can never feed the book next to its
replacement. The SDK's own auto-reconnect is disabled: exactly one component
decides when to reconnect.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import deque
from typing import Any, Callable

import upstox_client
from upstox_client import MarketDataStreamerV3

from ...config import get_access_token
from ...db.store import get_store
from ..mtf_rsi_manager import get_mtf_rsi_manager
from ..oi_momentum.ws_feed import get_stream_manager
from .baskets import default_baskets, load_nifty_members
from .clocks import (
    hold_through_close,
    in_session,
    now_ist,
    past_feed_end,
    required_daily_session,
    session_length,
    session_minute,
    session_name,
    trade_date,
)
from .context import load_context
from .feed import decode_frame
from .history import ensure_latest_candles, ensure_latest_index_candles
from .journal import CallJournal
from .ranker import rank_boards
from .state import LiveBook
from .universe import FULL_MODE_KEY_LIMIT, UniverseSymbol, build_universe
from .volume_profile import VolumeProfile
from .writer import LiveScanWriter

logger = logging.getLogger(__name__)

_SUBSCRIBE_CHUNK = 100
_FRESH_SECONDS = 30.0
_BUSY = {"connecting", "connected", "reconnecting"}
_FRAME_BACKLOG = 50_000
_HEALTHY_AFTER_SEC = 30.0
_MAX_BACKOFF_SEC = 60.0
_RANK_PERIOD_SEC = 1.0
_SEAL_EVERY_SEC = 0.5
_WINDOW_EVERY_SEC = 0.5
_SAMPLES = 512
_BOARDS = ("momentum", "breakout", "oi", "calls")
_SEGMENTS = {"fno", "cash"}
_MIN_RANK_SLEEP_SEC = 0.05


def _row_segment(row: dict[str, Any]) -> str:
    segment = row.get("segment")
    if segment in {"fno", "cash", "index"}:
        return str(segment)
    return "index" if row.get("kind") == "index" else "fno"


def _journal_view_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts for the rows on one tab. The stored summary covers both segments."""
    counts = {name: 0 for name in ("pending", "open", "target", "stopped", "closed", "cancelled")}
    swing = {name: 0 for name in ("pending", "open", "target", "stopped", "cancelled")}
    results: list[float] = []
    swing_results: list[float] = []
    for row in rows:
        status = str(row.get("status") or "")
        counts[status] = counts.get(status, 0) + 1
        if status in {"target", "stopped", "closed"} and row.get("result_pct") is not None:
            results.append(float(row["result_pct"]))
        swing_status = str(row.get("swing_status") or "")
        if swing_status in swing:
            swing[swing_status] += 1
        if swing_status in {"target", "stopped"} and row.get("swing_result_pct") is not None:
            swing_results.append(float(row["swing_result_pct"]))
    wins = sum(1 for value in results if value > 0)
    swing_wins = sum(1 for value in swing_results if value > 0)
    return {
        "plans": len(rows),
        "pending": counts["pending"],
        "open": counts["open"],
        "target": counts["target"],
        "stopped": counts["stopped"],
        "closed": counts["closed"],
        "cancelled": counts["cancelled"],
        "win_rate_pct": round(wins / len(results) * 100.0, 1) if results else None,
        "avg_result_pct": round(sum(results) / len(results), 2) if results else None,
        "swing_pending": swing["pending"],
        "swing_open": swing["open"],
        "swing_target": swing["target"],
        "swing_stopped": swing["stopped"],
        "swing_cancelled": swing["cancelled"],
        "swing_win_rate_pct": round(swing_wins / len(swing_results) * 100.0, 1) if swing_results else None,
        "swing_avg_result_pct": round(sum(swing_results) / len(swing_results), 2) if swing_results else None,
    }


def _check_segment(segment: str) -> str:
    if segment not in _SEGMENTS:
        raise ValueError("segment must be fno or cash")
    return segment


def _in_segment(row: dict[str, Any], segment: str) -> bool:
    current = _row_segment(row)
    if segment == "fno":
        return current in {"fno", "index"}
    return current == segment


def _with_indexes(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Keep Nifty and Sensex in the payload even when the board is long."""
    indexes = [row for row in rows if row.get("kind") == "index"]
    others = [row for row in rows if row.get("kind") != "index"]
    room = max(0, limit - len(indexes))
    return indexes + others[:room]


def _percentiles(samples: deque[float]) -> dict[str, float | None]:
    if not samples:
        return {"p50": None, "p99": None, "max": None}
    ordered = sorted(samples)
    last = len(ordered) - 1
    return {
        "p50": round(ordered[last // 2], 2),
        "p99": round(ordered[min(last, int(last * 0.99))], 2),
        "max": round(ordered[last], 2),
    }


def _dumps(payload: Any) -> bytes:
    return json.dumps(payload, separators=(",", ":"), default=str).encode()


class LiveScanConflict(RuntimeError):
    def __init__(self, holders: list[str]) -> None:
        self.holders = holders
        names = ", ".join(holders)
        super().__init__(
            f"Upstox allows 2 market-data connections. Stop these feeds first: {names}."
        )


def conflicting_feeds() -> list[str]:
    holders: list[str] = []
    try:
        status = get_stream_manager().status()
    except Exception:
        status = {}
    for session in status.get("sessions") or []:
        if session.get("status") in ("connecting", "connected"):
            holders.append(f"OI Momentum ({session.get('symbol') or 'session'})")
    try:
        mtf_status = str(get_mtf_rsi_manager().status().get("status") or "stopped")
    except Exception:
        mtf_status = "stopped"
    if mtf_status != "stopped":
        holders.append("MTF RSI")
    return holders


class RawFrameStreamer(MarketDataStreamerV3):
    """Hands raw binary frames to a sink instead of running ``MessageToDict`` on the socket thread."""

    def __init__(self, api_client: Any, sink: Callable[[bytes], None]) -> None:
        super().__init__(api_client, instrumentKeys=[], mode="full")
        self._sink = sink

    def handle_message(self, ws: Any, message: bytes) -> None:
        self._sink(message)


class LiveScanHub:
    def __init__(self, writer: LiveScanWriter | None = None) -> None:
        self._writer = writer or LiveScanWriter()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._publisher: threading.Thread | None = None
        self._ingest: threading.Thread | None = None
        self._streamer: MarketDataStreamerV3 | None = None
        self._book: LiveBook | None = None
        self._universe: list[UniverseSymbol] = []
        self.status = "stopped"
        self.last_error: str | None = None
        self.reconnect_attempts = 0
        self._hold_through_close = False
        self._session_flushed = False
        self._session_date = ""
        self._ranked: dict[str, list[dict[str, Any]]] = {name: [] for name in _BOARDS}
        self._ranked_at: float | None = None
        self._ranked_seq = 0
        self._encoded: dict[tuple[str, int], bytes] = {}
        self._encoded_seq = -1
        self._subscribed = 0
        self._generation = 0
        self._candle_sync: dict[str, Any] | None = None
        self._baskets = default_baskets()
        self._journal = CallJournal("")
        self._journal_rows: list[dict[str, Any]] = []
        self._journal_summary: dict[str, Any] = self._journal.summary()
        # Ingest pipeline. The deque is the only object the socket thread touches.
        # A ``None`` payload is the reconnect marker, ordered with the frames around it.
        self._frames: deque[tuple[int, float, bytes | None]] = deque(maxlen=_FRAME_BACKLOG)
        self._frame_signal = threading.Event()
        self._conn_epoch = 0
        self._run_connections = 0
        self._connected_at: float | None = None
        self._frames_in = 0
        self._frames_dropped = 0
        self._stale_frames = 0
        self._decode_errors = 0
        self._ingest_lag_ms: deque[float] = deque(maxlen=_SAMPLES)
        self._cycle_ms: deque[float] = deque(maxlen=_SAMPLES)
        self._unauthorized = False

    # ---------------------------------------------------------------- control

    async def start(self, access_token: str | None = None) -> dict[str, Any]:
        holders = conflicting_feeds()
        if holders:
            raise LiveScanConflict(holders)
        token = get_access_token(access_token)
        if not token:
            raise RuntimeError("Upstox access token required")

        with self._lock:
            if self.status == "starting" or (
                self._thread and self._thread.is_alive() and self.status in _BUSY
            ):
                return self.status_payload()
            self._generation += 1
            generation = self._generation
            self.status = "starting"

        try:
            universe = await build_universe()
            baskets = default_baskets()
            try:
                baskets["NIFTY"] = await load_nifty_members()
            except Exception:
                logger.warning("Nifty 50 constituent list unavailable; using the fallback basket")
            self._baskets = baskets
            session_date = required_daily_session()

            def note_missing(stale: list[str]) -> None:
                self._candle_sync = {
                    "session": session_date,
                    "requested": len(stale),
                    "success": 0,
                    "failed": 0,
                    "phase": "updating" if stale else "ready",
                }

            equity = [item for item in universe if item.kind != "index"]
            indexes = [item for item in universe if item.kind == "index"]
            equity_sync = await ensure_latest_candles(
                equity,
                token,
                session_date=session_date,
                should_cancel=lambda: generation != self._generation,
                on_found=note_missing,
            )
            index_sync = await ensure_latest_index_candles(
                indexes,
                token,
                session_date=session_date,
                should_cancel=lambda: generation != self._generation,
            )
            self._candle_sync = {
                "session": session_date,
                "requested": int(equity_sync.get("requested") or 0) + int(index_sync.get("requested") or 0),
                "success": int(equity_sync.get("success") or 0) + int(index_sync.get("success") or 0),
                "failed": int(equity_sync.get("failed") or 0) + int(index_sync.get("failed") or 0),
                "skipped": int(equity_sync.get("skipped") or 0) + int(index_sync.get("skipped") or 0),
                "total_bars": int(equity_sync.get("total_bars") or 0) + int(index_sync.get("total_bars") or 0),
                "deferred": int(equity_sync.get("deferred") or 0),
                "budget_remaining": equity_sync.get("budget_remaining"),
                "phase": "ready",
            }
            if generation != self._generation:
                return self.status_payload()
            as_of = trade_date()
            contexts = await asyncio.to_thread(load_context, universe, before_date=as_of)
            minute_rows = await asyncio.to_thread(get_store().live_minute_profile, as_of)
            profile = VolumeProfile.calibrated(minute_rows)
            book = LiveBook(contexts, profile=profile)
            journal = CallJournal(as_of)
            stored_plans = await asyncio.to_thread(get_store().list_live_call_journal, as_of)
            journal.load(stored_plans)
        except Exception:
            with self._lock:
                if self._generation == generation and self.status == "starting":
                    self.status = "stopped"
            raise
        if generation != self._generation:
            with self._lock:
                if self.status == "starting":
                    self.status = "stopped"
            return self.status_payload()

        await asyncio.to_thread(self._shutdown_threads)
        with self._lock:
            if generation != self._generation:
                if self.status == "starting":
                    self.status = "stopped"
                return self.status_payload()
            self._book = book
            self._journal = journal
            self._journal_rows = journal.rows()
            self._journal_summary = journal.summary()
            self._universe = universe
            self._session_date = as_of
            self._subscribed = len(book.instrument_keys)
            self._session_flushed = False
            self._ranked = {name: [] for name in _BOARDS}
            self._ranked_at = None
            self._encoded = {}
            self.last_error = None
            self.reconnect_attempts = 0
            self._unauthorized = False
            self._run_connections = 0
            self._frames.clear()
            self._hold_through_close = hold_through_close()
            self._stop = threading.Event()
            self.status = "connecting"
            self._writer.start()
            stop = self._stop
            self._ingest = threading.Thread(target=self._ingest_loop, args=(stop,), name="live-scan-ingest", daemon=True)
            self._publisher = threading.Thread(target=self._publish_loop, args=(stop,), name="live-scan-ranker", daemon=True)
            self._thread = threading.Thread(
                target=self._run_loop,
                args=(token, book.instrument_keys, stop),
                name="live-scan-ws",
                daemon=True,
            )
            self._ingest.start()
            self._publisher.start()
            self._thread.start()
        logger.info(
            "Live scan hub starting: %d symbols, %d keys, hold_through_close=%s, volume profile sessions=%d",
            len(universe),
            self._subscribed,
            self._hold_through_close,
            profile.sessions,
        )
        return self.status_payload()

    def stop(self) -> dict[str, Any]:
        """Blocking: joins threads. Call from a worker thread, not the event loop."""
        self._generation += 1
        self._shutdown_threads()
        self._flush_journal(force=True)
        self._writer.stop()
        self.status = "stopped"
        return self.status_payload()

    def _shutdown_threads(self) -> None:
        self._stop.set()
        self._frame_signal.set()
        self._disconnect_streamer()
        current = threading.current_thread()
        for thread in (self._thread, self._publisher, self._ingest):
            if thread and thread.is_alive() and thread is not current:
                thread.join(timeout=5)
        self._thread = None
        self._publisher = None
        self._ingest = None

    # ----------------------------------------------------------------- status

    def status_payload(self) -> dict[str, Any]:
        book = self._book
        counts = {"symbols": 0, "futures": 0, "symbols_live": 0, "tick_count": 0}
        last_tick_at = None
        ingest: dict[str, Any] = {}
        if book is not None:
            counts = book.counts(fresh_after=time.time() - _FRESH_SECONDS)
            last_tick_at = book.last_tick_at
            ingest = book.ingest_stats()
        age = None
        if last_tick_at is not None:
            age = round(max(0.0, time.time() - last_tick_at), 1)
        futures_matched = sum(1 for item in self._universe if item.future_key)
        fno_symbols = sum(1 for item in self._universe if item.segment == "fno")
        cash_symbols = sum(1 for item in self._universe if item.segment == "cash")
        return {
            "status": self.status,
            "error": self.last_error,
            "subscribed": self._subscribed,
            "universe": len(self._universe),
            "futures_matched": futures_matched,
            "fno_symbols": fno_symbols,
            "cash_symbols": cash_symbols,
            "full_key_limit": FULL_MODE_KEY_LIMIT,
            "tick_count": counts["tick_count"],
            "last_tick_at": last_tick_at,
            "last_tick_age_sec": age,
            "symbols_live": counts["symbols_live"],
            "reconnect_attempts": self.reconnect_attempts,
            "offhours": not self._hold_through_close and self.status in _BUSY,
            "session_name": session_name(),
            "session_flushed": self._session_flushed,
            "candle_sync": self._candle_sync,
            "pipeline": {
                "frames_in": self._frames_in,
                "frame_backlog": len(self._frames),
                "frames_dropped": self._frames_dropped,
                "stale_frames": self._stale_frames,
                "decode_errors": self._decode_errors,
                "ingest_lag_ms": _percentiles(self._ingest_lag_ms),
                "rank_cycle_ms": _percentiles(self._cycle_ms),
                **ingest,
            },
            "writer": self._writer.stats(),
        }

    def _board_body(self, board: str, limit: int, segment: str) -> dict[str, Any]:
        with self._lock:
            ranked = self._ranked
            ranked_at = self._ranked_at
            journal_rows = self._journal_rows
        visible = {
            name: [row for row in rows if _in_segment(row, segment)]
            for name, rows in ranked.items()
        }
        journal = [row for row in journal_rows if _in_segment(row, segment)]
        totals = {name: len(rows) for name, rows in visible.items()}
        totals["journal"] = len(journal)
        body: dict[str, Any] = {
            "board": board,
            "segment": segment,
            "ranked_at": ranked_at,
            "totals": totals,
            "journal": journal[:limit],
            "journal_summary": _journal_view_summary(journal),
        }
        if board == "all":
            for name in _BOARDS:
                rows = visible.get(name, [])
                body[name] = rows[:limit] if segment == "cash" else _with_indexes(rows, limit)
            return body
        if board not in _BOARDS:
            raise ValueError("board must be momentum, breakout, oi, calls, or all")
        rows = visible[board]
        body["rows"] = rows[:limit] if segment == "cash" else _with_indexes(rows, limit)
        body["total"] = totals[board]
        return body

    def snapshot(self, board: str = "all", limit: int = 50, segment: str = "fno") -> dict[str, Any]:
        limit = max(1, min(int(limit), 500))
        segment = _check_segment(segment)
        payload = self._board_body(board, limit, segment)
        payload["stale"] = self._is_stale(payload["ranked_at"])
        payload["status"] = self.status_payload()
        return payload

    def snapshot_json(self, board: str = "all", limit: int = 50, segment: str = "fno") -> bytes:
        """Boards are encoded once per ranking cycle; only status is encoded per request."""
        limit = max(1, min(int(limit), 500))
        segment = _check_segment(segment)
        key = (board, limit, segment)
        with self._lock:
            seq = self._ranked_seq
            cached = self._encoded.get(key) if self._encoded_seq == seq else None
        if cached is None:
            body = _dumps(self._board_body(board, limit, segment))
            with self._lock:
                if self._encoded_seq != seq:
                    self._encoded = {}
                    self._encoded_seq = seq
                if len(self._encoded) < 16:
                    self._encoded[key] = body
            cached = body
        stale = b"true" if self._is_stale(self._ranked_at) else b"false"
        return cached[:-1] + b',"stale":' + stale + b',"status":' + _dumps(self.status_payload()) + b"}"

    def _is_stale(self, ranked_at: float | None) -> bool:
        if self.status != "connected":
            return True
        if ranked_at is None:
            return True
        return (time.time() - ranked_at) > 5

    # ----------------------------------------------------------------- ranker

    def _publish_loop(self, stop: threading.Event) -> None:
        next_at = time.monotonic()
        while not stop.is_set():
            started = time.perf_counter()
            try:
                self._publish_once()
            except Exception:
                logger.exception("Live scan ranker failed")
            self._cycle_ms.append((time.perf_counter() - started) * 1000.0)
            if trade_date() != self._session_date and self._session_date:
                logger.info("Trading date rolled over; stopping the live scan feed")
                self._finish_session(stop)
                break
            if self._hold_through_close and past_feed_end() and not self._session_flushed:
                self._finish_session(stop)
                break
            next_at += _RANK_PERIOD_SEC
            now = time.monotonic()
            if next_at < now + _MIN_RANK_SLEEP_SEC:
                # Overran: skip the missed slots instead of firing back to back.
                next_at = now + _MIN_RANK_SLEEP_SEC
            stop.wait(next_at - now)

    def _publish_once(self) -> None:
        book = self._book
        if book is None:
            return
        now = time.time()
        quotes = book.export_quotes()
        ranked = rank_boards(
            quotes,
            progress=book.profile.expected_fraction(now),
            baskets=self._baskets,
            now=now,
        )
        windows = book.drain_windows()
        stamp = now_ist().isoformat()
        journal = self._journal
        journal.advance(ranked.get("calls") or [], stamp, windows=windows, tradable=in_session(now))
        if session_minute(now) >= session_length(now) and not journal.session_closed:
            journal.close_session(stamp)
        self._flush_journal(force=False)
        rows = journal.rows()
        summary = journal.summary()
        with self._lock:
            self._ranked = ranked
            self._ranked_at = time.time()
            self._journal_rows = rows
            self._journal_summary = summary
            self._ranked_seq += 1

    def _flush_journal(self, *, force: bool) -> None:
        rows = self._journal.take_flush(time.time(), min_interval=2.0, force=force)
        if rows:
            self._writer.enqueue_journal(rows)

    def _finish_session(self, stop: threading.Event) -> None:
        """Runs on the ranker thread, which owns the journal."""
        with self._lock:
            if self._session_flushed:
                return
            self._session_flushed = True
            book = self._book
        stamp = now_ist().isoformat()
        if not self._journal.session_closed:
            self._journal.close_session(stamp)
        self._flush_journal(force=True)
        if book is not None:
            session = self._session_date or trade_date()
            rows = book.session_rows(session)
            self._writer.enqueue_session(
                {
                    "trade_date": session,
                    "candles": rows["candles"],
                    "index_candles": rows["index_candles"],
                    "futures_oi": rows["futures_oi"],
                }
            )
        self.status = "stopped"
        stop.set()
        self._frame_signal.set()
        self._disconnect_streamer()
        logger.info("Live scan feed stopped at session end")

    # ----------------------------------------------------------------- ingest

    def _on_raw(self, epoch: int, raw: bytes) -> None:
        """Socket thread. O(1), no decoding, no locks."""
        if epoch != self._conn_epoch:
            self._stale_frames += 1
            return
        frames = self._frames
        if len(frames) == _FRAME_BACKLOG:
            self._frames_dropped += 1
        frames.append((epoch, time.time(), raw))
        self._frames_in += 1
        if not self._frame_signal.is_set():
            self._frame_signal.set()

    def _ingest_loop(self, stop: threading.Event) -> None:
        last_seal = 0.0
        last_window = 0.0
        while not stop.is_set():
            self._frame_signal.wait(0.25)
            self._frame_signal.clear()
            book = self._book
            if book is None:
                continue
            try:
                bars = self._drain_frames(book)
                now = time.time()
                if now - last_seal >= _SEAL_EVERY_SEC:
                    bars.extend(book.seal_minutes(now))
                    last_seal = now
                if now - last_window >= _WINDOW_EVERY_SEC:
                    book.close_window()
                    last_window = now
                if bars:
                    self._writer.enqueue_minutes(bars)
            except Exception:
                logger.exception("Live scan ingest failed")

    def _drain_frames(self, book: LiveBook) -> list[dict[str, Any]]:
        """Frames were epoch-checked on arrival; FIFO order puts a dead socket's
        last frames before the reconnect marker, so they are still good data."""
        bars: list[dict[str, Any]] = []
        frames = self._frames
        while True:
            try:
                _epoch, received, raw = frames.popleft()
            except IndexError:
                return bars
            if raw is None:
                book.mark_reconnect()
                continue
            try:
                _ts, items = decode_frame(raw)
            except Exception:
                self._decode_errors += 1
                continue
            if items:
                bars.extend(book.apply_frame(items, received))
            self._ingest_lag_ms.append((time.time() - received) * 1000.0)

    # ------------------------------------------------------------- connection

    def _run_loop(self, token: str, instrument_keys: list[str], stop: threading.Event) -> None:
        backoff = 1.0
        while not stop.is_set():
            if self._hold_through_close and past_feed_end():
                break
            self._connected_at = None
            try:
                self._connect_once(token, instrument_keys, stop)
            except Exception as exc:
                self.last_error = str(exc)
                self.status = "error"
                logger.exception("Live scan websocket failed")
            if stop.is_set() or (self._hold_through_close and past_feed_end()):
                break
            if self._unauthorized:
                self.status = "error"
                self.last_error = "Upstox rejected the access token (401). Log in again and restart."
                stop.set()
                break
            connected_at = self._connected_at
            if connected_at is not None and time.time() - connected_at >= _HEALTHY_AFTER_SEC:
                backoff = 1.0
                self.reconnect_attempts = 0
            self.reconnect_attempts += 1
            sleep_for = min(backoff, _MAX_BACKOFF_SEC)
            self.status = "reconnecting"
            logger.warning("Live scan reconnecting in %.1fs (attempt %d)", sleep_for, self.reconnect_attempts)
            stop.wait(sleep_for)
            backoff = min(backoff * 2.0, _MAX_BACKOFF_SEC)
        if self.status != "stopped" and not self._unauthorized:
            self.status = "stopped"

    def _connect_once(self, token: str, instrument_keys: list[str], stop: threading.Event) -> None:
        configuration = upstox_client.Configuration()
        configuration.access_token = token
        api_client = upstox_client.ApiClient(configuration)
        self._conn_epoch += 1
        epoch = self._conn_epoch
        streamer = RawFrameStreamer(api_client, lambda raw: self._on_raw(epoch, raw))
        streamer.auto_reconnect(False)
        session_done = threading.Event()

        def current() -> bool:
            return epoch == self._conn_epoch and not stop.is_set()

        def on_open(*_args: Any) -> None:
            if not current():
                return
            self._run_connections += 1
            if self._run_connections > 1:
                self._frames.append((epoch, time.time(), None))
                self._frame_signal.set()
            self.status = "connected"
            self.last_error = None
            self._connected_at = time.time()
            for offset in range(0, len(instrument_keys), _SUBSCRIBE_CHUNK):
                chunk = instrument_keys[offset : offset + _SUBSCRIBE_CHUNK]
                if not chunk or not current():
                    break
                try:
                    streamer.subscribe(chunk, "full")
                except Exception as exc:
                    self.last_error = f"Subscribe failed: {exc}"
                    self.status = "error"
                    logger.exception("Live scan subscribe failed at offset %d", offset)
                    session_done.set()
                    return
            logger.info("Live scan subscribed %d keys in full mode (epoch %d)", len(instrument_keys), epoch)

        def on_error(err: Any, *_args: Any) -> None:
            if not current():
                return
            text = str(err)
            if "401" in text:
                self._unauthorized = True
            self.last_error = text
            self.status = "error"
            logger.warning("Live scan websocket error: %s", err)
            session_done.set()

        def on_close(*args: Any) -> None:
            if current():
                code = args[0] if args else None
                reason = args[1] if len(args) > 1 else None
                self.status = "disconnected"
                self.last_error = f"closed: {code} {reason}"
                logger.warning("Live scan websocket closed: %s %s", code, reason)
            session_done.set()

        streamer.on("open", on_open)
        streamer.on("error", on_error)
        streamer.on("close", on_close)

        with self._lock:
            self._streamer = streamer
        self.status = "connecting"
        try:
            streamer.connect()
            while not stop.is_set() and not session_done.is_set():
                session_done.wait(0.5)
        finally:
            # Retire the epoch first so anything the old socket still delivers is ignored.
            if self._conn_epoch == epoch:
                self._conn_epoch = epoch + 1
            try:
                streamer.disconnect()
            except Exception:
                pass
            with self._lock:
                if self._streamer is streamer:
                    self._streamer = None

    def _disconnect_streamer(self) -> None:
        with self._lock:
            streamer = self._streamer
            self._streamer = None
        self._conn_epoch += 1
        if streamer is not None:
            try:
                streamer.disconnect()
            except Exception as exc:
                logger.warning("Live scan disconnect error: %s", exc)


_hub: LiveScanHub | None = None
_hub_lock = threading.Lock()


def get_live_scan_hub() -> LiveScanHub:
    global _hub
    with _hub_lock:
        if _hub is None:
            _hub = LiveScanHub()
        return _hub
