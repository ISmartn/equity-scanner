"""Record each live entry, stop, and exit, then follow the price after that plan.

The day leg is ``pending -> open -> target | stopped | closed`` or ``pending -> cancelled``.
The swing leg is the multi-session target on the same entry and stop. It follows the
same path, except the cash close does not flatten it: an open swing stays open until
its own target or the stop, including on a later session.

Rules that keep the record honest:

* Transitions read the whole price path since the last evaluation (first,
  high, low, last), not one sampled print, so a wick between samples counts.
* When one window touches both the stop and the target (or the entry and
  the stop), the worse outcome is assumed. The record never flatters itself.
* The fill is the entry level only when price crossed it continuously. If
  the first print of the window, or the first sighting of the plan, is
  already through the entry, the fill is that print.
* A plan first seen beyond its entry is recorded only if the board confirms
  it (Buy or Sell inside the entry window). Late or blocked breaks are not
  back-filled at a price nobody could have traded.
* Nothing is created or advanced on stale quotes or outside 09:15–15:30.
  Records are keyed by (session, symbol, side), so restarts and reconnects
  reload the same plan rather than opening a duplicate.
* At 15:30 the day leg closes at the last price. The swing leg stays open and
  is reloaded on the next session. A plan that never reached its entry is cancelled.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

_TERMINAL = {"target", "stopped", "cancelled", "closed"}
_STATUS_RANK = {"open": 0, "target": 1, "stopped": 2, "closed": 3, "pending": 4, "cancelled": 5}
_STATUS_LABELS = {
    "pending": "Waiting",
    "open": "Open",
    "target": "Target",
    "stopped": "Stopped",
    "closed": "Session end",
    "cancelled": "Cancelled",
}
_SOFT_FLUSH_SEC = 10.0


class PathLike(Protocol):
    first: float
    high: float
    low: float
    last: float


def plan_side(call: Mapping[str, Any]) -> str | None:
    """Buy plans exit above the entry. Sell plans exit below it."""
    entry = _price(call.get("entry"))
    exit_price = _price(call.get("exit"))
    stop = _price(call.get("stop"))
    if entry is None or exit_price is None or stop is None:
        return None
    if exit_price > entry:
        return "buy"
    if exit_price < entry:
        return "sell"
    return None


def _price(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _result_pct(side: str, entry: float, price: float) -> float:
    move = (price - entry) / entry * 100.0
    return move if side == "buy" else -move


def _favourable(side: str, high: float, low: float) -> float:
    return high if side == "buy" else low


def _adverse(side: str, high: float, low: float) -> float:
    return low if side == "buy" else high


def _through(side: str, price: float, level: float) -> bool:
    """Price is at or beyond ``level`` in the trade's favourable direction."""
    return price >= level if side == "buy" else price <= level


def _against(side: str, price: float, level: float) -> bool:
    """Price is at or beyond ``level`` in the trade's adverse direction."""
    return price <= level if side == "buy" else price >= level


def _fill(side: str, entry: float, first: float | None) -> float:
    if first is not None and _through(side, first, entry):
        return first
    return entry


def _close(record: dict[str, Any], status: str, price: float, now: str) -> None:
    fill = float(record.get("fill_price") or record["entry"])
    record["status"] = status
    record["closed_at"] = now
    record["result_pct"] = round(_result_pct(str(record["side"]), fill, price), 2)


def _swing_exit(record: dict[str, Any]) -> float | None:
    return _price(record.get("swing_exit"))


def _swing_live(record: dict[str, Any]) -> bool:
    """A filled multi-session target still has a price to resolve."""
    if _swing_exit(record) is None:
        return False
    return str(record.get("swing_status") or "") == "open"


def _planned_swing(side: str, entry: float, stop: float, call: Mapping[str, Any]) -> float:
    """Use the call's multi-session target, or four times the stop distance."""
    given = _price(call.get("swing_exit"))
    if given is not None and ((side == "buy" and given > entry) or (side == "sell" and given < entry)):
        return given
    risk = abs(entry - stop)
    return entry + 4.0 * risk if side == "buy" else entry - 4.0 * risk


