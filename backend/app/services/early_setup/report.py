"""How the watchlist did: how often the break held, and what trading it returned.

A stock near its 20-day high crosses that high on most days by noise alone, so
"the pivot was crossed" proves nothing. The numbers that matter are whether
the close held above the pivot and what the trade returned under a stated exit
rule, after costs, with the stop applied.

"Lead" is the gap between a stop-entry at the pivot and the close of the same
day. The close is where an end-of-day scan first reports the breakout, so lead
is the part of the move that scan gives up. It is negative when breaks fade.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from ...db.store import TimelineStore
from . import candles as candle_data, repo
from .repo import WatchEntry
from .trades import DEFAULT_COST_PCT, EXIT_RULES, MAIN_RULE, RULE_LABELS, net_return_pct, portfolio, simulate_exit

_STATES = ("green", "amber", "red")


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def _share(part: int, whole: int) -> float | None:
    return round(part / whole * 100.0, 1) if whole else None


def _held(entry: WatchEntry) -> bool:
    return entry.status == "triggered" and bool(entry.resolved_close) and float(entry.resolved_close or 0) >= entry.pivot


class _Bars:
    """One stock's adjusted daily bars as plain lists, with the two trailing averages."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self.dates: list[str] = frame["date"].tolist()
        self.at = {day: i for i, day in enumerate(self.dates)}
        self.opens: list[float] = frame["open"].tolist()
        self.highs: list[float] = frame["high"].tolist()
        self.lows: list[float] = frame["low"].tolist()
        self.closes: list[float] = frame["close"].tolist()
        close = frame["close"].astype(float)
        self.averages = {
            "trail10": close.rolling(10, min_periods=10).mean().to_numpy(),
            "trail20": close.rolling(20, min_periods=20).mean().to_numpy(),
        }


def _bucket_rows(resolved: list[WatchEntry], main: dict[int, float]) -> list[dict[str, Any]]:
    """Outcome by the score the setup had on the day it was first listed."""
    scored = sorted((entry for entry in resolved if entry.first_score is not None), key=lambda e: e.first_score or 0)
    if len(scored) < 9:
        return []
    third = len(scored) // 3
    groups = (("Lowest third", scored[:third]), ("Middle third", scored[third : 2 * third]), ("Highest third", scored[2 * third :]))
    rows = []
    for label, group in groups:
        triggered = sum(1 for entry in group if entry.status == "triggered")
        returns = [main[id(entry)] for entry in group if id(entry) in main]
        rows.append(
            {
                "bucket": label,
                "score_from": round(float(group[0].first_score or 0), 1),
                "score_to": round(float(group[-1].first_score or 0), 1),
                "setups": len(group),
                "pivot_crossed_pct": _share(triggered, len(group)),
                "held_above_pivot_pct": _share(sum(1 for entry in group if _held(entry)), len(group)),
                "trades": len(returns),
                "avg_pct": _mean(returns),
                "win_rate_pct": _share(sum(1 for value in returns if value > 0), len(returns)),
            }
        )
    return rows


