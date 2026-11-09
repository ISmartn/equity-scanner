"""Read Nifty 50 and Sensex from the live constituent stocks.

Both indexes are free-float weighted, so a large name moves the index more than
a small one. Weights here are relative free-float ranks. They are scaled to the
names actually streaming, which keeps the heavyweights ahead of the tail when
the official monthly weight file is not loaded.
"""

from __future__ import annotations

from typing import Any

import aiohttp

from ...config import NIFTY50_FALLBACK, normalize_symbol
from ..nse_client import fetch_nifty50_symbols

# Relative free-float weight. Unknown constituents use _DEFAULT_WEIGHT.
NIFTY_WEIGHTS: dict[str, float] = {
    "HDFCBANK": 12.5,
    "RELIANCE": 8.4,
    "ICICIBANK": 8.0,
    "BHARTIARTL": 4.6,
    "INFY": 4.8,
    "TCS": 4.0,
    "ITC": 3.6,
    "LT": 4.0,
    "SBIN": 3.4,
    "AXISBANK": 3.1,
    "KOTAKBANK": 2.6,
    "BAJFINANCE": 2.4,
    "HINDUNILVR": 2.3,
    "M_M": 2.5,
    "SUNPHARMA": 1.8,
    "MARUTI": 1.7,
    "HCLTECH": 1.6,
    "TITAN": 1.5,
    "NTPC": 1.5,
    "ULTRACEMCO": 1.3,
    "POWERGRID": 1.2,
    "BAJAJFINSV": 1.1,
    "TATASTEEL": 1.1,
    "ASIANPAINT": 1.1,
    "NESTLEIND": 1.0,
    "ADANIENT": 1.0,
    "ONGC": 0.9,
    "COALINDIA": 0.9,
    "BEL": 1.1,
    "TRENT": 1.0,
    "JIOFIN": 0.9,
    "ETERNAL": 0.8,
    "HINDALCO": 0.8,
    "ADANIPORTS": 0.8,
    "GRASIM": 0.8,
    "JSWSTEEL": 0.8,
    "TECHM": 0.7,
    "WIPRO": 0.7,
    "CIPLA": 0.7,
    "SHRIRAMFIN": 0.7,
    "SBILIFE": 0.7,
    "HDFCLIFE": 0.7,
    "EICHERMOT": 0.7,
    "DRREDDY": 0.7,
    "APOLLOHOSP": 0.7,
    "BAJAJ_AUTO": 0.7,
    "BRITANNIA": 0.6,
    "HEROMOTOCO": 0.6,
    "INDUSINDBK": 0.6,
    "BPCL": 0.6,
    "TATACONSUM": 0.6,
    "DIVISLAB": 0.6,
    "VEDL": 0.5,
}

SENSEX_MEMBERS: tuple[str, ...] = (
    "RELIANCE",
    "HDFCBANK",
    "BHARTIARTL",
    "TCS",
    "ICICIBANK",
    "SBIN",
    "INFY",
    "BAJFINANCE",
    "HINDUNILVR",
    "ITC",
    "LT",
    "HCLTECH",
    "KOTAKBANK",
    "AXISBANK",
    "MARUTI",
    "SUNPHARMA",
    "M_M",
    "ULTRACEMCO",
    "NTPC",
    "TITAN",
    "BAJAJFINSV",
    "POWERGRID",
    "TATASTEEL",
    "ASIANPAINT",
    "NESTLEIND",
    "TECHM",
    "INDUSINDBK",
    "ADANIPORTS",
    "HINDALCO",
    "BEL",
)

_DEFAULT_WEIGHT = 0.7
_FLAT_BAND = 0.05
_FLAT_INDEX = 0.08
_BROAD_SHARE = 0.60
_NARROW_SHARE = 0.50
_DRIVER_LIMIT = 3

_READS = {
    "broad_rise": "The rise is broad. Most constituents are up with the heavyweights.",
    "narrow_rise": "The index is up because the heavyweights are up. Most constituents are not.",
    "rise": "The index is up, and the constituents are split.",
    "broad_drop": "The drop is broad. Most constituents are down with the heavyweights.",
    "narrow_drop": "The index is down because the heavyweights are down. Most constituents are not.",
    "drop": "The index is down, and the constituents are split.",
    "flat": "Constituents are mixed and the weighted move is flat.",
    "waiting": "Waiting for constituent prices.",
}

