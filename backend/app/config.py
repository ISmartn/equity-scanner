from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT_DIR / ".env")

PORT = int(os.getenv("BACKEND_PORT", "8000"))
UPSTOX_BASE = "https://api.upstox.com"
NSE_BASE = "https://www.nseindia.com"
NSE_ARCHIVE_BASE = "https://nsearchives.nseindia.com/content/indices"
NSE_EQUITY_LIST_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_FO_MKTLOTS_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"

# NSE listing symbol → internal/Upstox ticker used in DB & profiles.
SYMBOL_ALIASES: dict[str, str] = {
    "M&M": "M_M",
    "BAJAJ-AUTO": "BAJAJ_AUTO",
}

# Reverse map for NSE APIs that reject underscored tickers.
NSE_SYMBOL_BY_INTERNAL: dict[str, str] = {v: k for k, v in SYMBOL_ALIASES.items()}

INDEX_INSTRUMENT_KEYS: dict[str, str] = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
}

EQUITY_INSTRUMENT_KEYS: dict[str, str] = {
    "RELIANCE": "NSE_EQ|INE002A01018",
    "TCS": "NSE_EQ|INE467B01029",
    "HDFCBANK": "NSE_EQ|INE040A01034",
    "INFY": "NSE_EQ|INE009A01021",
    "ICICIBANK": "NSE_EQ|INE090A01021",
    "HINDUNILVR": "NSE_EQ|INE030A01027",
    "ITC": "NSE_EQ|INE154A01025",
    "SBIN": "NSE_EQ|INE062A01020",
    "BHARTIARTL": "NSE_EQ|INE397D01024",
    "KOTAKBANK": "NSE_EQ|INE237A01036",
    "LT": "NSE_EQ|INE018A01030",
    "AXISBANK": "NSE_EQ|INE238A01034",
    "ASIANPAINT": "NSE_EQ|INE021A01026",
    "MARUTI": "NSE_EQ|INE585B01010",
    "TITAN": "NSE_EQ|INE280A01028",
    "SUNPHARMA": "NSE_EQ|INE044A01036",
    "BAJFINANCE": "NSE_EQ|INE296A01032",
    "BAJAJFINSV": "NSE_EQ|INE918I01026",
    "WIPRO": "NSE_EQ|INE075A01022",
    "HCLTECH": "NSE_EQ|INE860A01027",
    "TATAMOTORS": "NSE_EQ|INE155A01022",
    "TATASTEEL": "NSE_EQ|INE081A01020",
    "NTPC": "NSE_EQ|INE733E01010",
    "POWERGRID": "NSE_EQ|INE752E01010",
    "ONGC": "NSE_EQ|INE213A01029",
    "JSWSTEEL": "NSE_EQ|INE019A01038",
    "M_M": "NSE_EQ|INE101A01026",
    "ADANIENT": "NSE_EQ|INE423A01024",
    "ADANIPORTS": "NSE_EQ|INE742F01042",
    "ULTRACEMCO": "NSE_EQ|INE481G01011",
    "TECHM": "NSE_EQ|INE669C01036",
    "INDUSINDBK": "NSE_EQ|INE095A01012",
    "DRREDDY": "NSE_EQ|INE089A01031",
    "CIPLA": "NSE_EQ|INE059A01026",
    "EICHERMOT": "NSE_EQ|INE066A01021",
    "DIVISLAB": "NSE_EQ|INE361B01024",
    "BPCL": "NSE_EQ|INE029A01011",
    "COALINDIA": "NSE_EQ|INE522F01014",
    "GRASIM": "NSE_EQ|INE047A01021",
    "APOLLOHOSP": "NSE_EQ|INE437A01024",
    "HEROMOTOCO": "NSE_EQ|INE158A01026",
    "TATACONSUM": "NSE_EQ|INE192A01025",
    "SBILIFE": "NSE_EQ|INE123W01016",
    "BRITANNIA": "NSE_EQ|INE216A01030",
    "NESTLEIND": "NSE_EQ|INE239A01024",
    "BAJAJ_AUTO": "NSE_EQ|INE917I01010",
    "HDFCLIFE": "NSE_EQ|INE795G01014",
    "VEDL": "NSE_EQ|INE205A01025",
    "HINDALCO": "NSE_EQ|INE038A01020",
    "SHRIRAMFIN": "NSE_EQ|INE721A01047",
    "TRENT": "NSE_EQ|INE849A01020",
    "BEL": "NSE_EQ|INE263A01024",
    "JIOFIN": "NSE_EQ|INE758E01017",
    "ETERNAL": "NSE_EQ|INE758T01015",
}

