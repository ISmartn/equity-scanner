"""Exchange filings, read from NSE the minute they are published.

A filing is the first public appearance of company news: results, orders,
acquisitions, fund raising, rating changes. News sites and channels repost it
later. This module polls NSE's announcements, keeps the price-moving ones, and
alerts when one lands on a stock (by default, a stock on the setup watchlist).

The NSE endpoints are unofficial. They need the cookies a browser gets from the
filings page, and they can change or refuse without notice, so every failure
here is logged and retried on the next cycle.
"""

from __future__ import annotations

import asyncio
import bisect
import json
import logging
import os
import re
import threading
import time
from datetime import date, datetime, time as clock, timedelta
from typing import Any, Callable, Mapping

import aiohttp

from ...config import normalize_symbol
from ...db.store import TimelineStore
from ..live_scan.clocks import IST
from . import candles as candle_data, nse, preopen, repo, sizing
from .live import send_telegram

logger = logging.getLogger(__name__)

_ANNOUNCEMENTS = f"{nse.API}/corporate-announcements?index=equities"
_EVENTS = f"{nse.API}/event-calendar"

POLL_SECONDS = 60.0
EVENTS_EVERY_SECONDS = 1800.0
# A filing older than this when first seen is history, not news. No alert.
ALERT_MAX_AGE_MINUTES = 30
_QUIET_HOURS = (0, 7)  # IST. Nothing is filed overnight.
MARKET_OPEN = clock(9, 15)
MARKET_CLOSE = clock(15, 30)
# A kind of filing needs this many measured cases before its typical move is quoted.
MIN_CASES = 30
_SIZE_PER_CYCLE = 6
_SIZE_BUDGET_SEC = 25.0

# Routine paperwork by NSE subject line. Checked first, so these never alert.
_NOISE = re.compile(
    r"declaration of nav|newspaper|duplicate share|loss of share|share certificate|trading window|"
    r"analysts?/institutional|investor meet|con\. call|investor presentation|esop|esos|"
    r"shareholders? meeting|postal ballot|scrutinizer|redemption|payment of interest|"
    r"record date|book closure|certificate under|compliance|regulation 74|change in address|"
    r"registrar|transcript|voting results|monitoring agency|statement of deviation",
    re.I,
)

_CREDITOR_MEETING = re.compile(r"meetings? of (the )?committee of creditors", re.I)

# (category, label, pattern over subject + text). First match wins, so order matters.
_RULES: list[tuple[str, str, re.Pattern[str]]] = [
    ("results", "Results", re.compile(r"financial results?|unaudited results|audited results|quarterly results", re.I)),
    ("orders", "Order win", re.compile(r"bagging|receiving of orders?|order win|letter of (award|intent|acceptance)|awarded (a |the )?contract|received (an? |the )?(order|work order|purchase order)|secured (an? )?(order|contract)", re.I)),
    ("stake", "Stake change", re.compile(r"takeover regulations|\bsast\b|insider trading|pledge|encumbrance|promoter .{0,30}(acquired|sold|purchase|sale)", re.I)),
    ("deal", "Acquisition or merger", re.compile(r"acquisition|acquire[sd]?\b|amalgamation|merger|demerger|scheme of arrangement|open offer|slump sale|joint venture|strategic (stake|investment)|divest", re.I)),
    ("capital", "Fund raising or payout", re.compile(r"fund rais|raising of funds|qualified institutions? placement|\bqip\b|preferential (issue|allotment)|rights issue|buy-?back|bonus (issue|shares)|stock split|sub-?division|dividend", re.I)),
    ("rating", "Credit rating", re.compile(r"credit rating|rating (upgrade|downgrade|action|revision)", re.I)),
    ("management", "Management change", re.compile(r"resignation of .{0,40}(managing director|chief|ceo|cfo|auditor|chairman|company secretary)|appointment of .{0,40}(managing director|chief executive|ceo|cfo|chairman)|change in (statutory )?auditor", re.I)),
    ("regulatory", "Regulatory or legal", re.compile(r"action\(s\) (initiated|taken)|orders? passed|litigation|penalty|show cause|search (and|&) seizure|insolvency|default|fraud|\bsebi order\b|tax demand", re.I)),
    ("board", "Board decision", re.compile(r"outcome of board meeting", re.I)),
    ("business", "Business update", re.compile(r"press release|product launch|capacity (addition|expansion)|commenc(es|ed|ement) of (commercial )?(production|operations)|new plant|approval from|usfda|patent|agreement|memorandum of understanding|\bmou\b|partnership|tie-?up", re.I)),
]
CATEGORY_LABELS = {category: label for category, label, _ in _RULES}


