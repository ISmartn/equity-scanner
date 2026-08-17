#!/usr/bin/env python3
"""Backfill or incrementally sync Telegram news channels."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.news.ingest import ingest_channel, sync_configured_channels


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest Telegram channel news")
    parser.add_argument("--backfill", action="store_true", help="Pull recent history (not only new)")
    parser.add_argument("--limit", type=int, default=500, help="Max messages when backfilling")
    parser.add_argument("--channel", type=str, default=None, help="Override single channel")
    parser.add_argument("--no-process", action="store_true", help="Only store raw messages")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if args.channel:
        result = await ingest_channel(
            args.channel,
            limit=args.limit if args.backfill else None,
            backfill=args.backfill,
            process=not args.no_process,
        )
        print(json.dumps(result, indent=2, default=str))
    else:
        result = await sync_configured_channels(
            backfill=args.backfill,
            backfill_limit=args.limit,
            process=not args.no_process,
        )
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