def _swing_label(record: dict[str, Any]) -> str | None:
    status = record.get("swing_status")
    if not status:
        return None
    if status == "open" and record.get("status") in {"closed", "target"}:
        return "Carried"
    return _STATUS_LABELS.get(str(status), str(status))


def _mark_swing(record: dict[str, Any], side: str, price: float) -> None:
    if not _swing_live(record):
        return
    fill = float(record.get("fill_price") or record["entry"])
    record["swing_result_pct"] = round(_result_pct(side, fill, price), 2)


def _close_swing(record: dict[str, Any], status: str, price: float, now: str) -> None:
    fill = float(record.get("fill_price") or record["entry"])
    record["swing_status"] = status
    record["swing_closed_at"] = now
    record["swing_result_pct"] = round(_result_pct(str(record["side"]), fill, price), 2)


def _cancel_swing(record: dict[str, Any], now: str) -> None:
    if _swing_exit(record) is None or str(record.get("swing_status") or "pending") in _TERMINAL:
        return
    record["swing_status"] = "cancelled"
    record["swing_closed_at"] = now
    record["swing_result_pct"] = None


def _track_extremes(record: dict[str, Any], side: str, high: float, low: float) -> None:
    fill = float(record.get("fill_price") or record["entry"])
    best = record.get("best_price")
    worst = record.get("worst_price")
    fav = _favourable(side, high, low)
    adv = _adverse(side, high, low)
    if best is None:
        best = fav
    else:
        best = max(float(best), fav) if side == "buy" else min(float(best), fav)
    if worst is None:
        worst = adv
    else:
        worst = min(float(worst), adv) if side == "buy" else max(float(worst), adv)
    record["best_price"] = best
    record["worst_price"] = worst
    record["mfe_pct"] = round(_result_pct(side, fill, best), 2)
    record["mae_pct"] = round(_result_pct(side, fill, worst), 2)


def advance_plan(
    record: dict[str, Any],
    ltp: float,
    now: str,
    *,
    high: float | None = None,
    low: float | None = None,
    first: float | None = None,
) -> bool:
    """Move one saved plan through one price window. Levels stay at the prices first shown.

    The day leg stops changing once it is target, stopped, closed, or cancelled.
    The swing leg keeps following price until its own target or the same stop.
    Returns True when the status or the excursion changed; a last-price-only
    update returns False so the writer can batch it lazily.
    """
    if record["status"] in _TERMINAL and not _swing_live(record):
        return False
    before = (
        record["status"],
        record.get("mfe_pct"),
        record.get("mae_pct"),
        record.get("swing_status"),
    )
    side = str(record["side"])
    entry = float(record["entry"])
    stop = float(record["stop"])
    exit_price = float(record["exit_price"])
    hi = max(ltp, high) if high is not None else ltp
    lo = min(ltp, low) if low is not None else ltp
    status_before = record["status"]
    record["last_price"] = ltp
    record["updated_at"] = now

    if record["status"] == "pending":
        fav = _favourable(side, hi, lo)
        adv = _adverse(side, hi, lo)
        if _through(side, fav, entry):
            fill = _fill(side, entry, first)
            record["status"] = "open"
            record["entry_at"] = now
            record["fill_price"] = fill
            record["best_price"] = None
            record["worst_price"] = None
            if _swing_exit(record) is not None:
                record["swing_status"] = "open"
        elif _against(side, adv, stop):
            record["status"] = "cancelled"
            record["closed_at"] = now
            record["result_pct"] = None
            _cancel_swing(record, now)
            return True

    if record["status"] == "open":
        _track_extremes(record, side, hi, lo)
        adv = _adverse(side, hi, lo)
        fav = _favourable(side, hi, lo)
        stop_hit = _against(side, adv, stop)
        target_hit = _through(side, fav, exit_price)
        swing_level = _swing_exit(record)
        swing_hit = swing_level is not None and _through(side, fav, swing_level)
        if stop_hit:
            # Both touched in one window: assume the stop came first.
            gapped = first is not None and status_before == "open" and _against(side, first, stop)
            price = first if gapped and first is not None else stop
            _close(record, "stopped", price, now)
            if swing_level is not None and str(record.get("swing_status") or "") not in _TERMINAL:
                _close_swing(record, "stopped", price, now)
        elif target_hit:
            _close(record, "target", exit_price, now)
            if swing_hit and swing_level is not None:
                _close_swing(record, "target", swing_level, now)
            elif str(record.get("swing_status") or "") == "open":
                _mark_swing(record, side, ltp)
        else:
            fill = float(record.get("fill_price") or entry)
            record["result_pct"] = round(_result_pct(side, fill, ltp), 2)
            if str(record.get("swing_status") or "") == "open":
                _mark_swing(record, side, ltp)
    elif _swing_live(record):
        # Day result stays as booked. The multi-session target is still working.
        _track_extremes(record, side, hi, lo)
        adv = _adverse(side, hi, lo)
        fav = _favourable(side, hi, lo)
        swing_level = float(_swing_exit(record) or 0)
        if _against(side, adv, stop):
            gapped = first is not None and _against(side, first, stop)
            _close_swing(record, "stopped", first if gapped and first is not None else stop, now)
        elif _through(side, fav, swing_level):
            _close_swing(record, "target", swing_level, now)
        else:
            _mark_swing(record, side, ltp)

    return before != (
        record["status"],
        record.get("mfe_pct"),
        record.get("mae_pct"),
        record.get("swing_status"),
    )