def classify(subject: str | None, text: str | None) -> str | None:
    """The kind of price-moving news a filing is, or None for routine paperwork."""
    head = subject or ""
    if _NOISE.search(head):
        return None
    body = f"{head} | {text or ''}"
    # A company already in insolvency files a notice for every creditors' meeting. That is procedure, not news.
    if _CREDITOR_MEETING.search(body):
        return None
    for category, _, pattern in _RULES:
        if pattern.search(body):
            return category
    return None


def _parse_time(raw: Any) -> datetime | None:
    """NSE prints IST wall time as ``18-Nov-2026 21:50:55``."""
    try:
        return datetime.strptime(str(raw).strip(), "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
    except (TypeError, ValueError):
        return None


def _clean(text: Any, limit: int = 600) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def parse_announcement(row: dict[str, Any]) -> dict[str, Any] | None:
    """One NSE announcement as a stored filing, or None when it is routine or malformed."""
    seq = str(row.get("seq_id") or "").strip()
    symbol = str(row.get("symbol") or "").strip()
    filed = _parse_time(row.get("an_dt"))
    if not seq or not symbol or filed is None:
        return None
    subject = _clean(row.get("desc"), 200)
    text = _clean(row.get("attchmntText"))
    category = classify(subject, text)
    if category is None:
        return None
    published = _parse_time(row.get("exchdisstime")) or filed
    return {
        "seq_id": seq,
        "ticker": normalize_symbol(symbol),
        "company_name": _clean(row.get("sm_name"), 200) or None,
        "category": category,
        "subject": subject,
        "summary": text or _clean(row.get("voiceSummary")),
        "url": str(row.get("attchmntFile") or "") or None,
        "filed_at": filed.isoformat(),
        "published_at": published.isoformat(),
    }


def parse_event(row: dict[str, Any]) -> dict[str, Any] | None:
    symbol = str(row.get("symbol") or "").strip()
    try:
        day = datetime.strptime(str(row.get("date")).strip(), "%d-%b-%Y").date().isoformat()
    except (TypeError, ValueError):
        return None
    if not symbol:
        return None
    return {
        "ticker": normalize_symbol(symbol),
        "event_date": day,
        "purpose": _clean(row.get("purpose"), 120) or "Board meeting",
        "detail": _clean(row.get("bm_desc"), 400),
    }


def filing_alert_text(
    filing: dict[str, Any],
    watch: repo.WatchEntry | None,
    size: dict[str, Any] | None = None,
    typical: dict[str, Any] | None = None,
) -> str:
    label = CATEGORY_LABELS.get(str(filing["category"]), "Filing")
    filed = datetime.fromisoformat(filing["filed_at"]).strftime("%H:%M")
    impact = f" ({size['impact']} impact)" if size and size.get("impact") else ""
    lines = [
        f"{filing['ticker']} — Filing: {label}{impact}",
        str(filing.get("company_name") or filing["ticker"]),
        f"{filing['subject']} · filed {filed} IST",
    ]
    if size and size.get("headline"):
        lines.append(str(size["headline"]))
    elif filing.get("summary"):
        lines.append(str(filing["summary"])[:320])
    measured = sizing.describe(size)
    if measured:
        lines.append(measured[0].upper() + measured[1:])
    if typical:
        lines.append(
            f"After past filings of this kind the stock moved {typical['avg_after5_rel_pct']:+.1f}% against similar "
            f"stocks over 5 sessions on average ({typical['measured']} cases)"
        )
    if watch is not None:
        which = "weekly" if watch.timeframe == "weekly" else "setup"
        lines.append(f"On the {which} watchlist: pivot {watch.pivot:.2f}, stop {watch.stop:.2f}")
    if filing.get("url"):
        lines.append(str(filing["url"]))
    return "\n".join(lines)


def alert_scope() -> str:
    """``watchlist`` (default): alert only for stocks in a base. ``all``: every material filing."""
    return "all" if os.getenv("SETUP_FILINGS_SCOPE", "watchlist").strip().lower() == "all" else "watchlist"


def ingest(
    rows: list[dict[str, Any]],
    *,
    now: datetime,
    store: TimelineStore | None = None,
    sender: Callable[[str], bool] = send_telegram,
    scope: str | None = None,
    sizer: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Store the material filings in ``rows`` and alert on the fresh ones. Safe to repeat.

    ``sizer`` reads one filing for its size before the alert goes out. It is given
    a short time budget by the caller; a filing it cannot read is alerted without a size.
    """
    parsed = [filing for filing in (parse_announcement(row) for row in rows) if filing is not None]
    new = repo.save_filings(parsed, store)
    if not new:
        return {"seen": len(rows), "material": len(parsed), "new": 0, "alerted": 0}
    watching: dict[str, repo.WatchEntry] = {}
    for entry in repo.list_entries(status="active", limit=10_000, store=store):
        if entry.ticker not in watching or entry.timeframe == "daily":
            watching[entry.ticker] = entry
    use_scope = scope or alert_scope()
    alerted = 0
    for filing in sorted(new, key=lambda item: item["published_at"]):
        watch = watching.get(filing["ticker"])
        if use_scope == "watchlist" and watch is None:
            continue
        age = now - datetime.fromisoformat(filing["published_at"])
        if age > timedelta(minutes=ALERT_MAX_AGE_MINUTES):
            continue
        size = None
        if sizer is not None:
            try:
                size = sizer(filing)
            except Exception as exc:  # the alert matters more than its size
                logger.warning("Could not size filing %s: %s", filing["seq_id"], type(exc).__name__)
            else:
                repo.save_filing_size(filing["seq_id"], size, store)
        # With every stock in scope, a filing read as small is not worth a message.
        if use_scope == "all" and watch is None and size and size.get("impact") == "low":
            continue
        text = filing_alert_text(filing, watch, size, typical_move(str(filing["category"]), store))
        delivered = sender(text)
        repo.mark_filing_alerted(filing["seq_id"], delivered, store)
        alerted += 1
    return {"seen": len(rows), "material": len(parsed), "new": len(new), "alerted": alerted}


# ------------------------------------------------------------------ fetching


async def fetch(*, full_day: str | None = None, events: bool = False) -> dict[str, list[dict[str, Any]]]:
    """Latest announcements (NSE returns 20), or every one for ``full_day`` (``DD-MM-YYYY``)."""
    async with nse.NseClient() as client:
        url = _ANNOUNCEMENTS
        if full_day:
            url += f"&from_date={full_day}&to_date={full_day}"
        announcements = await client.json(url)
        calendar = await client.json(_EVENTS) if events else []
    return {
        "announcements": announcements if isinstance(announcements, list) else [],
        "events": calendar if isinstance(calendar, list) else [],
    }


# -------------------------------------------------------------------- sizing


def size_now(filing: dict[str, Any], store: TimelineStore | None = None) -> dict[str, Any] | None:
    """Read one filing for its size, within a few seconds. For the alert path."""
    if not sizing.enabled():
        return None

    async def read() -> dict[str, Any] | None:
        async with nse.NseClient(warm=False, timeout=_SIZE_BUDGET_SEC) as client:
            label = CATEGORY_LABELS.get(str(filing["category"]), "Filing")
            return await asyncio.wait_for(sizing.size_filing(filing, label, client, store=store), _SIZE_BUDGET_SEC)

    return nse.run(read())


def size_pending(limit: int = _SIZE_PER_CYCLE, store: TimelineStore | None = None) -> int:
    """Read the newest filings that have no size yet. A few per call, so a backlog never stalls the poller."""
    if not sizing.enabled():
        return 0
    pending = repo.filings_to_size(limit, store)
    if not pending:
        return 0

    async def read_all() -> int:
        done = 0
        async with nse.NseClient(warm=False, timeout=_SIZE_BUDGET_SEC) as client:
            for filing in pending:
                label = CATEGORY_LABELS.get(str(filing["category"]), "Filing")
                try:
                    size = await asyncio.wait_for(sizing.size_filing(filing, label, client, store=store), _SIZE_BUDGET_SEC)
                except (asyncio.TimeoutError, aiohttp.ClientError):
                    continue  # a network miss: leave it for the next cycle
                except nse.NseRefused:
                    break
                repo.save_filing_size(filing["seq_id"], size, store)
                done += 1
        return done

    return nse.run(read_all())


# ------------------------------------------------- history and typical moves


def backfill_history(
    days: int,
    *,
    pause: float = 1.2,
    store: TimelineStore | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Load past filings, one request per weekday, newest first. Nothing old is ever alerted."""
    db = repo.ensure_schema(store)
    today = datetime.now(IST).date()
    wanted = [today - timedelta(days=offset) for offset in range(1, int(days * 1.45) + 5)]
    wanted = [day for day in wanted if day.weekday() < 5][: max(1, int(days))]
    done_days = set(json.loads(repo.get_meta("filings_history_days", db) or "[]"))
    totals = {"days": 0, "seen": 0, "material": 0, "new": 0, "skipped": 0}

    async def load() -> str | None:
        async with nse.NseClient() as client:
            for position, day in enumerate(wanted, start=1):
                key = day.isoformat()
                if key in done_days:
                    totals["skipped"] += 1
                    continue
                url = f"{_ANNOUNCEMENTS}&from_date={day:%d-%m-%Y}&to_date={day:%d-%m-%Y}"
                try:
                    rows = await client.json(url)
                except nse.NseRefused as exc:
                    return str(exc)
                except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
                    return f"NSE stopped answering ({type(exc).__name__}). Run it again to continue."
                rows = rows if isinstance(rows, list) else []
                parsed = [filing for filing in map(parse_announcement, rows) if filing is not None]
                totals["days"] += 1
                totals["seen"] += len(rows)
                totals["material"] += len(parsed)
                totals["new"] += len(repo.save_filings(parsed, db))
                done_days.add(key)
                if on_progress:
                    on_progress({"day": key, "position": position, "total": len(wanted), **totals})
                await asyncio.sleep(pause)
        return None

    stopped = nse.run(load())
    repo.set_meta("filings_history_days", json.dumps(sorted(done_days)[-800:]), db)
    return {**totals, "stopped": stopped}


def reaction(
    published: datetime,
    dates: list[str],
    opens: list[float],
    closes: list[float],
    typical: Mapping[tuple[str, int], candle_data.Typical] | None = None,
    groups: list[float] | None = None,
) -> dict[str, Any] | None:
    """What the stock did around one filing, and what was left for someone who read it at once.

    ``react_pct``  the move on the first session that could show the news, close to close.
    ``gap_pct``    how much of that was already in the opening price.
    ``after5_pct`` the next 5 sessions from the first price one could trade at: that session's
                   open for a filing made outside market hours, its close for one made during them
                   (the price at the minute of filing is not in daily data, so the close is the
                   cautious stand-in).

    With ``typical`` (what stocks of each liquidity group did each day, from
    ``candles.typical_day``) and the stock's own ``groups`` per bar, each gets a ``_rel``
    twin: the stock's move minus the average move of stocks of similar liquidity over the
    same stretch. ``beat`` says whether it did better than the median such stock.
    """
    day = published.date().isoformat()
    at = bisect.bisect_left(dates, day)
    same_day = at < len(dates) and dates[at] == day
    when = published.time()
    if same_day and when < MARKET_CLOSE:
        session = at
        timing = "before_open" if when < MARKET_OPEN else "market_hours"
    else:
        session = at + 1 if same_day else at
        timing = "after_close"
    if session <= 0 or session >= len(dates) or closes[session - 1] <= 0:
        return None
    previous = closes[session - 1]
    entry = closes[session] if timing == "market_hours" else opens[session]
    found: dict[str, Any] = {
        "timing": timing,
        "session": dates[session],
        "react_pct": (closes[session] / previous - 1.0) * 100.0,
        "gap_pct": (opens[session] / previous - 1.0) * 100.0,
    }
    which = groups[session] if groups is not None and typical else None
    which = int(which) if which is not None and which == which else None  # NaN: too little history to place it
    norm = typical.get((dates[session], which)) if typical and which is not None else None
    if norm is not None:
        found["gap_rel_pct"] = found["gap_pct"] - norm[0]
        found["react_rel_pct"] = found["react_pct"] - norm[1]
    if session + 5 < len(dates) and entry > 0:
        after = (closes[session + 5] / entry - 1.0) * 100.0
        found["after5_pct"] = after
        if norm is not None:
            # Similar stocks bought at the same kind of price on the same day and held as long:
            # their average for the size of the edge, their median for the odds.
            average, middle = (norm[3], norm[5]) if timing == "market_hours" else (norm[2], norm[4])
            if average == average and middle == middle:
                capped = max(-candle_data.FORWARD_CAP_PCT, min(candle_data.FORWARD_CAP_PCT, after))
                found["after5_rel_pct"] = capped - average
                found["beat"] = after > middle
    return found


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def rebuild_impact(store: TimelineStore | None = None, *, days: int = 500) -> dict[str, Any]:
    """Measure, per kind of filing, the stock's reaction and what followed. Stored for alerts and the page."""
    db = repo.ensure_schema(store)
    now = datetime.now(IST)
    since = now - timedelta(days=days)
    filings = repo.list_filings(since=since.isoformat(), limit=500_000, store=db)
    table: dict[str, Any] = {"computed_at": now.isoformat(), "from": since.date().isoformat(), "to": now.date().isoformat(), "rows": []}
    if filings:
        table["from"] = min(filing["published_at"] for filing in filings)[:10]
        start = (since.date() - timedelta(days=12)).isoformat()
        candles = candle_data.load_adjusted(start, now.date().isoformat(), db)
        typical: dict[tuple[str, int], candle_data.Typical] = {}
        bars: dict[str, tuple[list[str], list[float], list[float], list[float]]] = {}
        if not candles.empty:
            candles = candles.assign(liquidity=candle_data.liquidity_group(candles))
            typical = candle_data.typical_day(candles, candles["liquidity"])
            wanted = {filing["ticker"] for filing in filings}
            bars = {
                str(ticker): (group["date"].tolist(), group["open"].tolist(), group["close"].tolist(), group["liquidity"].tolist())
                for ticker, group in candles[candles["ticker"].isin(wanted)].groupby("ticker", sort=False)
            }
        by_kind: dict[str, list[dict[str, Any]]] = {}
        seen: set[tuple[str, str, str]] = set()
        for filing in filings:
            stock = bars.get(filing["ticker"])
            if stock is None:
                continue
            dates, opens, closes, liquidity = stock
            found = reaction(datetime.fromisoformat(filing["published_at"]), dates, opens, closes, typical, liquidity)
            if found is None:
                continue
            # Several filings of one kind on one day are one event.
            key = (filing["ticker"], filing["category"], found["session"])
            if key in seen:
                continue
            seen.add(key)
            by_kind.setdefault(filing["category"], []).append(found)
        for category, _label, _pattern in _RULES:
            cases = by_kind.get(category, [])
            relative = [case["after5_rel_pct"] for case in cases if "after5_rel_pct" in case]
            table["rows"].append(
                {
                    "category": category,
                    "label": CATEGORY_LABELS[category],
                    "filings": len(cases),
                    "measured": len(relative),
                    "avg_react_pct": _avg([case["react_pct"] for case in cases]),
                    "avg_react_rel_pct": _avg([case["react_rel_pct"] for case in cases if "react_rel_pct" in case]),
                    "avg_gap_rel_pct": _avg([case["gap_rel_pct"] for case in cases if "gap_rel_pct" in case]),
                    "avg_after5_pct": _avg([case["after5_pct"] for case in cases if "after5_pct" in case]),
                    "avg_after5_rel_pct": _avg(relative),
                    "positive_after5_pct": (
                        round(sum(1 for case in cases if case.get("beat")) / len(relative) * 100.0, 1) if relative else None
                    ),
                }
            )
    repo.set_meta("filing_impact", json.dumps(table), db)
    return table


def load_impact(store: TimelineStore | None = None) -> dict[str, Any] | None:
    try:
        return json.loads(repo.get_meta("filing_impact", store) or "null")
    except ValueError:
        return None


def typical_move(category: str, store: TimelineStore | None = None) -> dict[str, Any] | None:
    """The measured average for this kind of filing, once there are enough cases to quote."""
    table = load_impact(store)
    for row in (table or {}).get("rows", []):
        if row["category"] == category and (row.get("measured") or 0) >= MIN_CASES and row.get("avg_after5_rel_pct") is not None:
            return row
    return None


# -------------------------------------------------------------------- poller


class FilingsPoller:
    """Reads NSE on its own daemon thread: filings every minute, and the opening auction at 9:08."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._events_at = 0.0
        self._caught_up_day: str | None = None
        self.last_ok_at: float | None = None
        self.last_error: str | None = None
        self.cycles = 0
        self.totals = {"new": 0, "alerted": 0, "sized": 0}
        self.preopen: dict[str, Any] | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,), name="setup-filings", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "last_ok_at": self.last_ok_at,
            "last_error": self.last_error,
            "cycles": self.cycles,
            "new_filings": self.totals["new"],
            "alerts": self.totals["alerted"],
            "sized": self.totals["sized"],
            "scope": alert_scope(),
            "sizing": "ai" if sizing.enabled() and sizing.ai_available() else "rules" if sizing.enabled() else "off",
            "preopen": self.preopen,
        }

    def _run(self, stop: threading.Event) -> None:
        failures = 0
        next_poll = 0.0
        while not stop.is_set():
            now = datetime.now(IST)
            if _QUIET_HOURS[0] <= now.hour < _QUIET_HOURS[1]:
                stop.wait(300)
                continue
            if preopen.in_window(now):
                self._read_preopen(now)
            if time.monotonic() >= next_poll:
                try:
                    self.poll_once(now)
                    failures = 0
                except Exception as exc:  # network, block page, changed payload: retry later
                    failures += 1
                    self.last_error = f"{type(exc).__name__}: {exc}"[:200]
                    logger.warning("Filings poll failed (%d in a row): %s", failures, self.last_error)
                # Back off when NSE refuses, so a block is not hammered.
                next_poll = time.monotonic() + min(POLL_SECONDS * (2 ** min(failures, 4)), 900.0)
                if not failures:
                    try:
                        self.totals["sized"] += size_pending()
                    except Exception as exc:
                        logger.warning("Filing sizing failed: %s", type(exc).__name__)
            # Tick quickly around the opening auction so the 9:08 reading is not a minute late.
            near_open = now.weekday() < 5 and clock(9, 5) <= now.time() < preopen.WINDOW_END
            stop.wait(10.0 if near_open else max(1.0, min(POLL_SECONDS, next_poll - time.monotonic())))

    def _read_preopen(self, now: datetime) -> None:
        try:
            if preopen.done_today(now):
                return
            result = preopen.run(now)
        except Exception as exc:  # retried on the next tick while the window is open
            logger.warning("Pre-open read failed: %s", type(exc).__name__)
            return
        if result.get("status") == "done":
            self.preopen = result
            logger.info("Pre-open read: %s", result)

    def poll_once(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(IST)
        want_events = time.time() - self._events_at >= EVENTS_EVERY_SECONDS
        payload = asyncio.run(fetch(events=want_events))
        rows = payload["announcements"]
        today = now.strftime("%d-%m-%Y")
        known = repo.known_filing_ids([str(row.get("seq_id")) for row in rows])
        # NSE returns the latest 20. If none of them is known, filings arrived
        # faster than the poll (or this is the first poll today): read the whole day.
        if rows and not known and self._caught_up_day != today:
            rows = asyncio.run(fetch(full_day=today))["announcements"] or rows
        self._caught_up_day = today
        result = ingest(rows, now=now, sizer=size_now)
        if want_events:
            repo.save_events([event for event in map(parse_event, payload["events"]) if event])
            self._events_at = time.time()
        self.cycles += 1
        self.last_ok_at = time.time()
        self.last_error = None
        self.totals["new"] += result["new"]
        self.totals["alerted"] += result["alerted"]
        return result


_poller: FilingsPoller | None = None


def get_filings_poller() -> FilingsPoller:
    global _poller
    if _poller is None:
        _poller = FilingsPoller()
    return _poller
