from __future__ import annotations

import logging
import sys
import threading
from datetime import datetime

from .config import RuntimeConfig
from .dashboard import TerminalDashboard
from .engine import MultiTimeframeEngine
from .history import seed_all_timeframes
from .websocket_feed import MarketDataFeed

logger = logging.getLogger(__name__)


class MtfRsiService:
    """Orchestrates historical seed → WebSocket ticks → RSI dashboard."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.engine = MultiTimeframeEngine(
            config.timeframes,
            rsi_period=config.rsi_period,
            buffer_maxlen=config.buffer_maxlen,
        )
        self.feed: MarketDataFeed | None = None
        self.dashboard: TerminalDashboard | None = None
        self._seeded = False
        self._tick_lock = threading.Lock()

    def seed_history(self) -> None:
        if self._seeded:
            logger.info("Historical seed already loaded in-memory; skipping refetch")
            return
        token = self.config.access_token
        if not token:
            raise RuntimeError(
                "UPSTOX_ACCESS_TOKEN is required (set in .env or environment)"
            )

        seeds = seed_all_timeframes(
            token,
            self.config.instrument_key,
            self.config.timeframes,
            self.config.cache_dir,
            limit=self.config.history_limit,
            force_refresh=self.config.force_refresh,
        )
        for tf, candles in seeds.items():
            self.engine.seed_timeframe(tf, candles)
            logger.info(
                "Seeded %dm buffer with %d closed closes (raw candles=%d)",
                tf,
                self.engine.buffer_len(tf),
                len(candles),
            )
        self._seeded = True

    def _on_tick(self, price: float, ts: datetime) -> None:
        with self._tick_lock:
            self.engine.on_tick(price, ts)

    def set_rsi_period(self, period: int) -> None:
        self.config.set_rsi_period(period)
        self.engine.set_rsi_period(period)
        logger.info("RSI period switched to %d (seed buffer retained)", period)

    def start(self) -> None:
        self.seed_history()
        token = self.config.access_token
        assert token is not None

        self.feed = MarketDataFeed(
            token,
            self.config.instrument_key,
            self._on_tick,
        )
        self.dashboard = TerminalDashboard(
            get_snapshot=self.engine.snapshot,
            get_feed_status=lambda: self.feed.status if self.feed else "n/a",
            instrument_label=self.config.instrument_label,
        )
        self.feed.start()
        self.dashboard.start()

    def stop(self) -> None:
        if self.dashboard:
            self.dashboard.stop()
        if self.feed:
            self.feed.stop()

    def run_forever(self) -> None:
        self.start()
        print(
            f"\nListening for ticks on {self.config.instrument_key}. "
            f"Type 'rsi 9' to switch period without reseeding.\n",
            flush=True,
        )
        try:
            while True:
                try:
                    line = sys.stdin.readline()
                except KeyboardInterrupt:
                    break
                if not line:
                    # EOF (non-interactive) — keep running until Ctrl+C via signal
                    threading.Event().wait(3600)
                    continue
                cmd = line.strip().lower()
                if not cmd:
                    continue
                if cmd in {"q", "quit", "exit"}:
                    break
                if cmd.startswith("rsi"):
                    parts = cmd.split()
                    if len(parts) != 2 or not parts[1].isdigit():
                        print("Usage: rsi <period>   e.g. rsi 9", flush=True)
                        continue
                    try:
                        self.set_rsi_period(int(parts[1]))
                        print(f"OK — now using RSI({parts[1]})", flush=True)
                    except ValueError as exc:
                        print(f"Invalid period: {exc}", flush=True)
                    continue
                print("Unknown command. Use: rsi <n> | quit", flush=True)
        finally:
            self.stop()
            print("Stopped.", flush=True)
