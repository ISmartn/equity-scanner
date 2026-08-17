from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from ...config import ROOT_DIR
from .engine import raw_atm_strike
from .snapshot_store import ChainSnapshot, get_oi_snapshot_store

ALERT_LOG_PATH = ROOT_DIR / "backend" / "data" / "oi_momentum_alerts.jsonl"
MAX_ALERT_LOG_LINES = 5000
ALERT_COOLDOWN_SEC = 45
PUT_DEDUP_BUCKET = 25_000


def _ensure_log_dir() -> None:
    ALERT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _strike_rows(snapshot: ChainSnapshot | None, strikes: list[float]) -> list[dict[str, Any]]:
    if snapshot is None:
        return []
    out: list[dict[str, Any]] = []
    for strike in strikes:
        row = snapshot.row_by_strike(strike)
        if not row:
            continue
        out.append(
            {
                "strike_price": strike,
                "put_oi": row.put_oi,
                "call_oi": row.call_oi,
                "put_volume": row.put_volume,
                "call_volume": row.call_volume,
            }
        )
    return out


def build_price_action(
    current: ChainSnapshot,
    baseline: ChainSnapshot | None,
) -> dict[str, Any]:
    spot_at_baseline = baseline.spot if baseline else None
    spot_delta = (current.spot - spot_at_baseline) if spot_at_baseline is not None else None
    spot_delta_pct = (
        round(100.0 * spot_delta / spot_at_baseline, 4)
        if spot_at_baseline and spot_delta is not None and spot_at_baseline > 0
        else None
    )
    return {
        "spot": current.spot,
        "spot_at_baseline": spot_at_baseline,
        "spot_delta": spot_delta,
        "spot_delta_pct": spot_delta_pct,
        "raw_atm": raw_atm_strike(current.spot, current.strike_step),
        "smoothed_atm": current.smoothed_atm,
        "captured_at": current.captured_at,
        "baseline_captured_at": baseline.captured_at if baseline else None,
    }


