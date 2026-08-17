from __future__ import annotations

import logging
import re
from typing import Any

from ...config import normalize_symbol
from ...db.store import TimelineStore, get_store
from .event_study import event_session_date
from .gemini_client import extract_news_entities, gemini_enabled
from .name_linker import CompanyNameLinker, get_linker

logger = logging.getLogger(__name__)

_TITLE_CASE = re.compile(r"\b([A-Z][a-zA-Z0-9&.'-]{2,}(?:\s+[A-Z][a-zA-Z0-9&.'-]{2,}){0,5})\b")


def _heuristic_company_candidates(text: str) -> list[str]:
    if not text:
        return []
    found = []
    for m in _TITLE_CASE.finditer(text):
        name = m.group(1).strip(" .-")
        if len(name) < 3:
            continue
        # Skip common non-company tokens
        low = name.lower()
        if low in {"india", "sensex", "nifty", "rbi", "sebi", "usd", "inr", "ceo", "ipo"}:
            continue
        found.append(name)
    # Also try first segment before em-dash / colon style wires
    head = re.split(r"[–—:\-|]", text, maxsplit=1)[0].strip()
    if head and len(head) <= 80:
        found.insert(0, head)
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for n in found:
        key = n.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out[:8]


async def analyze_message_text(text: str) -> dict[str, Any]:
    if gemini_enabled() and text.strip():
        try:
            return await extract_news_entities(text)
        except Exception:
            logger.exception("Gemini extract failed; falling back to heuristics")
    companies = [{"name": n, "ticker_hint": None} for n in _heuristic_company_candidates(text)]
    return {
        "companies": companies,
        "sentiment": "unknown",
        "themes": [],
        "summary": (text.strip()[:240] or None),
        "equity_relevant": bool(companies),
        "source": "heuristic",
    }


async def process_message(
    message: dict[str, Any],
    *,
    store: TimelineStore | None = None,
    linker: CompanyNameLinker | None = None,
    min_confidence: float = 78.0,
) -> list[int]:
    """Create news_events for a telegram message; mark processed. Returns event ids."""
    store = store or get_store()
    linker = linker or get_linker()
    from .ingest import is_media_placeholder_text

    text = (message.get("text") or "").strip()
    message_pk = int(message["id"])
    event_date = event_session_date(message["posted_at"])

    # Media-only placeholders like "[photo]" / "[document]" have no headline to link
    if is_media_placeholder_text(text):
        store.mark_message_processed(message_pk)
        return []

    extract = await analyze_message_text(text)
    companies = extract.get("companies") or []
    event_ids: list[int] = []

    if not companies or not extract.get("equity_relevant", True):
        store.insert_news_event(
            message_pk=message_pk,
            ticker=None,
            company_name_matched=None,
            match_confidence=None,
            event_date=event_date,
            sentiment=extract.get("sentiment"),
            themes=extract.get("themes"),
            summary=extract.get("summary"),
            gemini_extract=extract,
            status="skipped",
        )
        store.mark_message_processed(message_pk)
        return []

    linked_any = False
    for company in companies:
        name = company.get("name") or ""
        hint = company.get("ticker_hint")
        match = None
        if hint:
            profile = store.get_profile_by_ticker(normalize_symbol(hint))
            if profile:
                match_ticker = profile["ticker"]
                match_name = profile.get("company_name") or name
                confidence = 95.0
            else:
                match = linker.match(name, min_score=min_confidence)
                if match:
                    match_ticker, match_name, confidence = match.ticker, match.company_name, match.confidence
                else:
                    continue
        else:
            match = linker.match(name, min_score=min_confidence)
            if not match:
                continue
            match_ticker, match_name, confidence = match.ticker, match.company_name, match.confidence

        eid = store.insert_news_event(
            message_pk=message_pk,
            ticker=match_ticker,
            company_name_matched=match_name,
            match_confidence=confidence,
            event_date=event_date,
            sentiment=extract.get("sentiment"),
            themes=extract.get("themes"),
            summary=extract.get("summary"),
            gemini_extract=extract,
            status="linked",
        )
        event_ids.append(eid)
        linked_any = True

    if not linked_any:
        store.insert_news_event(
            message_pk=message_pk,
            ticker=None,
            company_name_matched=None,
            match_confidence=None,
            event_date=event_date,
            sentiment=extract.get("sentiment"),
            themes=extract.get("themes"),
            summary=extract.get("summary"),
            gemini_extract=extract,
            status="unmatched",
        )

    store.mark_message_processed(message_pk)
    return event_ids


async def process_unprocessed_messages(
    *,
    store: TimelineStore | None = None,
    limit: int = 100,
    build_reactions: bool = True,
) -> dict[str, Any]:
    from .event_study import compute_and_store_reactions

    store = store or get_store()
    linker = get_linker()
    linker.reload()
    messages = store.list_unprocessed_messages(limit=limit)
    event_ids: list[int] = []
    for msg in messages:
        ids = await process_message(msg, store=store, linker=linker)
        event_ids.extend(ids)

    reaction_stats = {"processed": 0, "written": 0, "skipped": 0}
    if build_reactions and event_ids:
        reaction_stats = compute_and_store_reactions(store, event_ids=event_ids)

    return {
        "messages_processed": len(messages),
        "events_created": len(event_ids),
        "event_ids": event_ids,
        "reactions": reaction_stats,
    }
