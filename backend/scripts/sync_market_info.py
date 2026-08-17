#!/usr/bin/env python3
"""Sync Upstox Market Information: FII/DII flows and derivative OI/PCR/max pain snapshots."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.market_info_sync import REQUEST_DELAY_SEC, sync_market_info


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Upstox market information into SQLite")
    parser.add_argument("--date", type=str, default=None, help="Trade date YYYY-MM-DD (derivatives)")
    parser.add_argument("--expiry", type=str, default=None, help="Option expiry YYYY-MM-DD")
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Comma-separated F&O underlyings (default: indices + top stocks)",
    )
    parser.add_argument("--flows-only", action="store_true", help="Sync FII/DII only")
    parser.add_argument("--derivatives-only", action="store_true", help="Sync derivatives only")
    parser.add_argument(
        "--flow-interval",
        type=str,
        default="1D",
        choices=("1D", "1M"),
        help="FII/DII interval",
    )
    parser.add_argument("--no-indices", action="store_true")
    parser.add_argument("--no-stocks", action="store_true")
    parser.add_argument("--stock-limit", type=int, default=5)
    parser.add_argument(
        "--all-fno",
        action="store_true",
        help="Sync derivatives for all NSE F&O equity underlyings with local profiles",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=REQUEST_DELAY_SEC,
        help=f"Delay between API calls (default: {REQUEST_DELAY_SEC})",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    args = parse_args()
    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else None
    trade_date = date.fromisoformat(args.date) if args.date else None

    flows = not args.derivatives_only
    derivatives = not args.flows_only

    def on_progress(update: dict) -> None:
        current = update.get("current_symbol") or ""
        processed = update.get("processed", 0)
        total = update.get("total", 0)
        ok = update.get("success", 0)
        fail = update.get("failed", 0)
        if total:
            print(f"\rDerivatives {processed}/{total} ok={ok} fail={fail} {current:<12}", end="", flush=True)

    result = asyncio.run(
        sync_market_info(
            None,
            trade_date=trade_date,
            expiry=args.expiry,
            symbols=symbols,
            flows=flows,
            derivatives=derivatives,
            flow_interval=args.flow_interval,
            include_indices=not args.no_indices,
            include_stocks=not args.no_stocks,
            stock_limit=args.stock_limit,
            all_fno_stocks=args.all_fno,
            request_delay_sec=args.delay,
            on_progress=on_progress if derivatives else None,
        )
    )
    if derivatives:
        print()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
