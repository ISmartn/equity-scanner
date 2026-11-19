"""The setup watchlist: stocks still inside a base, carried from day to day.

There are two lists. The daily list holds quiet ranges just under the 20-day
high. The weekly list holds tighter, longer bases under a ten-week high. Both
are advanced the same way. Each evening every active entry is checked against
the new bar:

* the high crossed the pivot              -> ``triggered`` (a stop-entry at the pivot filled)
* the open or the close is under the stop -> ``failed``
* still in a base                         -> stays ``active``; pivot, stop and score refresh
* drifted out of the base                 -> ``expired`` after a few sessions, or once too old

Then stocks that newly qualify are added. Nothing here places or implies an
order: a triggered entry is the record that the pivot was crossed.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Mapping

import pandas as pd

from ...db.store import TimelineStore, get_store
from . import breadth, candles as candle_data, repo
from .features import (
    FEATURES,
    add_forward_outcomes,
    attach_cross_section,
    compute_feature_frame,
    sector_acceleration,
)
from .model import load_weights, score_frame, score_row
from .repo import WatchEntry

logger = logging.getLogger(__name__)

# Calendar days of history loaded before the first processed session (252 sessions and spare).
_HISTORY_DAYS = 420
GRACE_SESSIONS = 3
MAX_SESSIONS_IN_BASE = 40
_update_lock = threading.Lock()
_STORED = ("range10_pct", "atr20_pct", "avg_volume_20", "ret5_pct", "group_members", "group_broke", "w_tight_pct")


@dataclass(frozen=True)
class ListSpec:
    """Which columns of the feature frame one list reads."""

    timeframe: str
    candidate: str
    pivot: str
    stop: str
    distance: str
    max_active: int


DAILY = ListSpec("daily", "candidate", "pivot", "base_low", "dist_to_pivot_pct", 150)
WEEKLY = ListSpec("weekly", "w_candidate", "w_pivot", "w_stop", "w_dist_pct", 100)
SPECS: dict[str, ListSpec] = {spec.timeframe: spec for spec in (DAILY, WEEKLY)}


@dataclass
class Frames:
    by_ticker: dict[str, pd.DataFrame]
    meta: dict[str, dict[str, Any]]
    sessions: list[str]
    health: pd.DataFrame = field(default_factory=pd.DataFrame)


def build_frames(
    start: str,
    end: str,
    *,
    store: TimelineStore | None = None,
    forward: bool = False,
) -> Frames:
    """Feature frames for every stock, indexed by date, covering ``start..end`` with history behind."""
    db = store or get_store()
    history_from = (date.fromisoformat(start) - timedelta(days=_HISTORY_DAYS)).isoformat()
    candles = candle_data.load_adjusted(history_from, end, db)
    if candles.empty:
        return Frames({}, {}, [])
    bench = candle_data.benchmark(candles, history_from, end, db)
    oi_by_symbol = repo.load_futures_oi(history_from, end, db)
    delivery = repo.load_delivery(history_from, end, db)
    # The group a stock moves with: NSE's industry where it has one, else the profile's sector.
    industries = repo.load_industries(db)
    if industries:
        candles = candles.assign(sector=candles["ticker"].map(industries).fillna(candles["sector"]))
    accel_by_sector = sector_acceleration(candles)

    counts = candles.groupby("date")["ticker"].count()
    floor = float(counts.median()) * 0.5
    sessions = [str(day) for day, count in counts.items() if count >= floor and start <= str(day) <= end]

    by_ticker: dict[str, pd.DataFrame] = {}
    meta: dict[str, dict[str, Any]] = {}
    groups: dict[str, Any] = {}
    for ticker, group in candles.groupby("ticker", sort=False):
        if len(group) < 60:
            continue
        group = group.drop_duplicates(subset="date", keep="last").reset_index(drop=True)
        sector = group["sector"].iloc[-1]
        sector = str(sector) if isinstance(sector, str) and sector else None
        by_ticker[str(ticker)] = compute_feature_frame(
            group,
            bench_close=bench,
            sector_accel=accel_by_sector.get(sector) if sector else None,
            oi=oi_by_symbol.get(str(ticker)),
            delivery=delivery.get(str(ticker)),
        )
        groups[str(ticker)] = sector
        meta[str(ticker)] = {
            "company_name": group["company_name"].iloc[-1],
            "sector": sector,
            "instrument_token": group["instrument_token"].iloc[-1],
        }

    # Second pass: readings that need every stock's frame at once.
    health = breadth.market_health(by_ticker)
    heat = breadth.group_heat(by_ticker, groups)
    for ticker, frame in by_ticker.items():
        attach_cross_section(frame, health, heat.get(groups.get(ticker) or ""))
        if forward:
            frame = add_forward_outcomes(frame)
        by_ticker[ticker] = frame.set_index("date", drop=False)
    return Frames(by_ticker, meta, sorted(sessions), health)


def _score(row: Mapping[str, Any], spec: ListSpec, weights: Mapping[str, Any]) -> dict[str, Any]:
    if spec.distance == "dist_to_pivot_pct":
        return score_row(row, weights)
    reading = dict(row)
    reading["dist_to_pivot_pct"] = row[spec.distance]
    return score_row(reading, weights)


def _features_of(row: Mapping[str, Any], score: Mapping[str, Any]) -> dict[str, Any]:
    stored: dict[str, Any] = {}
    for name in (*FEATURES, *_STORED):
        value = row.get(name)
        if value is not None and pd.notna(value):
            stored[name] = round(float(value), 4)
    stored["contributions"] = score["contributions"]
    return stored


def advance_entry(entry: WatchEntry, row: Mapping[str, Any], day: str, weights: Mapping[str, Any]) -> None:
    """Apply one new daily bar to an active entry. ``row`` is that day's feature row."""
    if entry.status != "active" or day <= entry.last_checked:
        return
    spec = SPECS[entry.timeframe]
    entry.dirty = True
    entry.last_checked = day
    open_, high, close = float(row["open"]), float(row["high"]), float(row["close"])
    if open_ <= entry.stop:
        entry.status, entry.resolved_date = "failed", day
        entry.resolved_price, entry.resolved_close, entry.last_close = open_, close, close
        return
    if high > entry.pivot:
        entry.status, entry.resolved_date = "triggered", day
        entry.resolved_price, entry.resolved_close, entry.last_close = max(open_, entry.pivot), close, close
        return
    entry.last_close = close
    if close < entry.stop:
        entry.status, entry.resolved_date = "failed", day
        entry.resolved_price, entry.resolved_close = close, close
        return
    if bool(row[spec.candidate]):
        score = _score(row, spec, weights)
        entry.pivot = float(row[spec.pivot])
        entry.stop = float(row[spec.stop])
        entry.score = score["score"]
        entry.features = _features_of(row, score)
        entry.last_seen = day
        entry.days_in_base += 1
        entry.misses = 0
    else:
        entry.misses += 1
    if entry.misses > GRACE_SESSIONS or entry.days_in_base > MAX_SESSIONS_IN_BASE:
        entry.status, entry.resolved_date = "expired", day
        entry.resolved_price, entry.resolved_close = close, close


