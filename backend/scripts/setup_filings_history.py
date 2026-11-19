#!/usr/bin/env python3
"""Load past NSE filings and measure what stocks did after each kind.

  setup_filings_history.py --days 250     # about a year, one request per weekday
  setup_filings_history.py --days 0       # only re-measure from what is stored

The result is the "typical move" quoted in filing alerts and on the Filings tab.
It needs daily candles for the same period. Nothing loaded here is ever alerted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.early_setup import filings


def main() -> None:
    parser = argparse.ArgumentParser(description="Load filing history and measure typical moves")
    parser.add_argument("--days", type=int, default=250, help="Weekdays of history to load (0: only re-measure)")
    parser.add_argument("--pause", type=float, default=1.2, help="Seconds between requests")
    args = parser.parse_args()

    if args.days > 0:
        def progress(update: dict) -> None:
            if update["position"] % 20 == 0 or update["position"] == update["total"]:
                print(f"{update['position']}/{update['total']} {update['day']} price-moving so far: {update['material']}", flush=True)

        result = filings.backfill_history(args.days, pause=args.pause, on_progress=progress)
        print(result)

    table = filings.rebuild_impact()
    print(f"\nWhat stocks did around each kind of filing, {table['from']} to {table['to']}")
    print("Each figure is the stock's move minus the average move of stocks of similar liquidity over the same stretch.")
    print("'Beat similar' is the share that did better than the median such stock.")
    print(f"{'Kind':<26}{'Cases':>7}{'Day of news':>13}{'At the open':>13}{'Next 5 sessions':>17}{'Beat similar':>14}")

    def show(value: float | None) -> str:
        return "—" if value is None else f"{value:+.2f}%"

    for row in table["rows"]:
        beat = "—" if row["positive_after5_pct"] is None else f"{row['positive_after5_pct']:.0f}%"
        print(
            f"{row['label']:<26}{row['filings']:>7}{show(row['avg_react_rel_pct']):>13}{show(row['avg_gap_rel_pct']):>13}"
            f"{show(row['avg_after5_rel_pct']):>17}{beat:>14}"
        )
    print(
        "\n'Day of news' is the first session that could show the filing, close to close. 'At the open' is how much "
        "of it was already in the opening price. 'Next 5 sessions' starts from the first price you could trade at "
        "after reading it."
    )


if __name__ == "__main__":
    main()
