"""Sector / thematic universe for rotation scanner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Category = Literal["Official", "Synthetic"]


@dataclass(frozen=True)
class SectorUniverseItem:
    name: str
    category: Category
    instrument_key: str | None = None
    """Upstox index key when Official; unused for Synthetic."""
    tickers: tuple[str, ...] = ()
    """Equity tickers used to build (or fall back) a synthetic series."""
    profile_sector: str | None = None
    """Optional security_profiles.sector label to expand constituents."""


BENCHMARK_KEY = "NSE_INDEX|Nifty 50"
BENCHMARK_NAME = "Nifty 50"

# Representative constituents when official index OHLC is not cached locally.
_OFFICIAL_FALLBACKS: dict[str, tuple[str, ...]] = {
    "Nifty Bank": (
        "HDFCBANK",
        "ICICIBANK",
        "SBIN",
        "KOTAKBANK",
        "AXISBANK",
        "INDUSINDBK",
        "BANKBARODA",
        "PNB",
        "IDFCFIRSTB",
        "FEDERALBNK",
    ),
    "Nifty IT": ("TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "PERSISTENT", "COFORGE", "MPHASIS", "LTTS"),
    "Nifty Auto": (
        "MARUTI",
        "TATAMOTORS",
        "M_M",
        "BAJAJ_AUTO",
        "HEROMOTOCO",
        "EICHERMOT",
        "TVSMOTOR",
        "ASHOKLEY",
        "BHARATFORG",
        "MOTHERSON",
    ),
    "Nifty FMCG": (
        "HINDUNILVR",
        "ITC",
        "NESTLEIND",
        "BRITANNIA",
        "TATACONSUM",
        "DABUR",
        "MARICO",
        "GODREJCP",
        "COLPAL",
        "UBL",
    ),
    "Nifty Metal": (
        "TATASTEEL",
        "JSWSTEEL",
        "HINDALCO",
        "VEDL",
        "COALINDIA",
        "NMDC",
        "SAIL",
        "JINDALSTEL",
        "NATIONALUM",
        "HINDZINC",
    ),
    "Nifty Pharma": (
        "SUNPHARMA",
        "DRREDDY",
        "CIPLA",
        "DIVISLAB",
        "AUROPHARMA",
        "LUPIN",
        "TORNTPHARM",
        "ALKEM",
        "BIOCON",
        "GLENMARK",
    ),
    "Nifty Energy": (
        "RELIANCE",
        "NTPC",
        "POWERGRID",
        "ONGC",
        "BPCL",
        "IOC",
        "GAIL",
        "TATAPOWER",
        "ADANIGREEN",
        "ADANIENSOL",
    ),
    "Nifty Realty": (
        "DLF",
        "GODREJPROP",
        "OBEROIRLTY",
        "PRESTIGE",
        "BRIGADE",
        "PHOENIXLTD",
        "SOBHA",
        "LODHA",
        "MAHLIFE",
        "ANANTRAJ",
    ),
    "Nifty Infra": (
        "LT",
        "ADANIPORTS",
        "NTPC",
        "POWERGRID",
        "ULTRACEMCO",
        "GRASIM",
        "SIEMENS",
        "ABB",
        "IRCTC",
        "CONCOR",
    ),
}

OFFICIAL_INDICES: tuple[SectorUniverseItem, ...] = (
    SectorUniverseItem(
        name="Nifty Bank",
        category="Official",
        instrument_key="NSE_INDEX|Nifty Bank",
        tickers=_OFFICIAL_FALLBACKS["Nifty Bank"],
        profile_sector="Banking",
    ),
    SectorUniverseItem(
        name="Nifty IT",
        category="Official",
        instrument_key="NSE_INDEX|Nifty IT",
        tickers=_OFFICIAL_FALLBACKS["Nifty IT"],
        profile_sector="IT",
    ),
    SectorUniverseItem(
        name="Nifty Auto",
        category="Official",
        instrument_key="NSE_INDEX|Nifty Auto",
        tickers=_OFFICIAL_FALLBACKS["Nifty Auto"],
        profile_sector="Auto",
    ),
    SectorUniverseItem(
        name="Nifty FMCG",
        category="Official",
        instrument_key="NSE_INDEX|Nifty FMCG",
        tickers=_OFFICIAL_FALLBACKS["Nifty FMCG"],
        profile_sector="FMCG",
    ),
    SectorUniverseItem(
        name="Nifty Metal",
        category="Official",
        instrument_key="NSE_INDEX|Nifty Metal",
        tickers=_OFFICIAL_FALLBACKS["Nifty Metal"],
        profile_sector="Metal",
    ),
    SectorUniverseItem(
        name="Nifty Pharma",
        category="Official",
        instrument_key="NSE_INDEX|Nifty Pharma",
        tickers=_OFFICIAL_FALLBACKS["Nifty Pharma"],
        profile_sector="Pharma",
    ),
    SectorUniverseItem(
        name="Nifty Energy",
        category="Official",
        instrument_key="NSE_INDEX|Nifty Energy",
        tickers=_OFFICIAL_FALLBACKS["Nifty Energy"],
        profile_sector="Energy",
    ),
    SectorUniverseItem(
        name="Nifty Realty",
        category="Official",
        instrument_key="NSE_INDEX|Nifty Realty",
        tickers=_OFFICIAL_FALLBACKS["Nifty Realty"],
        profile_sector="Realty",
    ),
    SectorUniverseItem(
        name="Nifty Infra",
        category="Official",
        instrument_key="NSE_INDEX|Nifty Infra",
        tickers=_OFFICIAL_FALLBACKS["Nifty Infra"],
        profile_sector="Infrastructure",
    ),
)

SYNTHETIC_THEMES: tuple[SectorUniverseItem, ...] = (
    SectorUniverseItem("Defense", "Synthetic", tickers=("HAL", "BEL", "MAZDOCK", "COCHINSHIP", "BDL")),
    SectorUniverseItem("Railways", "Synthetic", tickers=("IRFC", "RVNL", "IRCON", "TITAGARH", "RITES")),
    SectorUniverseItem("Capital Goods", "Synthetic", tickers=("LT", "SIEMENS", "ABB", "CUMMINSIND", "THERMAX")),
    SectorUniverseItem("Wires & Cables", "Synthetic", tickers=("POLYCAB", "HAVELLS", "KEI", "RRKABEL", "APARINDS")),
    SectorUniverseItem(
        "Green Energy",
        "Synthetic",
        tickers=("SUZLON", "IREDA", "WAAREEENER", "INOXWIND", "BORORENEW"),
    ),
    SectorUniverseItem(
        "Semiconductor / EMS",
        "Synthetic",
        tickers=("DIXON", "KAYNES", "CGPOWER", "CYIENTDLM", "SYRMA"),
    ),
    SectorUniverseItem(
        "Auto Ancillaries",
        "Synthetic",
        tickers=("MOTHERSON", "SONACOMS", "UNOMINDA", "BHARATFORG", "ARE&M"),
    ),
    SectorUniverseItem(
        "Logistics & Ports",
        "Synthetic",
        tickers=("CONCOR", "ADANIPORTS", "JSWINFRA", "DELHIVERY", "BLUEDART"),
    ),
    SectorUniverseItem(
        "QSR / Fast Food",
        "Synthetic",
        tickers=("JUBLFOOD", "DEVYANI", "SAPPHIRE", "WESTLIFE", "RBA"),
    ),
    SectorUniverseItem(
        "Hotels & Tourism",
        "Synthetic",
        tickers=("INDHOTEL", "EIHOTEL", "LEMONTREE", "CHALET", "IRCTC"),
    ),
    SectorUniverseItem(
        "Hospitals",
        "Synthetic",
        tickers=("APOLLOHOSP", "MAXHEALTH", "MEDANTA", "FORTIS", "NH"),
    ),
    SectorUniverseItem(
        "Capital Markets",
        "Synthetic",
        tickers=("BSE", "CDSL", "MCX", "CAMS", "ANGELONE"),
    ),
    SectorUniverseItem(
        "Paper",
        "Synthetic",
        tickers=("JKPAPER", "WESTCOAST", "ANDHRAPAP", "TNPL", "SESHAPAPER"),
    ),
    SectorUniverseItem(
        "Sugar",
        "Synthetic",
        tickers=("BALRAMCHIN", "TRIVENI", "RENUKA", "EIDPARRY", "DALMIASUG"),
    ),
    SectorUniverseItem(
        "Specialty Chemicals",
        "Synthetic",
        tickers=("SRF", "DEEPAKNTR", "TATACHEM", "NAVINFLUOR", "AARTIIND"),
    ),
    SectorUniverseItem(
        "Plastic Pipes",
        "Synthetic",
        tickers=("ASTRAL", "SUPREMEIND", "FINPIPE", "PRINCEPIPE"),
    ),
)


def all_universe_items() -> tuple[SectorUniverseItem, ...]:
    return OFFICIAL_INDICES + SYNTHETIC_THEMES


def all_constituent_tickers() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in all_universe_items():
        for t in item.tickers:
            up = t.upper()
            if up not in seen:
                seen.add(up)
                out.append(up)
    return out
