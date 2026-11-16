"""RSS sources and parsing for the news desk.

Feed list and routing rules follow Newsdesk's feed proxy. Fetches stay on
these known URLs.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree as ET

import aiohttp

from .companies import match_companies

logger = logging.getLogger(__name__)

RETENTION_DAYS = 30
FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.8",
}

FEEDS: list[dict[str, Any]] = [
    {"id": "livemint-markets", "name": "Livemint Markets", "url": "https://www.livemint.com/rss/markets", "fallback_url": "https://news.google.com/rss/search?q=site:livemint.com/market+when:2d&hl=en-IN&gl=IN&ceid=IN:en", "category": "Markets", "color": "#EC4327"},
    {"id": "et-markets", "name": "ET Markets", "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "fallback_url": "https://news.google.com/rss/search?q=site:economictimes.indiatimes.com/markets+when:2d&hl=en-IN&gl=IN&ceid=IN:en", "category": "Markets", "color": "#1A73E8"},
    {"id": "biztoc", "name": "BizToc", "url": "https://biztoc.com/feed", "category": "Global", "color": "#FF6B35"},
    {"id": "livemint-companies", "name": "Livemint Companies", "url": "https://www.livemint.com/rss/companies", "fallback_url": "https://news.google.com/rss/search?q=site:livemint.com/companies+when:2d&hl=en-IN&gl=IN&ceid=IN:en", "category": "Corporate", "color": "#EC4327"},
    {"id": "et-stocks", "name": "ET Stocks", "url": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms", "fallback_url": "https://news.google.com/rss/search?q=site:economictimes.indiatimes.com/markets/stocks+when:2d&hl=en-IN&gl=IN&ceid=IN:en", "category": "Stocks", "color": "#1A73E8"},
    {"id": "cnbc-business", "name": "CNBC Business", "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10001147", "category": "Business", "color": "#005994"},
    {"id": "livemint-news", "name": "Livemint News", "url": "https://www.livemint.com/rss/news", "fallback_url": "https://news.google.com/rss/search?q=site:livemint.com+when:1d&hl=en-IN&gl=IN&ceid=IN:en", "category": "Headlines", "color": "#EC4327"},
    {"id": "livemint-money", "name": "Livemint Money", "url": "https://www.livemint.com/rss/money", "fallback_url": "https://news.google.com/rss/search?q=site:livemint.com/money+when:2d&hl=en-IN&gl=IN&ceid=IN:en", "category": "Money", "color": "#EC4327"},
    {"id": "cnbc-world", "name": "CNBC World", "url": "https://www.cnbc.com/id/100727362/device/rss/rss.html", "category": "World", "color": "#005994"},
    {"id": "cnbc-economy", "name": "CNBC Economy", "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html", "category": "Economy", "color": "#005994"},
    {"id": "bbc-world", "name": "BBC World", "url": "http://feeds.bbci.co.uk/news/world/rss.xml", "category": "World", "color": "#BB1919"},
    {"id": "bbc-middleeast", "name": "BBC Middle East", "url": "http://feeds.bbci.co.uk/news/world/middle_east/rss.xml", "category": "MiddleEast", "color": "#BB1919"},
    {"id": "bbc-asia", "name": "BBC Asia", "url": "http://feeds.bbci.co.uk/news/world/asia/rss.xml", "category": "World", "color": "#BB1919"},
    {"id": "gn-iran-war", "name": "GN Iran Conflict", "url": "https://news.google.com/rss/search?q=Iran+war+conflict+missile+drone+strike&hl=en-US&gl=US&ceid=US:en", "category": "Geopolitics", "color": "#E53935"},
    {"id": "gn-middleeast", "name": "GN Middle East", "url": "https://news.google.com/rss/search?q=Middle+East+crisis+conflict+Israel+Lebanon+Syria&hl=en-US&gl=US&ceid=US:en", "category": "MiddleEast", "color": "#E53935"},
    {"id": "gn-defense", "name": "GN Defense", "url": "https://news.google.com/rss/search?q=defense+military+geopolitics+NATO+sanctions&hl=en-US&gl=US&ceid=US:en", "category": "Defense", "color": "#E53935"},
    {"id": "gn-geopolitics", "name": "GN Geopolitics", "url": "https://news.google.com/rss/search?q=geopolitics+diplomacy+sanctions+ceasefire+negotiations&hl=en-US&gl=US&ceid=US:en", "category": "Geopolitics", "color": "#E53935"},
    {"id": "gn-india-defense", "name": "GN India Defense", "url": "https://news.google.com/rss/search?q=India+defense+military+DRDO+HAL+border&hl=en-IN&gl=IN&ceid=IN:en", "category": "Defense", "color": "#E53935"},
    {"id": "gn-ai", "name": "GN Artificial Intelligence", "url": "https://news.google.com/rss/search?q=Artificial+Intelligence+OpenAI+ChatGPT+AI+Nvidia&hl=en-US&gl=US&ceid=US:en", "category": "AI", "color": "#10B981"},
    {"id": "defensenews-global", "name": "Defense News", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml", "category": "Defense", "color": "#1B3F5E"},
    {"id": "ndtv-world", "name": "NDTV World", "url": "https://feeds.feedburner.com/ndtvnews-world-news", "category": "World", "color": "#E23838"},
    {"id": "gn-aljazeera", "name": "Al Jazeera", "url": "https://news.google.com/rss/search?q=site:aljazeera.com+Middle+East+OR+Iran+OR+Israel&hl=en-US&gl=US&ceid=US:en", "category": "MiddleEast", "color": "#FA9000"},
    {"id": "gn-bloomberg", "name": "Bloomberg", "url": "https://news.google.com/rss/search?q=site:bloomberg.com+when:1d&hl=en-US&gl=US&ceid=US:en", "category": "Markets", "color": "#F59E0B"},
    {"id": "gn-reuters", "name": "Reuters", "url": "https://news.google.com/rss/search?q=site:reuters.com+when:1d&hl=en-US&gl=US&ceid=US:en", "category": "Global", "color": "#F97316"},
    {"id": "gn-wsj", "name": "Wall Street Journal", "url": "https://news.google.com/rss/search?q=site:wsj.com+when:1d&hl=en-US&gl=US&ceid=US:en", "category": "Business", "color": "#06B6D4"},
    {"id": "gn-ft", "name": "Financial Times", "url": "https://news.google.com/rss/search?q=site:ft.com+when:1d&hl=en-US&gl=US&ceid=US:en", "category": "Economy", "color": "#F472B6"},
    {"id": "zerohedge", "name": "ZeroHedge", "url": "https://feeds.feedburner.com/zerohedge/feed", "category": "Markets", "color": "#D97706"},
    {"id": "seeking-alpha", "name": "Seeking Alpha", "url": "https://seekingalpha.com/market_currents.xml", "category": "Stocks", "color": "#EA580C"},
]

GENERIC_CATEGORIES = {"Global", "General", "Headlines"}
GEO_KEYWORDS = {
    "MiddleEast": re.compile(r"\b(iran|israel|lebanon|hezbollah|hamas|gaza|west\s?bank|syria|iraq|yemen|houthi|saudi|uae|dubai|bahrain|kuwait|qatar|tehran|jerusalem|tel\s?aviv|netanyahu|khamenei|irgc|idf|middle\s?east|arab)\b", re.I),
    "Defense": re.compile(r"\b(military|defense|defence|missile|drone\s?strike|warplane|airstrike|air\s?strike|nato|pentagon|army|navy|air\s?force|weapons|ammunition|troops|soldiers|combat|warfare|munitions|artillery|nuclear|ballistic|cruise\s?missile|radar|submarine|fighter\s?jet|bomber|infantry|drdo|hal|isro|rafale)\b", re.I),
    "Geopolitics": re.compile(r"\b(geopoliti|sanctions|ceasefire|diplomacy|negotiations|embargo|treaty|alliance|summit|bilateral|multilateral|un\s?security|g7|g20|brics|coup|regime|invasion|occupation|territorial|sovereignty|humanitarian|refugee|asylum|border\s?conflict)\b", re.I),
    "War": re.compile(r"\b(war|conflict|bombing|shelling|casualties|killed|wounded|attack|explosion|blast|siege|offensive|counteroffensive|escalation|retaliation|strike)\b", re.I),
    "AI": re.compile(r"\b(artificial intelligence|openai|chatgpt|llm|generative ai|nvidia|anthropic|sam altman|machine learning|deep learning|ai startup|ai agent|gemini|claude)\b", re.I),
}
TOPIC_KEYWORDS = [
    ("Crypto", re.compile(r"\b(bitcoin|btc|ethereum|ether|crypto|cryptocurrency|stablecoin|binance|coinbase|solana|dogecoin|token)\b", re.I)),
    ("Commodities", re.compile(r"\b(crude|brent|oil prices?|opec|gold|silver|copper|natural gas|lng|wheat|commodit)", re.I)),
    ("IPO", re.compile(r"\b(ipo|listing|anchor investors?|grey market|gmp|public offer)\b", re.I)),
    ("Economy", re.compile(r"\b(inflation|gdp|rbi|central bank|interest rates?|rate (cut|hike)|fed|federal reserve|ecb|tariffs?|unemployment|jobs report|economy|economic|fiscal|budget|cpi|recession|bond yields?|treasury)\b", re.I)),
    ("Markets", re.compile(r"\b(stocks?|shares|nifty|sensex|s&p|nasdaq|dow|wall street|equities|equity|rally|sell-?off|market(s)?|index|futures|hang seng|nikkei|ftse)\b", re.I)),
    ("Business", re.compile(r"\b(earnings|revenue|profit|quarterly|ceo|cfo|merger|acquisition|acquires?|layoffs?|job cuts|startup|funding|valuation|bankruptcy|lawsuit|antitrust)\b", re.I)),
    ("Tech", re.compile(r"\b(apple|google|microsoft|meta|amazon|tesla|spacex|semiconductor|chip|chips|software|cyber|smartphone|iphone|android|app)\b", re.I)),
]
_TAG = re.compile(r"<[^>]*>?")
_LEADING_TAG = re.compile(r"^\s*/?[a-z0-9]{1,6}>\s*", re.I)
_HASH = re.compile(r"#(\w+)\s*$")
_GN_SUFFIX = re.compile(r"\s*-\s*[A-Z][A-Za-z\s&'.]+$")


def feed_configs() -> list[dict[str, str]]:
    return [{"id": feed["id"], "name": feed["name"], "category": feed["category"], "color": feed["color"]} for feed in FEEDS]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def classify_generic(title: str) -> str | None:
    for name, pattern in TOPIC_KEYWORDS:
        if pattern.search(title):
            return name
    return None


def extract_category(title: str, link: str, feed_category: str) -> str:
    hashed = _HASH.search(title)
    if hashed:
        word = hashed.group(1)
        return word[:1].upper() + word[1:]
    if GEO_KEYWORDS["MiddleEast"].search(title):
        return "MiddleEast"
    if GEO_KEYWORDS["Defense"].search(title):
        return "Defense"
    if GEO_KEYWORDS["Geopolitics"].search(title):
        return "Geopolitics"
    if GEO_KEYWORDS["AI"].search(title):
        return "AI"
    if feed_category in {"World", "Geopolitics", "MiddleEast", "Defense", "Global"} and GEO_KEYWORDS["War"].search(title):
        return "Geopolitics"
    url = link.lower()
    if "/market/stock-market" in url:
        return "Stocks"
    if "/market/ipo" in url:
        return "IPO"
    if "/market/commodit" in url:
        return "Commodities"
    if "/market/cryptocurrency" in url:
        return "Crypto"
    if "/market/forex" in url:
        return "Forex"
    if "/companies" in url:
        return "Corporate"
    if "/money" in url:
        return "Money"
    if "/economy" in url:
        return "Economy"
    if "/middle-east" in url or "/middleeast" in url:
        return "MiddleEast"
    if "/defense" in url or "/defence" in url or "/military" in url:
        return "Defense"
    if not feed_category or feed_category in GENERIC_CATEGORIES:
        return classify_generic(title) or feed_category or "General"
    return feed_category


def clean_description(raw: str) -> str:
    out = html.unescape(raw or "")
    out = _TAG.sub(" ", out)
    out = _LEADING_TAG.sub("", out)
    out = html.unescape(out)
    out = re.sub(r"\s+", " ", out).strip()
    return out[:300]


def clean_title(raw: str) -> str:
    cleaned = html.unescape(raw or "")
    cleaned = _HASH.sub("", cleaned).strip()
    cleaned = _GN_SUFFIX.sub("", cleaned).strip()
    return cleaned


def _parse_date(raw: str) -> datetime:
    text = (raw or "").strip()
    if not text:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        try:
            from email.utils import parsedate_to_datetime

            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            parsed = None
    if parsed is None:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed.timestamp() * 1000 > datetime.now(timezone.utc).timestamp() * 1000 + 60_000:
        return datetime.now(timezone.utc)
    return parsed


def _child_map(el: ET.Element) -> dict[str, list[ET.Element]]:
    grouped: dict[str, list[ET.Element]] = {}
    for child in list(el):
        grouped.setdefault(_local(child.tag), []).append(child)
    return grouped


def _link_of(grouped: dict[str, list[ET.Element]]) -> str:
    links = grouped.get("link") or []
    for link in links:
        href = link.attrib.get("href")
        rel = link.attrib.get("rel")
        if href and rel in (None, "", "alternate"):
            return html.unescape(href)
    for link in links:
        if link.attrib.get("href"):
            return html.unescape(link.attrib["href"])
        text = _text(link)
        if text:
            return html.unescape(text)
    return ""


def _image_of(grouped: dict[str, list[ET.Element]]) -> str | None:
    for name in ("content", "thumbnail"):
        for el in grouped.get(name) or []:
            url = el.attrib.get("url")
            if url:
                return html.unescape(url)
    for el in grouped.get("enclosure") or []:
        url = el.attrib.get("url")
        if url:
            return html.unescape(url)
    return None


def parse_feed_xml(xml: str, feed: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        logger.warning("RSS parse failed for %s: %s", feed["id"], exc)
        return []
    items = [el for el in root.iter() if _local(el.tag) in {"item", "entry"}]
    parsed: list[dict[str, Any]] = []
    for el in items:
        grouped = _child_map(el)
        title_raw = _text((grouped.get("title") or [None])[0])
        title = clean_title(title_raw)
        if not title:
            continue
        description = clean_description(
            _text((grouped.get("description") or grouped.get("summary") or grouped.get("content") or [None])[0])
        )
        link = _link_of(grouped)
        if not link:
            continue
        date_raw = _text((grouped.get("pubDate") or grouped.get("published") or grouped.get("updated") or [None])[0])
        published = _parse_date(date_raw)
        source_els = grouped.get("source") or []
        source_name = _text(source_els[0]) if source_els else ""
        category = extract_category(title_raw, link, str(feed["category"]))
        parsed.append(
            {
                "link": link,
                "title": title,
                "description": description,
                "published_at": int(published.timestamp() * 1000),
                "image": _image_of(grouped),
                "category": category,
                "companies": match_companies(f"{title} {description}"),
                "source_id": feed["id"],
                "source_name": source_name or feed["name"],
                "source_color": feed["color"],
            }
        )
    return parsed


async def _fetch_url(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url, headers=FETCH_HEADERS, allow_redirects=True) as response:
        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status}")
        return await response.text(errors="replace")


async def fetch_feed(session: aiohttp.ClientSession, feed: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        xml = await _fetch_url(session, feed["url"])
        return parse_feed_xml(xml, feed)
    except Exception as exc:
        fallback = feed.get("fallback_url")
        if not fallback:
            logger.info("Feed %s failed: %s", feed["id"], exc)
            return []
        logger.info("Feed %s primary failed (%s), using fallback", feed["id"], exc)
        try:
            xml = await _fetch_url(session, fallback)
            return parse_feed_xml(xml, feed)
        except Exception as fallback_exc:
            logger.info("Feed %s fallback failed: %s", feed["id"], fallback_exc)
            return []
