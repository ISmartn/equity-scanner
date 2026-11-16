"""The market file (schema 1), ported from the standalone Order Flow server (server/marketFile.mjs).

Each underlying's option chain at its nearest live expiry becomes one series,
in the compact form the page reads. Each row is an 18-field list:

    [strike, side (0 call | 1 put), ltp, prevClose, oi, prevOi, volume, prevVolume,
     avgPrice, iv, bid, ask, bidQty, askQty, dayHigh, dayLow, lastTradeAt, delta]

Input is a chain in rupees and units: ``{expiry, at, spot, prevClose, atm,
strikes: [{strike, call?, put?}]}``, where a leg is a dict with the keys read below.
"""

from __future__ import annotations

import math
from typing import Any

from .session import round_half_up


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _num(value: Any) -> float:
    return float(value) if _finite(value) else 0.0


def _or_null(value: Any) -> float | None:
    return float(value) if _finite(value) else None


def _pos_or_null(value: Any) -> float | None:
    return float(value) if _finite(value) and value > 0 else None


def _round2(value: float) -> float:
    return math.floor(value * 100 + 0.5) / 100


def leg_row(strike: float, side: int, leg: dict[str, Any], keep_idle: bool = False) -> list[Any] | None:
    """One side of one strike as a row, or None when it has neither OI nor volume (unless kept idle)."""
    oi = _num(leg.get("oi"))
    volume = _num(leg.get("volume"))
    if not keep_idle and not (oi > 0) and not (volume > 0):
        return None
    ltp = _num(leg.get("ltp"))
    iv = leg.get("iv")
    return [
        strike, side, _round2(ltp), _pos_or_null(leg.get("prevClose")), oi, _or_null(leg.get("prevOi")),
        volume, _or_null(leg.get("prevVolume")),
        _round2(_num(leg.get("avgPrice")) or ltp), _round2(float(iv)) if _finite(iv) else None,
        _round2(_num(leg.get("bid"))), _round2(_num(leg.get("ask"))),
        _num(leg.get("bidQty")), _num(leg.get("askQty")),
        _pos_or_null(leg.get("dayHigh")), _pos_or_null(leg.get("dayLow")),
        _or_null(leg.get("lastTradeAt")), _or_null(leg.get("delta")),
    ]


def encode_series(underlying: dict[str, Any], chain: dict[str, Any], read_at: float) -> dict[str, Any] | None:
    """One chain as one series, or None when it has no priced spot."""
    spot = _num(chain.get("spot"))
    if not spot > 0:
        return None
    rows: list[list[Any]] = []
    idle: list[list[Any]] = []
    ladder: list[float] = []
    for item in chain.get("strikes") or []:
        strike = _num(item.get("strike"))
        if not strike > 0:
            continue
        listed = False
        for side, leg in ((0, item.get("call")), (1, item.get("put"))):
            if leg is None:
                continue
            listed = True
            encoded = leg_row(strike, side, leg)
            if encoded is not None:
                rows.append(encoded)
            else:
                idle.append(leg_row(strike, side, leg, keep_idle=True))
        if listed:
            ladder.append(strike)
    ladder.sort()
    atm = _pos_or_null(chain.get("atm"))
    if atm is None and ladder:
        atm = min(ladder, key=lambda k: abs(k - spot))
    rows.sort(key=lambda r: (r[0], r[1]))
    idle.sort(key=lambda r: (r[0], r[1]))
    return {
        "s": underlying["symbol"],
        "k": "index" if underlying.get("kind") == "index" else "stock",
        "e": chain.get("expiry"),
        "lot": underlying.get("lot"),
        "ls": "catalogue",
        "t": round_half_up(read_at),
        "tp": _pos_or_null(chain.get("at")),
        "sp": _round2(spot),
        "pc": _pos_or_null(chain.get("prevClose")),
        "atm": atm,
        "r": rows,
        "ks": ladder,
        "z": idle,
    }


def market_file(*, at: float, date: str, series: list[dict[str, Any]], minutes: list[Any], ladders: dict[str, list[str]]) -> dict[str, Any]:
    """The whole file: every series read this tick, the stored minutes, and each symbol's live expiries."""
    return {"schema": 1, "t": round_half_up(at), "date": date, "series": series, "minutes": minutes, "ladders": ladders}
