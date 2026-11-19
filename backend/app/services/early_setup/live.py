"""Watchlist names against their pivots on the live feed, and the alerts that follow.

``rank_watch`` is a pure function of one quote. ``SetupAlerter`` turns state
changes into one alert per (session, stock, state) and hands delivery to its
own thread, so the 1 Hz ranker never waits on the network or the database.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from ..live_scan.ranker import session_rvol, testing_band
from . import repo

logger = logging.getLogger(__name__)

# Session volume against the normal pace for this time of day.
BREAKOUT_RVOL = 1.2
NEAR_PCT = 2.0
EXTENDED_PCT = 3.0
_STALE_TICK_SEC = 30.0
# Telegram allows about one message a second to a chat. The open can raise many at once.
_TELEGRAM_GAP_SEC = 1.1

_STATE_RANK = {
    "breakout": 0,
    "crossed_light": 1,
    "testing": 2,
    "near": 3,
    "gapped": 4,
    "extended": 5,
    "waiting": 6,
    "failed": 7,
}
_ALERT_STATES = ("testing", "breakout", "crossed_light", "gapped", "failed")
_STATE_LABELS = {
    "breakout": "Breaking out on volume",
    "crossed_light": "Over the pivot, volume light",
    "testing": "Testing the pivot",
    "near": "Near the pivot",
    "gapped": "Gapped over the pivot",
    "extended": "Already past the pivot",
    "waiting": "Waiting",
    "failed": "Lost the base low",
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _gap_limit_pct(atr_pct: float | None) -> float:
    """An open this far over the pivot leaves no entry near it."""
    return max(1.0, 0.5 * atr_pct) if atr_pct else 1.0


def rank_watch(
    quote: dict[str, Any],
    progress: float,
    now: float | None = None,
    *,
    weekly: bool = False,
) -> dict[str, Any] | None:
    """Where a watchlist stock stands against its pivot right now. None when it is not on that list.

    ``weekly`` reads the stock's weekly-list entry instead of its daily one.
    """
    if weekly:
        entry = quote.get("watch_weekly") or {}
    else:
        entry = {
            "pivot": quote.get("watch_pivot"),
            "stop": quote.get("watch_stop"),
            "score": quote.get("watch_score"),
            "days": quote.get("watch_days"),
            "first_seen": quote.get("watch_first_seen"),
        }
    pivot = _number(entry.get("pivot"))
    stop = _number(entry.get("stop"))
    ltp = _number(quote.get("ltp"))
    if pivot is None or stop is None or ltp is None:
        return None
    atr_pct = _number(quote.get("atr_pct"))
    day_open = _number(quote.get("day_open"))
    day_high = _number(quote.get("day_high"))
    rvol = session_rvol(float(quote.get("vtt") or 0), quote.get("avg_volume_20"), progress)
    distance_pct = (pivot - ltp) / pivot * 100.0
    tick_at = quote.get("last_tick_at")
    stale = now is not None and (tick_at is None or now - float(tick_at) > _STALE_TICK_SEC)

    if ltp <= stop:
        state = "failed"
        reason = f"Price is under the base low {stop:.2f}. The setup is off."
    elif ltp > pivot:
        gap_pct = (day_open / pivot - 1.0) * 100.0 if day_open else 0.0
        if gap_pct > _gap_limit_pct(atr_pct):
            state = "gapped"
            reason = f"Opened {gap_pct:.1f}% over the pivot {pivot:.2f}. Wait for a pullback; do not chase."
        elif -distance_pct >= EXTENDED_PCT:
            state = "extended"
            reason = f"Already {-distance_pct:.1f}% past the pivot {pivot:.2f}."
        elif rvol is not None and rvol >= BREAKOUT_RVOL:
            state = "breakout"
            reason = f"Crossed the pivot {pivot:.2f} with volume at {rvol:.1f}× the normal pace."
        else:
            state = "crossed_light"
            pace = f"{rvol:.1f}×" if rvol is not None else "unknown"
            reason = f"Over the pivot {pivot:.2f}, but volume pace is {pace}. Breaks on light volume often fail."
    elif ltp >= pivot * (1.0 - testing_band(atr_pct)):
        state = "testing"
        reason = f"Within {distance_pct:.2f}% of the pivot {pivot:.2f}."
    elif distance_pct <= NEAR_PCT:
        state = "near"
        reason = f"{distance_pct:.1f}% under the pivot {pivot:.2f}."
    else:
        state = "waiting"
        reason = f"{distance_pct:.1f}% under the pivot {pivot:.2f}."

    return {
        "symbol": quote["symbol"],
        "company_name": quote.get("company_name"),
        "sector": quote.get("sector"),
        "kind": quote.get("kind") or "equity",
        "segment": quote.get("segment") or "fno",
        "ltp": round(ltp, 2),
        "pivot": round(pivot, 2),
        "stop": round(stop, 2),
        "distance_pct": round(distance_pct, 2),
        "risk_pct": round((pivot - stop) / pivot * 100.0, 2),
        "session_rvol": round(rvol, 2) if rvol is not None else None,
        "day_high": round(day_high, 2) if day_high else None,
        "touched_pivot": bool(day_high and day_high > pivot),
        "state": state,
        "state_label": _STATE_LABELS[state],
        "reason": reason,
        "stale": stale,
        "list": "weekly" if weekly else "daily",
        "score": entry.get("score"),
        "days_in_base": entry.get("days"),
        "first_seen": entry.get("first_seen"),
    }


def rank_watchlist(quotes: list[dict[str, Any]], progress: float, now: float | None = None) -> list[dict[str, Any]]:
    """Every watchlist stock on the feed against its pivot, most urgent first.

    A stock on both lists with the same pivot is one event, so it gets one row,
    marked as also being a weekly base.
    """
    rows: list[dict[str, Any]] = []
    for quote in quotes:
        daily = rank_watch(quote, progress, now)
        weekly = rank_watch(quote, progress, now, weekly=True) if quote.get("watch_weekly") else None
        if daily is not None and weekly is not None and abs(weekly["pivot"] / daily["pivot"] - 1.0) < 0.001:
            daily["also_weekly"] = True
            weekly = None
        rows.extend(row for row in (daily, weekly) if row is not None)
    rows.sort(key=lambda row: (_STATE_RANK.get(str(row["state"]), 9), abs(float(row["distance_pct"]))))
    return rows


# ------------------------------------------------------------------ alerts


def alert_text(row: dict[str, Any], notes: list[str] | None = None) -> str:
    name = row.get("company_name") or row["symbol"]
    base = "weekly base" if row.get("list") == "weekly" else "weekly and daily base" if row.get("also_weekly") else None
    lines = [
        f"{row['symbol']} — {row['state_label']}" + (f" ({base})" if base else ""),
        f"{name}",
        f"Price {row['ltp']:.2f} · pivot {row['pivot']:.2f} · stop {row['stop']:.2f} ({row['risk_pct']:.1f}% risk)",
    ]
    if row.get("session_rvol") is not None:
        lines.append(f"Volume pace {row['session_rvol']:.1f}×")
    if row.get("days_in_base"):
        lines.append(f"{row['days_in_base']} sessions in the base")
    lines.append(str(row["reason"]))
    for note in notes or []:
        lines.append(f"Note: {note}")
    return "\n".join(lines)


def watch_notes(session_date: str, store: Any = None) -> dict[str, list[str]]:
    """Things worth knowing before acting on an alert, per ticker: flags, dated events, large buys."""
    from datetime import date, timedelta

    day = date.fromisoformat(session_date)
    notes: dict[str, list[str]] = {}
    for ticker, flags in repo.load_flags(store).items():
        for flag in flags:
            notes.setdefault(ticker, []).append(str(flag.get("detail") or flag["flag"]))
    for ticker, event in repo.upcoming_events(session_date, (day + timedelta(days=3)).isoformat(), store).items():
        notes.setdefault(ticker, []).append(f"{event['purpose']} on {event['event_date']}")
    for ticker, deals in repo.one_sided_buys((day - timedelta(days=10)).isoformat(), store).items():
        deal = deals[0]
        notes.setdefault(ticker, []).append(
            f"Large buy by {str(deal['client']).title()} on {deal['trade_date']} ({int(deal['quantity']):,} shares)"
        )
    return notes


def telegram_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_ALERT_CHAT_ID"))


def send_telegram(text: str, *, timeout: float = 8.0) -> bool:
    """Send through the bot named in the environment. False when unset or refused."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_ALERT_CHAT_ID")
    if not token or not chat_id:
        return False
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}).encode()
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return bool(json.loads(response.read().decode() or "{}").get("ok"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        # The URL holds the bot token, so log the error type only.
        logger.warning("Telegram alert was not delivered: %s", type(exc).__name__)
        return False


class SetupAlerter:
    """One alert per (session, stock, state). Delivery runs on its own daemon thread."""

    def __init__(
        self,
        session_date: str,
        *,
        sender: Callable[[str], bool] | None = None,
        seen: set[tuple[str, str]] | None = None,
        persist: bool = True,
        notes: dict[str, list[str]] | None = None,
    ) -> None:
        self.session_date = session_date
        self._notes = notes or {}
        self._sender = sender or send_telegram
        self._gap_sec = _TELEGRAM_GAP_SEC if sender is None else 0.0
        self._seen: set[tuple[str, str]] = set(seen or ())
        self._persist = persist
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=500)
        self._thread: threading.Thread | None = None
        self.raised = 0
        self.delivered = 0

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="setup-alerts", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        if self._thread is not None:
            self._queue.put(None)
            self._thread.join(timeout=5)
            self._thread = None

    def observe(self, rows: list[dict[str, Any]], *, tradable: bool) -> list[dict[str, Any]]:
        """Queue an alert for each stock that entered an alert state for the first time today."""
        if not tradable:
            return []
        raised: list[dict[str, Any]] = []
        for row in rows:
            state = str(row.get("state"))
            if state not in _ALERT_STATES or row.get("stale"):
                continue
            # The two lists alert separately: the same stock can test two different pivots.
            prefix = "weekly_" if row.get("list") == "weekly" else ""
            key = (str(row["symbol"]), prefix + state)
            if key in self._seen:
                continue
            # A break already alerted makes the "testing" alert noise, and a light
            # cross that later gains volume is still worth its own message.
            if state == "testing" and (
                (key[0], prefix + "breakout") in self._seen or (key[0], prefix + "crossed_light") in self._seen
            ):
                self._seen.add(key)
                continue
            self._seen.add(key)
            alert = {
                "session_date": self.session_date,
                "ticker": row["symbol"],
                "state": prefix + state,
                "price": row.get("ltp"),
                "pivot": row.get("pivot"),
                "stop": row.get("stop"),
                "session_rvol": row.get("session_rvol"),
                "message": alert_text(row, self._notes.get(str(row["symbol"]))),
            }
            raised.append(alert)
            self.raised += 1
            try:
                self._queue.put_nowait(alert)
            except queue.Full:
                logger.warning("Setup alert queue is full; dropped %s %s", alert["ticker"], state)
        return raised

    def _run(self) -> None:
        while True:
            alert = self._queue.get()
            if alert is None:
                return
            try:
                self._deliver(alert)
            except Exception:
                logger.exception("Setup alert failed for %s", alert.get("ticker"))

    def _deliver(self, alert: dict[str, Any]) -> None:
        if self._persist and not repo.record_alert(alert):
            return  # another process already recorded and sent it
        if self._sender(str(alert["message"])):
            self.delivered += 1
            if self._persist:
                repo.mark_alert_delivered(alert["session_date"], alert["ticker"], alert["state"])
            if self._gap_sec:
                time.sleep(self._gap_sec)
