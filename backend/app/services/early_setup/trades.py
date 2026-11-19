"""Trade rules on daily bars, shared by the score's training target and the results report.

The entry is always a stop-entry order at the pivot: it fills at the pivot, or
at the open when the stock gaps over it. What differs is the exit. The rules
that keep the numbers honest:

* On the entry day a low at or under the stop counts as stopped. One daily bar
  cannot say whether that low came before or after the entry.
* On a later day an open at or under the stop exits at that open, not at the stop.
* When a bar touches both the stop and the target, the stop wins.
* A trade without enough bars after it has no result yet. It is left out, never guessed.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

# Round-trip cost of a delivery trade as a share of price: STT, charges and slippage.
DEFAULT_COST_PCT = 0.25
MAX_TRAIL_SESSIONS = 60

EXIT_RULES: tuple[str, ...] = ("hold5", "hold10", "target2r", "trail10", "trail20")
RULE_LABELS: dict[str, str] = {
    "hold5": "Sell after 5 sessions",
    "hold10": "Sell after 10 sessions",
    "target2r": "Sell at twice the risk, or after 10 sessions",
    "trail10": "Hold until a close under the 10-day average",
    "trail20": "Hold until a close under the 20-day average",
}
# The rule the score is trained on and the headline numbers use.
MAIN_RULE = "hold10"

Exit = tuple[float, int, str]


def _stop_price(opens: Sequence[float], lows: Sequence[float], j: int, at: int, stop: float) -> float | None:
    if j > at and opens[j] <= stop:
        return float(opens[j])
    if lows[j] <= stop:
        return float(stop)
    return None


def simulate_exit(
    rule: str,
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    at: int,
    fill: float,
    stop: float,
    *,
    average: Sequence[float] | None = None,
) -> Exit | None:
    """(exit price, bar index, reason) for a trade entered on bar ``at``, or None when it is still open.

    ``average`` is the moving average the two trailing rules watch, aligned with the bars.
    """
    n = len(closes)
    if at < 0 or at >= n:
        return None
    if rule in ("hold5", "hold10", "target2r"):
        last = at + (5 if rule == "hold5" else 10)
        target = fill + 2.0 * (fill - stop) if rule == "target2r" and fill > stop else None
        for j in range(at, min(last, n - 1) + 1):
            price = _stop_price(opens, lows, j, at, stop)
            if price is not None:
                return price, j, "stop"
            if target is not None:
                if j > at and opens[j] >= target:
                    return float(opens[j]), j, "target"
                if highs[j] >= target:
                    return float(target), j, "target"
        if last >= n:
            return None
        return float(closes[last]), last, "time"
    if rule in ("trail10", "trail20"):
        if average is None:
            raise ValueError(f"{rule} needs the moving average")
        last = at + MAX_TRAIL_SESSIONS
        for j in range(at, min(last, n - 1) + 1):
            price = _stop_price(opens, lows, j, at, stop)
            if price is not None:
                return price, j, "stop"
            if j > at and not np.isnan(average[j]) and closes[j] < average[j]:
                return float(closes[j]), j, "trail"
        if last >= n:
            return None
        return float(closes[last]), last, "time"
    raise ValueError(f"unknown exit rule: {rule}")


def net_return_pct(fill: float, exit_price: float, cost_pct: float = DEFAULT_COST_PCT) -> float:
    return (exit_price / fill - 1.0) * 100.0 - cost_pct


def portfolio(
    trades: list[dict[str, float]],
    *,
    max_positions: int = 10,
) -> dict[str, float | int | None]:
    """Run the trades through an account that holds at most ``max_positions`` at once.

    Each trade is ``{"entry": bar index, "exit": bar index, "ret_pct": net %, "score": rank}``
    on one shared calendar. Every position gets an equal slice of the account's
    realised value. When more setups trigger on a day than there are free slots,
    the higher scores are taken. Profit and loss is booked on the exit day, so the
    drawdown shown ignores swings inside open trades.
    """
    if not trades or max_positions <= 0:
        return {"trades_taken": 0, "skipped": 0, "return_pct": None, "max_drawdown_pct": None}
    by_entry: dict[int, list[dict[str, float]]] = {}
    for trade in trades:
        by_entry.setdefault(int(trade["entry"]), []).append(trade)
    equity = 1.0
    peak = 1.0
    worst = 0.0
    open_positions: list[tuple[int, float, float]] = []  # (exit bar, stake, return %)
    taken = skipped = 0
    for day in range(min(by_entry), int(max(trade["exit"] for trade in trades)) + 1):
        still_open = []
        for exit_day, stake, ret in open_positions:
            if exit_day <= day:
                equity += stake * ret / 100.0
            else:
                still_open.append((exit_day, stake, ret))
        open_positions = still_open
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
        for trade in sorted(by_entry.get(day, []), key=lambda item: -(item.get("score") or 0.0)):
            if len(open_positions) >= max_positions:
                skipped += 1
                continue
            taken += 1
            stake = equity / max_positions
            if int(trade["exit"]) <= day:  # stopped on the entry day
                equity += stake * trade["ret_pct"] / 100.0
                # The slot stays used for the day: the money was committed.
                open_positions.append((day + 1, 0.0, 0.0))
            else:
                open_positions.append((int(trade["exit"]), stake, float(trade["ret_pct"])))
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    for _, stake, ret in open_positions:
        equity += stake * ret / 100.0
    worst = min(worst, equity / max(peak, equity) - 1.0)
    return {
        "trades_taken": taken,
        "skipped": skipped,
        "return_pct": round((equity - 1.0) * 100.0, 2),
        "max_drawdown_pct": round(worst * 100.0, 2),
    }
