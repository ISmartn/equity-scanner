#!/usr/bin/env python3
"""Evaluate forward performance for stored scanner signals → signal_outcomes + comparison report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT_DIR
from app.services.scanner.outcomes import evaluate_and_store_outcomes
from app.services.scanner.scoring import write_default_weights_template

OUTPUT_DIR = ROOT_DIR / "data" / "scanner_analysis"
SUMMARY_NAME = "outcome_comparison_summary.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-date", default=None, help="YYYY-MM-DD inclusive")
    parser.add_argument("--to-date", default=None, help="YYYY-MM-DD inclusive")
    parser.add_argument("--limit", type=int, default=50_000)
    args = parser.parse_args()

    write_default_weights_template()
    result = evaluate_and_store_outcomes(
        trade_date_from=args.from_date,
        trade_date_to=args.to_date,
        limit=args.limit,
        on_progress=lambda p: print(
            f"  [{p.get('index')}/{p.get('total')}] {p.get('ticker')}",
            flush=True,
        )
        if p.get("index") and int(p["index"]) % 250 == 0
        else None,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = OUTPUT_DIR / SUMMARY_NAME
    payload = {
        "outcomes_written": result["outcomes_written"],
        "signals_considered": result["signals_considered"],
        "stats": result["stats"],
        "comparison": result["comparison"],
    }
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    comp = result["comparison"]
    base = comp["baseline"]["horizon_5d"]
    ref = comp["refined"]["horizon_5d"]
    delta = comp["delta_5d"]
    print("\n=== Signal outcomes ===")
    print(f"Written: {result['outcomes_written']} / {result['signals_considered']}")
    print(f"DB stats: {result['stats']}")
    print("\n=== Baseline vs refined (5d) ===")
    print(
        f"Baseline: n={base.get('count')} win={base.get('win_rate_pct')}% "
        f"avg={base.get('avg_return_pct')} rr={base.get('mfe_mae_ratio')}"
    )
    print(
        f"Refined:  n={ref.get('count')} win={ref.get('win_rate_pct')}% "
        f"avg={ref.get('avg_return_pct')} rr={ref.get('mfe_mae_ratio')} "
        f"retention={comp['refined'].get('retention_pct')}%"
    )
    print(
        f"Delta:    win={delta.get('win_rate_pct')} avg={delta.get('avg_return_pct')} "
        f"rr={delta.get('mfe_mae_ratio')} n={delta.get('signal_count')}"
    )
    print(f"\nWrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
