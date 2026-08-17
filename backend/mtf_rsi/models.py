from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc


@dataclass(frozen=True)
class Candle:
    ts: datetime  # candle open time (timezone-aware, IST preferred)
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def as_dict(self) -> dict:
        return {
            "ts": self.ts.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> Candle:
        ts = raw["ts"]
        if isinstance(ts, str):
            parsed = datetime.fromisoformat(ts)
        else:
            parsed = ts
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=IST)
        return cls(
            ts=parsed.astimezone(IST),
            open=float(raw["open"]),
            high=float(raw["high"]),
            low=float(raw["low"]),
            close=float(raw["close"]),
            volume=float(raw.get("volume") or 0.0),
        )


def ensure_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def parse_epoch_to_ist(epoch: float | int) -> datetime:
    """Accept seconds or milliseconds since epoch."""
    value = float(epoch)
    if value > 1e12:
        value /= 1000.0
    return datetime.fromtimestamp(value, tz=UTC).astimezone(IST)


def market_open_on(day: datetime) -> datetime:
    day = ensure_ist(day)
    return day.replace(hour=9, minute=15, second=0, microsecond=0)


def candle_bucket_start(ts: datetime, timeframe_minutes: int) -> datetime:
    """Align candle open to NSE session clock from 09:15 IST."""
    if timeframe_minutes <= 0:
        raise ValueError("timeframe_minutes must be positive")
    ts = ensure_ist(ts)
    open_dt = market_open_on(ts)
    if ts < open_dt:
        # Pre-open ticks: pin to previous calendar day's last possible bucket open
        # is unnecessary for live session; treat as open_dt bucket.
        return open_dt

    elapsed = ts - open_dt
    total_minutes = int(elapsed.total_seconds() // 60)
    bucket = (total_minutes // timeframe_minutes) * timeframe_minutes
    return open_dt + timedelta(minutes=bucket)


def parse_upstox_candle_row(row: list | tuple) -> Candle | None:
    """Upstox candle row: [ts, open, high, low, close, volume, oi]."""
    if not row or len(row) < 5:
        return None
    raw_ts = row[0]
    if isinstance(raw_ts, (int, float)):
        ts = parse_epoch_to_ist(raw_ts)
    elif isinstance(raw_ts, str):
        # Often ISO with offset, e.g. 2024-01-01T09:15:00+05:30
        cleaned = raw_ts.replace("Z", "+00:00")
        ts = datetime.fromisoformat(cleaned)
        ts = ensure_ist(ts)
    else:
        return None
    return Candle(
        ts=ts,
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]) if len(row) > 5 and row[5] is not None else 0.0,
    )
