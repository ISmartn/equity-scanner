#!/usr/bin/env python3
"""Fetch up to N own tweets (no reposts) via FxTwitter profile statuses + pagination."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
API = "https://api.fxtwitter.com/2/profile/{handle}/statuses"


def fetch_page(handle: str, count: int = 100, cursor: str | None = None, with_replies: bool = False) -> dict:
    params: dict[str, str] = {"count": str(max(1, min(count, 100)))}
    if with_replies:
        params["with_replies"] = "1"
    if cursor:
        params["cursor"] = cursor
    url = API.format(handle=urllib.parse.quote(handle.lstrip("@"))) + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "equity-scanner-xtf-test/1.0"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def is_own_tweet(item: dict, handle: str) -> bool:
    handle_l = handle.lstrip("@").lower()
    author = ((item.get("author") or {}).get("screen_name") or "").lower()
    reposted_by = (item.get("reposted_by") or {}).get("screen_name")
    if reposted_by:
        return False
    return author == handle_l


def normalize(item: dict) -> dict:
    author = (item.get("author") or {}).get("screen_name")
    return {
        "url": item.get("url"),
        "id": item.get("id"),
        "author": author,
        "text": item.get("text") or "",
        "likes": item.get("likes"),
        "reposts": item.get("reposts"),
        "replies": item.get("replies"),
        "views": item.get("views"),
        "created_at": item.get("created_at"),
        "created_timestamp": item.get("created_timestamp"),
        "lang": item.get("lang"),
    }


def fetch_own_tweets(handle: str, limit: int = 200, with_replies: bool = False) -> list[dict]:
    handle = handle.lstrip("@")
    collected: list[dict] = []
    seen: set[str] = set()
    cursor: str | None = None
    pages = 0
    max_pages = 40

    while len(collected) < limit and pages < max_pages:
        pages += 1
        payload = fetch_page(handle, count=100, cursor=cursor, with_replies=with_replies)
        results = payload.get("results") or []
        if not results:
            break
        new_ids = 0
        for item in results:
            if not isinstance(item, dict):
                continue
            tid = str(item.get("id") or "")
            if not tid or tid in seen:
                continue
            seen.add(tid)
            new_ids += 1
            if not is_own_tweet(item, handle):
                continue
            collected.append(normalize(item))
            if len(collected) >= limit:
                break
        bottom = (payload.get("cursor") or {}).get("bottom")
        if not bottom or new_ids == 0:
            break
        cursor = bottom
        time.sleep(0.35)
    return collected[:limit]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("handle")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--with-replies", action="store_true")
    parser.add_argument("--out", type=str, default="")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    handle = args.handle.lstrip("@")
    tweets = fetch_own_tweets(handle, limit=args.limit, with_replies=args.with_replies)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(args.out) if args.out else OUT / f"user_{handle}_own_{args.limit}_{stamp}.json"
    payload = {
        "handle": handle,
        "limit": args.limit,
        "count_returned": len(tweets),
        "include_reposts": False,
        "with_replies": args.with_replies,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "tweets": tweets,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"@{handle}: {len(tweets)} own tweets → {out_path}")
    if tweets:
        print(f"newest: {tweets[0].get('created_at')}")
        print(f"oldest: {tweets[-1].get('created_at')}")
    return 0 if tweets else 1


if __name__ == "__main__":
    raise SystemExit(main())