def _new_entry(
    ticker: str,
    row: Mapping[str, Any],
    day: str,
    meta: Mapping[str, Any],
    spec: ListSpec,
    weights: Mapping[str, Any],
) -> WatchEntry:
    score = _score(row, spec, weights)
    return WatchEntry(
        ticker=ticker,
        timeframe=spec.timeframe,
        instrument_token=meta.get("instrument_token"),
        company_name=meta.get("company_name"),
        sector=meta.get("sector"),
        pivot=float(row[spec.pivot]),
        stop=float(row[spec.stop]),
        first_seen=day,
        last_seen=day,
        last_checked=day,
        last_close=float(row["close"]),
        score=score["score"],
        first_score=score["score"],
        features=_features_of(row, score),
    )


def _match_price_scale(entry: WatchEntry, frame: pd.DataFrame) -> None:
    """Bring an entry's stored prices to the scale of today's frame.

    After a split or bonus the whole price history is rescaled, but an entry made
    before it still holds the old pivot and stop. Its last recorded close is
    compared with the frame's close for that same day; a mismatch is the rescale.
    """
    if not entry.last_close or entry.last_checked not in frame.index:
        return
    ratio = float(frame.at[entry.last_checked, "close"]) / float(entry.last_close)
    if not (ratio > 0) or abs(ratio - 1.0) <= 0.02:
        return
    entry.pivot *= ratio
    entry.stop *= ratio
    entry.last_close *= ratio
    entry.dirty = True


def run_sessions(
    frames: Frames,
    sessions: list[str],
    active: list[WatchEntry],
    *,
    weights: Mapping[str, Any] | None = None,
    specs: tuple[ListSpec, ...] = (DAILY, WEEKLY),
) -> list[WatchEntry]:
    """Advance ``active`` through ``sessions`` in order and add new setups. Returns every entry touched."""
    use = weights or load_weights()
    entries = list(active)
    live: dict[tuple[str, str], WatchEntry] = {
        (entry.timeframe, entry.ticker): entry for entry in entries if entry.status == "active"
    }

    candidates: dict[tuple[str, str], list[tuple[float, str]]] = {}
    wanted = set(sessions)
    for ticker, frame in frames.by_ticker.items():
        in_range = frame["date"].isin(wanted)
        for spec in specs:
            hits = frame[frame[spec.candidate] & in_range]
            if hits.empty:
                continue
            reading = hits if spec.distance == "dist_to_pivot_pct" else hits.assign(dist_to_pivot_pct=hits[spec.distance])
            for day, value in zip(hits["date"], score_frame(reading, use)):
                candidates.setdefault((spec.timeframe, str(day)), []).append((float(value), ticker))

    for entry in live.values():
        frame = frames.by_ticker.get(entry.ticker)
        if frame is not None:
            _match_price_scale(entry, frame)

    for day in sessions:
        resolved_today: set[tuple[str, str]] = set()
        for key, entry in list(live.items()):
            frame = frames.by_ticker.get(entry.ticker)
            if frame is None or day not in frame.index:
                continue
            advance_entry(entry, frame.loc[day], day, use)
            if entry.status != "active":
                resolved_today.add(key)
                del live[key]
        for spec in specs:
            room = spec.max_active - sum(1 for timeframe, _ in live if timeframe == spec.timeframe)
            for _, ticker in sorted(candidates.get((spec.timeframe, day), []), reverse=True):
                if room <= 0:
                    break
                key = (spec.timeframe, ticker)
                if key in live or key in resolved_today:
                    continue
                entry = _new_entry(ticker, frames.by_ticker[ticker].loc[day], day, frames.meta.get(ticker, {}), spec, use)
                entries.append(entry)
                live[key] = entry
                room -= 1
    return entries


