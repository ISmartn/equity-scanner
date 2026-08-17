from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from ...config import INDEX_INSTRUMENT_KEYS, get_access_token, normalize_symbol
from .. import upstox_client
from ..market_info_sync import resolve_derivative_watchlist
from .alert_log import maybe_emit_alert_event
from .engine import (
    evaluate_support_momentum,
    parse_option_chain_rows,
    smooth_atm_strike,
    support_zone_strikes,
)
from .snapshot_store import get_oi_snapshot_store

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = ("NIFTY", "BANKNIFTY")
DEFAULT_WINDOW_SEC = 180
MIN_WINDOW_SEC = 60
MIN_WINDOW_SEC_STREAM = 30
API_MIN_WINDOW_SEC = MIN_WINDOW_SEC_STREAM
MAX_WINDOW_SEC = 900


async def _attach_alert_event(
    payload: dict[str, Any],
    *,
    symbol: str,
    window_sec: int,
    current: Any,
    baseline: Any | None,
) -> dict[str, Any]:
    evaluation_dict = payload["evaluation"]
    alert_event = await maybe_emit_alert_event(
        symbol=symbol,
        source=str(payload.get("source", "unknown")),
        expiry=payload.get("expiry"),
        window_sec=window_sec,
        evaluation_dict=evaluation_dict,
        current=current,
        baseline=baseline,
    )
    if alert_event is not None:
        payload["alert_event"] = alert_event
    return payload


async def resolve_underlying(symbol: str) -> dict[str, Any]:
    normalized = normalize_symbol(symbol)
    if normalized in INDEX_INSTRUMENT_KEYS:
        return {
            "symbol": normalized,
            "instrument_key": INDEX_INSTRUMENT_KEYS[normalized],
            "index": True,
        }
    watchlist = resolve_derivative_watchlist(
        symbols=[normalized],
        include_indices=False,
        include_stocks=True,
        stock_limit=1,
    )
    if not watchlist:
        raise ValueError(f"Unknown or unsupported F&O symbol: {normalized}")
    return watchlist[0]


async def fetch_live_option_chain(
    access_token: str | None,
    symbol: str,
    *,
    expiry: str | None = None,
) -> tuple[dict[str, Any], str]:
    token = get_access_token(access_token)
    if not token:
        raise RuntimeError("Upstox access token required for live option chain")

    underlying = await resolve_underlying(symbol)
    trade_date = date.today()

    if not expiry:
        expiry = await upstox_client.resolve_nearest_option_expiry(
            token,
            underlying["instrument_key"],
            trade_date,
        )
    if not expiry:
        raise ValueError(f"No option expiry found for {underlying['symbol']}")

    payload = await upstox_client.get_put_call_option_chain(
        token,
        underlying["instrument_key"],
        expiry,
    )
    return payload, expiry


async def poll_support_momentum(
    access_token: str | None,
    symbol: str,
    *,
    window_sec: int = DEFAULT_WINDOW_SEC,
    expiry: str | None = None,
) -> dict[str, Any]:
    window_sec = max(MIN_WINDOW_SEC, min(window_sec, MAX_WINDOW_SEC))
    normalized = normalize_symbol(symbol)
    store = get_oi_snapshot_store()
    previous_smoothed = await store.get_smoothed_atm(normalized)

    chain_payload, expiry_used = await fetch_live_option_chain(
        access_token,
        normalized,
        expiry=expiry,
    )
    current = parse_option_chain_rows(
        chain_payload,
        symbol=normalized,
        previous_smoothed_atm=previous_smoothed,
    )
    await store.append(normalized, current)

    baseline, baseline_mode, effective_window = await store.resolve_baseline(
        normalized,
        float(window_sec),
    )
    result = evaluate_support_momentum(
        current,
        baseline,
        window_sec=effective_window,
        target_window_sec=float(window_sec),
        baseline_mode=baseline_mode,
    )
    history = await store.stats(normalized)

    payload = {
        "symbol": normalized,
        "expiry": expiry_used,
        "source": "rest_poll",
        "polled_at": current.captured_at,
        "history": history,
        "evaluation": result.to_dict(),
        "note": (
            "Rolling OI deltas from REST option-chain polls. "
            "For live OI ticks, start the WebSocket stream (POST /api/oi-momentum/stream/start)."
        ),
    }
    return await _attach_alert_event(
        payload,
        symbol=normalized,
        window_sec=window_sec,
        current=current,
        baseline=baseline,
    )


