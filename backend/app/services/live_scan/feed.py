"""Decode one Upstox V3 full-mode market feed into the fields the live book stores.

Two decoders produce the same ``parsed`` dict:

* ``parse_market_tick`` reads the ``MessageToDict`` shape (tests, fallbacks).
* ``decode_frame`` reads the protobuf objects directly. ``MessageToDict`` walks
  every field through Python reflection and is the dominant ingest cost for a
  400-key full-mode frame, so the socket path never uses it.
"""

from __future__ import annotations

from typing import Any

_DAY_INTERVALS = {"1d", "d", "day"}
_MINUTE_INTERVALS = {"i1", "1m", "1min", "1"}


def _dig(mapping: dict[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _positive(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0 or number != number:
        return None
    return number


def _non_negative_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return number


def _market_payload(feed: dict[str, Any]) -> dict[str, Any] | None:
    market = (
        _dig(feed, "fullFeed", "marketFF")
        or _dig(feed, "fullFeed", "marketFf")
        or _dig(feed, "full_feed", "marketFF")
        or _dig(feed, "full_feed", "market_ff")
        or _dig(feed, "fullFeed", "indexFF")
        or _dig(feed, "fullFeed", "indexFf")
        or _dig(feed, "full_feed", "indexFF")
        or _dig(feed, "full_feed", "index_ff")
    )
    if isinstance(market, dict):
        return market
    if any(key in feed for key in ("ltpc", "atp", "vtt", "oi", "marketOHLC", "marketOhlc")):
        return feed
    return None


def _ohlc_bars(market: dict[str, Any]) -> list[dict[str, Any]]:
    root = market.get("marketOHLC") or market.get("marketOhlc") or market.get("market_ohlc")
    if not isinstance(root, dict):
        return []
    bars = root.get("ohlc")
    if not isinstance(bars, list):
        return []
    return [bar for bar in bars if isinstance(bar, dict)]


def _empty_parsed() -> dict[str, Any]:
    return {
        "ltp": None,
        "ltt": None,
        "ltq": None,
        "prev_close": None,
        "atp": None,
        "vtt": None,
        "oi": None,
        "bid": None,
        "ask": None,
        "day_open": None,
        "day_high": None,
        "day_low": None,
        "minute_volume": None,
    }


def parse_market_tick(feed: dict[str, Any]) -> dict[str, Any] | None:
    """Return LTP, ATP, day OHLC, cumulative volume, OI, top of book, and the latest 1-minute volume."""
    if not isinstance(feed, dict):
        return None
    market = _market_payload(feed)
    if market is None:
        return None

    ltpc = market.get("ltpc") if isinstance(market.get("ltpc"), dict) else {}
    parsed = _empty_parsed()
    parsed["ltp"] = _positive(ltpc.get("ltp"))
    parsed["ltt"] = _non_negative_int(ltpc.get("ltt")) or None
    parsed["ltq"] = _non_negative_int(ltpc.get("ltq"))
    parsed["prev_close"] = _positive(ltpc.get("cp"))
    parsed["atp"] = _positive(market.get("atp"))
    parsed["vtt"] = _non_negative_int(market.get("vtt"))
    parsed["oi"] = _positive(market.get("oi"))

    level = market.get("marketLevel")
    quotes = level.get("bidAskQuote") if isinstance(level, dict) else None
    if isinstance(quotes, list) and quotes and isinstance(quotes[0], dict):
        parsed["bid"] = _positive(quotes[0].get("bidP"))
        parsed["ask"] = _positive(quotes[0].get("askP"))

    for bar in _ohlc_bars(market):
        interval = str(bar.get("interval") or "").strip().lower()
        if interval in _DAY_INTERVALS:
            parsed["day_open"] = _positive(bar.get("open")) or parsed["day_open"]
            parsed["day_high"] = _positive(bar.get("high")) or parsed["day_high"]
            parsed["day_low"] = _positive(bar.get("low")) or parsed["day_low"]
            if parsed["ltp"] is None:
                parsed["ltp"] = _positive(bar.get("close"))
        elif interval in _MINUTE_INTERVALS:
            minute_volume = _non_negative_int(bar.get("vol") if "vol" in bar else bar.get("volume"))
            if minute_volume is not None:
                parsed["minute_volume"] = minute_volume

    if parsed["ltp"] is None and parsed["oi"] is None and parsed["vtt"] is None:
        return None
    return parsed


def iter_feed_items(message: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    feeds = message.get("feeds") if isinstance(message, dict) else None
    if not isinstance(feeds, dict):
        return []
    items: list[tuple[str, dict[str, Any]]] = []
    for key, feed in feeds.items():
        if isinstance(key, str) and isinstance(feed, dict):
            items.append((key, feed))
    return items


def _pos(value: float) -> float | None:
    return value if value > 0 and value == value else None


def _parse_market_proto(market: Any, *, has_depth: bool) -> dict[str, Any] | None:
    parsed = _empty_parsed()
    if market.HasField("ltpc"):
        ltpc = market.ltpc
        parsed["ltp"] = _pos(ltpc.ltp)
        parsed["ltt"] = int(ltpc.ltt) or None
        parsed["ltq"] = int(ltpc.ltq)
        parsed["prev_close"] = _pos(ltpc.cp)
    if has_depth:
        parsed["atp"] = _pos(market.atp)
        # proto3 scalars have no presence: a zero vtt means "not sent yet".
        parsed["vtt"] = int(market.vtt) if market.vtt > 0 else None
        parsed["oi"] = _pos(market.oi)
        if market.HasField("marketLevel") and len(market.marketLevel.bidAskQuote):
            top = market.marketLevel.bidAskQuote[0]
            parsed["bid"] = _pos(top.bidP)
            parsed["ask"] = _pos(top.askP)
    if market.HasField("marketOHLC"):
        for bar in market.marketOHLC.ohlc:
            interval = bar.interval.strip().lower()
            if interval in _DAY_INTERVALS:
                parsed["day_open"] = _pos(bar.open) or parsed["day_open"]
                parsed["day_high"] = _pos(bar.high) or parsed["day_high"]
                parsed["day_low"] = _pos(bar.low) or parsed["day_low"]
                if parsed["ltp"] is None:
                    parsed["ltp"] = _pos(bar.close)
            elif interval in _MINUTE_INTERVALS and bar.vol >= 0:
                parsed["minute_volume"] = int(bar.vol)
    if parsed["ltp"] is None and parsed["oi"] is None and parsed["vtt"] is None:
        return None
    return parsed


def parse_feed_proto(feed: Any) -> dict[str, Any] | None:
    """Same output as ``parse_market_tick`` for one protobuf ``Feed`` message."""
    if feed.HasField("fullFeed"):
        full = feed.fullFeed
        if full.HasField("marketFF"):
            return _parse_market_proto(full.marketFF, has_depth=True)
        if full.HasField("indexFF"):
            return _parse_market_proto(full.indexFF, has_depth=False)
        return None
    if feed.HasField("ltpc"):
        ltp = _pos(feed.ltpc.ltp)
        if ltp is None:
            return None
        parsed = _empty_parsed()
        parsed["ltp"] = ltp
        parsed["ltt"] = int(feed.ltpc.ltt) or None
        parsed["prev_close"] = _pos(feed.ltpc.cp)
        return parsed
    return None


_FEED_RESPONSE: Any = None


def _feed_response_type() -> Any:
    global _FEED_RESPONSE
    if _FEED_RESPONSE is None:
        from upstox_client.feeder.proto import MarketDataFeedV3_pb2

        _FEED_RESPONSE = MarketDataFeedV3_pb2.FeedResponse
    return _FEED_RESPONSE


def decode_frame(raw: bytes) -> tuple[int | None, list[tuple[str, dict[str, Any]]]]:
    """Decode one binary websocket frame into ``(exchange_ts_ms, [(key, parsed)])``."""
    message = _feed_response_type().FromString(raw)
    items: list[tuple[str, dict[str, Any]]] = []
    for key, feed in message.feeds.items():
        parsed = parse_feed_proto(feed)
        if parsed is not None:
            items.append((key, parsed))
    current_ts = int(message.currentTs) or None
    return current_ts, items
