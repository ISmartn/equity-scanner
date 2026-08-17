#!/usr/bin/env python3
"""Build LLM-friendly compact JSON from an existing scanner_refinement_dataset.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT_DIR
from app.services.scanner.analysis import build_llm_refinement_dataset

DEFAULT_INPUT = ROOT_DIR / "data" / "scanner_analysis" / "scanner_refinement_dataset.json"
DEFAULT_OUTPUT = ROOT_DIR / "data" / "scanner_analysis" / "scanner_refinement_llm.json"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Compact scanner dataset for LLM analysis")
    parser.add_argument("--input", type=str, default=str(DEFAULT_INPUT))
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    src = Path(args.input)
    if not src.is_file():
        raise SystemExit(f"Input not found: {src}")

    print(f"Reading {src} ({src.stat().st_size / 1e6:.1f} MB)…")
    payload = json.loads(src.read_text(encoding="utf-8"))
    records = payload.get("signals") or payload.get("records") or []
    manifest = {k: v for k, v in payload.items() if k not in {"signals", "records"}}

    llm = build_llm_refinement_dataset(manifest, records)
    out = Path(args.output)
    out.write_text(json.dumps(llm, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.2f} MB, {llm['signal_count']} signals)")


if __name__ == "__main__":
    main()