def update_watchlist(
    *,
    through: str | None = None,
    from_date: str | None = None,
    rebuild: bool = False,
    refresh_data: bool = False,
    store: TimelineStore | None = None,
) -> dict[str, Any]:
    """Bring the stored watchlist up to ``through`` (default: the last completed session with candles).

    Sessions already processed are skipped, and sessions missed since the last
    run are replayed in order, so running it late loses nothing. ``rebuild``
    clears the list and replays from ``from_date``. ``refresh_data`` first tops
    up delivery, deals, flags and corporate actions from NSE. One update runs at a time.
    """
    with _update_lock:
        return _update_watchlist(
            through=through, from_date=from_date, rebuild=rebuild, refresh_data=refresh_data, store=store
        )


def _update_watchlist(
    *,
    through: str | None,
    from_date: str | None,
    rebuild: bool,
    refresh_data: bool,
    store: TimelineStore | None,
) -> dict[str, Any]:
    db = repo.ensure_schema(store)
    end = through or db.stats().get("max_trade_date")
    if not end:
        return {"status": "no_data", "message": "No daily candles in the database yet."}
    end = str(end)[:10]
    if not through:
        # A bar for a session still trading is partial. Processing it would resolve
        # setups on half a day and then ignore the finished bar.
        from ..live_scan import clocks

        end = min(end, clocks.required_daily_session())
    market: dict[str, Any] | None = None
    if refresh_data:
        from . import market_data

        market = market_data.refresh(through=end, store=db)
    if rebuild:
        repo.clear_watchlist(db)
    done_through = None if rebuild else repo.get_meta("processed_through", db)

    def current() -> dict[str, Any]:
        return {
            "status": "current",
            "processed_through": done_through,
            "counts": repo.status_counts(db),
            "market_data": market,
        }

    if done_through and done_through >= end and not from_date:
        return current()
    if from_date:
        start = from_date
    elif done_through:
        start = (date.fromisoformat(done_through) + timedelta(days=1)).isoformat()
    else:
        start = end
    if start > end:
        return current()

    frames = build_frames(start, end, store=db)
    sessions = [day for day in frames.sessions if not done_through or day > done_through or rebuild]
    if not sessions:
        return {"status": "no_sessions", "message": f"No trading sessions between {start} and {end}.", "market_data": market}

    active = repo.list_entries(status="active", limit=10_000, store=db)
    entries = run_sessions(frames, sessions, active)
    saved = repo.save_entries(entries, db)
    if len(frames.health):
        covered = frames.health[(frames.health.index >= sessions[0]) & (frames.health.index <= sessions[-1])]
        repo.save_health(
            [
                {
                    "trade_date": str(day),
                    "stocks": int(row["stocks"]),
                    "pct_above_50": None if pd.isna(row["pct_above_50"]) else round(float(row["pct_above_50"]), 2),
                    "new_highs": int(row["new_highs"]),
                    "new_lows": int(row["new_lows"]),
                    "breadth_chg": None if pd.isna(row["breadth_chg"]) else round(float(row["breadth_chg"]), 2),
                    "state": str(row["state"]),
                }
                for day, row in covered.iterrows()
            ],
            db,
        )
    repo.set_meta("processed_through", sessions[-1], db)
    weights = load_weights()
    logger.info("Setup watchlist updated through %s: %d sessions, %d rows written", sessions[-1], len(sessions), saved)
    return {
        "status": "updated",
        "processed_from": sessions[0],
        "processed_through": sessions[-1],
        "sessions": len(sessions),
        "rows_written": saved,
        "counts": repo.status_counts(db),
        "counts_by_list": {name: repo.status_counts(db, name) for name in SPECS},
        "weights_fitted": bool(weights.get("fitted")),
        "market_data": market,
    }


def build_dataset(start: str, end: str, *, store: TimelineStore | None = None) -> pd.DataFrame:
    """Every (stock, day) on the daily list between two dates, with features and what happened next."""
    frames = build_frames(start, end, store=store, forward=True)
    wanted = set(frames.sessions)
    parts: list[pd.DataFrame] = []
    for ticker, frame in frames.by_ticker.items():
        hits = frame[frame["candidate"] & frame["date"].isin(wanted)]
        if hits.empty:
            continue
        part = hits.reset_index(drop=True).copy()
        part.insert(0, "ticker", ticker)
        parts.append(part)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)
