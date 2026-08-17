#!/usr/bin/env python3
"""Refresh all ingested symbols with the latest daily candles."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.candle_ingestion import DEFAULT_BOOTSTRAP_DAYS, ingest_candles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bring all symbols up to date from each symbol's last stored date",
    )
    parser.add_argument(
        "--bootstrap-days",
        type=int,
        default=DEFAULT_BOOTSTRAP_DAYS,
        help=(
            "Only used for symbols with no local history "
            f"(default: {DEFAULT_BOOTSTRAP_DAYS} calendar days)"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max symbols to process (default: all profiles)",
    )
    parser.add_argument(
        "--source",
        choices=["auto", "upstox", "nse"],
        default="auto",
        help="Data source preference",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.35,
        help="Delay between symbol requests per worker (seconds)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Parallel symbol fetches (default: 3)",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    result = await ingest_candles(
        limit=args.limit,
        refresh_all=True,
        since_last=True,
        bootstrap_days=args.bootstrap_days,
        source_preference=args.source,
        request_delay_sec=args.delay,
        concurrency=args.concurrency,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
