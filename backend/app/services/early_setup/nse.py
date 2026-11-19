"""Public NSE data the setup watchlist uses: fetching and parsing.

Everything here is published by the exchange for anyone to read. The archive
files (daily prices with delivery, index closes, deal lists) are plain
downloads. The ``/api`` endpoints are unofficial: they want the cookies a
browser gets from an NSE page and can refuse or change without notice, so
callers treat every failure as "try again later".

Parsers are pure functions over the downloaded text, so they are tested
without the network.
"""

from __future__ import annotations

import asyncio
import csv
import io
import re
from datetime import date, datetime
from typing import Any, Coroutine, TypeVar

import aiohttp

from ...config import normalize_symbol
from ..live_scan.clocks import IST

PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
API = "https://www.nseindia.com/api"
ARCHIVE = "https://nsearchives.nseindia.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": PAGE,
}

T = TypeVar("T")


class NseRefused(PermissionError):
    """NSE answered 401/403. Stop asking for a while."""


def run(coro: Coroutine[Any, Any, T]) -> T:
    """Run one fetch from synchronous code. Never call this on the event loop thread."""
    return asyncio.run(coro)


class NseClient:
    """One aiohttp session with NSE's cookies. ``async with NseClient() as nse``."""

    def __init__(self, *, warm: bool = True, timeout: float = 40.0) -> None:
        self._warm = warm
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "NseClient":
        self._session = aiohttp.ClientSession(timeout=self._timeout)
        if self._warm:
            # The page sets the cookies the API checks for.
            async with self._session.get(PAGE, headers={**HEADERS, "Accept": "text/html"}) as page:
                await page.read()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _get(self, url: str) -> aiohttp.ClientResponse:
        assert self._session is not None, "use NseClient as an async context manager"
        return await self._session.get(url, headers=HEADERS)

    async def text(self, url: str) -> str | None:
        """Body as text. None when the file does not exist (404)."""
        response = await self._get(url)
        async with response:
            if response.status == 404:
                return None
            if response.status in (401, 403):
                raise NseRefused(f"NSE refused the request ({response.status})")
            response.raise_for_status()
            return await response.text(errors="replace")

    async def json(self, url: str) -> Any:
        response = await self._get(url)
        async with response:
            if response.status in (401, 403):
                raise NseRefused(f"NSE refused the request ({response.status})")
            response.raise_for_status()
            return await response.json(content_type=None)

    async def bytes(self, url: str, *, limit: int) -> bytes | None:
        """Body as bytes, or None when it is larger than ``limit`` or missing."""
        response = await self._get(url)
        async with response:
            if response.status == 404:
                return None
            if response.status in (401, 403):
                raise NseRefused(f"NSE refused the request ({response.status})")
            response.raise_for_status()
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > limit:
                return None
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.content.iter_chunked(64 * 1024):
                size += len(chunk)
                if size > limit:
                    return None
                chunks.append(chunk)
            return b"".join(chunks)


# -------------------------------------------------------------------- helpers


def _number(raw: Any) -> float | None:
    try:
        text = str(raw).replace(",", "").strip()
        if text in ("", "-", "nan", "None"):
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _iso_day(raw: Any, *formats: str) -> str | None:
    text = str(raw or "").strip()
    for fmt in formats or ("%d-%b-%Y",):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _rows(text: str) -> list[dict[str, str]]:
    """CSV rows with header names and values stripped (NSE pads both with spaces)."""
    reader = csv.reader(io.StringIO(text))
    try:
        header = [cell.strip() for cell in next(reader)]
    except StopIteration:
        return []
    return [dict(zip(header, (cell.strip() for cell in row))) for row in reader if row]


def is_data(text: str | None) -> bool:
    return bool(text) and not str(text).lstrip().startswith("<")


# ---------------------------------------------------- daily prices + delivery


def bhavcopy_url(day: date) -> str:
    return f"{ARCHIVE}/products/content/sec_bhavdata_full_{day:%d%m%Y}.csv"


