#!/usr/bin/env python3
"""Sync NSE mainboard equity profiles into the local timeline database."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Allow running as: python backend/scripts/sync_profiles.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiohttp

from app.db.store import get_store
from app.services.profile_sync import sync_security_profiles


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        result = await sync_security_profiles(session, get_store())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
