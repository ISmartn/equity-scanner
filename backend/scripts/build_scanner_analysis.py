#!/usr/bin/env python3
"""Build one-month scanner analysis with forward performance; writes data/scanner_analysis/."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT_DIR
from app.services.scanner.analysis import (
    DEFAULT_MIN_SCORE,
    DEFAULT_PRE_SCAN_WEEKS,
    DEFAULT_TRADING_DAYS,
    build_llm_refinement_dataset,
    build_refinement_dataset,
    build_scanner_analysis_dataset,
)

OUTPUT_DIR = ROOT_DIR / "data" / "scanner_analysis"
REFINEMENT_JSON_NAME = "scanner_refinement_dataset.json"
LLM_JSON_NAME = "scanner_refinement_llm.json"
JSON_NAME = "signals_1m.json"
CSV_NAME = "signals_1m.csv"
DAILY_CSV_NAME = "signals_1m_daily.csv"
PRE_SCAN_CSV_NAME = "signals_1m_pre_scan.csv"
MANIFEST_NAME = "manifest.json"

CSV_FIELDS = [
    "trade_date",
    "ticker",
    "company_name",
    "sector",
    "pattern_type",
    "score",
    "pattern_score",
    "macro_pass",
    "triggered_today",
    "setup_ready",
    "entry_close",
    "last_trade_date",
    "last_close",
    "trading_days_forward",
    "return_to_last_pct",
    "return_1d_pct",
    "return_3d_pct",
    "return_5d_pct",
    "return_10d_pct",
    "return_20d_pct",
    "max_favorable_pct",
    "max_adverse_pct",
    "fundamental_pass",
    "market_score_delta",
]

DAILY_CSV_FIELDS = [
    "signal_date",
    "ticker",
    "pattern_type",
    "score",
    "entry_close",
    "date",
    "day_offset",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "return_from_entry_pct",
    "daily_return_pct",
]

PRE_SCAN_CSV_FIELDS = [
    "signal_date",
    "ticker",
    "pattern_type",
    "score",
    "date",
    "day_offset",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "daily_return_pct",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build momentum scanner 1-month analysis dataset")
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_TRADING_DAYS,
        help=f"Number of recent trading days to scan (default: {DEFAULT_TRADING_DAYS})",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=DEFAULT_MIN_SCORE,
        help=f"Minimum signal score to include (default: {DEFAULT_MIN_SCORE})",
    )
    parser.add_argument(
        "--pre-scan-weeks",
        type=int,
        default=DEFAULT_PRE_SCAN_WEEKS,
        help=f"Weeks of OHLCV before each signal (default: {DEFAULT_PRE_SCAN_WEEKS})",
    )
    parser.add_argument(
        "--skip-scan",
        action="store_true",
        help="Use existing scanner runs in DB instead of re-running scans",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(OUTPUT_DIR),
        help="Output directory (default: data/scanner_analysis)",
    )
    return parser.parse_args()


def write_csv(path: Path, records: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in records:
            writer.writerow(row)


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def on_progress(update: dict) -> None:
        phase = update.get("phase", "")
        if phase == "scan":
            print(
                f"\rScanning date {update.get('date_index')}/{update.get('date_total')} "
                f"{update.get('scan_date')}",
                end="",
                flush=True,
            )
        elif phase == "forward":
            print(
                f"\rForward perf {update.get('date_index')}/{update.get('date_total')} "
                f"{update.get('scan_date')} {update.get('ticker')}",
                end="",
                flush=True,
            )

    dataset = build_scanner_analysis_dataset(
        trading_days=args.days,
        min_score=args.min_score,
        pre_scan_sessions=max(1, args.pre_scan_weeks) * 5,
        run_scans=not args.skip_scan,
        on_progress=on_progress,
    )
    print()

    records = dataset.pop("records")
    daily_rows = dataset.pop("daily_rows", [])
    pre_scan_rows = dataset.pop("pre_scan_rows", [])
    manifest = dataset

    json_path = out_dir / JSON_NAME
    csv_path = out_dir / CSV_NAME
    daily_csv_path = out_dir / DAILY_CSV_NAME
    pre_scan_csv_path = out_dir / PRE_SCAN_CSV_NAME
    manifest_path = out_dir / MANIFEST_NAME
    refinement_path = out_dir / REFINEMENT_JSON_NAME
    llm_path = out_dir / LLM_JSON_NAME

    refinement = build_refinement_dataset(manifest, records)
    refinement_path.write_text(json.dumps(refinement, indent=2), encoding="utf-8")

    llm_dataset = build_llm_refinement_dataset(manifest, records)
    llm_path.write_text(json.dumps(llm_dataset, separators=(",", ":")), encoding="utf-8")

    # JSON: summary records include embedded daily_path per signal
    payload = {**manifest, "records": records}
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # CSV: one row per signal (no path columns)
    summary_rows = [
        {k: v for k, v in r.items() if k not in {"daily_path", "pre_scan_path"}}
        for r in records
    ]
    write_csv(csv_path, summary_rows, CSV_FIELDS + ["pre_scan_sessions"])
    write_csv(daily_csv_path, daily_rows, DAILY_CSV_FIELDS)
    write_csv(pre_scan_csv_path, pre_scan_rows, PRE_SCAN_CSV_FIELDS)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps(manifest, indent=2))
    print(f"\nWrote {len(records)} signals to:")
    print(f"  {llm_path}  (LLM-friendly — use this in chat)")
    print(f"  {refinement_path}  (full OHLCV paths)")
    print(f"  {json_path}")
    print(f"  {csv_path}")
    print(f"  {daily_csv_path}")
    print(f"  {pre_scan_csv_path}")
    print(f"  {manifest_path}")


if __name__ == "__main__":
    main()
