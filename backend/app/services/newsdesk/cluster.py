"""Group near-duplicate headlines the way Newsdesk's story builder does."""

from __future__ import annotations

import re
from typing import Any

STOP = {
    "the", "and", "for", "with", "from", "that", "this", "are", "was", "has", "have", "will", "its", "into",
    "over", "after", "amid", "says", "said", "new", "how", "why", "what", "who", "may", "can", "not", "but",
    "than", "now", "out", "all", "more", "about", "under", "live", "updates", "update", "news",
}
WINDOW_MS = 36 * 3600 * 1000
THRESHOLD = 0.55
_PUBLISHER_SUFFIX = re.compile(r"\s[-–—|]\s[^-–—|]{2,40}$")
_TOKEN = re.compile(r"[^a-z0-9\s]")


def _tokens(title: str) -> set[str]:
    cleaned = _PUBLISHER_SUFFIX.sub("", title.lower())
    out: set[str] = set()
    for word in _TOKEN.sub(" ", cleaned).split():
        if len(word) > 2 and word not in STOP:
            out.add(word)
    return out


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    inter = len(left & right)
    return inter / (len(left) + len(right) - inter or 1)


def build_stories(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cluster items that share a headline within 36 hours. Newest cluster first."""
    sorted_items = sorted(items, key=lambda item: int(item["published_at"]), reverse=True)
    clusters: list[dict[str, Any]] = []
    for item in sorted_items:
        published = int(item["published_at"])
        tokens = _tokens(item["title"])
        hit = -1
        if len(tokens) >= 4:
            for index in range(len(clusters) - 1, -1, -1):
                cluster = clusters[index]
                if cluster["time"] - published > WINDOW_MS:
                    continue
                if len(cluster["tokens"]) >= 4 and _jaccard(tokens, cluster["tokens"]) >= THRESHOLD:
                    hit = index
                    break
        if hit >= 0:
            clusters[hit]["items"].append(item)
        else:
            clusters.append({"items": [item], "tokens": tokens, "time": published})

    stories: list[dict[str, Any]] = []
    for cluster in clusters:
        members: list[dict[str, Any]] = cluster["items"]
        lead = next((item for item in members if item.get("image")), members[0])
        seen = {lead["source_id"]}
        others = []
        companies: list[str] = []
        company_seen: set[str] = set()
        for item in members:
            if item["source_id"] not in seen:
                seen.add(item["source_id"])
                others.append(
                    {
                        "id": item["source_id"],
                        "name": item["source_name"],
                        "color": item["source_color"],
                        "title": item["title"],
                        "link": item["link"],
                    }
                )
            for symbol in item.get("companies") or []:
                if symbol not in company_seen:
                    company_seen.add(symbol)
                    companies.append(symbol)
        earliest = members[-1]
        stories.append(
            {
                "id": earliest["link"],
                "time": cluster["time"],
                "category": lead.get("category") or "General",
                "companies": companies,
                "coverage": len(others) + 1,
                "lead": _public_item(lead),
                "others": others,
            }
        )
    return stories


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": item["title"],
        "description": item.get("description") or "",
        "link": item["link"],
        "published_at": int(item["published_at"]),
        "image": item.get("image"),
        "category": item.get("category") or "General",
        "companies": list(item.get("companies") or []),
        "source": {
            "id": item["source_id"],
            "name": item["source_name"],
            "color": item["source_color"],
        },
    }
