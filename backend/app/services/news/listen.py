from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from telethon import events

from ...db.store import TimelineStore, get_store
from .config import normalize_channel_key, telegram_channels
from .extract import process_message
from .event_study import compute_and_store_reactions
from .ingest import (
    _msg_posted_at_iso,
    is_media_placeholder_text,
    message_text_from_telegram,
    sync_configured_channels,
)
from .monitors import match_monitor_topics
from .name_linker import get_linker
from .telegram_client import build_telegram_client

logger = logging.getLogger(__name__)


async def persist_incoming_message(
    *,
    store: TimelineStore,
    channel_key: str,
    channel_id: str | None,
    title: str | None,
    msg: Any,
    process: bool = True,
) -> dict[str, Any]:
    """Store one Telegram message and optionally run extract + reactions."""
    text, media_kind = message_text_from_telegram(msg)
    if not text.strip():
        return {"inserted": False, "reason": "media_no_caption", "media_kind": media_kind}

    message_id = int(msg.id)
    posted_at = _msg_posted_at_iso(msg)
    topics = match_monitor_topics(text)
    raw = {
        "id": message_id,
        "date": posted_at,
        "views": getattr(msg, "views", None),
        "fwd_from": bool(getattr(msg, "fwd_from", None)),
        "source": "live",
        "media_kind": media_kind,
        "monitor_topics": topics,
    }
    row_id = store.insert_telegram_message(
        channel_key=channel_key,
        channel_id=channel_id,
        message_id=message_id,
        posted_at=posted_at,
        text=text,
        raw_json=json.dumps(raw),
    )

    existing = store.get_news_channel(channel_key)
    prev_last = int(existing["last_message_id"]) if existing and existing.get("last_message_id") else None
    new_last = message_id if prev_last is None else max(prev_last, message_id)
    store.upsert_news_channel(
        channel_key,
        channel_id=channel_id,
        title=title,
        last_message_id=new_last,
        last_synced_at=datetime.now(timezone.utc).isoformat(),
    )

    if row_id is None:
        return {
            "inserted": False,
            "reason": "duplicate",
            "message_id": message_id,
            "monitor_topics": topics,
        }

    event_ids: list[int] = []
    if process and not is_media_placeholder_text(text):
        target = store.get_telegram_message(row_id)
        if target and not target.get("processed"):
            linker = get_linker()
            linker.reload()
            event_ids = await process_message(target, store=store, linker=linker)
            if event_ids:
                compute_and_store_reactions(store, event_ids=event_ids)

    return {
        "inserted": True,
        "message_pk": row_id,
        "message_id": message_id,
        "event_ids": event_ids,
        "monitor_topics": topics,
    }


async def run_live_listener(
    *,
    catch_up: bool = True,
    process: bool = True,
    stop_event: asyncio.Event | None = None,
    on_message: Callable[[], None] | None = None,
) -> None:
    """
    Catch up from last_message_id, then stay connected for NewMessage events.

    Run via API live start or ``npm run news:listen``.
    """
    store = get_store()
    channels = telegram_channels()
    if not channels:
        raise RuntimeError("TELEGRAM_CHANNELS is empty")

    if catch_up:
        logger.info("Live listener catch-up sync starting…")
        result = await sync_configured_channels(backfill=False, process=process)
        logger.info("Catch-up done: %s", result.get("stats"))

    client = build_telegram_client()
    channel_meta: dict[str, dict[str, Any]] = {}
    stop_task: asyncio.Task[None] | None = None

    try:
        async with client:
            for channel in channels:
                key = normalize_channel_key(channel)
                entity = await client.get_entity(key)
                channel_id = str(getattr(entity, "id", "") or "")
                title = getattr(entity, "title", None) or key
                channel_meta[key] = {"entity": entity, "channel_id": channel_id, "title": title}
                store.upsert_news_channel(key, channel_id=channel_id, title=title)
                logger.info("Listening on %s (%s)", key, title)

            entities = [meta["entity"] for meta in channel_meta.values()]

            @client.on(events.NewMessage(chats=entities))
            async def on_new_message(event: events.NewMessage.Event) -> None:
                try:
                    chat = await event.get_chat()
                    chat_id = str(getattr(chat, "id", "") or "")
                    channel_key = None
                    meta = None
                    for key, m in channel_meta.items():
                        if m["channel_id"] == chat_id or m["entity"] == chat:
                            channel_key = key
                            meta = m
                            break
                    if not channel_key or not meta:
                        username = getattr(chat, "username", None)
                        if username:
                            channel_key = normalize_channel_key(username)
                            meta = channel_meta.get(channel_key) or {
                                "channel_id": chat_id,
                                "title": getattr(chat, "title", None),
                            }
                        else:
                            logger.warning("Ignoring message from unknown chat id=%s", chat_id)
                            return

                    outcome = await persist_incoming_message(
                        store=store,
                        channel_key=channel_key,
                        channel_id=meta.get("channel_id") or chat_id,
                        title=meta.get("title"),
                        msg=event.message,
                        process=process,
                    )
                    if on_message:
                        on_message()
                    logger.info(
                        "Live message %s/%s inserted=%s topics=%s events=%s",
                        channel_key,
                        outcome.get("message_id"),
                        outcome.get("inserted"),
                        outcome.get("monitor_topics"),
                        outcome.get("event_ids"),
                    )
                except Exception:
                    logger.exception("Failed to handle live Telegram message")

            if stop_event is not None:

                async def _watch_stop() -> None:
                    await stop_event.wait()
                    logger.info("Live stop requested — disconnecting Telegram client")
                    await client.disconnect()

                stop_task = asyncio.create_task(_watch_stop())

            logger.info("Live pool connected — waiting for posts")
            await client.run_until_disconnected()
    finally:
        if stop_task and not stop_task.done():
            stop_task.cancel()
            try:
                await stop_task
            except asyncio.CancelledError:
                pass
