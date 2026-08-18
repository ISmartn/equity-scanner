"""Scan universe for multi-year breakout / ATH pullback / custom strategies."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from threading import Lock
from typing import Any, Callable

import pandas as pd

from ...db.store import TimelineStore, get_store
from ..scanner.context import evaluate_fundamental_gate
from .detector import (
    DEFAULT_ATH_PULLBACK_PCT,
    StrategyId,
    detect_ath_pullback,
    detect_multi_year_breakout,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]
DEFAULT_LOOKBACK_YEARS = 3
DEFAULT_CONCURRENCY = 8
STRATEGIES: tuple[StrategyId, ...] = ("multi_year_breakout", "ath_pullback", "custom")
PROGRESS_EVERY = 25


def _default_trade_date(store: TimelineStore) -> str:
    stats = store.stats()
    return stats["max_trade_date"] or date.today().isoformat()


def _min_bars_for_strategy(strategy: str, years: int) -> int:
    if strategy == "ath_pullback":
        return 250
    return max(400, int(years * 200))


def _candle_window_limit(strategy: str, years: int, long_ma_period: int) -> int:
    min_bars = _min_bars_for_strategy(strategy, years)
    if strategy in ("ath_pullback", "custom"):
        # Need long history for ATH; local DB is ~5y so ~1300 bars covers it.
        return max(min_bars + 80, int(long_ma_period) + 50, 1300)
    return min_bars + 80


def _passes_global_filters(
    hit_details: dict[str, Any],
    *,
    close_price: float,
    rvol20: float | None,
    avg_turnover_inr: float | None,
    sector: str | None,
    size_tier: str | None,
    filters: dict[str, Any],
) -> bool:
    want_sector = filters.get("sector")
    if want_sector and sector and sector != want_sector:
        return False
    if want_sector and not sector:
        return False

    want_size = filters.get("size_tier")
    if want_size and want_size != "all":
        if size_tier != want_size:
            return False

    min_price = filters.get("min_price")
    max_price = filters.get("max_price")
    if min_price is not None and close_price < float(min_price):
        return False
    if max_price is not None and close_price > float(max_price):
        return False

    min_rvol = filters.get("min_rvol")
    if min_rvol is not None and (rvol20 is None or rvol20 < float(min_rvol)):
        return False

    min_turnover = filters.get("min_avg_turnover_inr")
    if min_turnover is not None and (
        avg_turnover_inr is None or avg_turnover_inr < float(min_turnover)
    ):
        return False

    return True


def _hit_to_row(
    hit: Any,
    *,
    meta: dict[str, Any],
    scan_date: str,
    lookback_years: int,
    run_id: int,
    strategy: str,
    fundamental: dict[str, Any] | None = None,
) -> dict[str, Any]:
    details = dict(hit.details or {})
    details["strategy"] = strategy
    if fundamental is not None:
        details["fundamental"] = fundamental
    return {
        "run_id": run_id,
        "trade_date": scan_date,
        "ticker": meta["ticker"],
        "sector": meta.get("sector"),
        "company_name": meta.get("company_name"),
        "strategy": strategy,
        "status": hit.status,
        "lookback_years": lookback_years,
        "prior_high": hit.prior_high,
        "prior_high_date": hit.prior_high_date,
        "years_since_high": hit.years_since_high,
        "close_price": hit.close_price,
        "breakout_pct": hit.breakout_pct,
        "drop_from_ath_pct": hit.drop_from_ath_pct,
        "rvol20": hit.rvol20,
        "rsi14": hit.rsi14,
        "avg_turnover_inr": hit.avg_turnover_inr,
        "score": hit.score,
        "details": details,
    }


def _scan_ticker_rows(
    meta: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    scan_date: str,
    strategy: str,
    lookback_years: int,
    run_id: int,
    pullback_pct: float,
    match_mode: str,
    band_width_pct: float,
    trend_filter: str,
    short_ma_period: int,
    long_ma_period: int,
    ma_type: str,
    custom_flags: dict[str, bool],
    filters: dict[str, Any],
    fundamental: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    min_bars = _min_bars_for_strategy(strategy, lookback_years)
    if len(rows) < min_bars or str(rows[-1]["date"]) != scan_date:
        return []

    df = pd.DataFrame(rows)
    out: list[dict[str, Any]] = []
    pullback_kwargs = {
        "pullback_pct": pullback_pct,
        "match_mode": match_mode,
        "band_width_pct": band_width_pct,
        "trend_filter": trend_filter,
        "short_ma_period": short_ma_period,
        "long_ma_period": long_ma_period,
        "ma_type": ma_type,
    }

    def maybe_add(hit: Any, strat: str, years: int) -> None:
        if hit is None:
            return
        size_tier = (hit.details or {}).get("size_tier")
        if not _passes_global_filters(
            hit.details or {},
            close_price=hit.close_price,
            rvol20=hit.rvol20,
            avg_turnover_inr=hit.avg_turnover_inr,
            sector=meta.get("sector"),
            size_tier=size_tier,
            filters=filters,
        ):
            return
        # Query-time trend filter can still refine; scan-time trend already applied in detector
        want_trend = filters.get("trend")
        if want_trend in ("uptrend", "downtrend"):
            if (hit.details or {}).get("trend") != want_trend:
                return
        row = _hit_to_row(
            hit,
            meta=meta,
            scan_date=scan_date,
            lookback_years=years,
            run_id=run_id,
            strategy=strat,
            fundamental=fundamental,
        )
        out.append(row)

    if strategy == "multi_year_breakout":
        maybe_add(
            detect_multi_year_breakout(df, lookback_years=lookback_years),
            "multi_year_breakout",
            lookback_years,
        )
    elif strategy == "ath_pullback":
        maybe_add(
            detect_ath_pullback(df, **pullback_kwargs),
            "ath_pullback",
            0,
        )
    else:
        want_breakout = custom_flags.get("include_multi_year", True)
        want_pullback = custom_flags.get("include_ath_pullback", True)
        if want_breakout:
            maybe_add(
                detect_multi_year_breakout(df, lookback_years=lookback_years),
                "custom",
                lookback_years,
            )
        if want_pullback and not out:
            maybe_add(
                detect_ath_pullback(df, **pullback_kwargs),
                "custom",
                lookback_years,
            )

    return out


def run_multi_year_breakout_scan(
    *,
    trade_date: str | None = None,
    strategy: str = "multi_year_breakout",
    lookback_years: int = DEFAULT_LOOKBACK_YEARS,
    pullback_pct: float = DEFAULT_ATH_PULLBACK_PCT,
    match_mode: str = "at_least",
    band_width_pct: float = 5.0,
    trend_filter: str = "all",
    short_ma_period: int = 50,
    long_ma_period: int = 200,
    ma_type: str = "sma",
    custom_flags: dict[str, bool] | None = None,
    filters: dict[str, Any] | None = None,
    store: TimelineStore | None = None,
    on_progress: ProgressCallback | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> dict[str, Any]:
    db = store or get_store()
    scan_date = trade_date or _default_trade_date(db)
    strat = strategy if strategy in STRATEGIES else "multi_year_breakout"
    years = max(2, min(int(lookback_years), 5))
    workers = max(1, concurrency)
    min_bars = _min_bars_for_strategy(strat, years)
    candle_limit = _candle_window_limit(strat, years, int(long_ma_period))
    filt = dict(filters or {})
    flags = dict(custom_flags or {"include_multi_year": True, "include_ath_pullback": True})
    trend = (trend_filter or "all").lower()

    tickers_meta = db.list_scan_eligible_tickers(min_bars=min_bars, as_of_date=scan_date)
    want_sector = filt.get("sector")
    if want_sector:
        tickers_meta = [m for m in tickers_meta if m.get("sector") == want_sector]

    # One bulk read replaces ~2 SQLite round-trips per ticker.
    candles_by_ticker = db.get_recent_candles_window_for_scan(
        min_bars=min_bars,
        limit=candle_limit,
        as_of_date=scan_date,
        instrument_tokens=[m["instrument_token"] for m in tickers_meta],
    )
    fundamentals_index = db.load_fundamentals_index()

    total = len(tickers_meta)

    db.delete_myb_data_for_date(scan_date, strategy=strat, lookback_years=years if strat != "ath_pullback" else 0)
    run_id = db.create_myb_run(
        scan_date,
        strategy=strat,
        lookback_years=0 if strat == "ath_pullback" else years,
        params={
            "pullback_pct": pullback_pct,
            "match_mode": match_mode,
            "band_width_pct": band_width_pct,
            "trend_filter": trend,
            "short_ma_period": short_ma_period,
            "long_ma_period": long_ma_period,
            "ma_type": ma_type,
            "custom_flags": flags,
            "filters": filt,
        },
    )

    signals: list[dict[str, Any]] = []
    scanned = 0
    lock = Lock()

    def emit(ticker: str | None = None, *, force: bool = False) -> None:
        if on_progress and (force or scanned % PROGRESS_EVERY == 0 or scanned == total):
            on_progress(
                {
                    "total": total,
                    "processed": scanned,
                    "alerts_count": len(signals),
                    "current_ticker": ticker,
                    "trade_date": scan_date,
                    "lookback_years": years,
                    "strategy": strat,
                }
            )

    emit(force=True)

    scan_kwargs = {
        "scan_date": scan_date,
        "strategy": strat,
        "lookback_years": years,
        "run_id": run_id,
        "pullback_pct": pullback_pct,
        "match_mode": match_mode,
        "band_width_pct": band_width_pct,
        "trend_filter": trend,
        "short_ma_period": int(short_ma_period),
        "long_ma_period": int(long_ma_period),
        "ma_type": ma_type,
        "custom_flags": flags,
        "filters": filt,
    }

    def consume(results: list[dict[str, Any]], ticker: str) -> None:
        nonlocal scanned
        with lock:
            scanned += 1
            signals.extend(results)
            emit(ticker)

    def work(meta: dict[str, Any]) -> list[dict[str, Any]]:
        rows = candles_by_ticker.get(meta["ticker"]) or []
        fundamental = evaluate_fundamental_gate(fundamentals_index.get(meta["ticker"]))
        return _scan_ticker_rows(meta, rows, fundamental=fundamental, **scan_kwargs)

    try:
        if workers == 1:
            for meta in tickers_meta:
                consume(work(meta), meta["ticker"])
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(work, meta): meta["ticker"] for meta in tickers_meta}
                for future in as_completed(futures):
                    ticker = futures[future]
                    try:
                        consume(future.result(), ticker)
                    except Exception as exc:
                        logger.warning("MYB scan failed for %s: %s", ticker, exc)
                        consume([], ticker)

        db.insert_myb_signals(signals)
        db.finish_myb_run(
            run_id,
            symbols_scanned=scanned,
            alerts_count=len(signals),
            status="completed",
        )
    except Exception:
        db.finish_myb_run(run_id, symbols_scanned=scanned, alerts_count=0, status="failed")
        raise

    emit(None, force=True)
    by_status: dict[str, int] = {}
    by_trend: dict[str, int] = {}
    for s in signals:
        by_status[s["status"]] = by_status.get(s["status"], 0) + 1
        t = (s.get("details") or {}).get("trend") or "unknown"
        by_trend[str(t)] = by_trend.get(str(t), 0) + 1

    return {
        "run_id": run_id,
        "trade_date": scan_date,
        "strategy": strat,
        "lookback_years": 0 if strat == "ath_pullback" else years,
        "pullback_pct": pullback_pct if strat in ("ath_pullback", "custom") else None,
        "match_mode": match_mode if strat in ("ath_pullback", "custom") else None,
        "trend_filter": trend if strat in ("ath_pullback", "custom") else None,
        "symbols_scanned": scanned,
        "alerts_count": len(signals),
        "breakout_count": by_status.get("breakout", 0),
        "near_count": by_status.get("near", 0),
        "pullback_count": by_status.get("pullback", 0),
        "trend_counts": by_trend if strat in ("ath_pullback", "custom") else None,
        "status": "completed",
        "concurrency": workers,
    }
