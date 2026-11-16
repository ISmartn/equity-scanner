"""Persist RSS articles in the lab database and build the story board."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

from ...db.store import TimelineStore
from .cluster import build_stories
from .companies import company_names
from .feeds import FEEDS, RETENTION_DAYS, feed_configs, fetch_feed
from .summarize import summarize_blurb

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS newsdesk_articles (
    link TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    published_at INTEGER NOT NULL,
    image TEXT,
    category TEXT,
    companies_json TEXT DEFAULT '[]',
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_color TEXT,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_newsdesk_published ON newsdesk_articles(published_at DESC);
CREATE TABLE IF NOT EXISTS newsdesk_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def ensure_schema(store: TimelineStore) -> None:
    with store.connection() as conn:
        conn.executescript(_SCHEMA)


def archive_articles(store: TimelineStore, articles: list[dict[str, Any]]) -> int:
    ensure_schema(store)
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    with store.connection() as conn:
        for article in articles:
            if not article.get("link"):
                continue
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO newsdesk_articles (
                    link, title, description, published_at, image, category,
                    companies_json, source_id, source_name, source_color, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article["link"],
                    article["title"],
                    article.get("description") or "",
                    int(article["published_at"]),
                    article.get("image"),
                    article.get("category") or "General",
                    json.dumps(article.get("companies") or []),
                    article["source_id"],
                    article["source_name"],
                    article.get("source_color") or "#888",
                    now,
                ),
            )
            inserted += cur.rowcount
    return inserted


def prune_articles(store: TimelineStore, days: int = RETENTION_DAYS) -> int:
    cutoff = int(datetime.now(timezone.utc).timestamp() * 1000) - days * 86_400_000
    with store.connection() as conn:
        cur = conn.execute("DELETE FROM newsdesk_articles WHERE published_at < ?", (cutoff,))
        return cur.rowcount


def list_articles(store: TimelineStore, *, days: int) -> list[dict[str, Any]]:
    ensure_schema(store)
    cutoff = int(datetime.now(timezone.utc).timestamp() * 1000) - days * 86_400_000
    with store.connection() as conn:
        rows = conn.execute(
            """
            SELECT link, title, description, published_at, image, category,
                   companies_json, source_id, source_name, source_color
            FROM newsdesk_articles
            WHERE published_at >= ?
            ORDER BY published_at DESC
            """,
            (cutoff,),
        ).fetchall()
    articles = []
    for row in rows:
        try:
            companies = json.loads(row["companies_json"] or "[]")
        except json.JSONDecodeError:
            companies = []
        articles.append(
            {
                "link": row["link"],
                "title": row["title"],
                "description": row["description"] or "",
                "published_at": int(row["published_at"]),
                "image": row["image"],
                "category": row["category"] or "General",
                "companies": companies,
                "source_id": row["source_id"],
                "source_name": row["source_name"],
                "source_color": row["source_color"] or "#888",
            }
        )
    return articles


def _set_meta(store: TimelineStore, key: str, value: str) -> None:
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO newsdesk_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def _get_meta(store: TimelineStore, key: str) -> str | None:
    ensure_schema(store)
    with store.connection() as conn:
        row = conn.execute("SELECT value FROM newsdesk_meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else None


async def refresh_feeds(store: TimelineStore) -> dict[str, Any]:
    ensure_schema(store)
    timeout = aiohttp.ClientTimeout(total=12)
    connector = aiohttp.TCPConnector(limit=8)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        batches = await asyncio.gather(*(fetch_feed(session, feed) for feed in FEEDS))
    cutoff = int(datetime.now(timezone.utc).timestamp() * 1000) - RETENTION_DAYS * 86_400_000
    fresh = [item for batch in batches for item in batch if item["published_at"] >= cutoff]
    inserted = archive_articles(store, fresh)
    pruned = prune_articles(store)
    refreshed_at = datetime.now(timezone.utc).isoformat()
    _set_meta(store, "refreshed_at", refreshed_at)
    logger.info("Newsdesk refresh: %d fetched, %d new, %d pruned", len(fresh), inserted, pruned)
    return {"fetched": len(fresh), "inserted": inserted, "pruned": pruned, "refreshed_at": refreshed_at}


def build_board(store: TimelineStore, *, days: int = 3, limit: int = 120) -> dict[str, Any]:
    articles = list_articles(store, days=days)
    stories = build_stories(articles)[:limit]
    names = company_names()
    counts: dict[str, int] = {}
    for story in stories:
        counts[story["category"]] = counts.get(story["category"], 0) + 1
        story["company_names"] = {symbol: names.get(symbol, symbol) for symbol in story["companies"]}
    categories = [{"id": key, "count": counts[key]} for key in sorted(counts, key=lambda key: (-counts[key], key))]
    return {
        "window_days": days,
        "retention_days": RETENTION_DAYS,
        "refreshed_at": _get_meta(store, "refreshed_at"),
        "article_count": len(articles),
        "story_count": len(stories),
        "sources": feed_configs(),
        "categories": categories,
        "stories": stories,
        "notes": [
            "Headlines are clustered when the wording matches across publishers.",
            "Company tags use the news desk alias list, stored as lab tickers.",
            "Summaries are extractive sentences from the feed blurb.",
        ],
    }


def summary_for_link(store: TimelineStore, link: str) -> dict[str, Any] | None:
    ensure_schema(store)
    with store.connection() as conn:
        row = conn.execute(
            "SELECT title, description, link, source_name FROM newsdesk_articles WHERE link = ?",
            (link,),
        ).fetchone()
    if not row:
        return None
    payload = summarize_blurb(row["title"], row["description"] or "")
    payload["link"] = row["link"]
    payload["source"] = row["source_name"]
    payload["description"] = row["description"] or ""
    return payload
