from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .snapshot_store import ChainSnapshot, StrikeSnapshot

AlertLevel = Literal["strong", "mild", "neutral", "warming"]

DEFAULT_STRIKE_STEP: dict[str, int] = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
    "NIFTYNXT50": 50,
}

PUT_SURGE_PCT = 0.02
PCR_MOMENTUM_STRONG = 2.0
ATM_HYSTERESIS_FRAC = 0.35
MIN_ZONE_PUT_OI = 5_000
MIN_PUT_VOLUME_DELTA = 500
REFERENCE_WINDOW_SEC = 60.0
MIN_PUT_VOLUME_DELTA_FLOOR = 200
PUT_SURGE_PCT_FLOOR = 0.01
OI_VOLUME_RATIO_MIN = 0.00002
OI_VOLUME_RATIO_MAX = 0.5
STRIKE_ROTATION_PUT_MIN = 5_000
STRIKE_ROTATION_LOWER_FRAC = 0.20


def momentum_thresholds(target_window_sec: float) -> tuple[float, int]:
    """Scale surge/volume gates down for sub-60s live windows (60s = baseline)."""
    scale = min(1.0, max(0.5, target_window_sec / REFERENCE_WINDOW_SEC))
    surge = max(PUT_SURGE_PCT_FLOOR, PUT_SURGE_PCT * scale)
    volume = max(MIN_PUT_VOLUME_DELTA_FLOOR, int(MIN_PUT_VOLUME_DELTA * scale))
    return surge, volume


def format_window_label(seconds: float) -> str:
    sec = int(seconds)
    if sec < 60:
        return f"{sec}s"
    if sec % 60 == 0:
        return f"{sec // 60}m"
    return f"{sec}s"


@dataclass
class ZoneMetrics:
    strikes: list[float]
    zone_put_addition: int
    zone_call_unwinding: int
    zone_put_volume_delta: int
    total_zone_put_oi: int
    rapid_put_surge: bool
    call_unwind: bool
    volume_confirmed: bool
    pcr_momentum: float | None
    oi_volume_ratio: float | None


def price_support_aligned(
    spot_delta: float | None,
    spot: float,
    window_sec: float,
) -> bool:
    """Bullish OI support should not fire on sharp spot drops in the window."""
    if spot_delta is None:
        return True
    max_drop_pts = max(4.0, spot * 0.00015 * max(window_sec / 60.0, 0.5))
    return spot_delta >= -max_drop_pts


def detect_strike_rotation(strike_details: list[dict[str, Any]]) -> bool:
    """ATM put build paired with lower-strike put unwind = roll, not fresh support."""
    if len(strike_details) < 2:
        return False
    ordered = sorted(strike_details, key=lambda row: row["strike_price"], reverse=True)
    atm_put_delta = ordered[0].get("put_oi_delta") or 0
    lower_put_delta = ordered[1].get("put_oi_delta") or 0
    return (
        atm_put_delta > STRIKE_ROTATION_PUT_MIN
        and lower_put_delta < 0
        and abs(lower_put_delta) >= STRIKE_ROTATION_LOWER_FRAC * atm_put_delta
    )


def volume_confirmed_for_build(
    zone_put_addition: int,
    zone_put_volume_delta: int,
    min_put_oi_addition: int,
) -> tuple[bool, float | None]:
    """
    Confirm OI build using OI/volume ratio — cumulative session volume deltas
    on index options always pass naive absolute thresholds.
    """
    if zone_put_addition < min_put_oi_addition or zone_put_volume_delta <= 0:
        return False, None
    ratio = zone_put_addition / zone_put_volume_delta
    if ratio < OI_VOLUME_RATIO_MIN or ratio > OI_VOLUME_RATIO_MAX:
        return False, ratio
    return True, ratio


@dataclass
class MomentumResult:
    alert: AlertLevel
    message: str
    spot: float
    raw_atm: float
    smoothed_atm: float
    strike_step: int
    window_sec: float
    target_window_sec: float
    baseline_mode: Literal["none", "partial", "full"]
    baseline_age_sec: float | None
    warming: bool
    put_surge_threshold_pct: float
    min_put_volume_threshold: int
    signal_quality: dict[str, Any]
    metrics: ZoneMetrics
    strike_details: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["metrics"] = asdict(self.metrics)
        return out


