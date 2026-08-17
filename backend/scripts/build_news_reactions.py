#!/usr/bin/env python3
"""Recompute news event reactions from daily candles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.news.event_study import compute_and_store_reactions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build news reaction windows")
    parser.add_argument("--limit", type=int, default=1000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = compute_and_store_reactions(limit=args.limit)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()