#!/usr/bin/env python3
"""CLI: run multi-year high breakout / ATH pullback scanner."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.multi_year_breakout.engine import run_multi_year_breakout_scan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None, help="Scan date YYYY-MM-DD")
    parser.add_argument(
        "--strategy",
        default="multi_year_breakout",
        choices=["multi_year_breakout", "ath_pullback", "custom"],
    )
    parser.add_argument("--years", type=int, default=3, choices=[2, 3, 4, 5])
    parser.add_argument("--pullback-pct", type=float, default=15.0)
    parser.add_argument(
        "--match-mode",
        default="at_least",
        choices=["at_least", "at_most", "band"],
    )
    parser.add_argument("--band-width", type=float, default=5.0)
    parser.add_argument(
        "--trend",
        default="all",
        choices=["all", "uptrend", "downtrend"],
    )
    parser.add_argument("--short-ma", type=int, default=50)
    parser.add_argument("--long-ma", type=int, default=200)
    parser.add_argument("--ma-type", default="sma", choices=["sma", "ema"])
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    def on_progress(u: dict) -> None:
        if int(u.get("processed") or 0) % 200 == 0:
            print(
                f"\r  {u.get('processed')}/{u.get('total')} "
                f"alerts={u.get('alerts_count')} {u.get('current_ticker') or ''}",
                end="",
                flush=True,
            )

    result = run_multi_year_breakout_scan(
        trade_date=args.date,
        strategy=args.strategy,
        lookback_years=args.years,
        pullback_pct=args.pullback_pct,
        match_mode=args.match_mode,
        band_width_pct=args.band_width,
        trend_filter=args.trend,
        short_ma_period=args.short_ma,
        long_ma_period=args.long_ma,
        ma_type=args.ma_type,
        concurrency=args.concurrency,
        on_progress=on_progress,
    )
    print()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
