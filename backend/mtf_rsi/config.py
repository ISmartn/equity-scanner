from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# backend/mtf_rsi/ → repo root (data/, .env)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
PACKAGE_DIR = Path(__file__).resolve().parent

load_dotenv(ROOT_DIR / ".env")
load_dotenv(PACKAGE_DIR / ".env")

TIMEFRAMES: list[int] = [1, 3, 5, 10, 15]
DEFAULT_RSI_PERIOD = 14
INSTRUMENT_KEY = "NSE_INDEX|Nifty 50"
INSTRUMENT_LABEL = "Nifty 50"
BUFFER_MAXLEN = 200
HISTORY_CANDLE_LIMIT = 100
CACHE_DIR = ROOT_DIR / "data" / "mtf_rsi_cache"

OVERBOUGHT = 70.0
OVERSOLD = 30.0

# NSE cash session (IST)
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15


@dataclass
class RuntimeConfig:
    timeframes: list[int] = field(default_factory=lambda: list(TIMEFRAMES))
    rsi_period: int = DEFAULT_RSI_PERIOD
    instrument_key: str = INSTRUMENT_KEY
    instrument_label: str = INSTRUMENT_LABEL
    access_token: str | None = None
    cache_dir: Path = CACHE_DIR
    force_refresh: bool = False
    history_limit: int = HISTORY_CANDLE_LIMIT
    buffer_maxlen: int = BUFFER_MAXLEN

    def set_rsi_period(self, period: int) -> None:
        if period < 1:
            raise ValueError("RSI period must be >= 1")
        self.rsi_period = int(period)


def _parse_timeframes(raw: str | None) -> list[int]:
    if not raw:
        return list(TIMEFRAMES)
    values = [int(x.strip()) for x in raw.split(",") if x.strip()]
    if not values:
        raise ValueError("TIMEFRAMES must contain at least one positive integer")
    if any(v <= 0 for v in values):
        raise ValueError("TIMEFRAMES must be positive minutes")
    return values


def build_config(argv: list[str] | None = None) -> RuntimeConfig:
    parser = argparse.ArgumentParser(
        description="Upstox multi-timeframe Nifty 50 RSI WebSocket service",
    )
    parser.add_argument(
        "--rsi-period",
        type=int,
        default=None,
        help="Wilder RSI period (overrides RSI_PERIOD env / default 14)",
    )
    parser.add_argument(
        "--timeframes",
        type=str,
        default=None,
        help="Comma-separated minutes, e.g. 1,3,5,10,15",
    )
    parser.add_argument(
        "--instrument-key",
        type=str,
        default=None,
        help='Upstox instrument key (default: "NSE_INDEX|Nifty 50")',
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore on-disk historical seed cache and refetch",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=None,
        help="Directory for historical candle seed cache",
    )
    args = parser.parse_args(argv)

    rsi_period = args.rsi_period
    if rsi_period is None:
        rsi_period = int(os.getenv("RSI_PERIOD", str(DEFAULT_RSI_PERIOD)))

    timeframes = _parse_timeframes(args.timeframes or os.getenv("TIMEFRAMES"))
    instrument_key = (
        args.instrument_key
        or os.getenv("UPSTOX_INSTRUMENT_KEY")
        or INSTRUMENT_KEY
    )
    cache_dir = Path(args.cache_dir or os.getenv("MTF_RSI_CACHE_DIR") or CACHE_DIR)
    token = os.getenv("UPSTOX_ACCESS_TOKEN")

    return RuntimeConfig(
        timeframes=timeframes,
        rsi_period=rsi_period,
        instrument_key=instrument_key,
        access_token=token,
        cache_dir=cache_dir,
        force_refresh=bool(args.force_refresh),
    )
