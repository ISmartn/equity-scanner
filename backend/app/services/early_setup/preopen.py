"""The opening auction, read at 9:08: which watchlist stocks are set to open at their pivot.

NSE collects orders from 9:00 and fixes each stock's opening price a little
after 9:07. That price is public about seven minutes before trading starts.
A watchlist stock set to open at or above its pivot will trigger in the first
seconds of the session, so this is the earliest the tool can know.

The reading is used only when NSE's own timestamp is from today's auction. On
a holiday, or before the auction is done, the endpoint still answers with the
last session's numbers, and acting on those would be acting on yesterday.
"""

from __future__ import annotations

import logging
from datetime import datetime, time as clock
from typing import Any, Callable

from ...db.store import TimelineStore
from ..live_scan.clocks import IST
from . import nse, repo
from .live import _gap_limit_pct, send_telegram
from .repo import WatchEntry

logger = logging.getLogger(__name__)

AUCTION_DONE = clock(9, 7)
WINDOW_START = clock(9, 8, 10)
WINDOW_END = clock(9, 15)
NEAR_PCT = 1.0
_RANK = {"preopen_above": 0, "preopen_gap": 1, "preopen_near": 2, "preopen_fail": 3}
LABELS = {
    "preopen_above": "Set to open above the pivot",
    "preopen_gap": "Set to gap well over the pivot",
    "preopen_near": "Set to open just under the pivot",
    "preopen_fail": "Set to open under the stop",
}


def in_window(now: datetime) -> bool:
    return now.weekday() < 5 and WINDOW_START <= now.time() < WINDOW_END


def scan(rows: list[dict[str, Any]], entries: list[WatchEntry], session_date: str) -> list[dict[str, Any]]:
    """Each active setup against its indicative opening price. Stocks far from the pivot are left out."""
    by_ticker = {row["ticker"]: row for row in rows}
    daily_pivots = {entry.ticker: entry.pivot for entry in entries if entry.timeframe == "daily"}
    found: list[dict[str, Any]] = []
    for entry in entries:
        row = by_ticker.get(entry.ticker)
        if row is None or entry.status != "active":
            continue
        # The same base on both lists is one event.
        same = daily_pivots.get(entry.ticker)
        if entry.timeframe == "weekly" and same and abs(entry.pivot / same - 1.0) < 0.001:
            continue
        price = float(row["iep"])
        gap = (price / entry.pivot - 1.0) * 100.0
        if price <= entry.stop:
            state = "preopen_fail"
        elif price > entry.pivot:
            state = "preopen_gap" if gap > _gap_limit_pct(entry.features.get("atr20_pct")) else "preopen_above"
        elif gap >= -NEAR_PCT:
            state = "preopen_near"
        else:
            continue
        normal = entry.features.get("avg_volume_20")
        found.append(
            {
                "session_date": session_date,
                "ticker": entry.ticker,
                "timeframe": entry.timeframe,
                "company_name": entry.company_name,
                "iep": round(price, 2),
                "prev_close": row.get("prev_close"),
                "pivot": round(entry.pivot, 2),
                "stop": round(entry.stop, 2),
                "gap_to_pivot_pct": round(gap, 2),
                # The auction's matched quantity as a share of a normal full day's volume.
                "qty_pct": round(float(row["final_qty"]) / float(normal) * 100.0, 2) if normal else None,
                "state": state,
                "label": LABELS[state],
            }
        )
    found.sort(key=lambda item: (_RANK[item["state"]], -item["gap_to_pivot_pct"]))
    return found


def message(rows: list[dict[str, Any]], stamp: datetime) -> str:
    lines = [f"Pre-open {stamp:%H:%M} — watchlist stocks against their pivots"]
    for row in rows[:20]:
        weekly = " (weekly)" if row["timeframe"] == "weekly" else ""
        quantity = f", auction qty {row['qty_pct']:.1f}% of a normal day" if row.get("qty_pct") is not None else ""
        lines.append(
            f"{row['ticker']}{weekly}: {row['label'].lower()} — {row['iep']:.2f} vs pivot {row['pivot']:.2f} "
            f"({row['gap_to_pivot_pct']:+.1f}%), stop {row['stop']:.2f}{quantity}"
        )
    if len(rows) > 20:
        lines.append(f"…and {len(rows) - 20} more in the app")
    lines.append("These are indicative opening prices. Orders placed now join the queue for 9:15.")
    return "\n".join(lines)


def apply(
    payload: Any,
    now: datetime,
    *,
    store: TimelineStore | None = None,
    sender: Callable[[str], bool] = send_telegram,
) -> dict[str, Any]:
    """Use one pre-open reading: store the hits, record the alerts, send one summary message."""
    stamp, rows = nse.parse_preopen(payload)
    if stamp is None or stamp.date() != now.date() or stamp.time() < AUCTION_DONE:
        return {"status": "not_ready", "stamp": stamp.isoformat() if stamp else None}
    session_date = now.date().isoformat()
    db = repo.ensure_schema(store)
    hits = scan(rows, repo.list_entries(status="active", limit=10_000, store=db), session_date)
    repo.save_preopen(hits, db)
    fresh = 0
    for hit in hits:
        prefix = "weekly_" if hit["timeframe"] == "weekly" else ""
        recorded = repo.record_alert(
            {
                "session_date": session_date,
                "ticker": hit["ticker"],
                "state": prefix + hit["state"],
                "price": hit["iep"],
                "pivot": hit["pivot"],
                "stop": hit["stop"],
                "session_rvol": None,
                "message": f"{hit['ticker']} — {hit['label']}\nIndicative open {hit['iep']:.2f}, pivot {hit['pivot']:.2f}",
            },
            db,
        )
        fresh += 1 if recorded else 0
    delivered = bool(fresh and sender(message(hits, stamp)))
    repo.set_meta("preopen_done", session_date, db)
    return {"status": "done", "stamp": stamp.isoformat(), "stocks_read": len(rows), "hits": len(hits), "new": fresh, "delivered": delivered}


def run(now: datetime | None = None, *, store: TimelineStore | None = None) -> dict[str, Any]:
    """Fetch the auction and apply it. Raises on a network failure; the caller retries."""

    async def fetch() -> Any:
        async with nse.NseClient() as client:
            return await client.json(nse.PREOPEN_URL)

    return apply(nse.run(fetch()), now or datetime.now(IST), store=store)


def done_today(now: datetime, store: TimelineStore | None = None) -> bool:
    return repo.get_meta("preopen_done", store) == now.date().isoformat()