def _restore_extremes(record: dict[str, Any]) -> None:
    """Rebuild the in-memory high and low from the saved excursion after a restart."""
    if record.get("best_price") is not None or record.get("mfe_pct") is None or not record.get("entry"):
        return
    base = float(record.get("fill_price") or record["entry"])
    mfe = float(record["mfe_pct"])
    mae = float(record["mae_pct"]) if record.get("mae_pct") is not None else mfe
    if record.get("side") == "buy":
        record["best_price"] = base * (1.0 + mfe / 100.0)
        record["worst_price"] = base * (1.0 + mae / 100.0)
    else:
        record["best_price"] = base * (1.0 - mfe / 100.0)
        record["worst_price"] = base * (1.0 - mae / 100.0)


def public_row(record: dict[str, Any]) -> dict[str, Any]:
    status = str(record["status"])
    side = str(record["side"])
    return {
        "session_date": record["session_date"],
        "symbol": record["symbol"],
        "company_name": record.get("company_name"),
        "kind": record.get("kind") or "equity",
        "segment": record.get("segment") or "fno",
        "side": side,
        "side_label": "Buy" if side == "buy" else "Sell",
        "status": status,
        "status_label": _STATUS_LABELS.get(status, status),
        "entry": record["entry"],
        "fill_price": record.get("fill_price"),
        "stop": record["stop"],
        "exit": record["exit_price"],
        "swing_exit": record.get("swing_exit"),
        "swing_status": record.get("swing_status"),
        "swing_status_label": _swing_label(record),
        "swing_result_pct": record.get("swing_result_pct"),
        "last_price": record.get("last_price"),
        "result_pct": record.get("result_pct"),
        "mfe_pct": record.get("mfe_pct"),
        "mae_pct": record.get("mae_pct"),
        "opened_at": record.get("opened_at"),
        "entry_at": record.get("entry_at"),
        "closed_at": record.get("closed_at"),
        "swing_closed_at": record.get("swing_closed_at"),
    }


_PERSIST_KEYS = (
    "session_date", "symbol", "side", "kind", "company_name", "stance", "entry", "stop",
    "exit_price", "status", "opened_at", "entry_at", "closed_at", "last_price", "result_pct",
    "mfe_pct", "mae_pct", "updated_at", "fill_price",
    "swing_exit", "swing_status", "swing_result_pct", "swing_closed_at", "segment",
)


def _persist_row(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in _PERSIST_KEYS}


