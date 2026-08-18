#!/usr/bin/env python3
"""Discover a user's recent tweet URLs via FxTwitter API v2, then optionally
fetch each with xtf --url (same path as the working single-tweet smoke test).

By default only returns posts authored by the handle (drops retweets / others).

Usage:
  .venv/bin/python fetch_user_tweets.py kyalashish
  .venv/bin/python fetch_user_tweets.py kyalashish --count 10
  .venv/bin/python fetch_user_tweets.py kyalashish --include-reposts
  .venv/bin/python fetch_user_tweets.py kyalashish --fetch   # also run xtf per URL
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
XTF = ROOT / ".venv" / "bin" / "xtf"
API = "https://api.fxtwitter.com/2/profile/{handle}/statuses"


def list_statuses(handle: str, count: int = 20, with_replies: bool = False) -> dict:
    params = {"count": str(max(1, min(count, 100)))}
    if with_replies:
        params["with_replies"] = "1"
    url = API.format(handle=urllib.parse.quote(handle.lstrip("@"))) + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "equity-scanner-xtf-test/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_urls(
    payload: dict,
    *,
    handle: str,
    include_reposts: bool = False,
    limit: int | None = None,
) -> list[dict]:
    handle_l = handle.lstrip("@").lower()
    rows = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not url:
            continue
        author = (item.get("author") or {}).get("screen_name")
        reposted_by = (item.get("reposted_by") or {}).get("screen_name")
        # Retweets: author is the original poster, reposted_by is the profile owner.
        is_repost = bool(reposted_by) or (author or "").lower() != handle_l
        if not include_reposts and is_repost:
            continue
        rows.append(
            {
                "url": url,
                "id": item.get("id"),
                "author": author,
                "text": (item.get("text") or "")[:240],
                "likes": item.get("likes"),
                "created_at": item.get("created_at"),
                "reposted_by": reposted_by,
                "is_repost": is_repost,
            }
        )
        if limit is not None and len(rows) >= limit:
            break
    return rows


def fetch_with_xtf(url: str) -> dict:
    proc = subprocess.run(
        [str(XTF), "--url", url, "--pretty", "--lang", "en"],
        capture_output=True,
        text=True,
        timeout=45,
        cwd=ROOT,
    )
    out: dict = {"url": url, "returncode": proc.returncode, "stderr": proc.stderr.strip()}
    try:
        out["json"] = json.loads(proc.stdout) if proc.stdout.strip() else None
    except json.JSONDecodeError:
        out["json"] = None
        out["stdout"] = proc.stdout.strip()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="List + optionally fetch a user's tweets via FxTwitter")
    parser.add_argument("handle", help="X username without @")
    parser.add_argument("--count", type=int, default=10, help="How many user tweets to keep (1-100)")
    parser.add_argument("--with-replies", action="store_true", help="Include the user's replies in the listing")
    parser.add_argument(
        "--include-reposts",
        action="store_true",
        help="Also keep retweets / other authors from the profile timeline",
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Also fetch each URL with xtf --url (slower; listing already has text)",
    )
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    handle = args.handle.lstrip("@")
    want = max(1, min(args.count, 100))
    # Over-fetch from API so filtering still fills --count.
    api_count = want if args.include_reposts else min(100, max(want * 3, want))

    try:
        payload = list_statuses(handle, count=api_count, with_replies=args.with_replies)
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code} listing @{handle}: {exc.reason}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to list @{handle}: {exc}", file=sys.stderr)
        return 1

    raw_n = len(payload.get("results") or [])
    urls = extract_urls(
        payload,
        handle=handle,
        include_reposts=args.include_reposts,
        limit=want,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    list_path = OUT / f"user_{handle}_list_{stamp}.json"
    list_path.write_text(
        json.dumps(
            {
                "handle": handle,
                "count_requested": want,
                "api_count": api_count,
                "api_returned": raw_n,
                "count_returned": len(urls),
                "include_reposts": args.include_reposts,
                "ran_at": datetime.now(timezone.utc).isoformat(),
                "tweets": urls,
                "raw_code": payload.get("code"),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    mode = "all timeline items" if args.include_reposts else "own tweets only"
    print(f"@{handle}: {len(urls)} URL(s) ({mode}; api returned {raw_n})\n")
    for row in urls:
        who = row["author"] or "?"
        print(f"- {row['url']}")
        print(f"  @{who} · likes={row['likes']} · {row['text'][:100]}…\n")
    print(f"Wrote {list_path}")

    if not args.fetch:
        print("\nTip: listing already includes text. Use --fetch only if you need xtf's exact schema.")
        return 0 if urls else 1

    if not XTF.exists():
        print(f"Missing {XTF}", file=sys.stderr)
        return 2

    fetched = []
    for row in urls:
        print(f"xtf --url {row['url']}")
        fetched.append(fetch_with_xtf(row["url"]))

    fetch_path = OUT / f"user_{handle}_fetched_{stamp}.json"
    fetch_path.write_text(json.dumps(fetched, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ok = sum(1 for f in fetched if f["returncode"] == 0 and not (f.get("json") or {}).get("error"))
    print(f"\nFetched {ok}/{len(fetched)} via xtf → {fetch_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
