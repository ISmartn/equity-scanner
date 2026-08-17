from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MonitorTopic:
    key: str
    label: str
    keywords: tuple[str, ...]


# Always-on commodity monitors (keyword match on Telegram text).
DEFAULT_MONITOR_TOPICS: tuple[MonitorTopic, ...] = (
    MonitorTopic(
        key="GOLD",
        label="Gold",
        keywords=("gold", "xgau", "bullion", "jewellery demand", "sovereign gold"),
    ),
    MonitorTopic(
        key="SILVER",
        label="Silver",
        keywords=("silver", "xag", "silver futures"),
    ),
    MonitorTopic(
        key="CRUDEOIL",
        label="Crude Oil",
        keywords=("crude oil", "crudeoil", "brent", "wti", "oil price", "opec"),
    ),
)


def monitor_topics() -> list[MonitorTopic]:
    """Topics from NEWS_MONITOR_TOPICS env (comma keys) or full default set."""
    raw = os.getenv("NEWS_MONITOR_TOPICS", "GOLD,SILVER,CRUDEOIL").strip()
    if not raw:
        return list(DEFAULT_MONITOR_TOPICS)
    wanted = {p.strip().upper() for p in raw.split(",") if p.strip()}
    by_key = {t.key: t for t in DEFAULT_MONITOR_TOPICS}
    out = [by_key[k] for k in wanted if k in by_key]
    return out or list(DEFAULT_MONITOR_TOPICS)


def match_monitor_topics(text: str | None) -> list[str]:
    """Return monitor topic keys found in text (case-insensitive)."""
    if not text:
        return []
    low = text.lower()
    hits: list[str] = []
    for topic in monitor_topics():
        for kw in topic.keywords:
            if kw.lower() in low:
                hits.append(topic.key)
                break
    return hits


def topic_filter_regex(topic_key: str) -> re.Pattern[str] | None:
    by_key = {t.key: t for t in DEFAULT_MONITOR_TOPICS}
    topic = by_key.get(topic_key.upper())
    if not topic:
        return None
    parts = [re.escape(k) for k in topic.keywords]
    return re.compile("|".join(parts), re.I)
