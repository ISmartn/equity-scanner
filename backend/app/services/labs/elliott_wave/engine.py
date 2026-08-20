"""Elliott Wave lab scan engine — local DB candles + parallel analysis."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ....db.store import TimelineStore, get_store
from .patterns import build_beginner_guide, detect_best_pattern
from .universe import (
    LOOKBACK_BARS,
    MIN_BARS,
    NIFTY_KEY,
    NIFTY_TICKER,
    equity_instrument_key,
    universe_items,
)
from .zigzag import extract_pivots

logger = logging.getLogger(__name__)


def _rows_to_frame(rows: list[dict[str, Any]], *, date_key: str = "date") -> pd.DataFrame | None:
    if not rows:
        return None
    df = pd.DataFrame(rows)
    if date_key not in df.columns and "ts" in df.columns:
        date_key = "ts"
    if date_key not in df.columns:
        return None
    # Chronological — assume store returns ASC; do NOT sort_values reverse
    df = df.copy()
    df["_dt"] = pd.to_datetime(df[date_key], errors="coerce")
    df = df.dropna(subset=["_dt"])
    if df.empty:
        return None
    # Only sort ascending if clearly out of order (stable chronological guarantee)
    if not df["_dt"].is_monotonic_increasing:
        df = df.sort_values("_dt", kind="mergesort")
    df = df.set_index("_dt")
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            return None
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    if len(df) > LOOKBACK_BARS:
        df = df.iloc[-LOOKBACK_BARS:]
    return df if len(df) >= MIN_BARS else None


def _load_equity_frames(
    store: TimelineStore,
    tickers: list[str],
) -> dict[str, pd.DataFrame]:
    """Bulk-load daily equity OHLCV from local daily_candles (chronological)."""
    if not tickers:
        return {}
    profiles: dict[str, str] = {}
    with store.connection() as conn:
        ph = ",".join("?" for _ in tickers)
        for row in conn.execute(
            f"""
            SELECT ticker, instrument_token
            FROM security_profiles
            WHERE UPPER(ticker) IN ({ph})
            """,
            [t.upper() for t in tickers],
        ).fetchall():
            profiles[str(row["ticker"]).upper()] = str(row["instrument_token"])

    if not profiles:
        return {}

    token_to_ticker = {v: k for k, v in profiles.items()}
    tokens = list(profiles.values())
    by_ticker: dict[str, list[dict[str, Any]]] = {t: [] for t in profiles}

    chunk = 300
    with store.connection() as conn:
        for i in range(0, len(tokens), chunk):
            part = tokens[i : i + chunk]
            ph = ",".join("?" for _ in part)
            for row in conn.execute(
                f"""
                SELECT instrument_token, trade_date AS date,
                       open_price AS open, high_price AS high,
                       low_price AS low, close_price AS close, volume
                FROM daily_candles
                WHERE instrument_token IN ({ph})
                ORDER BY instrument_token ASC, trade_date ASC
                """,
                part,
            ).fetchall():
                ticker = token_to_ticker.get(str(row["instrument_token"]))
                if ticker:
                    by_ticker[ticker].append(dict(row))

    out: dict[str, pd.DataFrame] = {}
    for ticker, rows in by_ticker.items():
        if len(rows) > LOOKBACK_BARS:
            rows = rows[-LOOKBACK_BARS:]
        frame = _rows_to_frame(rows)
        if frame is not None:
            out[ticker] = frame
    return out


def _load_nifty_frame(store: TimelineStore) -> pd.DataFrame | None:
    rows = store.get_index_candles(NIFTY_KEY, "daily", limit=LOOKBACK_BARS)
    # index candles use ts — may be newest-first depending on store; normalize
    if not rows:
        return None
    # get_index_candles typically returns newest first — reverse to chronological WITHOUT sort_values
    # if already chronological, reversing would break; detect via first/last
    parsed = []
    for r in rows:
        d = dict(r)
        if "ts" in d and "date" not in d:
            d["date"] = d["ts"]
        parsed.append(d)
    if len(parsed) >= 2:
        t0 = str(parsed[0].get("date", ""))[:10]
        t1 = str(parsed[-1].get("date", ""))[:10]
        if t0 > t1:
            parsed = list(reversed(parsed))
    return _rows_to_frame(parsed)


def _analyze_symbol_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Process-pool worker: plain dict in / out (picklable)."""
    ticker = payload["ticker"]
    instrument_key = payload["instrument_key"]
    kind = payload["kind"]
    records = payload["ohlcv"]  # list of {date, open, high, low, close, volume}

    if not records or len(records) < MIN_BARS:
        return None

    df = pd.DataFrame(records)
    df["_dt"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["_dt"])
    if not df["_dt"].is_monotonic_increasing:
        df = df.sort_values("_dt", kind="mergesort")
    df = df.set_index("_dt")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    if len(df) < MIN_BARS:
        return None

    pivots = extract_pivots(df)
    if len(pivots) < 4:
        guide = build_beginner_guide(None, float(df["close"].iloc[-1]))
        return {
            "ticker": ticker,
            "instrument_key": instrument_key,
            "kind": kind,
            "phase": "Insufficient Pivots",
            "surety_score": 0,
            "invalidation_price": None,
            "invalidation_risk_pct": None,
            "price": round(float(df["close"].iloc[-1]), 2),
            "pattern": None,
            "direction": None,
            "as_of": df.index[-1].strftime("%Y-%m-%d"),
            "pivot_count": len(pivots),
            "current_wave": guide["current_wave"],
            "trend": guide["trend"],
            "what_next": guide["what_next"],
            "guide": guide,
        }

    last_close = float(df["close"].iloc[-1])
    hit = detect_best_pattern(pivots, last_close)
    guide = build_beginner_guide(hit, last_close)
    if not hit:
        return {
            "ticker": ticker,
            "instrument_key": instrument_key,
            "kind": kind,
            "phase": "No Valid Count",
            "surety_score": 0,
            "invalidation_price": None,
            "invalidation_risk_pct": None,
            "price": round(last_close, 2),
            "pattern": None,
            "direction": None,
            "as_of": df.index[-1].strftime("%Y-%m-%d"),
            "pivot_count": len(pivots),
            "current_wave": guide["current_wave"],
            "trend": guide["trend"],
            "what_next": guide["what_next"],
            "guide": guide,
        }

    inv = hit.get("invalidation_price")
    risk = None
    if inv is not None and last_close > 0:
        risk = round(abs(last_close - float(inv)) / last_close * 100.0, 2)

    return {
        "ticker": ticker,
        "instrument_key": instrument_key,
        "kind": kind,
        "phase": hit["phase"],
        "surety_score": hit["surety_score"],
        "invalidation_price": inv,
        "invalidation_risk_pct": risk,
        "price": round(last_close, 2),
        "pattern": hit["pattern"],
        "direction": hit["direction"],
        "fib": hit.get("fib"),
        "neo_wave_ok": hit.get("neo_wave_ok"),
        "as_of": df.index[-1].strftime("%Y-%m-%d"),
        "pivot_count": len(pivots),
        "wave_labels": [
            {
                "label": w["label"],
                "timestamp": w["pivot"]["timestamp"],
                "price": w["pivot"]["price"],
                "type": w["pivot"]["type"],
            }
            for w in hit.get("waves", [])
        ],
        "current_wave": guide["current_wave"],
        "trend": guide["trend"],
        "what_next": guide["what_next"],
        "guide": guide,
    }