NIFTY50_FALLBACK: list[str] = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC", "SBIN",
    "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "TITAN",
    "SUNPHARMA", "BAJFINANCE", "BAJAJFINSV", "WIPRO", "HCLTECH", "TATAMOTORS",
    "TATASTEEL", "NTPC", "POWERGRID", "ONGC", "JSWSTEEL", "M_M", "ADANIENT",
    "ADANIPORTS", "ULTRACEMCO", "TECHM", "INDUSINDBK", "DRREDDY", "CIPLA",
    "EICHERMOT", "DIVISLAB", "BPCL", "COALINDIA", "GRASIM", "APOLLOHOSP",
    "HEROMOTOCO", "TATACONSUM", "SBILIFE", "BRITANNIA", "NESTLEIND", "BAJAJ_AUTO",
    "HDFCLIFE", "VEDL", "HINDALCO", "SHRIRAMFIN",
]


# Populated from NSE equity master (symbol → ISIN) for Upstox instrument resolution.
EQUITY_ISIN_BY_SYMBOL: dict[str, str] = {}

# NSE listing series per symbol (EQ, BE, BZ, …).
EQUITY_SERIES_BY_SYMBOL: dict[str, str] = {}

# Search / watchlist instrument keys (symbol → NSE_EQ|ISIN).
DYNAMIC_INSTRUMENT_KEYS: dict[str, str] = {}


def normalize_symbol(symbol: str) -> str:
    """Map NSE listing symbols to internal tickers (e.g. M&M → M_M)."""
    upper = symbol.strip().upper()
    return SYMBOL_ALIASES.get(upper, upper)


def to_nse_symbol(symbol: str) -> str:
    """Map internal tickers to NSE listing symbols (e.g. M_M → M&M)."""
    upper = symbol.strip().upper()
    if upper in SYMBOL_ALIASES:
        return upper
    return NSE_SYMBOL_BY_INTERNAL.get(upper, upper)


def register_instrument_key(symbol: str, instrument_key: str) -> None:
    normalized = normalize_symbol(symbol)
    DYNAMIC_INSTRUMENT_KEYS[normalized] = instrument_key


def _strip_exchange_suffix(symbol: str) -> str:
    upper = symbol.strip().upper()
    for suffix in (".NS", ".NSE", ".BSE", "-EQ", ":EQ"):
        if upper.endswith(suffix):
            return upper[: -len(suffix)]
    return upper


def resolve_instrument_key(symbol: str) -> str | None:
    normalized = normalize_symbol(_strip_exchange_suffix(symbol))
    static = INDEX_INSTRUMENT_KEYS.get(normalized) or EQUITY_INSTRUMENT_KEYS.get(normalized)
    if static:
        return static
    dynamic = DYNAMIC_INSTRUMENT_KEYS.get(normalized)
    if dynamic:
        return dynamic
    isin = EQUITY_ISIN_BY_SYMBOL.get(normalized)
    if isin:
        return f"NSE_EQ|{isin}"

    # Persisted security profiles cover the full mainboard (beyond the static Nifty map).
    try:
        from .db.store import get_store

        profile = get_store().get_profile_by_ticker(normalized)
    except Exception:
        profile = None
    if profile:
        token = profile.get("instrument_token")
        if isinstance(token, str) and token.strip():
            key = token.strip()
            register_instrument_key(normalized, key)
            return key
        isin_db = profile.get("isin")
        if isinstance(isin_db, str) and isin_db.strip():
            key = f"NSE_EQ|{isin_db.strip()}"
            register_instrument_key(normalized, key)
            return key
    return None


def warm_instrument_keys_from_profiles() -> int:
    """Load instrument keys from SQLite into the in-memory resolver cache."""
    try:
        from .db.store import get_store

        profiles = get_store().list_profiles_with_isin()
    except Exception:
        return 0
    loaded = 0
    for profile in profiles:
        ticker = profile.get("ticker")
        token = profile.get("instrument_token")
        if not isinstance(ticker, str) or not ticker.strip():
            continue
        if isinstance(token, str) and token.strip():
            register_instrument_key(ticker, token.strip())
            loaded += 1
            continue
        isin = profile.get("isin")
        if isinstance(isin, str) and isin.strip():
            register_instrument_key(ticker, f"NSE_EQ|{isin.strip()}")
            loaded += 1
    return loaded


def get_access_token(custom_token: str | None = None) -> str | None:
    return custom_token or os.getenv("UPSTOX_ACCESS_TOKEN")


def get_default_forecast_model() -> str:
    return os.getenv("FORECAST_MODEL", "timesfm-2.5").strip().lower()