def watchlist_report(
    *,
    since: str | None = None,
    cost_pct: float = DEFAULT_COST_PCT,
    timeframe: str = "daily",
    max_positions: int = 10,
    store: TimelineStore | None = None,
) -> dict[str, Any]:
    db = repo.ensure_schema(store)
    entries = repo.list_entries(status=None, limit=200_000, since=since, timeframe=timeframe, store=db)
    if not entries:
        return {"setups": 0, "timeframe": timeframe, "message": "This list is empty. Build it first."}
    counts = {name: sum(1 for entry in entries if entry.status == name) for name in ("active", "triggered", "failed", "expired")}
    resolved = [entry for entry in entries if entry.status != "active"]
    triggered = [entry for entry in resolved if entry.status == "triggered"]

    first = min(entry.first_seen for entry in entries)
    last = str(db.stats().get("max_trade_date") or max(entry.last_checked for entry in entries))[:10]
    history_from = (date.fromisoformat(first) - timedelta(days=45)).isoformat()
    candles = candle_data.load_adjusted(history_from, last, db)
    wanted = {entry.ticker for entry in triggered}
    bars: dict[str, _Bars] = {
        str(ticker): _Bars(group.reset_index(drop=True))
        for ticker, group in candles[candles["ticker"].isin(wanted)].groupby("ticker", sort=False)
    }
    calendar = {day: i for i, day in enumerate(sorted(candles["date"].unique()))} if not candles.empty else {}
    health = {row["trade_date"]: row["state"] for row in repo.load_health(history_from, last, db)}
    health_days = sorted(health)

    sessions_to_trigger: list[float] = []
    lead: list[float] = []
    fwd5_pivot: list[float] = []
    fwd5_close: list[float] = []
    closed_under = 0
    results: dict[str, list[dict[str, float]]] = {rule: [] for rule in EXIT_RULES}
    still_open: dict[str, int] = {rule: 0 for rule in EXIT_RULES}
    main_by_entry: dict[int, float] = {}
    by_state: dict[str, list[float]] = {state: [] for state in _STATES}

    for entry in triggered:
        fill, close = entry.resolved_price, entry.resolved_close
        stock = bars.get(entry.ticker)
        if not fill or not close or stock is None or entry.resolved_date not in stock.at:
            continue
        at = stock.at[entry.resolved_date]
        stop, pivot = entry.stop, entry.pivot
        # The list may have been built before a later split. Bring its prices to today's scale.
        scale = stock.closes[at] / close
        if abs(scale - 1.0) > 0.02:
            fill, close, stop, pivot = fill * scale, close * scale, stop * scale, pivot * scale
        lead.append((close / fill - 1.0) * 100.0)
        if close < pivot:
            closed_under += 1
        if entry.first_seen in stock.at:
            sessions_to_trigger.append(float(at - stock.at[entry.first_seen]))
        if at + 5 < len(stock.closes):
            later = stock.closes[at + 5]
            fwd5_pivot.append((later / fill - 1.0) * 100.0)
            fwd5_close.append((later / close - 1.0) * 100.0)
        for rule in EXIT_RULES:
            outcome = simulate_exit(
                rule, stock.opens, stock.highs, stock.lows, stock.closes, at, fill, stop,
                average=stock.averages.get(rule),
            )
            if outcome is None:
                still_open[rule] += 1
                continue
            price, exit_at, reason = outcome
            net = net_return_pct(fill, price, cost_pct)
            results[rule].append(
                {
                    "ret_pct": net,
                    "sessions": float(exit_at - at),
                    "stopped": 1.0 if reason == "stop" else 0.0,
                    "entry": float(calendar.get(entry.resolved_date, 0)),
                    "exit": float(calendar.get(stock.dates[exit_at], 0)),
                    "score": float(entry.score or 0.0),
                }
            )
            if rule == MAIN_RULE:
                main_by_entry[id(entry)] = net
                # The market's state the evening before, which is what was known when the order went in.
                before = int(np.searchsorted(health_days, entry.resolved_date)) - 1
                if before >= 0:
                    by_state[health[health_days[before]]].append(net)

    exits = []
    for rule in EXIT_RULES:
        rows = results[rule]
        returns = [row["ret_pct"] for row in rows]
        exits.append(
            {
                "rule": rule,
                "label": RULE_LABELS[rule],
                "trades": len(rows),
                "still_open": still_open[rule],
                "avg_pct": _mean(returns),
                "median_pct": _median(returns),
                "win_rate_pct": _share(sum(1 for value in returns if value > 0), len(returns)),
                "avg_sessions": _mean([row["sessions"] for row in rows]),
                "stopped_pct": _share(int(sum(row["stopped"] for row in rows)), len(rows)),
                "portfolio": portfolio(rows, max_positions=max_positions),
            }
        )

    within_5 = sum(1 for value in sessions_to_trigger if value <= 5)
    return {
        "timeframe": timeframe,
        "since": since or first,
        "through": last,
        "setups": len(entries),
        "counts": counts,
        "resolved": len(resolved),
        "pivot_crossed_pct": _share(len(triggered), len(resolved)),
        "held_above_pivot_pct": _share(sum(1 for entry in resolved if _held(entry)), len(resolved)),
        "failed_rate_pct": _share(counts["failed"], len(resolved)),
        "expired_rate_pct": _share(counts["expired"], len(resolved)),
        "crossed_within_5_sessions_pct": _share(within_5, len(resolved)),
        "median_sessions_to_cross": _median(sessions_to_trigger),
        "after_breakout": {
            "pivot_crosses": len(triggered),
            "avg_lead_pct": _mean(lead),
            "median_lead_pct": _median(lead),
            "closed_back_under_pivot_pct": _share(closed_under, len(lead)),
            "measured_5_sessions": len(fwd5_pivot),
            "avg_5d_from_pivot_pct": _mean(fwd5_pivot),
            "avg_5d_from_breakout_close_pct": _mean(fwd5_close),
            "win_rate_5d_from_pivot_pct": _share(sum(1 for value in fwd5_pivot if value > 0), len(fwd5_pivot)),
            "win_rate_5d_from_breakout_close_pct": _share(sum(1 for value in fwd5_close if value > 0), len(fwd5_close)),
        },
        "cost_pct": cost_pct,
        "max_positions": max_positions,
        "main_rule": MAIN_RULE,
        "exits": exits,
        "by_health": [
            {
                "state": state,
                "trades": len(by_state[state]),
                "avg_pct": _mean(by_state[state]),
                "win_rate_pct": _share(sum(1 for value in by_state[state] if value > 0), len(by_state[state])),
            }
            for state in _STATES
        ],
        "by_score": _bucket_rows(resolved, main_by_entry),
    }
