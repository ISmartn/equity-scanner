"""Morning context loaded once: prior day, average volume, pivots, and yesterday's futures OI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from ...db.store import TimelineStore, get_store
from .universe import UniverseSymbol

_PIVOT_KEYS = ("pivot_high", "pivot_high_20d", "pivot")


@dataclass
class SymbolContext:
    symbol: str
    company_name: str | None
    sector: str | None
    cash_key: str
    future_key: str | None
    future_expiry: str | None
    avg_volume_20: float | None = None
    prior_high: float | None = None
    prior_low: float | None = None
    prior_close: float | None = None
    prior_date: str | None = None
    sma20: float | None = None
    high_20: float | None = None
    low_20: float | None = None
    trend_20_pct: float | None = None
    return_5d_pct: float | None = None
    history_bars: int = 0
    scanner_score: float | None = None
    scanner_pattern: str | None = None
    scanner_pivot: float | None = None
    scanner_trade_date: str | None = None
    myb_score: float | None = None
    myb_level: float | None = None
    myb_status: str | None = None
    myb_trade_date: str | None = None
    seeded_poi: float | None = None
    seeded_poi_date: str | None = None
    kind: str = "equity"
    segment: str = "fno"
    atr_pct: float | None = None
    efficiency_20: float | None = None
    days_to_expiry: int | None = None

    @property
    def on_last_scan(self) -> bool:
        return self.scanner_score is not None or self.myb_score is not None


def extract_pivot(details: Any) -> float | None:
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except json.JSONDecodeError:
            return None
    if not isinstance(details, dict):
        return None
    for key in _PIVOT_KEYS:
        value = details.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) > 0:
            return float(value)
    return None


def _best_pattern(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    with_pivot = [row for row in rows if extract_pivot(row.get("details_json")) is not None]
    pool = with_pivot or rows
    return max(pool, key=lambda row: float(row.get("score") or 0))


def _best_myb(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return max(rows, key=lambda row: float(row.get("score") or 0))


def load_context(
    universe: list[UniverseSymbol],
    *,
    before_date: str,
    store: TimelineStore | None = None,
) -> dict[str, SymbolContext]:
    db = store or get_store()
    equity = [item for item in universe if item.kind != "index"]
    indexes = [item for item in universe if item.kind == "index"]
    candles = db.live_scan_candle_stats([item.cash_key for item in equity], before_date)
    candles.update(db.live_scan_index_candle_stats([item.cash_key for item in indexes], before_date))
    poi_rows = db.latest_futures_oi([item.symbol for item in universe if item.future_key], before_date)

    patterns: dict[str, list[dict[str, Any]]] = {}
    for row in db.latest_scan_pattern_rows():
        patterns.setdefault(str(row["ticker"]), []).append(row)
    myb: dict[str, list[dict[str, Any]]] = {}
    for row in db.latest_scan_myb_rows():
        myb.setdefault(str(row["ticker"]), []).append(row)

    contexts: dict[str, SymbolContext] = {}
    for item in universe:
        candle = candles.get(item.cash_key) or {}
        pattern = _best_pattern(patterns.get(item.symbol, []))
        breakout = _best_myb(myb.get(item.symbol, []))
        poi = poi_rows.get(item.symbol)
        if poi and poi.get("instrument_key") and poi["instrument_key"] != item.future_key:
            # Yesterday's row is the expired contract. Its OI says nothing about the
            # new front month; the session-open print is the honest baseline.
            poi = None
        contexts[item.symbol] = SymbolContext(
            symbol=item.symbol,
            company_name=item.company_name,
            sector=item.sector,
            cash_key=item.cash_key,
            future_key=item.future_key,
            future_expiry=item.future_expiry,
            avg_volume_20=_float_or_none(candle.get("avg_volume_20")),
            prior_high=_float_or_none(candle.get("prior_high")),
            prior_low=_float_or_none(candle.get("prior_low")),
            prior_close=_float_or_none(candle.get("prior_close")),
            prior_date=candle.get("prior_date"),
            sma20=_float_or_none(candle.get("sma20")),
            high_20=_float_or_none(candle.get("high_20")),
            low_20=_float_or_none(candle.get("low_20")),
            trend_20_pct=_float_or_none(candle.get("trend_20_pct")),
            return_5d_pct=_float_or_none(candle.get("return_5d_pct")),
            history_bars=int(candle.get("history_bars") or 0),
            scanner_score=_float_or_none(pattern.get("score")) if pattern else None,
            scanner_pattern=str(pattern["pattern_type"]) if pattern else None,
            scanner_pivot=extract_pivot(pattern.get("details_json")) if pattern else None,
            scanner_trade_date=str(pattern["trade_date"]) if pattern else None,
            myb_score=_float_or_none(breakout.get("score")) if breakout else None,
            myb_level=_float_or_none(breakout.get("prior_high")) if breakout else None,
            myb_status=str(breakout["status"]) if breakout else None,
            myb_trade_date=str(breakout["trade_date"]) if breakout else None,
            seeded_poi=_float_or_none(poi.get("oi")) if poi else None,
            seeded_poi_date=str(poi["trade_date"]) if poi else None,
            kind=item.kind,
            segment=item.segment,
            atr_pct=_float_or_none(candle.get("atr_pct")),
            efficiency_20=_float_or_none(candle.get("efficiency_20")),
            days_to_expiry=_days_between(before_date, item.future_expiry),
        )
    return contexts


def _days_between(start: str, end: str | None) -> int | None:
    if not end:
        return None
    try:
        return (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days
    except ValueError:
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
