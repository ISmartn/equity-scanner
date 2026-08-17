#!/usr/bin/env python3
"""Reprofile stale symbols: refresh NSE master, migrate ISINs, mark delisted as ingest-skip."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiohttp

from app.db.store import get_store
from app.services.profile_sync import reprofile_stale_profiles


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        result = await reprofile_stale_profiles(session, get_store())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
