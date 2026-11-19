#!/usr/bin/env python3
"""Update the setup watchlist from local daily candles.

  build_setup_watchlist.py                                    # catch up to the latest candle date
  build_setup_watchlist.py --rebuild --from-date 2026-01-01   # clear and replay history

Before updating it tops up delivery, large deals, surveillance flags and
corporate actions from NSE. Pass --no-refresh to skip that.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.early_setup import repo
from app.services.early_setup.watchlist import update_watchlist


def main() -> None:
    parser = argparse.ArgumentParser(description="Update the setup watchlist")
    parser.add_argument("--through", default=None, help="Last session to process, YYYY-MM-DD (default: latest in DB)")
    parser.add_argument("--from-date", default=None, help="First session to replay, YYYY-MM-DD (needs --rebuild)")
    parser.add_argument("--rebuild", action="store_true", help="Clear the stored list first")
    parser.add_argument("--no-refresh", action="store_true", help="Do not fetch delivery, deals and flags from NSE first")
    parser.add_argument("--top", type=int, default=20, help="Rows to print per list")
    args = parser.parse_args()
    if args.rebuild and not args.from_date:
        parser.error("--rebuild needs --from-date")
    if args.from_date and not args.rebuild:
        parser.error("--from-date needs --rebuild (replaying over stored rows would duplicate them)")

    result = update_watchlist(
        through=args.through, from_date=args.from_date, rebuild=args.rebuild, refresh_data=not args.no_refresh
    )
    print(json.dumps(result, indent=2))
    if result.get("status") == "updated":
        # Fresh candles change what followed recent filings, so re-measure the typical moves.
        try:
            from app.services.early_setup import filings

            filings.rebuild_impact()
        except Exception as exc:  # the list is built; this table is an extra
            print(f"Typical filing moves were not re-measured: {type(exc).__name__}")
    health = repo.latest_health()
    if health:
        print(
            f"\nMarket on {health['trade_date']}: {health['state']} "
            f"({health['pct_above_50']}% of {health['stocks']} stocks above their 50-day average)"
        )
    for name, title in (("daily", "daily list (under the 20-day high)"), ("weekly", "weekly list (under a ten-week high)")):
        rows = repo.list_entries(status="active", limit=args.top, timeframe=name)
        if not rows:
            continue
        print(f"\nTop {len(rows)} on the {title}. Buy above the pivot, stop at the base low.")
        print(f"{'Ticker':<14}{'Score':>6}{'Days':>6}{'Close':>10}{'Pivot':>10}{'Stop':>10}{'To pivot':>10}{'Risk':>8}")
        for entry in rows:
            row = entry.public()
            print(
                f"{entry.ticker:<14}{entry.score or 0:>6.1f}{entry.days_in_base:>6}{entry.last_close or 0:>10.2f}"
                f"{entry.pivot:>10.2f}{entry.stop:>10.2f}{row.get('distance_pct', 0):>9.2f}%{row.get('risk_pct', 0):>7.2f}%"
            )


if __name__ == "__main__":
    main()
