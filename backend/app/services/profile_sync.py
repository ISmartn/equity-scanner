from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp

from ..config import NSE_BASE, ROOT_DIR, normalize_symbol
from ..db.store import TimelineStore, get_store
from . import nse_client

logger = logging.getLogger(__name__)

SECTOR_MAPPING_PATH = ROOT_DIR / "data" / "sector_mapping.csv"

# NSE sector indices → human-readable sector labels.
NSE_SECTOR_INDICES: dict[str, str] = {
    "NIFTY BANK": "Banking",
    "NIFTY IT": "IT",
    "NIFTY AUTO": "Auto",
    "NIFTY FMCG": "FMCG",
    "NIFTY PHARMA": "Pharma",
    "NIFTY METAL": "Metal",
    "NIFTY REALTY": "Realty",
    "NIFTY ENERGY": "Energy",
    "NIFTY MEDIA": "Media",
    "NIFTY PSU BANK": "PSU Banking",
    "NIFTY PRIVATE BANK": "Private Banking",
    "NIFTY FINANCIAL SERVICES": "Financial Services",
    "NIFTY HEALTHCARE": "Healthcare",
    "NIFTY CONSUMER DURABLES": "Consumer Durables",
    "NIFTY OIL & GAS": "Oil & Gas",
    "NIFTY INFRASTRUCTURE": "Infrastructure",
    "NIFTY COMMODITIES": "Commodities",
    "NIFTY INDIA CONSUMPTION": "Consumption",
}


def _load_sector_mapping_csv() -> dict[str, tuple[str | None, str | None]]:
    if not SECTOR_MAPPING_PATH.exists():
        return {}

    mapping: dict[str, tuple[str | None, str | None]] = {}
    with SECTOR_MAPPING_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ticker = normalize_symbol(row.get("ticker") or row.get("symbol") or "")
            if not ticker:
                continue
            sector = (row.get("sector") or "").strip() or None
            industry = (row.get("industry") or "").strip() or None
            mapping[ticker] = (sector, industry)
    return mapping


async def _fetch_sector_index_symbols(
    session: aiohttp.ClientSession,
    index_name: str,
) -> list[str]:
    cookies = await nse_client.get_nse_session(session)
    if not cookies:
        return []

    url = f"{NSE_BASE}/api/equity-stockIndices?index={quote(index_name)}"
    headers = {**nse_client.NSE_HEADERS, "Cookie": cookies}
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as res:
            if not res.ok:
                return []
            payload = await res.json()
    except (aiohttp.ClientError, json.JSONDecodeError):
        return []

    symbols: list[str] = []
    for row in payload.get("data") or []:
        sym = normalize_symbol(str(row.get("symbol") or ""))
        if sym:
            symbols.append(sym)
    return symbols


async def build_sector_mapping(session: aiohttp.ClientSession) -> dict[str, tuple[str, str | None]]:
    """Map tickers to sectors using NSE sector index constituents."""
    mapping: dict[str, tuple[str, str | None]] = {}
    for index_name, sector_label in NSE_SECTOR_INDICES.items():
        symbols = await _fetch_sector_index_symbols(session, index_name)
        for sym in symbols:
            if sym not in mapping:
                mapping[sym] = (sector_label, index_name)
    return mapping


async def sync_security_profiles(
    session: aiohttp.ClientSession,
    store: TimelineStore | None = None,
    *,
    include_sector_indices: bool = True,
) -> dict[str, Any]:
    db = store or get_store()
    master = await nse_client.fetch_equity_master(session)

    csv_sectors = _load_sector_mapping_csv()
    index_sectors: dict[str, tuple[str, str | None]] = {}
    if include_sector_indices:
        try:
            index_sectors = await build_sector_mapping(session)
        except Exception as exc:
            logger.warning("Sector index fetch failed: %s", exc)

    profiles: list[dict[str, Any]] = []
    for row in master:
        ticker = row["symbol"]
        sector: str | None = None
        industry: str | None = None

        if ticker in csv_sectors:
            sector, industry = csv_sectors[ticker]
        elif ticker in index_sectors:
            sector, industry = index_sectors[ticker]

        profiles.append(
            {
                "instrument_token": f"NSE_EQ|{row['isin']}",
                "ticker": ticker,
                "company_name": row["name"],
                "sector": sector,
                "industry": industry,
                "isin": row["isin"],
                "series": row["series"],
            }
        )

    count = db.upsert_profiles(profiles)
    sectors_assigned = sum(1 for p in profiles if p.get("sector"))
    return {
        "profiles_upserted": count,
        "total_mainboard": len(profiles),
        "sectors_assigned": sectors_assigned,
        "csv_mappings": len(csv_sectors),
        "index_mappings": len(index_sectors),
    }


async def reprofile_stale_profiles(
    session: aiohttp.ClientSession,
    store: TimelineStore | None = None,
    *,
    include_sector_indices: bool = True,
) -> dict[str, Any]:
    """Refresh NSE profiles, migrate ISIN changes, and skip delisted symbols in ingest."""
    db = store or get_store()
    master = await nse_client.fetch_equity_master(session)
    master_by_ticker = {row["symbol"]: row for row in master}

    migrated: list[str] = []
    marked_skip: list[str] = []
    cleared_skip: list[str] = []

    for prof in db.list_profiles():
        ticker = prof["ticker"]
        row = master_by_ticker.get(ticker)
        if not row:
            if not prof.get("ingest_skip"):
                db.set_ingest_skip(ticker, True, "not_in_nse_equity_master")
            marked_skip.append(ticker)
            continue

        new_token = f"NSE_EQ|{row['isin']}"
        if prof["instrument_token"] != new_token:
            db.migrate_instrument_token(prof["instrument_token"], new_token)
            migrated.append(ticker)

        if prof.get("ingest_skip"):
            db.set_ingest_skip(ticker, False, None)
            cleared_skip.append(ticker)

    sync_result = await sync_security_profiles(
        session,
        db,
        include_sector_indices=include_sector_indices,
    )

    return {
        **sync_result,
        "ingest_skip_marked": len(marked_skip),
        "ingest_skip_cleared": len(cleared_skip),
        "instrument_tokens_migrated": len(migrated),
        "marked_tickers": marked_skip,
        "migrated_tickers": migrated,
        "cleared_tickers": cleared_skip,
    }