def default_strike_step(symbol: str) -> int:
    return DEFAULT_STRIKE_STEP.get(symbol.upper(), 50)


def infer_strike_step(strikes: list[float], spot: float, fallback: int) -> int:
    if len(strikes) < 2:
        return fallback
    near = sorted(strike for strike in strikes if abs(strike - spot) <= max(spot * 0.04, fallback * 3))
    pool = near if len(near) >= 2 else sorted(strikes)
    diffs = [round(pool[i + 1] - pool[i]) for i in range(len(pool) - 1) if pool[i + 1] > pool[i]]
    if not diffs:
        return fallback
    step = int(statistics.median(diffs))
    return step if step > 0 else fallback


def raw_atm_strike(spot: float, strike_step: int) -> float:
    return round(spot / strike_step) * strike_step


def smooth_atm_strike(
    spot: float,
    strike_step: int,
    previous_smoothed: float | None,
) -> float:
    raw = raw_atm_strike(spot, strike_step)
    if previous_smoothed is None:
        return raw
    if raw == previous_smoothed:
        return raw
    threshold = strike_step * ATM_HYSTERESIS_FRAC
    if abs(spot - previous_smoothed) >= threshold:
        return raw
    return previous_smoothed


def support_zone_strikes(smoothed_atm: float, strike_step: int) -> list[float]:
    return [smoothed_atm, smoothed_atm - strike_step]


def _extract_chain_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, list):
            return [row for row in inner if isinstance(row, dict)]
    return []


def parse_option_chain_rows(
    payload: Any,
    *,
    symbol: str,
    previous_smoothed_atm: float | None = None,
    captured_at: float | None = None,
) -> ChainSnapshot:
    rows_raw = _extract_chain_list(payload)
    if not rows_raw:
        raise ValueError("Option chain payload has no strike rows")

    spot = 0.0
    parsed: list[StrikeSnapshot] = []
    for item in rows_raw:
        strike = item.get("strike_price")
        if strike is None:
            continue
        if spot <= 0:
            spot_val = item.get("underlying_spot_price")
            if spot_val is not None:
                spot = float(spot_val)
        call_md = ((item.get("call_options") or {}).get("market_data") or {})
        put_md = ((item.get("put_options") or {}).get("market_data") or {})
        parsed.append(
            StrikeSnapshot(
                strike_price=float(strike),
                call_oi=int(float(call_md.get("oi") or 0)),
                put_oi=int(float(put_md.get("oi") or 0)),
                call_volume=int(float(call_md.get("volume") or 0)),
                put_volume=int(float(put_md.get("volume") or 0)),
            )
        )

    if spot <= 0:
        raise ValueError("Option chain missing underlying spot price")

    strikes = [row.strike_price for row in parsed]
    step = infer_strike_step(strikes, spot, default_strike_step(symbol))
    smoothed = smooth_atm_strike(spot, step, previous_smoothed_atm)

    return ChainSnapshot(
        captured_at=captured_at or time.time(),
        spot=spot,
        smoothed_atm=smoothed,
        strike_step=step,
        rows=tuple(parsed),
    )


