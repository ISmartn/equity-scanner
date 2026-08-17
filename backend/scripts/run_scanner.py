#!/usr/bin/env python3
"""Run momentum pattern scanner over local daily candle data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.scanner.engine import run_scanner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run momentum pattern scanner")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Scan as of trade date YYYY-MM-DD (default: latest in DB)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Parallel symbol workers (default: 1)",
    )
    parser.add_argument(
        "--skip-fo-sync",
        action="store_true",
        help="Skip live F&O derivative fetch",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    def on_progress(update: dict) -> None:
        ticker = update.get("current_ticker") or ""
        processed = update.get("processed", 0)
        total = update.get("total", 0)
        alerts = update.get("alerts_count", 0)
        print(f"\rScanning {processed}/{total} {ticker} alerts={alerts}", end="", flush=True)

    result = run_scanner(
        trade_date=args.date,
        on_progress=on_progress,
        concurrency=args.concurrency,
        skip_fo_sync=args.skip_fo_sync,
    )
    print()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
