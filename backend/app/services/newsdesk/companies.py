"""Headline company mentions, using Newsdesk's alias list and the lab's tickers."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from ...config import normalize_symbol

_MAP_PATH = Path(__file__).with_name("companies.json")

AMBIGUOUS = {
    "reliance",
    "titan",
    "apollo",
    "hero",
    "eternal",
    "trent",
    "larsen",
    "britannia",
    "union bank",
    "power grid",
    "indian oil",
    "eicher",
}
FINANCE_CONTEXT = re.compile(
    r"\b(shares?|stocks?|NSE|BSE|Nifty|Sensex|Ltd|Limited|Q[1-4]|FY\s?\d{2}|earnings|dividend|"
    r"IPO|market cap|brokerage|target price|stake|results|profit|revenue|crore|Rs\.?|investors?|analysts?)\b|₹",
    re.IGNORECASE,
)
NOT_FOLLOWED_BY = {
    "apollo": re.compile(r"^\s+(Global|Management|Tyres?|Group|Hospitality)\b"),
    "hero": re.compile(r"^\s+(Group|Honda|Wars)\b"),
    "eternal": re.compile(r"^\s+(Sunshine|Love|City)\b"),
}


def _escape(alias: str) -> str:
    return re.escape(alias)


@lru_cache(maxsize=1)
def _rules() -> tuple[tuple[str, str, re.Pattern[str], bool, re.Pattern[str] | None], ...]:
    raw: dict[str, list[str]] = json.loads(_MAP_PATH.read_text())
    rules = []
    for symbol, aliases in raw.items():
        ticker = normalize_symbol(symbol)
        for alias in aliases:
            if not alias or len(alias) < 2:
                continue
            ambiguous = alias.lower() in AMBIGUOUS
            short_alias = len(alias) <= 4 and alias == alias.upper()
            flags = 0 if ambiguous or short_alias else re.IGNORECASE
            pattern = re.compile(rf"(?<![\w&]){_escape(alias)}(?![\w&])", flags)
            rules.append((ticker, alias, pattern, ambiguous, NOT_FOLLOWED_BY.get(alias.lower())))
    return tuple(rules)


@lru_cache(maxsize=1)
def company_names() -> dict[str, str]:
    raw: dict[str, list[str]] = json.loads(_MAP_PATH.read_text())
    names: dict[str, str] = {}
    for symbol, aliases in raw.items():
        ticker = normalize_symbol(symbol)
        if aliases and ticker not in names:
            names[ticker] = aliases[0]
    return names


def match_companies(text: str | None) -> list[str]:
    """Symbols mentioned in a headline or blurb. Short tickers must match case."""
    if not text:
        return []
    has_context = FINANCE_CONTEXT.search(text) is not None
    matched: list[str] = []
    seen: set[str] = set()
    for ticker, _alias, pattern, ambiguous, bad in _rules():
        if ticker in seen:
            continue
        found = pattern.search(text)
        if not found:
            continue
        if ambiguous and not has_context:
            continue
        if bad and bad.search(text[found.end() :]):
            continue
        seen.add(ticker)
        matched.append(ticker)
    return matched