def _zone_metrics(
    current: ChainSnapshot,
    previous: ChainSnapshot,
    *,
    put_surge_pct: float = PUT_SURGE_PCT,
    min_put_volume_delta: int = MIN_PUT_VOLUME_DELTA,
) -> ZoneMetrics:
    strikes = support_zone_strikes(current.smoothed_atm, current.strike_step)
    zone_put_addition = 0
    zone_call_unwinding = 0
    zone_put_volume_delta = 0
    total_zone_put_oi = 0

    for strike in strikes:
        curr = current.row_by_strike(strike)
        prev = previous.row_by_strike(strike)
        if not curr or not prev:
            continue
        put_delta = curr.put_oi - prev.put_oi
        call_delta = curr.call_oi - prev.call_oi
        put_vol_delta = curr.put_volume - prev.put_volume
        if put_delta > 0:
            zone_put_addition += put_delta
        if call_delta < 0:
            zone_call_unwinding += call_delta
        zone_put_volume_delta += max(put_vol_delta, 0)
        total_zone_put_oi += curr.put_oi

    base_oi = max(total_zone_put_oi, MIN_ZONE_PUT_OI)
    rapid_put_surge = zone_put_addition > base_oi * put_surge_pct
    call_unwind = zone_call_unwinding < 0
    volume_confirmed, oi_volume_ratio = volume_confirmed_for_build(
        zone_put_addition,
        zone_put_volume_delta,
        min_put_volume_delta,
    )

    if zone_call_unwinding != 0:
        pcr_momentum = zone_put_addition / abs(zone_call_unwinding)
    elif zone_put_addition > 0:
        pcr_momentum = float(zone_put_addition)
    else:
        pcr_momentum = None

    return ZoneMetrics(
        strikes=strikes,
        zone_put_addition=zone_put_addition,
        zone_call_unwinding=zone_call_unwinding,
        zone_put_volume_delta=zone_put_volume_delta,
        total_zone_put_oi=total_zone_put_oi,
        rapid_put_surge=rapid_put_surge,
        call_unwind=call_unwind,
        volume_confirmed=volume_confirmed,
        pcr_momentum=pcr_momentum,
        oi_volume_ratio=oi_volume_ratio,
    )


