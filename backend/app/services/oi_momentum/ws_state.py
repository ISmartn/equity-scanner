from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Literal

from .snapshot_store import ChainSnapshot, StrikeSnapshot

StreamStatus = Literal["stopped", "connecting", "connected", "error"]


@dataclass
class StrikeInstrumentMap:
    strike_price: float
    call_key: str
    put_key: str


@dataclass
class LiveStrikeQuote:
    call_oi: int = 0
    put_oi: int = 0
    call_volume: int = 0
    put_volume: int = 0
    call_ltp: float = 0.0
    put_ltp: float = 0.0
    call_updated_at: float | None = None
    put_updated_at: float | None = None


@dataclass
class LiveOiBook:
    symbol: str
    expiry: str
    spot: float = 0.0
    spot_updated_at: float | None = None
    smoothed_atm: float = 0.0
    strike_step: int = 50
    zone_strikes: list[float] = field(default_factory=list)
    strikes: dict[float, LiveStrikeQuote] = field(default_factory=dict)
    key_side: dict[str, tuple[float, Literal["CE", "PE"]]] = field(default_factory=dict)
    tick_count: int = 0
    last_tick_at: float | None = None

    def apply_call_tick(self, strike: float, *, oi: int, volume: int, ltp: float, ts: float) -> None:
        row = self.strikes.setdefault(strike, LiveStrikeQuote())
        row.call_oi = oi
        row.call_volume = volume
        row.call_ltp = ltp
        row.call_updated_at = ts
        self.tick_count += 1
        self.last_tick_at = ts

    def apply_put_tick(self, strike: float, *, oi: int, volume: int, ltp: float, ts: float) -> None:
        row = self.strikes.setdefault(strike, LiveStrikeQuote())
        row.put_oi = oi
        row.put_volume = volume
        row.put_ltp = ltp
        row.put_updated_at = ts
        self.tick_count += 1
        self.last_tick_at = ts

    def to_chain_snapshot(self, *, smoothed_atm: float, strike_step: int) -> ChainSnapshot:
        zone = self.zone_strikes or [smoothed_atm]
        rows: list[StrikeSnapshot] = []
        for strike in zone:
            q = self.strikes.get(strike) or LiveStrikeQuote()
            rows.append(
                StrikeSnapshot(
                    strike_price=strike,
                    call_oi=q.call_oi,
                    put_oi=q.put_oi,
                    call_volume=q.call_volume,
                    put_volume=q.put_volume,
                )
            )
        return ChainSnapshot(
            captured_at=time.time(),
            spot=self.spot,
            smoothed_atm=smoothed_atm,
            strike_step=strike_step,
            rows=tuple(rows),
        )


@dataclass
class StreamSessionState:
    symbol: str
    expiry: str
    status: StreamStatus = "stopped"
    error: str | None = None
    index_key: str = ""
    subscribed_keys: list[str] = field(default_factory=list)
    zone_strikes: list[float] = field(default_factory=list)
    strike_maps: list[StrikeInstrumentMap] = field(default_factory=list)
    started_at: float | None = None
    chain_bootstrapped_at: float | None = None
    last_snapshot_at: float | None = None
    tick_count: int = 0
    last_tick_at: float | None = None
    book: LiveOiBook | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot_status(self) -> dict:
        with self._lock:
            book = self.book
            return {
                "symbol": self.symbol,
                "expiry": self.expiry,
                "status": self.status,
                "error": self.error,
                "index_key": self.index_key,
                "subscribed_keys": list(self.subscribed_keys),
                "zone_strikes": list(self.zone_strikes),
                "started_at": self.started_at,
                "tick_count": book.tick_count if book else self.tick_count,
                "last_tick_at": book.last_tick_at if book else self.last_tick_at,
                "spot": book.spot if book else None,
            }
