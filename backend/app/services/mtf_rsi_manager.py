from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any

from ..config import get_access_token

# Ensure backend/ is on path so `mtf_rsi` resolves when imported from app.*
_backend_dir = str(Path(__file__).resolve().parents[2])
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from mtf_rsi.config import BUFFER_MAXLEN, CACHE_DIR, HISTORY_LOOKBACK_YEARS, TIMEFRAMES  # noqa: E402
from mtf_rsi.engine import MultiTimeframeEngine  # noqa: E402
from mtf_rsi.history import HISTORY_LOOKBACK_DAYS  # noqa: E402
from mtf_rsi.market_hours import market_session_info  # noqa: E402
from mtf_rsi.websocket_feed import MarketDataFeed  # noqa: E402

from .mtf_rsi_seed import seed_all_timeframes_to_db  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_INSTRUMENT_KEY = "NSE_INDEX|Nifty 50"
DEFAULT_INSTRUMENT_LABEL = "Nifty 50"


class MtfRsiLiveManager:
    """Process-wide multi-TF RSI WebSocket session for the API/UI."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._engine: MultiTimeframeEngine | None = None
        self._feed: MarketDataFeed | None = None
        self._seeded = False
        self._rsi_period = 14
        self._timeframes = list(TIMEFRAMES)
        self._instrument_key = DEFAULT_INSTRUMENT_KEY
        self._instrument_label = DEFAULT_INSTRUMENT_LABEL
        self._cache_dir = Path(CACHE_DIR)

    def _mode_note(self, feed_status: str) -> str:
        session = market_session_info()
        if not session["is_open"]:
            return (
                f"{session['label']}. Showing last available seed/session data; "
                "RSI will not tick-update until the market is open and the stream receives ticks."
            )
        if feed_status == "connected":
            return "Market open — live WebSocket ticks updating candles and RSI."
        if feed_status in ("connecting", "reconnecting"):
            return "Market open — connecting to Upstox WebSocket…"
        if feed_status == "error":
            return "Market open but feed error — check token / reconnect."
        return "Market open — start the stream for live updates, or load seed for static RSI."

    def status(self) -> dict[str, Any]:
        with self._lock:
            feed_status = self._feed.status if self._feed else "stopped"
            snap = self._engine.snapshot() if self._engine else None
            session = market_session_info()
            return {
                "status": feed_status,
                "seeded": self._seeded,
                "instrument_key": self._instrument_key,
                "instrument_label": self._instrument_label,
                "rsi_period": self._rsi_period,
                "timeframes": list(self._timeframes),
                "error": self._feed.last_error if self._feed else None,
                "reconnect_attempts": self._feed.reconnect_attempts if self._feed else 0,
                "market": session,
                "mode_note": self._mode_note(feed_status),
                "lookback_years": HISTORY_LOOKBACK_YEARS,
                "lookback_days": HISTORY_LOOKBACK_DAYS,
                "snapshot": snap,
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            session = market_session_info()
            feed_status = self._feed.status if self._feed else "stopped"
            if not self._engine:
                return {
                    "ltp": None,
                    "ts": None,
                    "seed_ts": None,
                    "rsi_period": self._rsi_period,
                    "timeframes": {},
                    "feed_status": feed_status,
                    "seeded": False,
                    "market": session,
                    "mode_note": self._mode_note(feed_status),
                    "live_ticks": False,
                }
            out = self._engine.snapshot()
            out["feed_status"] = feed_status
            out["seeded"] = self._seeded
            out["instrument_key"] = self._instrument_key
            out["instrument_label"] = self._instrument_label
            out["market"] = session
            out["mode_note"] = self._mode_note(feed_status)
            out["live_ticks"] = bool(
                feed_status == "connected" and session["is_open"] and out.get("ltp") is not None
            )
            return out

    def chart(self, timeframe: int | None = None) -> dict[str, Any]:
        with self._lock:
            session = market_session_info()
            feed_status = self._feed.status if self._feed else "stopped"
            if not self._engine:
                return {
                    "rsi_period": self._rsi_period,
                    "series": {},
                    "ltp": None,
                    "ts": None,
                    "market": session,
                    "mode_note": self._mode_note(feed_status),
                    "seeded": False,
                }
            out = self._engine.chart_series(timeframe)
            out["market"] = session
            out["mode_note"] = self._mode_note(feed_status)
            out["seeded"] = self._seeded
            out["feed_status"] = feed_status
            out["instrument_label"] = self._instrument_label
            return out

    def candles(self, timeframe: int) -> dict[str, Any]:
        with self._lock:
            session = market_session_info()
            feed_status = self._feed.status if self._feed else "stopped"
            if not self._engine:
                return {
                    "timeframe": int(timeframe),
                    "instrument_key": self._instrument_key,
                    "instrument_label": self._instrument_label,
                    "candles": [],
                    "ltp": None,
                    "ts": None,
                    "market": session,
                    "mode_note": self._mode_note(feed_status),
                    "seeded": False,
                    "feed_status": feed_status,
                }
            if int(timeframe) not in self._timeframes:
                raise ValueError(
                    f"Unsupported timeframe {timeframe}. Use one of: {self._timeframes}"
                )
            out = self._engine.ohlc_series(int(timeframe))
            out["instrument_key"] = self._instrument_key
            out["instrument_label"] = self._instrument_label
            out["market"] = session
            out["mode_note"] = self._mode_note(feed_status)
            out["seeded"] = self._seeded
            out["feed_status"] = feed_status
            return out

    def set_rsi_period(self, period: int) -> dict[str, Any]:
        if period < 1 or period > 200:
            raise ValueError("RSI period must be between 1 and 200")
        with self._lock:
            self._rsi_period = int(period)
            if self._engine:
                self._engine.set_rsi_period(self._rsi_period)
        return self.snapshot()

    def _ensure_seeded(
        self,
        access_token: str,
        *,
        force_refresh: bool = False,
        allow_skip_if_warm: bool = True,
    ) -> None:
        with self._lock:
            if (
                allow_skip_if_warm
                and self._seeded
                and self._engine
                and not force_refresh
            ):
                min_buf = min(
                    (self._engine.buffer_len(tf) for tf in self._timeframes),
                    default=0,
                )
                if min_buf >= 1000:
                    logger.info(
                        "MTF RSI already warm in memory (min buffer=%d); skip network seed",
                        min_buf,
                    )
                    return

            seeds = seed_all_timeframes_to_db(
                access_token,
                self._instrument_key,
                self._timeframes,
                cache_dir=self._cache_dir,
                force_refresh=force_refresh,
                lookback_days=HISTORY_LOOKBACK_DAYS,
            )
            engine = MultiTimeframeEngine(
                self._timeframes,
                rsi_period=self._rsi_period,
                buffer_maxlen=BUFFER_MAXLEN,
            )
            for tf, candles in seeds.items():
                engine.seed_timeframe(tf, candles)
                logger.info(
                    "Seeded %dm with %d candles from index_candles (~%dy%s)",
                    tf,
                    len(candles),
                    HISTORY_LOOKBACK_YEARS,
                    ", force" if force_refresh else ", incremental",
                )
            self._engine = engine
            self._seeded = True

    def seed_only(
        self,
        access_token: str | None = None,
        *,
        rsi_period: int | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Load historical buffers without starting WebSocket (works off-hours)."""
        token = get_access_token(access_token)
        if not token:
            raise RuntimeError("Upstox access token required to seed MTF RSI")

        with self._lock:
            if rsi_period is not None:
                if rsi_period < 1 or rsi_period > 200:
                    raise ValueError("RSI period must be between 1 and 200")
                self._rsi_period = int(rsi_period)
            # Explicit seed always runs (incremental from last cache, or full if forced).
            self._ensure_seeded(
                token,
                force_refresh=force_refresh,
                allow_skip_if_warm=False,
            )
            assert self._engine is not None
            self._engine.set_rsi_period(self._rsi_period)
        return self.status()

    def start(
        self,
        access_token: str | None = None,
        *,
        rsi_period: int | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        token = get_access_token(access_token)
        if not token:
            raise RuntimeError("Upstox access token required for MTF RSI stream")

        with self._lock:
            if rsi_period is not None:
                if rsi_period < 1 or rsi_period > 200:
                    raise ValueError("RSI period must be between 1 and 200")
                self._rsi_period = int(rsi_period)

            if self._feed is not None:
                self._feed.stop()
                self._feed = None

            self._ensure_seeded(token, force_refresh=force_refresh)
            assert self._engine is not None
            self._engine.set_rsi_period(self._rsi_period)

            def on_tick(price: float, ts: Any) -> None:
                if self._engine is not None:
                    self._engine.on_tick(price, ts)

            feed = MarketDataFeed(token, self._instrument_key, on_tick)
            self._feed = feed
            feed.start()

        return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self._feed is not None:
                self._feed.stop()
                self._feed = None
        return self.status()


_manager = MtfRsiLiveManager()


def get_mtf_rsi_manager() -> MtfRsiLiveManager:
    return _manager