async def evaluate_stream_momentum(
    symbol: str,
    *,
    window_sec: int = DEFAULT_WINDOW_SEC,
) -> dict[str, Any]:
    """Evaluate using live WebSocket OI book (no REST poll per evaluate)."""
    from .ws_feed import get_stream_manager, stream_sample_interval

    window_sec = max(MIN_WINDOW_SEC_STREAM, min(window_sec, MAX_WINDOW_SEC))
    normalized = normalize_symbol(symbol)
    mgr = get_stream_manager()
    session = mgr.get_session(normalized)
    if not session or session.status != "connected" or session.book is None:
        raise ValueError(
            f"WebSocket stream not active for {normalized}. "
            "POST /api/oi-momentum/stream/start first."
        )

    sample_min_sec = stream_sample_interval(window_sec)

    store = get_oi_snapshot_store()
    book = session.book
    now = time.time()

    with session._lock:
        if book.spot <= 0:
            raise ValueError("Waiting for first spot tick on WebSocket stream")
        previous_smoothed = await store.get_smoothed_atm(normalized)
        smoothed = smooth_atm_strike(book.spot, book.strike_step, previous_smoothed)
        book.smoothed_atm = smoothed
        book.zone_strikes = support_zone_strikes(smoothed, book.strike_step)
        current = book.to_chain_snapshot(smoothed_atm=smoothed, strike_step=book.strike_step)

    if session.last_snapshot_at is None or now - session.last_snapshot_at >= sample_min_sec:
        await store.append(normalized, current)
        session.last_snapshot_at = now

    baseline, baseline_mode, effective_window = await store.resolve_baseline(
        normalized,
        float(window_sec),
    )
    result = evaluate_support_momentum(
        current,
        baseline,
        window_sec=effective_window,
        target_window_sec=float(window_sec),
        baseline_mode=baseline_mode,
    )
    history = await store.stats(normalized)

    payload = {
        "symbol": normalized,
        "expiry": session.expiry,
        "source": "websocket",
        "polled_at": current.captured_at,
        "stream": session.snapshot_status(),
        "history": history,
        "evaluation": result.to_dict(),
        "note": (
            "Live OI from Upstox Market Data Feed V3 (full mode) on ATM zone strikes. "
            f"Snapshots every ~{sample_min_sec}s; rolling window {window_sec}s. "
            + (
                "Scalp mode (≤30s): high noise — volume/surge gates scaled for short window."
                if window_sec <= 30
                else "Shorter windows (1–2m) are viable in live mode — OI updates continuously."
            )
        ),
    }
    return await _attach_alert_event(
        payload,
        symbol=normalized,
        window_sec=window_sec,
        current=current,
        baseline=baseline,
    )


async def evaluate_momentum(
    access_token: str | None,
    symbol: str,
    *,
    window_sec: int = DEFAULT_WINDOW_SEC,
    expiry: str | None = None,
    source: str = "auto",
) -> dict[str, Any]:
    normalized = normalize_symbol(symbol)
    if source == "rest":
        return await poll_support_momentum(
            access_token, normalized, window_sec=window_sec, expiry=expiry
        )
    if source == "websocket":
        return await evaluate_stream_momentum(normalized, window_sec=window_sec)

    from .ws_feed import get_stream_manager

    session = get_stream_manager().get_session(normalized)
    if session and session.status == "connected":
        return await evaluate_stream_momentum(normalized, window_sec=window_sec)
    return await poll_support_momentum(
        access_token, normalized, window_sec=window_sec, expiry=expiry
    )
