"""The Order Flow trigger log: every buy / sell / stale the board raised, kept for backtests.

The board derives its triggers in the browser (frontend ``flowSignals.ts``) and
posts each one here as it is raised, again when it goes stale, and again when
the reader closes it or continues it (``decision``). Layout, one
directory per session, kept apart from the market files (the collector deletes
those when a new session is stored; these are never deleted):

    data/order_flow_signals/<date>/signals.json          {id: record}
    data/order_flow_signals/<date>/candles/<SYMBOL>.json  [[epoch_ms, close, oi], ...]

A record is the trigger as the board had it (kind, entry band, stop, target,
trigger time) plus the reading that raised it (``context``) and when this
server first heard of it (``recordedAt``). The 1-minute futures candles of each
underlying that triggered are stored beside it, so a backtest can walk forward
from ``triggeredAt`` without asking a provider for history it does not serve.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

SIGNALS_DIR = Path(__file__).resolve().parents[3] / "data" / "order_flow_signals"

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SYMBOL = re.compile(r"^[A-Za-z0-9&._-]{1,40}$")


def valid_date(date: str) -> bool:
    return bool(_DATE.match(date))


def valid_symbol(symbol: str) -> bool:
    return bool(_SYMBOL.match(symbol))


def _write_json(path: Path, value: Any) -> None:
    """Write through a temp file so a crash never leaves half a log behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, separators=(",", ":"))
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


# How far a trigger has got: active, stale and waiting, stale and watched on, then the two ends.
_STAGE = {None: 0, "continued": 1, "closed": 2, "missed": 2}


def _stage(record: dict[str, Any]) -> int:
    if record.get("state") != "stale":
        return -1
    return _STAGE.get(record.get("decision"), 0)


def _newer(before: dict[str, Any], record: dict[str, Any]) -> bool:
    """A record replaces the held one only by going further: a late, older copy never undoes a stale, a continue or a close."""
    if _stage(record) != _stage(before):
        return _stage(record) > _stage(before)
    if _stage(before) in (-1, 2):
        return False
    ignore = ("recordedAt", "updatedAt")
    return {k: v for k, v in record.items() if k not in ignore} != {k: v for k, v in before.items() if k not in ignore}


class SignalLog:
    def __init__(self, root: Path = SIGNALS_DIR) -> None:
        self.root = root
        self._lock = threading.Lock()

    def _signals_path(self, date: str) -> Path:
        return self.root / date / "signals.json"

    def _read_signals(self, date: str) -> dict[str, dict[str, Any]]:
        try:
            return json.loads(self._signals_path(date).read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def upsert(self, date: str, records: list[dict[str, Any]], now_ms: float | None = None) -> dict[str, int]:
        """Add new triggers and update known ones. A stale trigger never goes back to active."""
        stamp = int(now_ms if now_ms is not None else time.time() * 1000)
        added = updated = 0
        with self._lock:
            held = self._read_signals(date)
            for record in records:
                key = record["id"]
                before = held.get(key)
                if before is None:
                    held[key] = {**record, "recordedAt": stamp, "updatedAt": stamp}
                    added += 1
                    continue
                if not _newer(before, record):
                    continue
                held[key] = {**record, "recordedAt": before.get("recordedAt", stamp), "updatedAt": stamp}
                updated += 1
            if added or updated:
                _write_json(self._signals_path(date), held)
        return {"added": added, "updated": updated, "total": len(held)}

    def put_candles(self, date: str, symbol: str, candles: list[list[float]]) -> None:
        """Replace one underlying's candles for the session; a shorter series never overwrites a longer one."""
        path = self.root / date / "candles" / f"{symbol}.json"
        with self._lock:
            try:
                held = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                held = []
            if len(candles) >= len(held):
                _write_json(path, candles)

    def read(self, date: str, with_candles: bool = False) -> dict[str, Any]:
        with self._lock:
            signals = sorted(self._read_signals(date).values(), key=lambda row: (row.get("triggeredAt", 0), row["id"]))
            out: dict[str, Any] = {"date": date, "count": len(signals), "signals": signals}
            if with_candles:
                folder = self.root / date / "candles"
                candles: dict[str, Any] = {}
                for symbol in sorted({row["symbol"] for row in signals}):
                    try:
                        candles[symbol] = json.loads((folder / f"{symbol}.json").read_text(encoding="utf-8"))
                    except (FileNotFoundError, json.JSONDecodeError):
                        continue
                out["candles"] = candles
        return out

    def dates(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        rows = []
        for entry in sorted(self.root.iterdir(), reverse=True):
            if entry.is_dir() and valid_date(entry.name):
                with self._lock:
                    count = len(self._read_signals(entry.name))
                rows.append({"date": entry.name, "count": count})
        return rows


_log: SignalLog | None = None


def get_signal_log() -> SignalLog:
    global _log
    if _log is None:
        _log = SignalLog()
    return _log
