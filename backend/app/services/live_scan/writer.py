"""Batch SQLite writes off the ingest and ranking threads.

* Minute bars arrive in per-frame lists and are written in bulk.
* Journal rows go through a coalescing mailbox keyed by (session, symbol,
  side): the latest state of a plan replaces any unwritten older state, and
  the mailbox is never dropped. A failed write puts the rows back unless a
  newer version arrived in the meantime.
* Each drain is one transaction (``upsert_live_batch``), so a minute
  rollover for 400 names costs one write lock and one WAL sync.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

from ...db.store import TimelineStore, get_store

logger = logging.getLogger(__name__)

_MAX_ITEMS_PER_DRAIN = 2_000
_IDLE_WAIT_SEC = 0.5

JournalKey = tuple[str, str, str]


def _journal_key(row: dict[str, Any]) -> JournalKey:
    return (str(row.get("session_date")), str(row.get("symbol")), str(row.get("side")))


class LiveScanWriter:
    def __init__(self, store: TimelineStore | None = None) -> None:
        self._store = store
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=20_000)
        self._journal: dict[JournalKey, dict[str, Any]] = {}
        self._journal_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.dropped = 0
        self.minute_rows = 0
        self.journal_rows = 0
        self.session_flushes = 0
        self.failures = 0
        self.last_write_ms = 0.0
        self.max_write_ms = 0.0

    def _db(self) -> TimelineStore:
        return self._store or get_store()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="live-scan-writer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._drain_once(block=False)

    def enqueue_minute(self, bar: dict[str, Any]) -> None:
        self._put(("minutes", [bar]))

    def enqueue_minutes(self, bars: list[dict[str, Any]]) -> None:
        if bars:
            self._put(("minutes", bars))

    def enqueue_session(self, payload: dict[str, Any]) -> None:
        self._put(("session", payload))

    def enqueue_journal(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        with self._journal_lock:
            for row in rows:
                self._journal[_journal_key(row)] = row

    def pending(self) -> int:
        with self._journal_lock:
            journal = len(self._journal)
        return self._queue.qsize() + journal

    def stats(self) -> dict[str, Any]:
        return {
            "queued": self.pending(),
            "dropped": self.dropped,
            "minute_rows": self.minute_rows,
            "journal_rows": self.journal_rows,
            "session_flushes": self.session_flushes,
            "failures": self.failures,
            "last_write_ms": round(self.last_write_ms, 2),
            "max_write_ms": round(self.max_write_ms, 2),
        }

    def _put(self, item: tuple[str, Any]) -> None:
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self.dropped += len(item[1]) if item[0] == "minutes" else 1

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._drain_once(block=True)

    def _take_journal(self) -> list[dict[str, Any]]:
        with self._journal_lock:
            if not self._journal:
                return []
            rows = list(self._journal.values())
            self._journal = {}
        return rows

    def _restore_journal(self, rows: list[dict[str, Any]]) -> None:
        with self._journal_lock:
            for row in rows:
                self._journal.setdefault(_journal_key(row), row)

    def _drain_once(self, *, block: bool) -> None:
        bars: list[dict[str, Any]] = []
        sessions: list[dict[str, Any]] = []
        try:
            if block:
                kind, payload = self._queue.get(timeout=_IDLE_WAIT_SEC)
            else:
                kind, payload = self._queue.get_nowait()
            self._collect(kind, payload, bars, sessions)
            for _ in range(_MAX_ITEMS_PER_DRAIN):
                kind, payload = self._queue.get_nowait()
                self._collect(kind, payload, bars, sessions)
        except queue.Empty:
            pass
        journal = self._take_journal()
        self._write(bars, journal)
        for payload in sessions:
            self._flush_session(payload)
        if not block and not self._queue.empty():
            self._drain_once(block=False)

    @staticmethod
    def _collect(kind: str, payload: Any, bars: list[dict[str, Any]], sessions: list[dict[str, Any]]) -> None:
        if kind == "minutes" and isinstance(payload, list):
            bars.extend(payload)
        elif kind == "session" and isinstance(payload, dict):
            sessions.append(payload)

    def _write(self, bars: list[dict[str, Any]], journal: list[dict[str, Any]]) -> None:
        if not bars and not journal:
            return
        started = time.perf_counter()
        try:
            written_bars, written_plans = self._db().upsert_live_batch(bars, journal)
            self.minute_rows += written_bars
            self.journal_rows += written_plans
        except Exception:
            self.failures += 1
            self._restore_journal(journal)
            logger.exception("Failed to persist %d live minute bars and %d plans", len(bars), len(journal))
        elapsed = (time.perf_counter() - started) * 1000.0
        self.last_write_ms = elapsed
        self.max_write_ms = max(self.max_write_ms, elapsed)

    def _flush_session(self, payload: dict[str, Any]) -> None:
        candles = payload.get("candles") or []
        index_candles = payload.get("index_candles") or []
        futures = payload.get("futures_oi") or []
        try:
            if candles:
                self._db().upsert_candles(candles)
            if index_candles:
                self._db().upsert_index_candles(index_candles)
            if futures:
                self._db().upsert_futures_oi_daily(futures)
            self.session_flushes += 1
            logger.info(
                "Session close persisted %d cash bars and %d futures OI rows for %s",
                len(candles),
                len(futures),
                payload.get("trade_date"),
            )
        except Exception:
            self.failures += 1
            logger.exception("Failed to persist live scan session close")
