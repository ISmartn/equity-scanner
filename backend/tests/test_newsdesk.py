"""News desk: company tags, RSS parse, story clusters, stored board."""

from __future__ import annotations

import time

from app.db.store import TimelineStore
from app.services.newsdesk.cluster import build_stories
from app.services.newsdesk.companies import match_companies
from app.services.newsdesk.feeds import parse_feed_xml
from app.services.newsdesk.service import archive_articles, build_board
from app.services.newsdesk.summarize import summarize_blurb


RSS = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Reliance shares rise after Q2 results - Livemint</title>
      <link>https://example.com/reliance</link>
      <pubDate>Wed, 11 Nov 2026 09:00:00 +0530</pubDate>
      <description>Reliance Industries reported profit of Rs 20,000 crore.</description>
    </item>
    <item>
      <title>itc is not a ticker here</title>
      <link>https://example.com/lower</link>
      <pubDate>Wed, 11 Nov 2026 08:00:00 +0530</pubDate>
      <description>A lowercase itc mention should not tag the stock.</description>
    </item>
  </channel>
</rss>
"""


def test_company_match_respects_case_and_finance_context() -> None:
    assert "RELIANCE" in match_companies("Reliance shares rise after results")
    assert match_companies("The reliance of the method") == []
    assert "ITC" in match_companies("ITC reported earnings")
    assert "ITC" not in match_companies("itc reported earnings")


def test_rss_parse_tags_reliance_and_strips_source_suffix() -> None:
    feed = {"id": "livemint-markets", "name": "Livemint Markets", "category": "Markets", "color": "#EC4327"}
    items = parse_feed_xml(RSS, feed)
    assert items[0]["title"] == "Reliance shares rise after Q2 results"
    assert items[0]["companies"] == ["RELIANCE"]
    assert "ITC" not in items[1]["companies"]
    assert "20,000 crore" in items[0]["description"] or "crore" in items[0]["description"]


def test_stories_cluster_matching_headlines() -> None:
    now = 1_700_000_000_000
    items = [
        _item("https://a.example/1", "Reliance Industries profit jumps in Q2 results", now, "Livemint"),
        _item("https://b.example/2", "Reliance Industries profit jumps in Q2 results today", now - 60_000, "ET Markets"),
        _item("https://c.example/3", "RBI holds the policy rate at the review", now - 120_000, "BBC"),
    ]
    stories = build_stories(items)
    clustered = next(story for story in stories if story["coverage"] == 2)
    assert clustered["lead"]["source"]["name"] == "Livemint"
    assert len(clustered["others"]) == 1
    assert any(story["coverage"] == 1 for story in stories)


def test_board_reads_archived_articles(tmp_path) -> None:
    store = TimelineStore(tmp_path / "desk.db")
    archive_articles(
        store,
        [
            {
                "link": "https://example.com/r",
                "title": "Reliance shares rise after Q2 results",
                "description": "Reliance Industries reported profit of Rs 20,000 crore for the quarter.",
                "published_at": int(time.time() * 1000),
                "image": None,
                "category": "Markets",
                "companies": ["RELIANCE"],
                "source_id": "livemint-markets",
                "source_name": "Livemint Markets",
                "source_color": "#EC4327",
            }
        ],
    )
    board = build_board(store, days=30)
    assert board["article_count"] == 1
    assert board["stories"][0]["companies"] == ["RELIANCE"]
    summary = summarize_blurb(
        "Reliance shares rise after Q2 results",
        "Reliance Industries reported profit of Rs 20,000 crore for the quarter and guided for steady demand.",
    )
    assert summary["figures"]


def _item(link: str, title: str, published: int, source: str) -> dict:
    return {
        "link": link,
        "title": title,
        "description": "",
        "published_at": published,
        "image": None,
        "category": "Markets",
        "companies": [],
        "source_id": source.lower(),
        "source_name": source,
        "source_color": "#111",
    }