def _frame_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ts, row in df.iterrows():
        out.append(
            {
                "date": pd.Timestamp(ts).strftime("%Y-%m-%d"),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]) if pd.notna(row["volume"]) else 0.0,
            }
        )
    return out


def run_elliott_wave_scan(
    *,
    store: TimelineStore | None = None,
    max_workers: int | None = None,
) -> dict[str, Any]:
    db = store or get_store()
    items = universe_items(db)
    equity_tickers = [i["ticker"] for i in items if i["kind"] == "equity"]
    frames = _load_equity_frames(db, equity_tickers)
    nifty = _load_nifty_frame(db)

    payloads: list[dict[str, Any]] = []
    for item in items:
        if item["kind"] == "index":
            if nifty is None:
                continue
            payloads.append(
                {
                    **item,
                    "ohlcv": _frame_to_records(nifty),
                }
            )
        else:
            frame = frames.get(item["ticker"])
            if frame is None:
                continue
            payloads.append({**item, "ohlcv": _frame_to_records(frame)})

    workers = max_workers or max(1, min(8, (os.cpu_count() or 2)))
    results: list[dict[str, Any]] = []

    # ProcessPool for CPU-bound wave math; fall back to sequential on failure
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_analyze_symbol_payload, p): p["ticker"] for p in payloads}
            for fut in as_completed(futures):
                ticker = futures[fut]
                try:
                    row = fut.result()
                    if row:
                        results.append(row)
                except Exception:
                    logger.exception("Elliott wave worker failed for %s", ticker)
    except Exception:
        logger.exception("ProcessPool failed — running sequential")
        for p in payloads:
            try:
                row = _analyze_symbol_payload(p)
                if row:
                    results.append(row)
            except Exception:
                logger.exception("Elliott wave sequential failed for %s", p.get("ticker"))

    results.sort(key=lambda r: (r.get("surety_score") or 0), reverse=True)

    high_surety = sum(1 for r in results if (r.get("surety_score") or 0) >= 75)
    wave3 = sum(1 for r in results if r.get("phase") == "Wave 3 Breakout")
    wave4 = sum(1 for r in results if r.get("phase") == "Wave 4 Dip")

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "universe_size": len(payloads),
        "analyzed": len(results),
        "workers": workers,
        "summary": {
            "high_surety": high_surety,
            "wave_3_breakouts": wave3,
            "wave_4_dips": wave4,
        },
        "results": results,
    }


