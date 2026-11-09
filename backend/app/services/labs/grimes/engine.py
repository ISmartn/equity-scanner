"""Grimes lab scan + chart payloads (local daily candles only)."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any

import pandas as pd

from ....db.store import TimelineStore, get_store
from ..elliott_wave.engine import _frame_to_records, _load_equity_frames, _load_nifty_frame
from .universe import (
    MIN_BARS,
    NIFTY_KEY,
    NIFTY_TICKER,
    equity_instrument_key,
    universe_items,
)
from .diagnostics import calculate_expectancy, run_monte_carlo_control, simulate_paper_trade
from .indicators import attach_indicators, weekly_ema_rising
from .chart_guide import CHART_GUIDE_INTRO, CHART_GUIDE_SECTIONS
from .knowledge import KNOWLEDGE_CARDS, SETUP_CHECKLISTS
from .patterns import detect_all_on_bar, scan_history
from .pivots import fractal_pivots, recent_sr_zones
from .regime import classify_regime
from .risk import (
    calculate_position_size,
    calculate_r_multiples,
    evaluate_time_stop,
    evaluate_trailing_stop,
    hybrid_stop,
)

logger = logging.getLogger(__name__)

MIN_GRIMES_BARS = max(80, MIN_BARS)
ENGINE_VERSION = "1"
# Bars drawn after a historical session so outcomes are visible on the chart.
CHART_FORWARD_BARS = 260

_EMPTY_SUMMARY = {
    "trend_bull": 0,
    "trend_bear": 0,
    "range": 0,
    "squeeze": 0,
    "climax": 0,
    "pullbacks": 0,
    "squeezes": 0,
    "mean_reversion": 0,
    "high_quality": 0,
}


def _company_name_for_ticker(store: TimelineStore, ticker: str, kind: str) -> str | None:
    if kind == "index" or ticker.upper() in {"NIFTY", "NIFTY 50"}:
        return "Nifty 50 Index"
    with store.connection() as conn:
        row = conn.execute(
            """
            SELECT company_name FROM security_profiles
            WHERE UPPER(ticker) = ?
            LIMIT 1
            """,
            [ticker.upper()],
        ).fetchone()
    if not row:
        return None
    name = row["company_name"]
    return str(name).strip() if name else None


def _quality_score(
    setup: dict[str, Any] | None,
    regime_info: dict[str, Any],
    row: pd.Series,
) -> int:
    score = 20
    if regime_info.get("weekly_aligned") is True:
        score += 20
    elif regime_info.get("weekly_aligned") is False:
        score -= 8
    regime = regime_info.get("regime")
    if setup:
        group = setup.get("group")
        if setup["type"] in ("TREND_PULLBACK", "COMPLEX_PULLBACK") and regime in (
            "TREND_BULL",
            "TREND_BEAR",
        ):
            score += 25
        elif setup["type"] == "VOL_SQUEEZE" and regime == "VOLATILITY_COMPRESSION":
            score += 25
        elif setup["type"] in ("FAILED_BREAKOUT", "ABSORPTION") and regime in (
            "TRADING_RANGE",
            "VOLATILITY_COMPRESSION",
        ):
            score += 20
        elif setup["type"] == "CLIMACTIC_EXHAUSTION" and regime == "CLIMACTIC_EXHAUSTION":
            score += 22
        else:
            score += 8
        score += int((setup.get("quality_hint") or 50) * 0.15)
        if setup.get("volume_declining"):
            score += 8
        vol_z = row.get("vol_z")
        if pd.notna(vol_z) and float(vol_z) > 1.2 and setup["type"] in (
            "FAILED_BREAKOUT",
            "CLIMACTIC_EXHAUSTION",
            "ABSORPTION",
        ):
            score += 8
    else:
        if regime in ("TREND_BULL", "TREND_BEAR"):
            score += 10
    if regime == "CLIMACTIC_EXHAUSTION" and setup and setup["type"] == "TREND_PULLBACK":
        score -= 15
    return int(max(0, min(100, score)))


def _primary_setup(setups: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not setups:
        return None
    rank = {
        "CLIMACTIC_EXHAUSTION": 6,
        "FAILED_BREAKOUT": 5,
        "COMPLEX_PULLBACK": 4,
        "TREND_PULLBACK": 3,
        "VOL_SQUEEZE": 2,
        "ABSORPTION": 1,
    }
    return max(setups, key=lambda s: (rank.get(str(s.get("type")), 0), s.get("quality_hint") or 0))


def _risk_box(
    df: pd.DataFrame,
    setup: dict[str, Any],
    account_size: float,
    risk_pct: float,
) -> dict[str, Any] | None:
    i = int(setup["index"])
    row = df.iloc[i]
    side = setup.get("side") or "long"
    atr_v = float(row["atr14"]) if pd.notna(row.get("atr14")) else abs(float(row["close"])) * 0.02
    if side == "long":
        entry = float(row["high"])
    else:
        entry = float(row["low"])
    stop = hybrid_stop(
        side=side,
        entry=entry,
        swing_stop=setup.get("swing_stop"),
        atr_value=atr_v,
    )
    sizing = calculate_position_size(account_size, risk_pct, entry, stop)
    r_mult = calculate_r_multiples(entry, stop, [1, 2, 3], side=side)
    trail = evaluate_trailing_stop(df, side, "SWING_PIVOT", i)
    time_stop = evaluate_time_stop(i + 1, len(df) - 1, 8, 0.0)
    return {
        "side": side,
        "setup_type": setup["type"],
        "entry": round(entry, 4),
        "stop": round(stop, 4),
        "atr": round(atr_v, 4),
        "targets": r_mult["prices"],
        "sizing": sizing,
        "trail_swing": trail,
        "time_stop": time_stop,
        "signal_date": setup.get("timestamp"),
    }


def _overlay_series(df: pd.DataFrame, col: str, n: int = 180) -> list[dict[str, Any]]:
    start = max(0, len(df) - n)
    out: list[dict[str, Any]] = []
    for ts, val in df[col].iloc[start:].items():
        if pd.isna(val):
            continue
        out.append({"time": str(ts)[:10], "value": round(float(val), 6)})
    return out


def analyze_frame(
    df: pd.DataFrame,
    *,
    ticker: str,
    instrument_key: str,
    kind: str,
    company_name: str | None = None,
    account_size: float = 1_000_000.0,
    risk_pct: float = 0.01,
    n_simulations: int = 400,
    full: bool = False,
    chart_df: pd.DataFrame | None = None,
) -> dict[str, Any] | None:
    """Analyse ``df``; when ``chart_df`` is given it supplies the drawn candles.

    ``chart_df`` may extend past ``df`` so a historical session can be charted
    with the bars that followed it, while signals stay as of ``df``'s last bar.
    """
    if df is None or len(df) < MIN_GRIMES_BARS:
        return None
    work = attach_indicators(df)
    pivots = fractal_pivots(work, n=2)
    weekly_up = weekly_ema_rising(work)
    regime_info = classify_regime(work, pivots, weekly_up)
    last_i = len(work) - 1
    last_setups = detect_all_on_bar(work, pivots, last_i)
    primary = _primary_setup(last_setups)
    last = work.iloc[-1]
    quality = _quality_score(primary, regime_info, last)
    vol_rank = None if pd.isna(last.get("atr_pctile")) else round(float(last["atr_pctile"]), 1)

    row: dict[str, Any] = {
        "ticker": ticker,
        "instrument_key": instrument_key,
        "kind": kind,
        "company_name": company_name,
        "as_of": work.index[-1].strftime("%Y-%m-%d"),
        "price": round(float(last["close"]), 4),
        "regime": regime_info["regime"],
        "swing_trend": regime_info.get("swing_trend"),
        "ma_stack": regime_info.get("ma_stack"),
        "weekly_aligned": regime_info.get("weekly_aligned"),
        "weekly_ema_up": regime_info.get("weekly_ema_up"),
        "squeeze": regime_info.get("squeeze"),
        "setup_type": primary["type"] if primary else None,
        "setup_group": primary["group"] if primary else None,
        "setup_side": primary.get("side") if primary else None,
        "setup_flags": primary.get("flags") if primary else None,
        "active_setups": [
            {"type": s["type"], "side": s.get("side"), "group": s.get("group")} for s in last_setups
        ],
        "quality_score": quality,
        "volatility_rank": vol_rank,
        "atr": None if pd.isna(last.get("atr14")) else round(float(last["atr14"]), 4),
        "pivot_count": len(pivots),
    }

    if not full:
        return row

    history = scan_history(work, pivots, lookback=200)
    paper: list[dict[str, Any]] = []
    seen_i: set[int] = set()
    for s in history:
        key = (s["index"], s["type"])
        if s["index"] in seen_i:
            continue
        # one paper trade per bar
        seen_i.add(s["index"])
        stop = hybrid_stop(
            side=s.get("side") or "long",
            entry=float(work["high"].iloc[s["index"]])
            if s.get("side") == "long"
            else float(work["low"].iloc[s["index"]]),
            swing_stop=s.get("swing_stop"),
            atr_value=float(work["atr14"].iloc[s["index"]])
            if pd.notna(work["atr14"].iloc[s["index"]])
            else abs(float(work["close"].iloc[s["index"]])) * 0.02,
        )
        sim = simulate_paper_trade(
            work,
            signal_index=s["index"],
            side=s.get("side") or "long",
            stop=stop,
        )
        if sim:
            sim["setup_type"] = s["type"]
            paper.append(sim)

    # MC on latest setup type dates
    mc = None
    if primary:
        idxs = [s["index"] for s in history if s["type"] == primary["type"]]
        mc = run_monte_carlo_control(
            idxs,
            work,
            n_simulations=n_simulations,
            horizon=10,
            side=primary.get("side") or "long",
        )

    chart_work = work
    forward_bars = 0
    if chart_df is not None and len(chart_df) > len(work):
        try:
            chart_work = attach_indicators(chart_df)
            forward_bars = len(chart_work) - len(work)
        except Exception:
            logger.exception("Grimes chart frame failed for %s — using analysis window", ticker)
            chart_work = work
            forward_bars = 0
    overlay_bars = 180 + forward_bars

    candles = _frame_to_records(chart_work)
    risk = _risk_box(work, primary, account_size, risk_pct) if primary else None

    row.update(
        {
            "candles": candles,
            "pivots": pivots[-80:],
            "sr_zones": recent_sr_zones(pivots, float(last["close"])),
            "ema20": _overlay_series(chart_work, "ema20", n=overlay_bars),
            "sma50": _overlay_series(chart_work, "sma50", n=overlay_bars),
            "kc_upper": _overlay_series(chart_work, "kc_upper", n=overlay_bars),
            "kc_lower": _overlay_series(chart_work, "kc_lower", n=overlay_bars),
            "history_setups": [
                {
                    "type": s["type"],
                    "side": s.get("side"),
                    "group": s.get("group"),
                    "timestamp": s.get("timestamp"),
                    "index": s["index"],
                    "flags": s.get("flags"),
                    "variant": s.get("variant"),
                }
                for s in history
                if s["index"] >= len(work) - 180
            ],
            "risk_box": risk,
            "paper_trades": paper[-80:],
            "expectancy": calculate_expectancy(paper),
            "monte_carlo": mc,
            "regime_detail": regime_info,
            "checklist": SETUP_CHECKLISTS.get(primary["type"]) if primary else None,
        }
    )
    return row


def _analyze_symbol_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    records = payload.get("ohlcv") or []
    if len(records) < MIN_GRIMES_BARS:
        return None
    df = pd.DataFrame(records)
    df["_dt"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["_dt"])
    if not df["_dt"].is_monotonic_increasing:
        df = df.sort_values("_dt", kind="mergesort")
    df = df.set_index("_dt")
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    return analyze_frame(
        df,
        ticker=payload["ticker"],
        instrument_key=payload["instrument_key"],
        kind=payload["kind"],
        company_name=payload.get("company_name"),
        full=False,
    )


def run_grimes_scan(
    *,
    store: TimelineStore | None = None,
    max_workers: int | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    db = store or get_store()
    items = universe_items(db)
    equity_tickers = [i["ticker"] for i in items if i["kind"] == "equity"]
    frames: dict[str, pd.DataFrame] = {}
    batch = 400
    as_of_day = as_of[:10] if as_of else None
    for i in range(0, len(equity_tickers), batch):
        chunk = equity_tickers[i : i + batch]
        frames.update(_load_equity_frames(db, chunk, as_of=as_of_day))
    nifty = _load_nifty_frame(db, as_of=as_of_day)

    payloads: list[dict[str, Any]] = []
    for item in items:
        if item["kind"] == "index":
            if nifty is None:
                continue
            payloads.append({**item, "ohlcv": _frame_to_records(nifty)})
        else:
            frame = frames.get(item["ticker"])
            if frame is None:
                continue
            payloads.append({**item, "ohlcv": _frame_to_records(frame)})

    workers = max_workers or max(1, min(12, (os.cpu_count() or 4)))
    results: list[dict[str, Any]] = []
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
                    logger.exception("Grimes worker failed for %s", ticker)
    except Exception:
        logger.exception("ProcessPool failed — sequential Grimes scan")
        for p in payloads:
            try:
                row = _analyze_symbol_payload(p)
                if row:
                    results.append(row)
            except Exception:
                logger.exception("Grimes sequential failed for %s", p.get("ticker"))

    results.sort(key=lambda r: (r.get("quality_score") or 0), reverse=True)

    def count_reg(name: str) -> int:
        return sum(1 for r in results if r.get("regime") == name)

    def count_setup(name: str) -> int:
        return sum(1 for r in results if r.get("setup_type") == name)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "universe_size": len(payloads),
        "analyzed": len(results),
        "workers": workers,
        "engine_version": ENGINE_VERSION,
        "source": "scan",
        "has_run": True,
        "summary": {
            "trend_bull": count_reg("TREND_BULL"),
            "trend_bear": count_reg("TREND_BEAR"),
            "range": count_reg("TRADING_RANGE"),
            "squeeze": count_reg("VOLATILITY_COMPRESSION"),
            "climax": count_reg("CLIMACTIC_EXHAUSTION"),
            "pullbacks": count_setup("TREND_PULLBACK") + count_setup("COMPLEX_PULLBACK"),
            "squeezes": count_setup("VOL_SQUEEZE"),
            "mean_reversion": sum(
                1
                for r in results
                if r.get("setup_group") == "Mean Reversion"
            ),
            "high_quality": sum(1 for r in results if (r.get("quality_score") or 0) >= 70),
        },
        "results": results,
    }


def empty_grimes_payload(trade_date: str | None = None) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trade_date": trade_date,
        "universe_size": 0,
        "analyzed": 0,
        "workers": 0,
        "engine_version": ENGINE_VERSION,
        "source": "scan",
        "has_run": False,
        "summary": dict(_EMPTY_SUMMARY),
        "results": [],
    }


def get_or_run_grimes_scan(
    *,
    trade_date: str | None = None,
    refresh: bool = False,
    store: TimelineStore | None = None,
    runner: Callable[..., dict[str, Any]] | None = None,
    auto_run_latest: bool = True,
) -> dict[str, Any]:
    """Return persisted scan for ``trade_date``, or compute and store it.

    Historical dates load from DB when a run exists. Missing historical dates
    return an empty payload until Rescan. The latest candle date auto-runs when
    no stored row exists so a new session is not served yesterday's results.
    """
    db = store or get_store()
    latest = db.max_daily_trade_date()
    as_of = (trade_date or "").strip()[:10] or latest
    if not as_of:
        return empty_grimes_payload(None)
    if latest and as_of > latest:
        as_of = latest
    if not refresh:
        loaded = db.load_grimes_summary(as_of, engine_version=ENGINE_VERSION)
        if loaded:
            loaded["has_run"] = True
            return loaded
        if not (auto_run_latest and latest and as_of == latest):
            payload = empty_grimes_payload(as_of)
            payload["source"] = "db"
            return payload
    scan_fn = runner or run_grimes_scan
    payload = scan_fn(store=db, as_of=as_of)
    payload["trade_date"] = as_of
    payload["engine_version"] = ENGINE_VERSION
    payload["source"] = "scan"
    payload["has_run"] = True
    db.replace_grimes_scan(as_of, payload, engine_version=ENGINE_VERSION)
    return payload


def _forward_frame(
    store: TimelineStore,
    *,
    ticker: str,
    kind: str,
    after_day: str,
) -> pd.DataFrame | None:
    """Daily bars strictly after ``after_day`` (chronological), capped for payload size."""
    if kind == "index":
        rows = [
            {
                "date": r.get("ts"),
                "open": r.get("open"),
                "high": r.get("high"),
                "low": r.get("low"),
                "close": r.get("close"),
                "volume": r.get("volume"),
            }
            for r in store.get_index_candles(
                NIFTY_KEY, "daily", from_ts=f"{after_day}T23:59:59.999"
            )
        ]
    else:
        with store.connection() as conn:
            rows = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT trade_date AS date, open_price AS open, high_price AS high,
                           low_price AS low, close_price AS close, volume
                    FROM daily_candles
                    WHERE instrument_token = (
                            SELECT instrument_token FROM security_profiles
                            WHERE UPPER(ticker) = ? LIMIT 1
                          )
                      AND trade_date > ?
                    ORDER BY trade_date ASC
                    LIMIT ?
                    """,
                    [ticker.upper(), after_day, CHART_FORWARD_BARS],
                ).fetchall()
            ]
    if not rows:
        return None
    df = pd.DataFrame(rows[:CHART_FORWARD_BARS])
    df["_dt"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["_dt"]).set_index("_dt")
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            return None
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df[["open", "high", "low", "close", "volume"]] if len(df) else None