class CallJournal:
    """Owned by the ranker thread. Readers get copies through ``rows`` and ``summary``."""

    def __init__(self, session_date: str) -> None:
        self.session_date = session_date
        self._rows: dict[tuple[str, str], dict[str, Any]] = {}
        self._dirty: set[tuple[str, str]] = set()
        self._soft: set[tuple[str, str]] = set()
        self._last_flush = 0.0
        self._last_soft_flush = 0.0
        self.session_closed = False

    def load(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            symbol = str(row.get("symbol") or "")
            side = str(row.get("side") or "")
            if not symbol or not side:
                continue
            record = dict(row)
            _restore_extremes(record)
            key = (symbol, side)
            existing = self._rows.get(key)
            if existing is not None and _swing_live(existing) and not _swing_live(record):
                continue
            self._rows[key] = record
        self._dirty = self._settle_carried()
        self._soft.clear()

    def advance(
        self,
        calls: list[dict[str, Any]],
        now: str,
        *,
        windows: list[Mapping[str, PathLike]] | None = None,
        tradable: bool = True,
    ) -> None:
        """Advance open plans through every price window, then record new plans.

        ``windows`` are the book's closed path windows, oldest first. Without
        them (tests, legacy callers) each call's ``ltp`` is the whole window.
        """
        if not tradable or self.session_closed:
            return
        if windows is not None:
            self._advance_windows(windows, now)
        for call in calls:
            side = plan_side(call)
            ltp = _price(call.get("ltp"))
            if side is None or ltp is None or call.get("stale"):
                continue
            key = (str(call["symbol"]), side)
            record = self._rows.get(key)
            if record is None:
                self._create(key, call, side, ltp, now)
                continue
            if record["status"] in _TERMINAL and not _swing_live(record):
                continue
            if record["status"] not in _TERMINAL:
                if call.get("company_name"):
                    record["company_name"] = call["company_name"]
                if call.get("stance"):
                    record["stance"] = call["stance"]
            if windows is None:
                self._step(key, record, ltp, now, None, None, None)

    def _advance_windows(self, windows: list[Mapping[str, PathLike]], now: str) -> None:
        live = [
            (key, record)
            for key, record in self._rows.items()
            if record["status"] not in _TERMINAL or _swing_live(record)
        ]
        if not live:
            return
        for window_set in windows:
            for key, record in live:
                window = window_set.get(key[0])
                if window is None or (record["status"] in _TERMINAL and not _swing_live(record)):
                    continue
                self._step(key, record, window.last, now, window.high, window.low, window.first)

    def _step(
        self,
        key: tuple[str, str],
        record: dict[str, Any],
        ltp: float,
        now: str,
        high: float | None,
        low: float | None,
        first: float | None,
    ) -> None:
        if advance_plan(record, ltp, now, high=high, low=low, first=first):
            self._dirty.add(key)
        else:
            self._soft.add(key)

    def _create(self, key: tuple[str, str], call: dict[str, Any], side: str, ltp: float, now: str) -> None:
        entry = float(call["entry"])
        stop = float(call["stop"])
        exit_price = float(call["exit"])
        stance = str(call.get("stance") or "")
        through = _through(side, ltp, entry)
        if not through:
            if _against(side, ltp, stop):
                return
            status = "pending"
        elif stance in {"buy", "sell"}:
            status = "open"
        else:
            return
        swing_exit = _planned_swing(side, entry, stop, call)
        record: dict[str, Any] = {
            "session_date": self.session_date,
            "symbol": key[0],
            "side": side,
            "kind": call.get("kind") or "equity",
            "segment": call.get("segment") or "fno",
            "company_name": call.get("company_name"),
            "stance": stance or None,
            "entry": entry,
            "stop": stop,
            "exit_price": exit_price,
            "swing_exit": swing_exit,
            "swing_status": "open" if status == "open" else "pending",
            "swing_result_pct": 0.0 if status == "open" else None,
            "swing_closed_at": None,
            "status": status,
            "opened_at": now,
            "entry_at": now if status == "open" else None,
            "closed_at": None,
            "fill_price": ltp if status == "open" else None,
            "last_price": ltp,
            "best_price": None,
            "worst_price": None,
            "result_pct": None,
            "mfe_pct": None,
            "mae_pct": None,
            "updated_at": now,
        }
        if status == "open":
            _track_extremes(record, side, ltp, ltp)
            record["result_pct"] = 0.0
        self._rows[key] = record
        self._dirty.add(key)

    def close_session(self, now: str) -> int:
        """Session end: the day leg flattens. An open swing stays open for the next session."""
        changed = 0
        for key, record in self._rows.items():
            if record["status"] == "open":
                last = _price(record.get("last_price")) or float(record.get("fill_price") or record["entry"])
                _close(record, "closed", last, now)
                _mark_swing(record, str(record["side"]), last)
            elif record["status"] == "pending":
                record["status"] = "cancelled"
                record["closed_at"] = now
                record["result_pct"] = None
                _cancel_swing(record, now)
            else:
                continue
            record["updated_at"] = now
            self._dirty.add(key)
            changed += 1
        self.session_closed = True
        return changed

    def _settle_carried(self) -> set[tuple[str, str]]:
        """A prior session's day leg is over. Freeze it so today's prices cannot rewrite it."""
        dirty: set[tuple[str, str]] = set()
        for key, record in self._rows.items():
            if str(record.get("session_date") or "") >= self.session_date:
                continue
            if record["status"] == "open":
                last = _price(record.get("last_price")) or float(record.get("fill_price") or record["entry"])
                _close(record, "closed", last, str(record.get("updated_at") or record.get("opened_at") or ""))
                dirty.add(key)
            elif record["status"] == "pending":
                record["status"] = "cancelled"
                record["closed_at"] = record.get("updated_at")
                record["result_pct"] = None
                _cancel_swing(record, str(record.get("updated_at") or ""))
                dirty.add(key)
        return dirty

    def rows(self) -> list[dict[str, Any]]:
        stored = [public_row(record) for record in self._rows.values()]
        stored.sort(
            key=lambda row: (
                0 if row.get("swing_status") == "open" else 1,
                _STATUS_RANK.get(str(row["status"]), 9),
                -(abs(float(row["result_pct"])) if row.get("result_pct") is not None else -1),
                str(row["symbol"]),
            )
        )
        return stored

    def persist_rows(self) -> list[dict[str, Any]]:
        return [_persist_row(record) for record in self._rows.values()]

    def summary(self) -> dict[str, Any]:
        counts = {name: 0 for name in _STATUS_RANK}
        swing_counts = {name: 0 for name in ("pending", "open", "target", "stopped", "cancelled")}
        closed_results: list[float] = []
        swing_results: list[float] = []
        for record in self._rows.values():
            status = str(record.get("status") or "")
            counts[status] = counts.get(status, 0) + 1
            if status in {"target", "stopped", "closed"} and record.get("result_pct") is not None:
                closed_results.append(float(record["result_pct"]))
            swing = str(record.get("swing_status") or "")
            if swing in swing_counts:
                swing_counts[swing] += 1
            if swing in {"target", "stopped"} and record.get("swing_result_pct") is not None:
                swing_results.append(float(record["swing_result_pct"]))
        wins = sum(1 for result in closed_results if result > 0)
        swing_wins = sum(1 for result in swing_results if result > 0)
        return {
            "plans": len(self._rows),
            "pending": counts["pending"],
            "open": counts["open"],
            "target": counts["target"],
            "stopped": counts["stopped"],
            "closed": counts["closed"],
            "cancelled": counts["cancelled"],
            "win_rate_pct": round(wins / len(closed_results) * 100.0, 1) if closed_results else None,
            "avg_result_pct": round(sum(closed_results) / len(closed_results), 2) if closed_results else None,
            "swing_pending": swing_counts["pending"],
            "swing_open": swing_counts["open"],
            "swing_target": swing_counts["target"],
            "swing_stopped": swing_counts["stopped"],
            "swing_cancelled": swing_counts["cancelled"],
            "swing_win_rate_pct": round(swing_wins / len(swing_results) * 100.0, 1) if swing_results else None,
            "swing_avg_result_pct": round(sum(swing_results) / len(swing_results), 2) if swing_results else None,
        }

    def take_flush(self, now_ts: float, min_interval: float = 2.0, *, force: bool = False) -> list[dict[str, Any]]:
        """Changed rows only. Status changes go out every ``min_interval``; last-price
        drift on otherwise unchanged plans every ten seconds."""
        if not force and self._last_flush and now_ts - self._last_flush < min_interval:
            return []
        keys = set(self._dirty)
        if force or now_ts - self._last_soft_flush >= _SOFT_FLUSH_SEC:
            keys |= self._soft
            self._soft.clear()
            self._last_soft_flush = now_ts
        else:
            self._soft -= keys
        self._dirty.clear()
        if not keys:
            return []
        self._last_flush = now_ts
        return [_persist_row(self._rows[key]) for key in keys if key in self._rows]