def get_chart_payload(
    instrument_key: str,
    *,
    store: TimelineStore | None = None,
) -> dict[str, Any]:
    """OHLCV + pivots + primary wave polyline + invalidation for one instrument."""
    db = store or get_store()
    key = instrument_key.strip()
    ticker = key.split("|")[-1].upper() if "|" in key else key.upper()
    if ticker in {"NIFTY", "NIFTY 50"} or key == NIFTY_KEY:
        ticker = NIFTY_TICKER
        key = NIFTY_KEY
        frame = _load_nifty_frame(db)
        kind = "index"
    else:
        # Accept NSE_EQ|TICKER or raw ticker
        if key.upper().startswith("NSE_EQ|"):
            ticker = key.split("|", 1)[1].upper()
        frames = _load_equity_frames(db, [ticker])
        frame = frames.get(ticker)
        key = equity_instrument_key(ticker)
        kind = "equity"

    if frame is None:
        raise ValueError(f"No local daily candles for {instrument_key}")

    records = _frame_to_records(frame)
    pivots = extract_pivots(frame)
    last_close = float(frame["close"].iloc[-1])
    hit = detect_best_pattern(pivots, last_close)

    wave_path = []
    invalidation = None
    phase = "No Valid Count"
    surety = 0.0
    if hit:
        phase = hit["phase"]
        surety = hit["surety_score"]
        invalidation = hit.get("invalidation_price")
        for w in hit.get("waves", []):
            p = w["pivot"]
            wave_path.append(
                {
                    "label": w["label"],
                    "time": p["timestamp"],
                    "price": p["price"],
                    "type": p["type"],
                }
            )

    zigzag_path = [{"time": p["timestamp"], "price": p["price"], "type": p["type"]} for p in pivots]
    guide = build_beginner_guide(hit, last_close)

    return {
        "ticker": ticker,
        "instrument_key": key,
        "kind": kind,
        "as_of": frame.index[-1].strftime("%Y-%m-%d"),
        "phase": phase,
        "surety_score": surety,
        "invalidation_price": invalidation,
        "candles": records,
        "pivots": pivots,
        "zigzag_path": zigzag_path,
        "wave_path": wave_path,
        "pattern": hit.get("pattern") if hit else None,
        "direction": hit.get("direction") if hit else None,
        "fib": hit.get("fib") if hit else None,
        "current_wave": guide["current_wave"],
        "trend": guide["trend"],
        "what_next": guide["what_next"],
        "guide": guide,
    }