def _strike_details(
    current: ChainSnapshot,
    previous: ChainSnapshot | None,
    strikes: list[float],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for strike in strikes:
        curr = current.row_by_strike(strike)
        if not curr:
            continue
        prev = previous.row_by_strike(strike) if previous else None
        out.append(
            {
                "strike_price": strike,
                "put_oi": curr.put_oi,
                "call_oi": curr.call_oi,
                "put_volume": curr.put_volume,
                "call_volume": curr.call_volume,
                "put_oi_delta": (curr.put_oi - prev.put_oi) if prev else None,
                "call_oi_delta": (curr.call_oi - prev.call_oi) if prev else None,
                "put_volume_delta": (curr.put_volume - prev.put_volume) if prev else None,
            }
        )
    return out


def evaluate_support_momentum(
    current: ChainSnapshot,
    previous: ChainSnapshot | None,
    *,
    window_sec: float,
    target_window_sec: float | None = None,
    baseline_mode: Literal["none", "partial", "full"] = "full",
) -> MomentumResult:
    target = target_window_sec if target_window_sec is not None else window_sec
    put_surge_pct, min_put_volume = momentum_thresholds(target)
    target_label = format_window_label(target)
    baseline_age = (
        round(current.captured_at - previous.captured_at, 1) if previous is not None else None
    )
    zone = support_zone_strikes(current.smoothed_atm, current.strike_step)

    if previous is None or baseline_mode == "none":
        metrics = ZoneMetrics(
            strikes=zone,
            zone_put_addition=0,
            zone_call_unwinding=0,
            zone_put_volume_delta=0,
            total_zone_put_oi=sum(
                (current.row_by_strike(s).put_oi if current.row_by_strike(s) else 0) for s in zone
            ),
            rapid_put_surge=False,
            call_unwind=False,
            volume_confirmed=False,
            pcr_momentum=None,
            oi_volume_ratio=None,
        )
        return MomentumResult(
            alert="warming",
            message=(
                f"First poll recorded — deltas appear on the next poll "
                f"(target window {target_label})."
            ),
            spot=current.spot,
            raw_atm=raw_atm_strike(current.spot, current.strike_step),
            smoothed_atm=current.smoothed_atm,
            strike_step=current.strike_step,
            window_sec=window_sec,
            target_window_sec=target,
            baseline_mode="none",
            baseline_age_sec=None,
            warming=True,
            put_surge_threshold_pct=put_surge_pct,
            min_put_volume_threshold=min_put_volume,
            signal_quality={
                "strike_rotation": False,
                "price_aligned": True,
                "oi_volume_ratio": None,
                "notify_eligible": False,
                "suppress_reason": None,
            },
            metrics=metrics,
            strike_details=_strike_details(current, None, metrics.strikes),
        )

    strike_details = _strike_details(current, previous, zone)
    spot_delta = current.spot - previous.spot
    strike_rotation = detect_strike_rotation(strike_details)
    price_aligned = price_support_aligned(spot_delta, current.spot, target)

    metrics = _zone_metrics(
        current,
        previous,
        put_surge_pct=put_surge_pct,
        min_put_volume_delta=min_put_volume,
    )
    pcr = metrics.pcr_momentum or 0.0
    window_label = (
        f"{int(baseline_age or window_sec)}s"
        if baseline_mode == "partial"
        else target_label
    )
    remaining_sec = max(0.0, target - (baseline_age or 0.0))
    polls_hint = max(1, int(remaining_sec // 10) + 1)
    suppress_reason: str | None = None

    if baseline_mode == "partial":
        if metrics.rapid_put_surge and metrics.volume_confirmed:
            alert: AlertLevel = "mild"
            message = (
                f"Early signal (partial {window_label} of {target_label}): puts building at "
                f"{int(current.smoothed_atm)} zone (+{metrics.zone_put_addition:,} put OI vs last poll, "
                f"volume confirmed). Full-window confirmation pending."
            )
        else:
            alert = "warming"
            message = (
                f"Partial window ({window_label} of {target_label} target) — "
                f"strike deltas vs last poll shown below; full-window alerts after "
                f"~{polls_hint} more poll(s)."
            )
    elif (
        metrics.rapid_put_surge
        and metrics.call_unwind
        and pcr >= PCR_MOMENTUM_STRONG
        and metrics.volume_confirmed
    ):
        alert = "strong"
        message = (
            f"Strong bullish momentum: support building at {int(current.smoothed_atm)} zone "
            f"(+{metrics.zone_put_addition:,} put OI, {metrics.zone_call_unwinding:,} call OI "
            f"in {window_label} window, volume confirmed)."
        )
    elif metrics.rapid_put_surge and metrics.volume_confirmed:
        alert = "mild"
        message = (
            f"Mild bullish momentum: puts building at {int(current.smoothed_atm)} zone "
            f"(+{metrics.zone_put_addition:,} put OI in window; "
            f"{'calls unwinding' if metrics.call_unwind else 'calls not capitulating yet'})."
        )
    elif metrics.rapid_put_surge:
        alert = "mild"
        ratio_txt = f"{metrics.oi_volume_ratio:.4f}" if metrics.oi_volume_ratio is not None else "n/a"
        message = (
            f"Put OI surge at {int(current.smoothed_atm)} zone but OI/volume ratio gate not met "
            f"(+{metrics.zone_put_addition:,} OI, ratio {ratio_txt})."
        )
    else:
        alert = "neutral"
        message = "Neutral — no rapid ATM support-zone put build-up in the rolling window."

    if alert in ("strong", "mild"):
        if strike_rotation:
            suppress_reason = "strike_rotation"
            alert = "warming"
            message = (
                f"Put OI rotating across strikes (ATM build + lower-strike unwind) — "
                f"not treated as fresh support (+{metrics.zone_put_addition:,} net zone OI)."
            )
        elif not price_aligned:
            suppress_reason = "price_divergence"
            alert = "warming"
            message = (
                f"Put build at {int(current.smoothed_atm)} zone but spot fell {spot_delta:+.1f} pts "
                f"in window — waiting for price alignment."
            )

    signal_quality = {
        "strike_rotation": strike_rotation,
        "price_aligned": price_aligned,
        "spot_delta_pts": round(spot_delta, 2),
        "oi_volume_ratio": metrics.oi_volume_ratio,
        "notify_eligible": alert in ("strong", "mild"),
        "suppress_reason": suppress_reason,
    }

    return MomentumResult(
        alert=alert,
        message=message,
        spot=current.spot,
        raw_atm=raw_atm_strike(current.spot, current.strike_step),
        smoothed_atm=current.smoothed_atm,
        strike_step=current.strike_step,
        window_sec=window_sec,
        target_window_sec=target,
        baseline_mode=baseline_mode,
        baseline_age_sec=baseline_age,
        warming=(baseline_mode == "partial" and alert == "warming") or suppress_reason is not None,
        put_surge_threshold_pct=put_surge_pct,
        min_put_volume_threshold=min_put_volume,
        signal_quality=signal_quality,
        metrics=metrics,
        strike_details=strike_details,
    )
