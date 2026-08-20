"""Universe for Elliott Wave lab — local DB only (no Upstox candle fetches)."""

from __future__ import annotations

from typing import Any

from ....db.store import TimelineStore

NIFTY_KEY = "NSE_INDEX|Nifty 50"
NIFTY_TICKER = "NIFTY"
LOOKBACK_BARS = 520  # ~2y trading days when available
MIN_BARS = 120


def equity_instrument_key(ticker: str) -> str:
    return f"NSE_EQ|{ticker.upper()}"


def resolve_fno_tickers(store: TimelineStore) -> list[str]:
    """
    Prefer distinct underlyings already present in local derivative_snapshots
    (DB-only). Fall back to cached F&O symbol list intersected with profiles
    that have daily candles.
    """
    with store.connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT UPPER(symbol) AS symbol
            FROM derivative_snapshots
            WHERE symbol IS NOT NULL AND TRIM(symbol) != ''
            ORDER BY 1
            """
        ).fetchall()
    tickers = [str(r["symbol"]).upper() for r in rows]

    if not tickers:
        try:
            from ...scanner.fo_sync import load_fno_symbol_set_sync

            fno = load_fno_symbol_set_sync()
        except Exception:
            fno = set()
        if fno:
            with store.connection() as conn:
                ph = ",".join("?" for _ in fno)
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT UPPER(ticker) AS ticker
                    FROM security_profiles
                    WHERE UPPER(ticker) IN ({ph})
                    ORDER BY 1
                    """,
                    list(fno),
                ).fetchall()
            tickers = [str(r["ticker"]).upper() for r in rows]

    return tickers


def universe_items(store: TimelineStore) -> list[dict[str, Any]]:
    """Return [{ticker, instrument_key, kind}] including Nifty 50 benchmark."""
    items = [
        {
            "ticker": NIFTY_TICKER,
            "instrument_key": NIFTY_KEY,
            "kind": "index",
        }
    ]
    for t in resolve_fno_tickers(store):
        items.append(
            {
                "ticker": t,
                "instrument_key": equity_instrument_key(t),
                "kind": "equity",
            }
        )
    return items