def _chart_frame(
    store: TimelineStore,
    frame: pd.DataFrame,
    *,
    ticker: str,
    kind: str,
    as_of_day: str | None,
) -> pd.DataFrame | None:
    """Analysis window plus later bars, so a past session shows what followed."""
    if not as_of_day:
        return None
    try:
        forward = _forward_frame(store, ticker=ticker, kind=kind, after_day=as_of_day)
    except Exception:
        logger.exception("Grimes forward bars failed for %s", ticker)
        return None
    if forward is None or forward.empty:
        return None
    cols = ["open", "high", "low", "close", "volume"]
    combined = pd.concat([frame[cols], forward])
    combined = combined[~combined.index.duplicated(keep="first")].sort_index()
    return combined


def get_chart_payload(
    instrument_key: str,
    *,
    store: TimelineStore | None = None,
    account_size: float = 1_000_000.0,
    risk_pct: float = 0.01,
    n_simulations: int = 400,
    as_of: str | None = None,
) -> dict[str, Any]:
    db = store or get_store()
    key = instrument_key.strip()
    ticker = key.split("|")[-1].upper() if "|" in key else key.upper()
    as_of_day = as_of[:10] if as_of else None
    if ticker in {"NIFTY", "NIFTY 50"} or key == NIFTY_KEY:
        ticker = NIFTY_TICKER
        key = NIFTY_KEY
        frame = _load_nifty_frame(db, as_of=as_of_day)
        kind = "index"
    else:
        if key.upper().startswith("NSE_EQ|"):
            ticker = key.split("|", 1)[1].upper()
        frames = _load_equity_frames(db, [ticker], as_of=as_of_day)
        frame = frames.get(ticker)
        key = equity_instrument_key(ticker)
        kind = "equity"
    if frame is None:
        raise ValueError(f"No local daily candles for {instrument_key}")
    payload = analyze_frame(
        frame,
        ticker=ticker,
        instrument_key=key,
        kind=kind,
        company_name=_company_name_for_ticker(db, ticker, kind),
        account_size=account_size,
        risk_pct=risk_pct,
        n_simulations=n_simulations,
        full=True,
        chart_df=_chart_frame(db, frame, ticker=ticker, kind=kind, as_of_day=as_of_day),
    )
    if payload is None:
        raise ValueError(f"Insufficient history for {instrument_key}")
    return payload


def knowledge_payload() -> dict[str, Any]:
    return {
        "cards": KNOWLEDGE_CARDS,
        "checklists": SETUP_CHECKLISTS,
        "chart_guide": {"intro": CHART_GUIDE_INTRO, "sections": CHART_GUIDE_SECTIONS},
    }
