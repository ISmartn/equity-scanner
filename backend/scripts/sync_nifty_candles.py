#!/usr/bin/env python3
"""Sync Nifty 50 multi-timeframe candles into index_candles."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.nifty_candles import TIMEFRAMES, sync_nifty


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Nifty 50 candles (1m/3m/5m/10m/daily)")
    parser.add_argument(
        "--timeframes",
        type=str,
        default=",".join(TIMEFRAMES),
        help="Comma-separated timeframes (default: all)",
    )
    parser.add_argument("--from-date", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument("--to-date", type=str, default=None, help="YYYY-MM-DD")
    return parser.parse_args()


def _parse_date(value: str | None):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


async def main() -> int:
    args = parse_args()
    tfs = [x.strip() for x in args.timeframes.split(",") if x.strip()]
    result = await sync_nifty(
        timeframes=tfs,
        from_date=_parse_date(args.from_date),
        to_date=_parse_date(args.to_date),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
