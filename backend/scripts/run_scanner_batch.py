#!/usr/bin/env python3
"""Clear scanner history and run parallel batch scans (previous + current month)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.store import get_store
from app.services.market_calendar import (
    trading_days_in_range,
    trading_days_previous_and_current_month,
)
from app.services.scanner.engine import DEFAULT_SCANNER_CONCURRENCY, run_scanner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-scan momentum scanner over a date range or previous+current month",
    )
    parser.add_argument(
        "--anchor-date",
        type=str,
        default=None,
        help="Last trade date to include for month mode (default: latest candle date in DB)",
    )
    parser.add_argument(
        "--from-date",
        type=str,
        default=None,
        help="Inclusive start YYYY-MM-DD (with --to-date, overrides month mode)",
    )
    parser.add_argument(
        "--to-date",
        type=str,
        default=None,
        help="Inclusive end YYYY-MM-DD (with --from-date, overrides month mode)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete all existing scanner_runs and pattern_signals before scanning",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_SCANNER_CONCURRENCY,
        help=f"Parallel workers per scan date (default: {DEFAULT_SCANNER_CONCURRENCY})",
    )
    parser.add_argument(
        "--date-concurrency",
        type=int,
        default=1,
        help="How many scan dates to process in parallel (default: 1; use 1 for SQLite)",
    )
    parser.add_argument(
        "--skip-fo-sync",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip live F&O derivative fetch during batch (default: true, much faster)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show dates that would be scanned without running",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    store = get_store()
    stats = store.stats()

    if args.from_date or args.to_date:
        if not args.from_date or not args.to_date:
            raise SystemExit("Both --from-date and --to-date are required together")
        start = date.fromisoformat(args.from_date)
        end = date.fromisoformat(args.to_date)
        scan_dates = trading_days_in_range(start, end)
        anchor_iso = end.isoformat()
    else:
        anchor_iso = args.anchor_date or stats.get("max_trade_date")
        if not anchor_iso:
            raise SystemExit("No candle data in DB — ingest daily candles first")
        anchor = date.fromisoformat(anchor_iso)
        scan_dates = trading_days_previous_and_current_month(anchor)

    if not scan_dates:
        raise SystemExit("No trading days found for the requested range")

    print(f"Anchor date: {anchor_iso}", flush=True)
    print(f"Scan dates: {len(scan_dates)} ({scan_dates[0]} → {scan_dates[-1]})", flush=True)
    print(
        f"Workers: {args.concurrency}/date × {args.date_concurrency} dates "
        f"(skip_fo_sync={args.skip_fo_sync})",
        flush=True,
    )

    if args.dry_run:
        print(json.dumps({"dates": scan_dates}, indent=2))
        return

    if args.clear:
        cleared = store.clear_scanner_data()
        print(
            "Cleared scanner data:",
            f"{cleared['pattern_signals_deleted']} signals,",
            f"{cleared['scanner_runs_deleted']} runs",
            flush=True,
        )

    started = time.perf_counter()
    results: list[dict] = []
    total_alerts = 0
    date_workers = max(1, args.date_concurrency)
    symbol_workers = max(1, args.concurrency)

    def scan_one(trade_date: str) -> dict:
        t0 = time.perf_counter()
        result = run_scanner(
            trade_date=trade_date,
            store=store,
            concurrency=symbol_workers,
            skip_fo_sync=args.skip_fo_sync,
        )
        elapsed = round(time.perf_counter() - t0, 1)
        print(
            f"  ✓ {trade_date}: {result.get('alerts_count', 0)} alerts "
            f"({result.get('symbols_scanned', 0)} symbols, "
            f"engine={result.get('engine_version')}, {elapsed}s)",
            flush=True,
        )
        return result

    print(f"\nScanning {len(scan_dates)} sessions…", flush=True)
    with ThreadPoolExecutor(max_workers=date_workers) as pool:
        futures = {pool.submit(scan_one, d): d for d in scan_dates}
        for future in as_completed(futures):
            trade_date = futures[future]
            try:
                result = future.result()
                results.append(result)
                total_alerts += int(result.get("alerts_count") or 0)
            except Exception as exc:
                print(f"  ✗ {trade_date}: {exc}", file=sys.stderr)
                results.append({"trade_date": trade_date, "status": "failed", "error": str(exc)})

    elapsed = round(time.perf_counter() - started, 1)
    summary = {
        "status": "completed",
        "anchor_date": anchor_iso,
        "dates_scanned": len(scan_dates),
        "dates_succeeded": sum(1 for r in results if r.get("status") == "completed"),
        "total_alerts": total_alerts,
        "elapsed_seconds": elapsed,
        "concurrency": symbol_workers,
        "date_concurrency": date_workers,
        "skip_fo_sync": args.skip_fo_sync,
        "runs": results,
    }
    print(f"\nDone in {elapsed}s — {total_alerts} total alerts across {len(scan_dates)} dates")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
