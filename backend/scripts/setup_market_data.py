#!/usr/bin/env python3
"""Load the public NSE data the setup watchlist uses.

  setup_market_data.py                       # daily top-up (the watchlist build also does this)
  setup_market_data.py --days 500            # history: delivery, corporate actions, industries
  setup_market_data.py --days 500 --candles  # also add daily candles where the database has none
  setup_market_data.py --days 500 --index    # also add Nifty 50 daily closes where missing

History is one small file per trading day, newest first. It can be stopped and rerun.
Candles from NSE's file are raw prices; splits and bonuses are adjusted when the
watchlist reads them, using the corporate actions loaded here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.early_setup import market_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Load NSE delivery, deals, flags and corporate actions")
    parser.add_argument("--days", type=int, default=0, help="Trading days of history to load (0: daily top-up only)")
    parser.add_argument("--candles", action="store_true", help="Add daily candles for stocks and days that have none")
    parser.add_argument("--index", action="store_true", help="Add Nifty 50 daily closes where missing")
    parser.add_argument("--pause", type=float, default=0.4, help="Seconds between requests")
    args = parser.parse_args()

    if args.days <= 0:
        print(json.dumps(market_data.refresh(), indent=2))
        return

    def progress(update: dict) -> None:
        if update["position"] % 20 == 0 or update["position"] == update["total"]:
            print(
                f"{update['position']}/{update['total']} {update['day']} loaded={update['days_loaded']} "
                f"no_file={update['no_file']} candles_added={update['candles_added']}",
                flush=True,
            )

    result = market_data.backfill(
        args.days, candles=args.candles, index=args.index, pause=args.pause, on_progress=progress
    )
    print(json.dumps(result, indent=2))
    print(json.dumps({"top_up": market_data.refresh()}, indent=2))


if __name__ == "__main__":
    main()