class OiAlertDedup:
    """Per-symbol dedup + cooldown so notify/log does not spam on 30s scalp."""

    def __init__(self) -> None:
        self._last_key: dict[str, str] = {}
        self._last_at: dict[str, float] = {}

    def cooldown_sec(self, window_sec: int) -> float:
        return max(ALERT_COOLDOWN_SEC, min(120.0, window_sec * 1.5))

    def notify_key(
        self,
        symbol: str,
        alert: str,
        phase: str,
        smoothed_atm: float,
        zone_put_addition: int,
    ) -> str:
        put_bucket = max(0, zone_put_addition // PUT_DEDUP_BUCKET)
        return f"{symbol.upper()}:{phase}:{alert}:{int(smoothed_atm)}:{put_bucket}"

    def is_new(self, symbol: str, key: str, *, window_sec: int = 180) -> bool:
        sym = symbol.upper()
        if key.endswith(":reset"):
            self._last_key.pop(sym, None)
            self._last_at.pop(sym, None)
            return False
        prev = self._last_key.get(sym)
        now = time.time()
        if prev == key:
            return False
        cooldown = self.cooldown_sec(window_sec)
        last_at = self._last_at.get(sym, 0.0)
        if now - last_at < cooldown:
            # Allow escalation mild -> strong at same ATM within cooldown
            if ":strong:" in key and prev and ":mild:" in prev:
                same_atm = key.split(":")[3] == prev.split(":")[3]
                if same_atm:
                    self._last_key[sym] = key
                    self._last_at[sym] = now
                    return True
            return False
        self._last_key[sym] = key
        self._last_at[sym] = now
        return True

    def reset_symbol(self, symbol: str) -> None:
        self._last_key.pop(symbol.upper(), None)


_dedup = OiAlertDedup()


def get_oi_alert_dedup() -> OiAlertDedup:
    return _dedup


def compute_notify_tier(
    alert: str,
    baseline_mode: str,
    *,
    rapid_put_surge: bool,
    volume_confirmed: bool,
) -> tuple[str | None, Literal["full", "early"] | None]:
    if alert in ("strong", "mild") and baseline_mode == "full":
        return alert, "full"
    if (
        baseline_mode == "partial"
        and rapid_put_surge
        and volume_confirmed
    ):
        return "mild", "early"
    return None, None


async def build_alert_record(
    *,
    symbol: str,
    source: str,
    expiry: str | None,
    window_sec: int,
    evaluation: dict[str, Any],
    current: ChainSnapshot,
    baseline: ChainSnapshot | None,
    notify_alert: str,
    notify_phase: Literal["full", "early"],
) -> dict[str, Any]:
    store = get_oi_snapshot_store()
    spot_trail = await store.recent_spot_trail(symbol, limit=12)
    strikes = evaluation.get("metrics", {}).get("strikes") or []
    return {
        "id": str(uuid.uuid4()),
        "recorded_at": time.time(),
        "symbol": symbol.upper(),
        "source": source,
        "expiry": expiry,
        "window_sec": window_sec,
        "notify_alert": notify_alert,
        "notify_phase": notify_phase,
        "evaluation_alert": evaluation.get("alert"),
        "baseline_mode": evaluation.get("baseline_mode"),
        "message": evaluation.get("message"),
        "price_action": build_price_action(current, baseline),
        "zone_metrics": evaluation.get("metrics"),
        "gates": {
            "rapid_put_surge": evaluation.get("metrics", {}).get("rapid_put_surge"),
            "call_unwind": evaluation.get("metrics", {}).get("call_unwind"),
            "volume_confirmed": evaluation.get("metrics", {}).get("volume_confirmed"),
            "pcr_momentum": evaluation.get("metrics", {}).get("pcr_momentum"),
            "oi_volume_ratio": evaluation.get("metrics", {}).get("oi_volume_ratio"),
            "put_surge_threshold_pct": evaluation.get("put_surge_threshold_pct"),
            "min_put_volume_threshold": evaluation.get("min_put_volume_threshold"),
        },
        "signal_quality": evaluation.get("signal_quality"),
        "strike_details": evaluation.get("strike_details"),
        "baseline_oi": _strike_rows(baseline, strikes),
        "current_oi": _strike_rows(current, strikes),
        "spot_trail": spot_trail,
    }


def append_alert_record(record: dict[str, Any]) -> None:
    _ensure_log_dir()
    line = json.dumps(record, separators=(",", ":"), default=str)
    with ALERT_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    _trim_log_if_needed()


def _trim_log_if_needed() -> None:
    if not ALERT_LOG_PATH.exists():
        return
    lines = ALERT_LOG_PATH.read_text(encoding="utf-8").splitlines()
    if len(lines) <= MAX_ALERT_LOG_LINES:
        return
    keep = lines[-MAX_ALERT_LOG_LINES:]
    ALERT_LOG_PATH.write_text("\n".join(keep) + "\n", encoding="utf-8")


def read_alert_records(
    *,
    symbol: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if not ALERT_LOG_PATH.exists():
        return []
    cap = max(1, min(limit, 500))
    rows: list[dict[str, Any]] = []
    sym = symbol.upper() if symbol else None
    for line in reversed(ALERT_LOG_PATH.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if sym and row.get("symbol") != sym:
            continue
        rows.append(row)
        if len(rows) >= cap:
            break
    return rows


async def maybe_emit_alert_event(
    *,
    symbol: str,
    source: str,
    expiry: str | None,
    window_sec: int,
    evaluation_dict: dict[str, Any],
    current: ChainSnapshot,
    baseline: ChainSnapshot | None,
) -> dict[str, Any] | None:
    alert = evaluation_dict.get("alert", "neutral")
    metrics = evaluation_dict.get("metrics") or {}

    if not evaluation_dict.get("signal_quality", {}).get("notify_eligible", False):
        if alert in ("neutral", "warming"):
            get_oi_alert_dedup().reset_symbol(symbol)
        return None

    notify_alert, notify_phase = compute_notify_tier(
        alert,
        evaluation_dict.get("baseline_mode", "none"),
        rapid_put_surge=bool(metrics.get("rapid_put_surge")),
        volume_confirmed=bool(metrics.get("volume_confirmed")),
    )
    if not notify_alert or not notify_phase:
        return None

    dedup = get_oi_alert_dedup()
    key = dedup.notify_key(
        symbol,
        notify_alert,
        notify_phase,
        float(evaluation_dict.get("smoothed_atm") or 0),
        int(metrics.get("zone_put_addition") or 0),
    )
    is_new = dedup.is_new(symbol, key, window_sec=window_sec)
    record = await build_alert_record(
        symbol=symbol,
        source=source,
        expiry=expiry,
        window_sec=window_sec,
        evaluation=evaluation_dict,
        current=current,
        baseline=baseline,
        notify_alert=notify_alert,
        notify_phase=notify_phase,
    )
    if is_new:
        append_alert_record(record)

    return {
        "is_new": is_new,
        "notify_alert": notify_alert,
        "notify_phase": notify_phase,
        "dedup_key": key,
        "record": record,
    }
