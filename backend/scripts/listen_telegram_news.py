#!/usr/bin/env python3
"""Live Telegram news pool: catch-up from last_message_id, then NewMessage stream."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.logging_config import setup_logging
from app.services.news.listen import run_live_listener

setup_logging()
logger = logging.getLogger("news.listen")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live Redbox / Telegram news listener")
    parser.add_argument(
        "--no-catch-up",
        action="store_true",
        help="Skip incremental sync before listening",
    )
    parser.add_argument(
        "--no-process",
        action="store_true",
        help="Store raw messages only (no Gemini/linker/reactions)",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    await run_live_listener(catch_up=not args.no_catch_up, process=not args.no_process)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Live listener stopped")
