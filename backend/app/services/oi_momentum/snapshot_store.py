from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StrikeSnapshot:
    strike_price: float
    call_oi: int
    put_oi: int
    call_volume: int
    put_volume: int


@dataclass(frozen=True)
class ChainSnapshot:
    captured_at: float
    spot: float
    smoothed_atm: float
    strike_step: int
    rows: tuple[StrikeSnapshot, ...]

    def row_by_strike(self, strike: float) -> StrikeSnapshot | None:
        key = round(strike, 4)
        for row in self.rows:
            if round(row.strike_price, 4) == key:
                return row
        return None


class OiSnapshotStore:
    """In-memory rolling history of option-chain snapshots per symbol."""

    def __init__(self, *, max_snapshots: int = 120) -> None:
        self._max = max_snapshots
        self._history: dict[str, deque[ChainSnapshot]] = {}
        self._smoothed_atm: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def append(self, symbol: str, snapshot: ChainSnapshot) -> None:
        key = symbol.upper()
        async with self._lock:
            bucket = self._history.setdefault(key, deque(maxlen=self._max))
            bucket.append(snapshot)
            self._smoothed_atm[key] = snapshot.smoothed_atm

    async def latest(self, symbol: str) -> ChainSnapshot | None:
        key = symbol.upper()
        async with self._lock:
            bucket = self._history.get(key)
            if not bucket:
                return None
            return bucket[-1]

    async def snapshot_at_or_before(
        self,
        symbol: str,
        min_age_sec: float,
    ) -> ChainSnapshot | None:
        """Return the newest snapshot at least min_age_sec older than the latest."""
        key = symbol.upper()
        async with self._lock:
            bucket = self._history.get(key)
            if not bucket or len(bucket) < 2:
                return None
            latest = bucket[-1]
            target_ts = latest.captured_at - min_age_sec
            candidate: ChainSnapshot | None = None
            for snap in bucket:
                if snap.captured_at <= target_ts:
                    candidate = snap
            return candidate

    async def prior_snapshot(self, symbol: str) -> ChainSnapshot | None:
        """Snapshot from the poll immediately before the latest."""
        key = symbol.upper()
        async with self._lock:
            bucket = self._history.get(key)
            if not bucket or len(bucket) < 2:
                return None
            return bucket[-2]

    async def resolve_baseline(
        self,
        symbol: str,
        window_sec: float,
    ) -> tuple[ChainSnapshot | None, str, float]:
        """
        Pick comparison snapshot for deltas/alerts.

        Returns (baseline, mode, effective_window_sec) where mode is:
        - none: first poll only
        - partial: vs previous poll (window not yet filled)
        - full: vs snapshot at least window_sec ago
        """
        key = symbol.upper()
        async with self._lock:
            bucket = self._history.get(key)
            if not bucket or len(bucket) < 2:
                return None, "none", window_sec
            latest = bucket[-1]
            target_ts = latest.captured_at - window_sec
            candidate: ChainSnapshot | None = None
            for snap in bucket:
                if snap.captured_at <= target_ts:
                    candidate = snap
            if candidate is not None:
                age = latest.captured_at - candidate.captured_at
                return candidate, "full", max(age, 1.0)
            prior = bucket[-2]
            age = latest.captured_at - prior.captured_at
            return prior, "partial", max(age, 1.0)

    async def stats(self, symbol: str) -> dict[str, Any]:
        key = symbol.upper()
        async with self._lock:
            bucket = self._history.get(key)
            if not bucket:
                return {"count": 0, "oldest_age_sec": None, "newest_age_sec": None}
            import time

            now = time.time()
            oldest = bucket[0]
            newest = bucket[-1]
            return {
                "count": len(bucket),
                "oldest_age_sec": round(now - oldest.captured_at, 1),
                "newest_age_sec": round(now - newest.captured_at, 1),
                "smoothed_atm": self._smoothed_atm.get(key),
            }

    async def get_smoothed_atm(self, symbol: str) -> float | None:
        key = symbol.upper()
        async with self._lock:
            return self._smoothed_atm.get(key)

    async def recent_spot_trail(self, symbol: str, *, limit: int = 12) -> list[dict[str, Any]]:
        key = symbol.upper()
        async with self._lock:
            bucket = self._history.get(key)
            if not bucket:
                return []
            tail = list(bucket)[-max(1, limit) :]
            return [
                {
                    "captured_at": snap.captured_at,
                    "spot": snap.spot,
                    "smoothed_atm": snap.smoothed_atm,
                }
                for snap in tail
            ]


_store = OiSnapshotStore()


def get_oi_snapshot_store() -> OiSnapshotStore:
    return _store
