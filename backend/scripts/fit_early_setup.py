#!/usr/bin/env python3
"""Learn the setup score's weights from local daily candles.

For every stock-day on the daily list whose pivot was crossed the next session,
the trade is played out: stop-entry at the pivot, stop at the base low, sold
after 10 sessions, costs taken off. The earlier sessions fit the weights. The
latest 30% of sessions, which the fit never sees, measure them.

The fitted weights are saved only when they rank setups on those unseen
sessions. Otherwise the hand-set weights stay in use.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.store import get_store
from app.services.early_setup.model import TARGET, fit, save_weights
from app.services.early_setup.watchlist import build_dataset


def _line(label: str, group: dict) -> str:
    if not group or not group.get("trades"):
        return f"  {label:<22} no trades"
    return (
        f"  {label:<22}{group['trades']:>7} trades   avg {group['avg_pct']:+.2f}%   "
        f"median {group['median_pct']:+.2f}%   profitable {group['win_rate_pct']}%"
    )


def _show(title: str, result: dict) -> None:
    print(f"\n{title}")
    print(_line("All setups", result.get("all", {})))
    print(_line("Top fifth by score", result.get("top_fifth", {})))
    print(_line("The rest", result.get("rest", {})))
    if result.get("spread_low_pct") is not None:
        print(
            f"  Top fifth minus the rest: {result['spread_pct']:+.2f}% a trade "
            f"(90% range {result['spread_low_pct']:+.2f}% to {result['spread_high_pct']:+.2f}%)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit the setup score")
    parser.add_argument("--from-date", default=None, help="YYYY-MM-DD (default: two years before --to-date)")
    parser.add_argument("--to-date", default=None, help="YYYY-MM-DD (default: latest in DB)")
    parser.add_argument("--test-share", type=float, default=0.3, help="Share of the latest sessions held out")
    parser.add_argument("--dry-run", action="store_true", help="Print the result without saving the weights")
    parser.add_argument("--save-anyway", action="store_true", help="Save even when the weights do not rank unseen sessions")
    parser.add_argument("--export", default=None, help="Also write the labelled dataset to this CSV path")
    args = parser.parse_args()

    end = args.to_date or get_store().stats().get("max_trade_date")
    if not end:
        sys.exit("No daily candles in the database yet.")
    end = str(end)[:10]
    start = args.from_date or (date.fromisoformat(end) - timedelta(days=730)).isoformat()

    print(f"Building the dataset {start} → {end} …", flush=True)
    dataset = build_dataset(start, end)
    if dataset.empty:
        sys.exit("No stock was inside a base in that range. Check that candles are loaded.")
    trades = dataset.dropna(subset=[TARGET])
    print(
        f"{len(dataset)} stock-days on the daily list. {len(trades)} crossed the pivot the next session "
        f"and have a finished trade."
    )
    if args.export:
        dataset.to_csv(args.export, index=False)
        print(f"Dataset written to {args.export}")

    try:
        weights = fit(dataset, test_share=args.test_share)
    except ValueError as exc:
        sys.exit(str(exc))

    metrics = weights["metrics"]
    print("\nWeights (per standard deviation; positive raises the expected result)")
    for name, spec in sorted(weights["features"].items(), key=lambda item: -abs(item[1]["weight"])):
        print(f"  {name:<22}{spec['weight']:>+8.3f}")
    print(f"\nFitted on {metrics['train_from']} to {metrics['train_to']}, tested on {metrics['test_from']} to {metrics['test_to']}.")
    _show("Unseen sessions, fitted weights", metrics["test"])
    _show("Unseen sessions, hand-set weights", metrics["test_with_default_weights"])

    verdict = metrics["test"].get("verdict")
    if verdict == "ranks":
        print("\nThe fitted score ranked setups on sessions it never saw: the whole 90% range is above zero.")
    else:
        print(
            "\nThe fitted score did not reliably rank setups on sessions it never saw. "
            "Do not lean on the score; the list itself and the market-health reading are still usable."
        )
    if args.dry_run:
        print("Dry run: weights not saved.")
        return
    if verdict != "ranks" and not args.save_anyway:
        print("Weights not saved, so the hand-set weights stay in use. Pass --save-anyway to override.")
        return
    path = save_weights(weights, datetime.now(timezone.utc).isoformat())
    print(f"Saved to {path}")
    print(json.dumps({"saved": str(path)}))


if __name__ == "__main__":
    main()
