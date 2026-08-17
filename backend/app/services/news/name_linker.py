from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from rapidfuzz import fuzz, process

from ...db.store import TimelineStore, get_store

_STRIP_SUFFIXES = re.compile(
    r"\b(limited|ltd|ltee|plc|inc|corp|corporation|company|co|pvt|private|"
    r"india|industries|industrial|enterprises|services|bank|finance|finserv)\b",
    re.I,
)
_NON_ALNUM = re.compile(r"[^a-z0-9\s]+")
_WS = re.compile(r"\s+")


def normalize_company_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = _STRIP_SUFFIXES.sub(" ", text)
    text = _NON_ALNUM.sub(" ", text)
    text = _WS.sub(" ", text).strip()
    return text


@dataclass(frozen=True)
class NameMatch:
    ticker: str
    company_name: str
    confidence: float
    query: str


class CompanyNameLinker:
    def __init__(self, store: TimelineStore | None = None) -> None:
        self.store = store or get_store()
        self._names: list[str] = []
        self._by_norm: dict[str, dict[str, Any]] = {}
        self.reload()

    def reload(self) -> None:
        rows = self.store.list_company_name_index()
        self._names = []
        self._by_norm = {}
        for row in rows:
            company = (row.get("company_name") or "").strip()
            if not company:
                continue
            norm = normalize_company_name(company)
            if len(norm) < 3:
                continue
            # Prefer first / EQ-ish profiles; keep first seen for collisions.
            if norm not in self._by_norm:
                self._by_norm[norm] = row
                self._names.append(norm)
            ticker_norm = normalize_company_name(row["ticker"].replace("_", " "))
            if ticker_norm and ticker_norm not in self._by_norm:
                self._by_norm[ticker_norm] = row
                self._names.append(ticker_norm)

    def match(self, query: str, *, min_score: float = 78.0) -> NameMatch | None:
        q = normalize_company_name(query)
        if len(q) < 3 or not self._names:
            return None
        if q in self._by_norm:
            row = self._by_norm[q]
            return NameMatch(
                ticker=row["ticker"],
                company_name=row["company_name"],
                confidence=100.0,
                query=query,
            )
        hit = process.extractOne(
            q,
            self._names,
            scorer=fuzz.token_set_ratio,
            score_cutoff=min_score,
        )
        if not hit:
            return None
        norm, score, _ = hit
        row = self._by_norm[norm]
        return NameMatch(
            ticker=row["ticker"],
            company_name=row["company_name"],
            confidence=float(score),
            query=query,
        )

    def match_many(self, queries: list[str], *, min_score: float = 78.0) -> list[NameMatch]:
        seen: set[str] = set()
        out: list[NameMatch] = []
        for query in queries:
            m = self.match(query, min_score=min_score)
            if not m or m.ticker in seen:
                continue
            seen.add(m.ticker)
            out.append(m)
        return out


@lru_cache(maxsize=1)
def get_linker() -> CompanyNameLinker:
    return CompanyNameLinker()
