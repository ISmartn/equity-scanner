from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ...db.store import TimelineStore, get_store
from ..market_calendar import expected_latest_session

IST = ZoneInfo("Asia/Kolkata")
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30

HORIZONS = ("t_m2", "t_m1", "t0", "t1", "t2", "t3", "t4", "t5")


def parse_posted_at(posted_at: str) -> datetime:
    raw = posted_at.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def event_session_date(posted_at: str | datetime) -> str:
    """Map post timestamp to NSE session date (after close → next weekday)."""
    dt = posted_at if isinstance(posted_at, datetime) else parse_posted_at(posted_at)
    d = dt.date()
    if dt.hour > MARKET_CLOSE_HOUR or (
        dt.hour == MARKET_CLOSE_HOUR and dt.minute >= MARKET_CLOSE_MINUTE
    ):
        d = d + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def _session_index(candles: list[dict[str, Any]], event_date: str) -> int | None:
    dates = [c["date"] for c in candles]
    if event_date in dates:
        return dates.index(event_date)
    # If holiday / missing bar, use next available session on/after event_date.
    for i, d in enumerate(dates):
        if d >= event_date:
            return i
    return None


def _cum_return(baseline_close: float, close: float) -> float | None:
    if baseline_close is None or close is None or baseline_close == 0:
        return None
    return ((close / baseline_close) - 1.0) * 100.0


def compute_reactions_for_ticker(
    store: TimelineStore,
    ticker: str,
    event_date: str,
    *,
    index_ticker: str = "NIFTY",
) -> list[dict[str, Any]]:
    # Pull a window of sessions around the event.
    start = (date.fromisoformat(event_date) - timedelta(days=20)).isoformat()
    end = (date.fromisoformat(event_date) + timedelta(days=25)).isoformat()
    candles = store.get_candles_for_ticker(ticker, from_date=start, to_date=end)
    if not candles:
        return []

    idx = _session_index(candles, event_date)
    if idx is None:
        return []

    # Baseline: previous session close when available, else event open.
    if idx > 0 and candles[idx - 1].get("close"):
        baseline = float(candles[idx - 1]["close"])
    elif candles[idx].get("open"):
        baseline = float(candles[idx]["open"])
    else:
        return []

    index_candles = store.get_candles_for_ticker(index_ticker, from_date=start, to_date=end)
    index_by_date = {c["date"]: c for c in index_candles}
    index_baseline = None
    if idx > 0:
        prev_date = candles[idx - 1]["date"]
        prev_idx = index_by_date.get(prev_date)
        if prev_idx and prev_idx.get("close"):
            index_baseline = float(prev_idx["close"])

    offsets = {
        "t_m2": -2,
        "t_m1": -1,
        "t0": 0,
        "t1": 1,
        "t2": 2,
        "t3": 3,
        "t4": 4,
        "t5": 5,
    }
    out: list[dict[str, Any]] = []
    for horizon, offset in offsets.items():
        j = idx + offset
        if j < 0 or j >= len(candles):
            continue
        bar = candles[j]
        close = bar.get("close")
        if close is None:
            continue
        close_f = float(close)
        # Pre-event horizons: return from that day's close to baseline (leading into event).
        if offset < 0:
            ret = _cum_return(close_f, baseline)
        else:
            ret = _cum_return(baseline, close_f)

        rel = None
        if index_baseline is not None:
            ib = index_by_date.get(bar["date"])
            if ib and ib.get("close") is not None:
                if offset < 0:
                    iret = _cum_return(float(ib["close"]), index_baseline)
                else:
                    iret = _cum_return(index_baseline, float(ib["close"]))
                if ret is not None and iret is not None:
                    rel = ret - iret

        out.append(
            {
                "horizon": horizon,
                "return_pct": ret,
                "rel_return_pct": rel,
                "close_price": close_f,
                "trade_date": bar["date"],
            }
        )
    return out


def build_reactions_for_event(store: TimelineStore | None, event: dict[str, Any]) -> list[dict[str, Any]]:
    store = store or get_store()
    ticker = event.get("ticker")
    event_date = event.get("event_date")
    if not ticker or not event_date:
        return []
    return compute_reactions_for_ticker(store, ticker, event_date)


def compute_and_store_reactions(
    store: TimelineStore | None = None,
    *,
    limit: int = 500,
    event_ids: list[int] | None = None,
) -> dict[str, int]:
    store = store or get_store()
    if event_ids:
        events = []
        for eid in event_ids:
            ev = store.get_news_event(eid)
            if ev:
                events.append(ev)
    else:
        events = store.list_events_missing_reactions(limit=limit)

    written = 0
    skipped = 0
    for ev in events:
        reactions = build_reactions_for_event(store, ev)
        if not reactions:
            skipped += 1
            continue
        store.replace_news_reactions(int(ev["id"]), reactions)
        written += 1
    return {"processed": len(events), "written": written, "skipped": skipped}


def aggregate_ticker_impact(events_with_reactions: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate avg / win-rate for t1,t3,t5 by sentiment."""
    buckets: dict[str, dict[str, list[float]]] = {}
    for ev in events_with_reactions:
        sentiment = (ev.get("sentiment") or "unknown").lower()
        buckets.setdefault(sentiment, {"t1": [], "t3": [], "t5": []})
        by_h = {r["horizon"]: r.get("return_pct") for r in ev.get("reactions") or []}
        for h in ("t1", "t3", "t5"):
            val = by_h.get(h)
            if val is not None:
                buckets[sentiment][h].append(float(val))

    def _stats(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"count": 0, "avg_return_pct": None, "win_rate": None}
        wins = sum(1 for v in values if v > 0)
        return {
            "count": len(values),
            "avg_return_pct": sum(values) / len(values),
            "win_rate": wins / len(values),
        }

    by_sentiment = {
        sent: {h: _stats(vals) for h, vals in horizons.items()}
        for sent, horizons in buckets.items()
    }
    all_vals = {"t1": [], "t3": [], "t5": []}
    for horizons in buckets.values():
        for h in all_vals:
            all_vals[h].extend(horizons[h])
    return {
        "overall": {h: _stats(v) for h, v in all_vals.items()},
        "by_sentiment": by_sentiment,
        "event_count": len(events_with_reactions),
        "as_of_session": expected_latest_session(),
    }
