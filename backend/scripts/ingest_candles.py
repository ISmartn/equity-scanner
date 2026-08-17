#!/usr/bin/env python3
"""Backfill daily candles for mainboard stocks into the local timeline database."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.candle_ingestion import ingest_candles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest historical daily candles")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Days of history to fetch (overrides --years; fixed window unless --upto-date is used)",
    )
    parser.add_argument("--years", type=int, default=2, help="Years of history to fetch")
    parser.add_argument("--limit", type=int, default=None, help="Max symbols to process")
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated tickers (e.g. RELIANCE,TCS). Default: missing candles first.",
    )
    parser.add_argument(
        "--refresh-all",
        action="store_true",
        help="Process all symbols instead of only those missing history",
    )
    parser.add_argument(
        "--upto-date",
        action="store_true",
        help="Fetch only from each symbol's last stored date (implies --refresh-all)",
    )
    parser.add_argument(
        "--since-last",
        action="store_true",
        help="Same as --upto-date",
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
    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
    since_last = args.upto_date or args.since_last
    refresh_all = args.refresh_all or since_last
    result = await ingest_candles(
        years=args.years,
        days=args.days,
        limit=args.limit,
        tickers=tickers,
        refresh_all=refresh_all,
        since_last=since_last,
        source_preference=args.source,
        request_delay_sec=args.delay,
        concurrency=args.concurrency,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
