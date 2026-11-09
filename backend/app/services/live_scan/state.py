"""Single-writer live book with read-copy-update publication.

Threading contract
------------------
* Exactly one thread (the ingest/decoder thread) calls the mutating methods:
  ``apply_frame``, ``apply``, ``seal_minutes``, ``mark_reconnect`` and
  ``close_window``. Mutable per-instrument state is private to that thread.
* After each frame the writer builds an immutable ``QuoteView`` for every
  touched instrument and publishes a *new* dict by swapping one reference.
  Published dicts are never mutated, so readers (ranker, API, status) take a
  coherent point-in-time copy with a single attribute read and no lock. The
  socket path never waits on a reader.
* Journal path windows (first/high/low/last of accepted prints) are closed by
  the writer and handed over through a deque, so the journal sees every
  extreme in order and never shares a window with the writer.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from .clocks import (
    absolute_minute,
    ensure_ist,
    is_muhurat_epoch,
    minute_label,
    open_minute_for_absolute,
    orb_minutes,
    session_length,
    session_minute,
)
from .context import SymbolContext
from .ticks import TickGuard, sane_atp, spike_band
from .volume_profile import VolumeProfile

_MINUTE_HISTORY = 20
_LTT_MAX_SKEW_SEC = 120.0
_PARTIAL_JOIN_SEC = 5.0
_SEAL_GRACE_SEC = 2.0
_WINDOW_BACKLOG = 240


def _minute_weights(profile: VolumeProfile, cash: "QuoteView", tick_at: float | None) -> list[float]:
    """Muhurat is 70 minutes, so the regular 375-minute volume curve does not apply."""
    if tick_at and is_muhurat_epoch(tick_at):
        return [1.0 for _index in cash.minute_index]
    return [profile.minute_intensity(index) for index in cash.minute_index]


def _mark_minute(state: "SymbolLiveState", price: float) -> None:
    if state.minute_open <= 0:
        state.minute_open = state.minute_high = state.minute_low = price
        return
    if price > state.minute_high:
        state.minute_high = price
    if price < state.minute_low:
        state.minute_low = price


@dataclass(slots=True)
class PathWindow:
    """Accepted session prints for one symbol between two journal evaluations."""

    first: float
    high: float
    low: float
    last: float
    ticks: int = 1

    def extend(self, price: float) -> None:
        if price > self.high:
            self.high = price
        if price < self.low:
            self.low = price
        self.last = price
        self.ticks += 1


@dataclass(frozen=True, slots=True)
class QuoteView:
    """Immutable published state of one instrument."""

    ltp: float
    prev_close: float
    atp: float
    day_open: float
    day_high: float
    day_low: float
    vtt: int
    oi: float
    poi: float | None
    poi_source: str
    bid: float
    ask: float
    session_high: float
    session_low: float
    orb_high: float | None
    orb_locked: bool
    post_orb_high: float
    last_minute_volume: int | None
    minute_history: tuple[int, ...]
    minute_index: tuple[int, ...]
    last_tick_at: float | None


@dataclass(slots=True)
class SymbolLiveState:
    instrument_key: str
    symbol: str
    kind: str
    guard: TickGuard = field(default_factory=TickGuard)
    ltp: float = 0.0
    prev_close: float = 0.0
    atp: float = 0.0
    day_open: float = 0.0
    day_high: float = 0.0
    day_low: float = 0.0
    vtt: int = 0
    oi: float = 0.0
    poi: float | None = None
    poi_source: str = ""
    bid: float = 0.0
    ask: float = 0.0
    last_tick_at: float | None = None
    last_ltt: int = 0
    session_high: float = 0.0
    session_low: float = 0.0
    orb_high: float | None = None
    orb_locked: bool = False
    post_orb_high: float = 0.0
    resync: bool = True
    # Minute bucketing, keyed by absolute IST minute so ordering is integer math.
    current_minute: int | None = None
    current_label: str | None = None
    minute_volume: int = 0
    minute_close: float = 0.0
    # Traded session prints only, the same ones the journal's path windows see.
    minute_open: float = 0.0
    minute_high: float = 0.0
    minute_low: float = 0.0
    minute_partial: bool = False
    last_vtt: int | None = None
    i1_volume: int | None = None
    completed: deque[tuple[int, int]] = field(default_factory=lambda: deque(maxlen=_MINUTE_HISTORY))
    history_volumes: tuple[int, ...] = ()
    history_index: tuple[int, ...] = ()
    last_minute_volume: int | None = None
    window: PathWindow | None = None

    def view(self) -> QuoteView:
        return QuoteView(
            ltp=self.ltp,
            prev_close=self.prev_close,
            atp=self.atp,
            day_open=self.day_open,
            day_high=self.day_high,
            day_low=self.day_low,
            vtt=self.vtt,
            oi=self.oi,
            poi=self.poi,
            poi_source=self.poi_source,
            bid=self.bid,
            ask=self.ask,
            session_high=self.session_high,
            session_low=self.session_low,
            orb_high=self.orb_high,
            orb_locked=self.orb_locked,
            post_orb_high=self.post_orb_high,
            last_minute_volume=self.last_minute_volume,
            minute_history=self.history_volumes,
            minute_index=self.history_index,
            last_tick_at=self.last_tick_at,
        )


@dataclass(slots=True)
class SymbolPair:
    context: SymbolContext
    cash: SymbolLiveState
    future: SymbolLiveState | None = None


@dataclass(slots=True)
class IngestStats:
    ticks: int = 0
    frames: int = 0
    out_of_order: int = 0
    zero_volume_prints: int = 0
    atp_rejected: int = 0
    resyncs: int = 0
    windows_dropped: int = 0
    minutes_sealed: int = 0


class LiveBook:
    def __init__(
        self,
        contexts: dict[str, SymbolContext],
        *,
        profile: VolumeProfile | None = None,
    ) -> None:
        self.profile = profile or VolumeProfile.default()
        self._by_key: dict[str, SymbolLiveState] = {}
        self._pairs: dict[str, SymbolPair] = {}
        self._view: dict[str, QuoteView] = {}
        self._windows: deque[dict[str, PathWindow]] = deque(maxlen=_WINDOW_BACKLOG)
        self.stats = IngestStats()
        self.last_tick_at: float | None = None
        for context in contexts.values():
            band = spike_band(context.atr_pct)
            cash = SymbolLiveState(
                instrument_key=context.cash_key,
                symbol=context.symbol,
                kind="cash",
                guard=TickGuard(band),
            )
            if context.kind == "index" and context.prior_close:
                # Shown before the first print; last_tick_at stays None so nothing trades on it.
                cash.prev_close = float(context.prior_close)
                cash.ltp = float(context.prior_close)
            future: SymbolLiveState | None = None
            self._by_key[context.cash_key] = cash
            if context.future_key:
                future = SymbolLiveState(
                    instrument_key=context.future_key,
                    symbol=context.symbol,
                    kind="future",
                    guard=TickGuard(band),
                    poi=context.seeded_poi,
                    poi_source="prior_close" if context.seeded_poi else "",
                )
                self._by_key[context.future_key] = future
            self._pairs[context.symbol] = SymbolPair(context=context, cash=cash, future=future)
        self._view = {key: state.view() for key, state in self._by_key.items()}
        self._key_list = tuple(self._by_key)

    # ------------------------------------------------------------------ reads

    @property
    def instrument_keys(self) -> list[str]:
        return list(self._key_list)

    @property
    def tick_count(self) -> int:
        return self.stats.ticks

    def view(self) -> dict[str, QuoteView]:
        """Point-in-time published state. Never mutated after publication."""
        return self._view

    # ----------------------------------------------------------------- writes

    def apply(self, instrument_key: str, parsed: dict[str, Any], ts: datetime) -> dict[str, Any] | None:
        """Apply one parsed tick. Returns the first minute bar it closed, if any."""
        bars = self.apply_frame([(instrument_key, parsed)], ensure_ist(ts).timestamp())
        return bars[0] if bars else None

    def apply_frame(self, items: Iterable[tuple[str, dict[str, Any]]], received: float) -> list[dict[str, Any]]:
        """Apply every feed in one websocket frame, then publish once."""
        bars: list[dict[str, Any]] = []
        touched: dict[str, QuoteView] = {}
        by_key = self._by_key
        for instrument_key, parsed in items:
            state = by_key.get(instrument_key)
            if state is None:
                continue
            if self._apply_one(state, parsed, received, bars):
                touched[instrument_key] = state.view()
        self.stats.frames += 1
        if touched:
            self._publish(touched)
        return bars

    def seal_minutes(self, now: float) -> list[dict[str, Any]]:
        """Close minutes that ended without a tick so bars do not wait for the next print."""
        due_minute = absolute_minute(now - _SEAL_GRACE_SEC)
        bars: list[dict[str, Any]] = []
        touched: dict[str, QuoteView] = {}
        label = minute_label(now - _SEAL_GRACE_SEC)
        for key, state in self._by_key.items():
            if state.current_minute is None or state.current_minute >= due_minute:
                continue
            self._roll(state, due_minute, label, bars)
            touched[key] = state.view()
        if touched:
            self._publish(touched)
        return bars

    def mark_reconnect(self) -> None:
        """Re-baseline cumulative volume after a gap. Volume traded while the
        socket was down must not land in one minute as a phantom burst."""
        for state in self._by_key.values():
            state.resync = True
            state.guard.reset()
        self.stats.resyncs += 1

    def close_window(self) -> None:
        """Hand the current journal path windows to the reader and start new ones."""
        closed: dict[str, PathWindow] = {}
        for pair in self._pairs.values():
            window = pair.cash.window
            if window is not None:
                closed[pair.context.symbol] = window
                pair.cash.window = None
        if closed:
            if len(self._windows) == self._windows.maxlen:
                self.stats.windows_dropped += 1
            self._windows.append(closed)

    def drain_windows(self) -> list[dict[str, PathWindow]]:
        """Reader side. Windows come back oldest first."""
        out: list[dict[str, PathWindow]] = []
        while True:
            try:
                out.append(self._windows.popleft())
            except IndexError:
                return out

    def _publish(self, touched: dict[str, QuoteView]) -> None:
        fresh = dict(self._view)
        fresh.update(touched)
        self._view = fresh

    def _apply_one(
        self,
        state: SymbolLiveState,
        parsed: dict[str, Any],
        received: float,
        bars: list[dict[str, Any]],
    ) -> bool:
        ltt = parsed.get("ltt")
        tick_at = received
        if ltt:
            if ltt < state.last_ltt:
                self.stats.out_of_order += 1
                return False
            exchange_at = ltt / 1000.0
            if abs(exchange_at - received) <= _LTT_MAX_SKEW_SEC:
                tick_at = exchange_at
            state.last_ltt = ltt

        resync = state.resync
        if resync:
            self._resync(state, parsed, tick_at)

        minute = absolute_minute(tick_at)
        vtt = parsed.get("vtt")
        traded = True
        if vtt is not None:
            traded = self._note_volume(state, int(vtt), minute, tick_at, bars, resync)

        prev_close = parsed.get("prev_close")
        if prev_close:
            state.prev_close = float(prev_close)
        day_open = parsed.get("day_open")
        if day_open:
            state.day_open = float(day_open)
        day_high = parsed.get("day_high")
        if day_high:
            state.day_high = max(state.day_high, float(day_high))
        day_low = parsed.get("day_low")
        if day_low:
            low = float(day_low)
            state.day_low = low if state.day_low <= 0 else min(state.day_low, low)
        bid = parsed.get("bid")
        ask = parsed.get("ask")
        if bid and ask and ask >= bid:
            state.bid = float(bid)
            state.ask = float(ask)

        ltp = parsed.get("ltp")
        if ltp:
            price = float(ltp)
            reference = state.ltp or state.prev_close or None
            if price != state.ltp and state.guard.check(reference, price):
                self._accept_price(state, price, tick_at, traded)
            elif price == state.ltp:
                state.minute_close = price
                if traded and 0 <= session_minute(tick_at) < session_length(tick_at):
                    _mark_minute(state, price)

        atp = parsed.get("atp")
        if atp:
            if sane_atp(float(atp), state.day_low, state.day_high):
                state.atp = float(atp)
            else:
                self.stats.atp_rejected += 1

        minute_volume = parsed.get("minute_volume")
        if minute_volume is not None:
            state.i1_volume = int(minute_volume)
        oi = parsed.get("oi")
        if oi and state.kind == "future":
            state.oi = float(oi)
            if state.poi is None:
                state.poi = state.oi
                state.poi_source = "session_open"

        state.last_tick_at = received
        self.last_tick_at = received
        self.stats.ticks += 1
        return True

    def _resync(self, state: SymbolLiveState, parsed: dict[str, Any], tick_at: float) -> None:
        """Cold start or reconnect. Trust the exchange day high/low for what we missed."""
        if 0 <= session_minute(tick_at):
            high = parsed.get("day_high")
            low = parsed.get("day_low")
            if high:
                state.session_high = max(state.session_high, float(high))
            if low:
                state.session_low = float(low) if state.session_low <= 0 else min(state.session_low, float(low))
            # post_orb_high is not seeded: the day high includes the opening range
            # itself, so it cannot prove a break that happened while disconnected.

    def _accept_price(self, state: SymbolLiveState, price: float, tick_at: float, traded: bool) -> None:
        state.ltp = price
        state.minute_close = price
        if state.day_high <= 0 or price > state.day_high:
            state.day_high = price
        if state.day_low <= 0 or price < state.day_low:
            state.day_low = price
        minute = session_minute(tick_at)
        if not (0 <= minute < session_length(tick_at)):
            return
        if not traded:
            # The price moved but no volume printed: an indicative or spread print.
            self.stats.zero_volume_prints += 1
            return
        _mark_minute(state, price)
        if price > state.session_high:
            state.session_high = price
        if state.session_low <= 0 or price < state.session_low:
            state.session_low = price
        if minute < orb_minutes(tick_at):
            high = max(state.day_high, price)
            state.orb_high = high if state.orb_high is None else max(state.orb_high, high)
        elif state.orb_high is not None:
            state.orb_locked = True
            if price > state.post_orb_high:
                state.post_orb_high = price
        if state.kind == "cash":
            if state.window is None:
                state.window = PathWindow(first=price, high=price, low=price, last=price)
            else:
                state.window.extend(price)

    def _note_volume(
        self,
        state: SymbolLiveState,
        vtt: int,
        minute: int,
        tick_at: float,
        bars: list[dict[str, Any]],
        resync: bool,
    ) -> bool:
        """Bucket cumulative volume into minutes. Returns False for a zero-volume print."""
        state.vtt = max(state.vtt, vtt) if not resync else vtt
        if state.current_minute is None:
            state.current_minute = minute
            state.current_label = minute_label(tick_at)
            state.minute_volume = 0
            state.minute_partial = (tick_at % 60.0) >= _PARTIAL_JOIN_SEC
            state.last_vtt = vtt
            state.resync = False
            return True
        if resync:
            if minute > state.current_minute:
                self._roll(state, minute, minute_label(tick_at), bars, gap=True)
            state.minute_partial = True
            state.last_vtt = vtt
            state.resync = False
            return True
        last = state.last_vtt if state.last_vtt is not None else vtt
        delta = vtt - last
        if delta < 0:
            delta = 0
        else:
            state.last_vtt = vtt
        if minute > state.current_minute:
            self._roll(state, minute, minute_label(tick_at), bars)
        state.minute_volume += delta
        return delta > 0

    def _roll(
        self,
        state: SymbolLiveState,
        minute: int,
        label: str,
        bars: list[dict[str, Any]],
        *,
        gap: bool = False,
    ) -> None:
        finished = state.minute_volume if state.minute_volume > 0 else int(state.i1_volume or 0)
        partial = state.minute_partial or gap
        current = state.current_minute
        if current is None:
            return
        if finished > 0:
            bars.append(
                {
                    "instrument_key": state.instrument_key,
                    "minute_ts": state.current_label,
                    "volume": finished,
                    "close_price": state.minute_close or state.ltp or None,
                    "open_price": state.minute_open or None,
                    "high_price": state.minute_high or None,
                    "low_price": state.minute_low or None,
                    "source": "live_ws_partial" if partial else "live_ws",
                }
            )
        session_index = (current % 1440) - open_minute_for_absolute(current)
        # Partial minutes (joined late, or cut by a reconnect) undercount and stay
        # out of the burst baseline. Minutes with no prints are real zeros.
        if partial:
            state.last_minute_volume = None
        else:
            state.completed.append((session_index, finished))
            state.last_minute_volume = finished
        if not gap:
            empty = min(minute - current - 1, _MINUTE_HISTORY)
            for step in range(empty, 0, -1):
                state.completed.append((session_index + (minute - current) - step, 0))
            if empty > 0:
                state.last_minute_volume = 0
        state.history_volumes = tuple(volume for _index, volume in state.completed)
        state.history_index = tuple(index for index, _volume in state.completed)
        state.current_minute = minute
        state.current_label = label
        state.minute_volume = 0
        state.minute_open = state.minute_high = state.minute_low = 0.0
        state.minute_partial = False
        state.i1_volume = None
        self.stats.minutes_sealed += 1

    # --------------------------------------------------------------- exports

    def export_quotes(self) -> list[dict[str, Any]]:
        """Ranker input. Built from one published view without any lock."""
        view = self._view
        quotes: list[dict[str, Any]] = []
        for pair in self._pairs.values():
            context = pair.context
            cash = view[context.cash_key]
            future = view.get(context.future_key) if context.future_key else None
            prev_close = cash.prev_close or context.prior_close or 0.0
            ltp = cash.ltp
            spread_pct = None
            if cash.bid > 0 and cash.ask >= cash.bid:
                mid = (cash.bid + cash.ask) / 2.0
                spread_pct = (cash.ask - cash.bid) / mid * 100.0 if mid else None
            high = cash.session_high
            quotes.append(
                {
                    "symbol": context.symbol,
                    "company_name": context.company_name,
                    "sector": context.sector,
                    "ltp": ltp,
                    "prev_close": prev_close,
                    "atp": cash.atp,
                    "day_open": cash.day_open,
                    "day_high": cash.day_high,
                    "day_low": cash.day_low,
                    "vtt": cash.vtt,
                    "avg_volume_20": context.avg_volume_20,
                    "sma20": context.sma20,
                    "atr_pct": context.atr_pct,
                    "efficiency_20": context.efficiency_20,
                    "high_20": context.high_20,
                    "low_20": context.low_20,
                    "trend_20_pct": context.trend_20_pct,
                    "return_5d_pct": context.return_5d_pct,
                    "history_bars": context.history_bars,
                    "last_minute_volume": cash.last_minute_volume,
                    "minute_history": list(cash.minute_history),
                    "minute_weights": _minute_weights(self.profile, cash, self.last_tick_at),
                    "spread_pct": spread_pct,
                    "on_last_scan": context.on_last_scan,
                    "scanner_score": context.scanner_score,
                    "scanner_pattern": context.scanner_pattern,
                    "scanner_pivot": context.scanner_pivot,
                    "kind": context.kind,
                    "segment": context.segment,
                    "prior_high": context.prior_high,
                    "prior_low": context.prior_low,
                    "orb_high": cash.orb_high,
                    "orb_locked": cash.orb_locked,
                    "myb_level": context.myb_level,
                    "myb_status": context.myb_status,
                    "latch_prev_high": bool(context.prior_high and high >= context.prior_high),
                    "latch_orb": bool(cash.orb_locked and cash.orb_high and cash.post_orb_high >= cash.orb_high),
                    "latch_pivot": bool(context.scanner_pivot and high >= context.scanner_pivot),
                    "latch_myb": bool(context.myb_level and high >= context.myb_level),
                    "fut_ltp": future.ltp if future else 0.0,
                    "fut_prev_close": future.prev_close if future else 0.0,
                    "fut_oi": future.oi if future else 0.0,
                    "fut_poi": future.poi if future else None,
                    "fut_poi_source": future.poi_source if future else "",
                    "future_key": context.future_key,
                    "future_expiry": context.future_expiry,
                    "days_to_expiry": context.days_to_expiry,
                    "cash_key": context.cash_key,
                    "last_tick_at": cash.last_tick_at,
                    "future_last_tick_at": future.last_tick_at if future else None,
                }
            )
        return quotes

    def counts(self, *, fresh_after: float) -> dict[str, int]:
        view = self._view
        live = 0
        futures = 0
        for pair in self._pairs.values():
            seen = view[pair.context.cash_key].last_tick_at
            if seen is not None and seen >= fresh_after:
                live += 1
            if pair.future is not None:
                futures += 1
        return {
            "symbols": len(self._pairs),
            "futures": futures,
            "symbols_live": live,
            "tick_count": self.stats.ticks,
        }

    def ingest_stats(self) -> dict[str, int]:
        rejected = sum(state.guard.rejected for state in self._by_key.values())
        confirmed = sum(state.guard.confirmed_jumps for state in self._by_key.values())
        stats = self.stats
        return {
            "ticks": stats.ticks,
            "frames": stats.frames,
            "spikes_rejected": rejected,
            "jumps_confirmed": confirmed,
            "out_of_order": stats.out_of_order,
            "zero_volume_prints": stats.zero_volume_prints,
            "atp_rejected": stats.atp_rejected,
            "resyncs": stats.resyncs,
            "minutes_sealed": stats.minutes_sealed,
            "windows_dropped": stats.windows_dropped,
        }

    def session_rows(self, trade_date: str) -> dict[str, list[dict[str, Any]]]:
        view = self._view
        candles: list[dict[str, Any]] = []
        index_candles: list[dict[str, Any]] = []
        futures: list[dict[str, Any]] = []
        for pair in self._pairs.values():
            context = pair.context
            cash = view[context.cash_key]
            if cash.ltp > 0 and context.kind == "index":
                index_candles.append(
                    {
                        "instrument_token": context.cash_key,
                        "timeframe": "daily",
                        "ts": trade_date,
                        "open_price": cash.day_open or None,
                        "high_price": cash.day_high or None,
                        "low_price": cash.day_low or None,
                        "close_price": cash.ltp,
                        "volume": cash.vtt or 0,
                        "oi": None,
                        "source": "live_ws",
                    }
                )
            elif cash.ltp > 0:
                # Same definition as candle ingestion: open to close, not prior close to close.
                change = ((cash.ltp - cash.day_open) / cash.day_open * 100.0) if cash.day_open else None
                candles.append(
                    {
                        "trade_date": trade_date,
                        "instrument_token": context.cash_key,
                        "open_price": cash.day_open or None,
                        "high_price": cash.day_high or None,
                        "low_price": cash.day_low or None,
                        "close_price": cash.ltp,
                        "volume": cash.vtt or None,
                        "daily_return_pct": round(change, 4) if change is not None else None,
                        "source": "live_ws",
                    }
                )
            future = view.get(context.future_key) if context.future_key else None
            if future and future.oi > 0:
                futures.append(
                    {
                        "trade_date": trade_date,
                        "instrument_key": context.future_key,
                        "symbol": context.symbol,
                        "expiry": context.future_expiry,
                        "oi": future.oi,
                        "poi": future.poi,
                        "ltp": future.ltp or None,
                        "prev_close": future.prev_close or None,
                        "source": "live_ws",
                    }
                )
        return {"candles": candles, "index_candles": index_candles, "futures_oi": futures}