def parse_bhavcopy(text: str) -> tuple[str | None, list[dict[str, Any]]]:
    """The day's prices and delivery for every stock in the EQ and BE series.

    Returns the file's own date with the rows. NSE answers a request for a
    non-trading day with the previous session's file, so the caller must
    compare this date with the one it asked for.
    """
    rows: list[dict[str, Any]] = []
    file_day: str | None = None
    for raw in _rows(text):
        series = raw.get("SERIES", "")
        if series not in ("EQ", "BE"):
            continue
        day = _iso_day(raw.get("DATE1"))
        close = _number(raw.get("CLOSE_PRICE"))
        if not day or not raw.get("SYMBOL") or not close or close <= 0:
            continue
        file_day = file_day or day
        deliv_pct = _number(raw.get("DELIV_PER"))
        rows.append(
            {
                "trade_date": day,
                "ticker": normalize_symbol(raw["SYMBOL"]),
                "series": series,
                "prev_close": _number(raw.get("PREV_CLOSE")),
                "open": _number(raw.get("OPEN_PRICE")),
                "high": _number(raw.get("HIGH_PRICE")),
                "low": _number(raw.get("LOW_PRICE")),
                "close": close,
                "volume": _number(raw.get("TTL_TRD_QNTY")),
                "deliv_qty": _number(raw.get("DELIV_QTY")),
                # BE (trade-for-trade) is all delivery by rule, so its share says nothing.
                "deliv_pct": deliv_pct if series == "EQ" else None,
            }
        )
    return file_day, rows


def index_close_url(day: date) -> str:
    return f"{ARCHIVE}/content/indices/ind_close_all_{day:%d%m%Y}.csv"


def parse_index_close(text: str, name: str = "Nifty 50") -> dict[str, Any] | None:
    for raw in _rows(text):
        if raw.get("Index Name", "").lower() != name.lower():
            continue
        day = _iso_day(raw.get("Index Date"), "%d-%m-%Y", "%d-%b-%Y")
        close = _number(raw.get("Closing Index Value"))
        if not day or not close:
            return None
        return {
            "trade_date": day,
            "open": _number(raw.get("Open Index Value")) or close,
            "high": _number(raw.get("High Index Value")) or close,
            "low": _number(raw.get("Low Index Value")) or close,
            "close": close,
        }
    return None


# ----------------------------------------------------------------- big trades

BULK_URL = f"{ARCHIVE}/content/equities/bulk.csv"
BLOCK_URL = f"{ARCHIVE}/content/equities/block.csv"


def parse_deals(text: str, kind: str) -> list[dict[str, Any]]:
    """NSE's list of large trades for the latest session. ``kind`` is ``bulk`` or ``block``."""
    deals: list[dict[str, Any]] = []
    for raw in _rows(text):
        day = _iso_day(raw.get("Date"))
        side = raw.get("Buy/Sell", "").upper()
        quantity = _number(raw.get("Quantity Traded"))
        if not day or side not in ("BUY", "SELL") or not raw.get("Symbol") or not quantity:
            continue
        deals.append(
            {
                "trade_date": day,
                "ticker": normalize_symbol(raw["Symbol"]),
                "client": re.sub(r"\s+", " ", raw.get("Client Name", "")).strip().upper(),
                "side": side,
                "quantity": quantity,
                "price": _number(raw.get("Trade Price / Wght. Avg. Price")) or 0.0,
                "kind": kind,
                "churn": 0,
            }
        )
    return deals


