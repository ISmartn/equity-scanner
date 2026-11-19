#!/usr/bin/env python3
"""Report how the setup watchlist did: breakout rate, lead over an end-of-day signal, follow-through."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.early_setup.report import watchlist_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Setup watchlist report")
    parser.add_argument("--since", default=None, help="Only setups first listed on or after YYYY-MM-DD")
    parser.add_argument("--list", default="daily", choices=("daily", "weekly"), help="Which list to report on")
    parser.add_argument("--max-positions", type=int, default=10, help="Most positions held at once in the account view")
    args = parser.parse_args()
    report = watchlist_report(since=args.since, timeframe=args.list, max_positions=args.max_positions)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
