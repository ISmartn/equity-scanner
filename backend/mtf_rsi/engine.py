from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque

from .models import Candle, candle_bucket_start, ensure_ist
from .rsi import rsi_status, wilders_rsi, wilders_rsi_series
from .history import CHART_MAX_POINTS, trim_points


@dataclass
class ActiveCandle:
    open_ts: datetime
    open: float
    high: float
    low: float
    close: float

    def update(self, price: float) -> None:
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price

    def to_candle(self) -> Candle:
        return Candle(
            ts=self.open_ts,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
        )


@dataclass
class TimeframeState:
    minutes: int
    closes: Deque[float]
    open_times: Deque[datetime]
    ohlc: Deque[Candle]
    active: ActiveCandle | None = None
    last_closed_ts: datetime | None = None

    def _append_closed(self, candle: Candle) -> None:
        self.closes.append(float(candle.close))
        self.open_times.append(candle.ts)
        self.ohlc.append(candle)
        self.last_closed_ts = candle.ts

    def seed_closed(self, candles: list[Candle], *, drop_forming: bool = True) -> None:
        """Load historical closed candles into the rolling buffer."""
        if not candles:
            return
        ordered = sorted(candles, key=lambda c: c.ts)
        closed = ordered[:-1] if drop_forming and len(ordered) > 1 else ordered
        for candle in closed:
            self._append_closed(candle)
        if drop_forming and ordered:
            last = ordered[-1]
            self.active = ActiveCandle(
                open_ts=last.ts,
                open=last.open,
                high=last.high,
                low=last.low,
                close=last.close,
            )


