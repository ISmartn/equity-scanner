#!/usr/bin/env python3
"""Bulk-fetch Upstox fundamentals for all mainboard stocks with ISIN into SQLite."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.fundamentals_sync import (
    DEFAULT_ERROR_LOG,
    REQUEST_DELAY_SEC,
    SECTION_DELAY_SEC,
    sync_all_fundamentals,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Upstox fundamentals for all stocks (one-time bulk sync)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch all tickers, ignoring cache and error log",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max symbols to process (default: all with ISIN)",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated tickers (default: all profiles with ISIN)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=REQUEST_DELAY_SEC,
        help=f"Delay between tickers in seconds (default: {REQUEST_DELAY_SEC})",
    )
    parser.add_argument(
        "--section-delay",
        type=float,
        default=SECTION_DELAY_SEC,
        help=f"Delay between Upstox API calls per ticker (default: {SECTION_DELAY_SEC})",
    )
    parser.add_argument(
        "--no-retry-from-log",
        action="store_true",
        help="Do not re-queue tickers listed in the error log",
    )
    parser.add_argument(
        "--error-log",
        type=str,
        default=str(DEFAULT_ERROR_LOG),
        help=f"Error log file path (default: {DEFAULT_ERROR_LOG})",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.WARNING)

    args = parse_args()
    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None

    def on_progress(update: dict) -> None:
        current = update.get("current_ticker") or ""
        processed = update.get("processed", 0)
        total = update.get("total", 0)
        ok = update.get("success", 0)
        fail = update.get("failed", 0)
        skip = update.get("skipped", 0)
        if current:
            print(
                f"\rFetching {processed}/{total} {current} "
                f"(ok={ok} fail={fail} skip={skip})",
                end="",
                flush=True,
            )
        elif total == 0:
            print(f"\rNothing to fetch (skipped {skip} already cached)", end="", flush=True)

    try:
        result = asyncio.run(
            sync_all_fundamentals(
                force=args.force,
                tickers=tickers,
                limit=args.limit,
                request_delay_sec=args.delay,
                section_delay_sec=args.section_delay,
                retry_from_log=not args.no_retry_from_log,
                on_progress=on_progress,
                error_log_path=args.error_log,
            )
        )
    except RuntimeError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)

    print()
    print(json.dumps(result, indent=2))

    if result.get("failed"):
        print(
            f"\n{result['failed']} failures logged to: {result['error_log']}",
            file=sys.stderr,
        )
        print(
            "Re-run without --force to skip cached tickers and retry only logged failures.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
