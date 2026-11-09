"""Universe for Grimes lab — all timeline equities with enough daily bars + Nifty."""

from __future__ import annotations

from typing import Any

from ....db.store import TimelineStore

NIFTY_KEY = "NSE_INDEX|Nifty 50"
NIFTY_TICKER = "NIFTY"
LOOKBACK_BARS = 520  # ~2y trading days when available
MIN_BARS = 80  # Grimes engine minimum (regime + patterns)


def equity_instrument_key(ticker: str) -> str:
    return f"NSE_EQ|{ticker.upper()}"


def universe_items(store: TimelineStore) -> list[dict[str, Any]]:
    """
    Every NSE equity with >= MIN_BARS daily candles in the local DB, plus Nifty 50.
    Unlike Elliott Wave lab, this is not limited to F&O underlyings.
    """
    items: list[dict[str, Any]] = [
        {
            "ticker": NIFTY_TICKER,
            "instrument_key": NIFTY_KEY,
            "kind": "index",
            "company_name": "Nifty 50 Index",
        }
    ]
    rows = store.list_scan_eligible_tickers(min_bars=MIN_BARS)
    seen: set[str] = set()
    for row in rows:
        ticker = str(row.get("ticker") or "").upper().strip()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        items.append(
            {
                "ticker": ticker,
                "instrument_key": equity_instrument_key(ticker),
                "kind": "equity",
                "company_name": row.get("company_name"),
            }
        )
    return items