class MultiTimeframeEngine:
    """Thread-safe multi-TF OHLC builder + live RSI evaluator."""

    def __init__(
        self,
        timeframes: list[int],
        *,
        rsi_period: int,
        buffer_maxlen: int = 200,
    ) -> None:
        self._lock = threading.RLock()
        self._rsi_period = int(rsi_period)
        self._states: dict[int, TimeframeState] = {
            tf: TimeframeState(
                minutes=tf,
                closes=deque(maxlen=buffer_maxlen),
                open_times=deque(maxlen=buffer_maxlen),
                ohlc=deque(maxlen=buffer_maxlen),
            )
            for tf in timeframes
        }
        self.ltp: float | None = None
        self.last_tick_ts: datetime | None = None
        self.last_seed_ts: datetime | None = None

    @property
    def timeframes(self) -> list[int]:
        return sorted(self._states.keys())

    def get_rsi_period(self) -> int:
        with self._lock:
            return self._rsi_period

    def set_rsi_period(self, period: int) -> None:
        if period < 1:
            raise ValueError("RSI period must be >= 1")
        with self._lock:
            self._rsi_period = int(period)

    def seed_timeframe(self, minutes: int, candles: list[Candle]) -> None:
        with self._lock:
            state = self._states[minutes]
            state.closes.clear()
            state.open_times.clear()
            state.ohlc.clear()
            state.active = None
            state.last_closed_ts = None
            state.seed_closed(candles, drop_forming=True)
            if candles:
                last = max(candles, key=lambda c: c.ts)
                if self.ltp is None:
                    self.ltp = float(last.close)
                if self.last_seed_ts is None or last.ts > self.last_seed_ts:
                    self.last_seed_ts = last.ts
                if self.last_tick_ts is None:
                    self.last_tick_ts = last.ts

    def buffer_len(self, minutes: int) -> int:
        with self._lock:
            return len(self._states[minutes].closes)

    def on_tick(self, price: float, ts: datetime) -> dict[int, float | None]:
        """Update all TF candles from a tick; return live RSI per timeframe."""
        ts = ensure_ist(ts)
        price = float(price)
        with self._lock:
            self.ltp = price
            self.last_tick_ts = ts
            for state in self._states.values():
                self._apply_tick(state, price, ts)
            return self._compute_all_rsi_unlocked(include_live=True)

    def _apply_tick(self, state: TimeframeState, price: float, ts: datetime) -> None:
        bucket = candle_bucket_start(ts, state.minutes)
        active = state.active
        if active is None:
            state.active = ActiveCandle(
                open_ts=bucket, open=price, high=price, low=price, close=price
            )
            return

        if bucket == active.open_ts:
            active.update(price)
            return

        if state.last_closed_ts is None or active.open_ts > state.last_closed_ts:
            state._append_closed(active.to_candle())

        state.active = ActiveCandle(
            open_ts=bucket, open=price, high=price, low=price, close=price
        )

    def _price_series_unlocked(self, state: TimeframeState, *, include_live: bool) -> tuple[list[datetime], list[float]]:
        times = list(state.open_times)
        prices = list(state.closes)
        if include_live and state.active is not None:
            times = times + [state.active.open_ts]
            prices = prices + [float(state.active.close)]
        return times, prices

    def _compute_all_rsi_unlocked(self, *, include_live: bool) -> dict[int, float | None]:
        period = self._rsi_period
        out: dict[int, float | None] = {}
        for tf, state in self._states.items():
            _, prices = self._price_series_unlocked(state, include_live=include_live)
            out[tf] = wilders_rsi(prices, period)
        return out

    def _ohlc_series_unlocked(self, state: TimeframeState, *, include_live: bool) -> list[Candle]:
        candles = list(state.ohlc)
        if include_live and state.active is not None:
            candles = candles + [state.active.to_candle()]
        return candles

    def chart_series(self, timeframe: int | None = None) -> dict:
        """RSI history points for charting (one or all timeframes)."""
        with self._lock:
            period = self._rsi_period
            targets = [timeframe] if timeframe is not None else sorted(self._states.keys())
            series: dict[str, list[dict]] = {}
            for tf in targets:
                state = self._states.get(tf)
                if state is None:
                    continue
                times, prices = self._price_series_unlocked(state, include_live=True)
                values = wilders_rsi_series(prices, period)
                # RSI[i] corresponds to closes[period + i]
                points: list[dict] = []
                for i, value in enumerate(values):
                    idx = period + i
                    if idx >= len(times):
                        break
                    points.append(
                        {
                            "t": int(times[idx].timestamp()),
                            "v": round(float(value), 4),
                        }
                    )
                series[str(tf)] = trim_points(points, CHART_MAX_POINTS)
            return {
                "rsi_period": period,
                "series": series,
                "ltp": self.ltp,
                "ts": self.last_tick_ts.isoformat() if self.last_tick_ts else None,
            }

    def ohlc_series(self, timeframe: int) -> dict:
        """Closed + forming OHLC bars for a single timeframe (Nifty price chart)."""
        with self._lock:
            state = self._states.get(int(timeframe))
            if state is None:
                raise ValueError(f"Unsupported timeframe: {timeframe}")
            candles = self._ohlc_series_unlocked(state, include_live=True)
            rows = [
                {
                    "ts": c.ts.isoformat(),
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                    "volume": float(c.volume),
                }
                for c in candles
            ]
            return {
                "timeframe": int(timeframe),
                "instrument_label": "Nifty 50",
                "candles": trim_points(rows, CHART_MAX_POINTS),
                "candle_count_total": len(rows),
                "candle_count_returned": min(len(rows), CHART_MAX_POINTS),
                "ltp": self.ltp,
                "ts": self.last_tick_ts.isoformat() if self.last_tick_ts else None,
            }

    def snapshot(self) -> dict:
        with self._lock:
            period = self._rsi_period
            rsi_map = self._compute_all_rsi_unlocked(include_live=True)
            frames = {}
            for tf, state in self._states.items():
                value = rsi_map[tf]
                frames[tf] = {
                    "rsi": value,
                    "status": rsi_status(value),
                    "buffer": len(state.closes),
                    "active_close": state.active.close if state.active else None,
                    "active_open_ts": (
                        state.active.open_ts.isoformat() if state.active else None
                    ),
                }
            return {
                "ltp": self.ltp,
                "ts": self.last_tick_ts.isoformat() if self.last_tick_ts else None,
                "seed_ts": self.last_seed_ts.isoformat() if self.last_seed_ts else None,
                "rsi_period": period,
                "timeframes": frames,
            }
