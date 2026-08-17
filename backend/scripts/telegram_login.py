#!/usr/bin/env python3
"""Interactive Telethon login for news ingest (creates session file)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.news.config import telegram_channels, telegram_session_path
from app.services.news.telegram_client import build_telegram_client


async def main() -> None:
    client = build_telegram_client()
    session = telegram_session_path()
    print(f"Session path: {session}.session")
    print(f"Channels: {', '.join(telegram_channels())}")
    async with client:
        me = await client.get_me()
        print(f"Logged in as {me.first_name} (id={me.id})")
        for channel in telegram_channels():
            try:
                entity = await client.get_entity(channel)
                title = getattr(entity, "title", channel)
                print(f"  OK  {channel} → {title}")
            except Exception as exc:
                print(f"  FAIL {channel}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