def mark_churn(deals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag deals by a client that both bought and sold the stock that day.

    Most of the list is trading firms going in and out within the session.
    Those say nothing about accumulation; a one-sided buy does.
    """
    sides: dict[tuple[str, str, str], set[str]] = {}
    for deal in deals:
        sides.setdefault((deal["trade_date"], deal["ticker"], deal["client"]), set()).add(deal["side"])
    for deal in deals:
        both = sides[(deal["trade_date"], deal["ticker"], deal["client"])]
        deal["churn"] = 1 if {"BUY", "SELL"} <= both else 0
    return deals


# -------------------------------------------------------------------- pre-open

PREOPEN_URL = f"{API}/market-data-pre-open?key=ALL"


def parse_preopen(payload: Any) -> tuple[datetime | None, list[dict[str, Any]]]:
    """The opening auction: each stock's indicative opening price and matched quantity."""
    if not isinstance(payload, dict):
        return None, []
    stamp: datetime | None = None
    try:
        stamp = datetime.strptime(str(payload.get("timestamp")), "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
    except (TypeError, ValueError):
        stamp = None
    rows: list[dict[str, Any]] = []
    for item in payload.get("data") or []:
        meta = item.get("metadata") if isinstance(item, dict) else None
        if not isinstance(meta, dict) or meta.get("series") not in ("EQ", None):
            continue
        price = _number(meta.get("iep")) or _number(meta.get("lastPrice"))
        if not meta.get("symbol") or not price:
            continue
        rows.append(
            {
                "ticker": normalize_symbol(str(meta["symbol"])),
                "iep": price,
                "prev_close": _number(meta.get("previousClose")),
                "change_pct": _number(meta.get("pChange")),
                "final_qty": _number(meta.get("finalQuantity")) or 0.0,
            }
        )
    return stamp, rows


# ------------------------------------------------------------------ reference

INDUSTRY_URL = f"{ARCHIVE}/content/indices/ind_niftytotalmarket_list.csv"
BAN_URL = f"{ARCHIVE}/content/fo/fo_secban.csv"
ASM_URL = f"{API}/reportASM"


def parse_industries(text: str) -> list[dict[str, Any]]:
    found = []
    for raw in _rows(text):
        symbol, industry = raw.get("Symbol"), raw.get("Industry")
        if symbol and industry:
            found.append(
                {"ticker": normalize_symbol(symbol), "industry": industry, "company_name": raw.get("Company Name") or None}
            )
    return found


def parse_asm(payload: Any) -> list[dict[str, Any]]:
    """Stocks under NSE's Additional Surveillance Measure, long and short term."""
    flags: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return flags
    for key, flag in (("longterm", "asm_long"), ("shortterm", "asm_short")):
        section = payload.get(key)
        rows = section.get("data") if isinstance(section, dict) else section
        for row in rows or []:
            if isinstance(row, dict) and row.get("symbol"):
                stage = str(row.get("asmSurvIndicator") or "").strip()
                label = "Long-term surveillance" if flag == "asm_long" else "Short-term surveillance"
                flags.append(
                    {"ticker": normalize_symbol(str(row["symbol"])), "flag": flag, "detail": f"{label} {stage}".strip()}
                )
    return flags


def parse_ban(text: str) -> list[dict[str, Any]]:
    """F&O ban list: ``1,KAYNES`` lines under a one-line heading."""
    flags = []
    for line in text.splitlines()[1:]:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 2 and parts[0].isdigit() and parts[1]:
            flags.append({"ticker": normalize_symbol(parts[1]), "flag": "fo_ban", "detail": "In the F&O ban"})
    return flags


# ----------------------------------------------------------- corporate actions

_BONUS = re.compile(r"\bbonus\s+(\d+)\s*:\s*(\d+)", re.I)
_SPLIT = re.compile(r"from\s+r[se]\.?\s*([\d.]+)\s*/?-?.*?\bto\s+r[se]\.?\s*([\d.]+)", re.I)
# A bonus paid in preference shares or debentures does not change the share price.
_NOT_EQUITY = re.compile(r"ncrps|preference|debenture|\bncd\b", re.I)


def action_factor(subject: str) -> tuple[str, float | None]:
    """(kind, price factor for the days before the ex-date). Factor is None when it cannot be read.

    Bonus 1:1 halves the price (0.5). A split from Rs 10 to Rs 2 divides it by five (0.2).
    """
    text = subject or ""
    lowered = text.lower()
    if "bonus" in lowered:
        match = _BONUS.search(text)
        if match and not _NOT_EQUITY.search(text):
            new, held = float(match.group(1)), float(match.group(2))
            if new > 0 and held > 0:
                return "bonus", held / (new + held)
        return "bonus", None
    if "split" in lowered or "sub-division" in lowered or "consolidation" in lowered:
        match = _SPLIT.search(text)
        if match:
            old, new = float(match.group(1)), float(match.group(2))
            if old > 0 and new > 0 and old != new:
                return "split", new / old
        return "split", None
    if "dividend" in lowered:
        return "dividend", None
    return "other", None


def actions_url(start: date, end: date) -> str:
    return f"{API}/corporates-corporateActions?index=equities&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}"


def parse_actions(payload: Any) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for row in payload if isinstance(payload, list) else []:
        if not isinstance(row, dict) or row.get("series") not in ("EQ", "BE", None, "-"):
            continue
        day = _iso_day(row.get("exDate"))
        subject = re.sub(r"\s+", " ", str(row.get("subject") or "")).strip()
        if not day or not row.get("symbol") or not subject:
            continue
        kind, factor = action_factor(subject)
        actions.append(
            {"ticker": normalize_symbol(str(row["symbol"])), "ex_date": day, "subject": subject[:200], "kind": kind, "factor": factor}
        )
    return actions