_TONE_LABELS = {
    "broad_rise": "Broad rise",
    "narrow_rise": "Narrow rise",
    "rise": "Rise",
    "broad_drop": "Broad drop",
    "narrow_drop": "Narrow drop",
    "drop": "Drop",
    "flat": "Flat",
    "waiting": "Waiting",
}


def default_baskets() -> dict[str, list[str]]:
    return {
        "NIFTY": [normalize_symbol(symbol) for symbol in NIFTY50_FALLBACK],
        "SENSEX": list(SENSEX_MEMBERS),
    }


async def load_nifty_members() -> list[str]:
    async with aiohttp.ClientSession() as session:
        symbols = await fetch_nifty50_symbols(session)
    members = [normalize_symbol(symbol) for symbol in symbols if str(symbol).strip()]
    return members or default_baskets()["NIFTY"]


def _change_pct(quote: dict[str, Any]) -> float | None:
    ltp = float(quote.get("ltp") or 0)
    prev = float(quote.get("prev_close") or 0)
    if ltp <= 0 or prev <= 0:
        return None
    return (ltp - prev) / prev * 100.0


def _tone(weighted: float, up_share: float, down_share: float) -> str:
    if abs(weighted) < _FLAT_INDEX:
        return "flat"
    if weighted > 0:
        if up_share >= _BROAD_SHARE:
            return "broad_rise"
        if up_share < _NARROW_SHARE:
            return "narrow_rise"
        return "rise"
    if down_share >= _BROAD_SHARE:
        return "broad_drop"
    if down_share < _NARROW_SHARE:
        return "narrow_drop"
    return "drop"


def _drivers(rows: list[dict[str, Any]], *, positive: bool) -> list[dict[str, Any]]:
    pool = [row for row in rows if (row["contribution"] > 0 if positive else row["contribution"] < 0)]
    pool.sort(key=lambda row: row["contribution"], reverse=positive)
    return [
        {
            "symbol": row["symbol"],
            "change_pct": round(row["change_pct"], 2),
            "contribution": round(row["contribution"], 3),
        }
        for row in pool[:_DRIVER_LIMIT]
    ]


def read_index(symbol: str, members: list[str], quotes_by_symbol: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Breadth plus the weighted move of one index from the stocks in the live book."""
    rows: list[dict[str, Any]] = []
    for member in dict.fromkeys(members):
        quote = quotes_by_symbol.get(member)
        if quote is None or quote.get("kind") == "index":
            continue
        change = _change_pct(quote)
        if change is None:
            continue
        rows.append(
            {
                "symbol": member,
                "change_pct": change,
                "weight": float(NIFTY_WEIGHTS.get(member, _DEFAULT_WEIGHT)),
            }
        )

    base = {
        "breadth_up": 0,
        "breadth_down": 0,
        "breadth_flat": 0,
        "breadth_seen": 0,
        "breadth_total": len(set(members)),
        "weighted_change_pct": None,
        "tone": "waiting",
        "tone_label": _TONE_LABELS["waiting"],
        "read": _READS["waiting"],
        "leaders": [],
        "drags": [],
    }
    if not rows:
        return base

    weight_sum = sum(row["weight"] for row in rows)
    up = down = flat = 0
    weighted = 0.0
    for row in rows:
        share = row["weight"] / weight_sum
        row["contribution"] = share * row["change_pct"]
        weighted += row["contribution"]
        if row["change_pct"] > _FLAT_BAND:
            up += 1
        elif row["change_pct"] < -_FLAT_BAND:
            down += 1
        else:
            flat += 1

    seen = len(rows)
    tone = _tone(weighted, up / seen, down / seen)
    base.update(
        {
            "breadth_up": up,
            "breadth_down": down,
            "breadth_flat": flat,
            "breadth_seen": seen,
            "weighted_change_pct": round(weighted, 2),
            "tone": tone,
            "tone_label": _TONE_LABELS[tone],
            "read": _READS[tone],
            "leaders": _drivers(rows, positive=True),
            "drags": _drivers(rows, positive=False),
        }
    )
    return base


def index_reads(quotes: list[dict[str, Any]], baskets: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
    by_symbol = {str(quote.get("symbol")): quote for quote in quotes if quote.get("symbol")}
    return {
        symbol: read_index(symbol, members, by_symbol)
        for symbol, members in baskets.items()
        if members
    }
