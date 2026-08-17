from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ...db.store import TimelineStore, get_store
from .config import normalize_channel_key, telegram_channels
from .extract import process_unprocessed_messages
from .monitors import match_monitor_topics
from .telegram_client import build_telegram_client

logger = logging.getLogger(__name__)


def _msg_posted_at_iso(msg: Any) -> str:
    dt = msg.date
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def message_text_from_telegram(msg: Any) -> tuple[str, str | None]:
    """
    Extract caption/text from a Telethon message.

    Returns (text, media_kind). Media-only posts with no caption/filename return ("", kind)
    and should be skipped by callers — we do not store them.
    """
    text = (getattr(msg, "message", None) or getattr(msg, "raw_text", None) or "").strip()
    media = getattr(msg, "media", None)
    media_kind: str | None = None
    if media is not None:
        name = media.__class__.__name__.replace("MessageMedia", "").lower() or "media"
        media_kind = name
        file_obj = getattr(msg, "file", None)
        file_name = getattr(file_obj, "name", None) if file_obj else None
        if not text and file_name:
            text = str(file_name).strip()
    return text, media_kind


def is_media_placeholder_text(text: str | None) -> bool:
    """True for empty text or legacy '[photo]' / '[document]' placeholders."""
    t = (text or "").strip()
    if not t:
        return True
    return t.startswith("[") and t.endswith("]") and len(t) < 24


async def ingest_channel(
    channel: str,
    *,
    store: TimelineStore | None = None,
    limit: int | None = None,
    min_id: int | None = None,
    backfill: bool = False,
    process: bool = True,
    process_batch: int = 100,
) -> dict[str, Any]:
    """Pull messages from a Telegram channel into SQLite."""
    store = store or get_store()
    channel_key = normalize_channel_key(channel)
    client = build_telegram_client()

    inserted = 0
    scanned = 0
    max_message_id: int | None = None
    channel_id: str | None = None
    title: str | None = None

    async with client:
        entity = await client.get_entity(channel_key)
        channel_id = str(getattr(entity, "id", "") or "")
        title = getattr(entity, "title", None) or channel_key

        existing = store.get_news_channel(channel_key)
        if not backfill and min_id is None and existing and existing.get("last_message_id"):
            min_id = int(existing["last_message_id"])

        kwargs: dict[str, Any] = {}
        if limit is not None:
            kwargs["limit"] = int(limit)
        if min_id is not None:
            kwargs["min_id"] = int(min_id)

        async for msg in client.iter_messages(entity, **kwargs):
            scanned += 1
            if not msg or msg.id is None:
                continue
            text, media_kind = message_text_from_telegram(msg)
            # Drop media-only posts with no caption (common Redbox screenshots)
            if not text.strip():
                continue
            raw = {
                "id": msg.id,
                "date": _msg_posted_at_iso(msg),
                "views": getattr(msg, "views", None),
                "fwd_from": bool(getattr(msg, "fwd_from", None)),
                "source": "sync",
                "media_kind": media_kind,
                "monitor_topics": match_monitor_topics(text),
            }
            row_id = store.insert_telegram_message(
                channel_key=channel_key,
                channel_id=channel_id,
                message_id=int(msg.id),
                posted_at=_msg_posted_at_iso(msg),
                text=text,
                raw_json=json.dumps(raw),
            )
            if row_id is not None:
                inserted += 1
            if max_message_id is None or int(msg.id) > max_message_id:
                max_message_id = int(msg.id)

        prev_last = int(existing["last_message_id"]) if existing and existing.get("last_message_id") else None
        id_candidates = [x for x in (max_message_id, prev_last) if x is not None]
        store.upsert_news_channel(
            channel_key,
            channel_id=channel_id,
            title=title,
            last_message_id=max(id_candidates) if id_candidates else None,
            last_synced_at=datetime.now(timezone.utc).isoformat(),
        )

    process_stats: dict[str, Any] | None = None
    if process:
        totals = {
            "messages_processed": 0,
            "events_created": 0,
            "reactions": {"processed": 0, "written": 0, "skipped": 0},
        }
        while True:
            batch = await process_unprocessed_messages(
                store=store,
                limit=process_batch,
                build_reactions=True,
            )
            totals["messages_processed"] += batch["messages_processed"]
            totals["events_created"] += batch["events_created"]
            for k in ("processed", "written", "skipped"):
                totals["reactions"][k] += batch["reactions"].get(k, 0)
            if batch["messages_processed"] < process_batch:
                break
        process_stats = totals

    return {
        "channel": channel_key,
        "channel_id": channel_id,
        "title": title,
        "scanned": scanned,
        "inserted": inserted,
        "last_message_id": max_message_id,
        "process": process_stats,
    }


async def sync_configured_channels(
    *,
    backfill: bool = False,
    backfill_limit: int | None = 500,
    process: bool = True,
) -> dict[str, Any]:
    store = get_store()
    purged = store.purge_media_placeholder_messages()
    if purged:
        logger.info("Purged %s media-only Telegram messages (no caption)", purged)
    results = []
    for channel in telegram_channels():
        result = await ingest_channel(
            channel,
            store=store,
            limit=backfill_limit if backfill else None,
            backfill=backfill,
            process=process,
        )
        results.append(result)
        logger.info(
            "News sync %s scanned=%s inserted=%s",
            result["channel"],
            result["scanned"],
            result["inserted"],
        )
    return {
        "channels": results,
        "purged_media_no_caption": purged,
        "stats": store.news_stats(),
    }