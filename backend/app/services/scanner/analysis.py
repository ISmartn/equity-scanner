from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from ...db.store import TimelineStore, get_store
from .engine import run_scanner

DEFAULT_MIN_SCORE = 70.0
DEFAULT_TRADING_DAYS = 22
DEFAULT_PRE_SCAN_WEEKS = 5
DEFAULT_PRE_SCAN_SESSIONS = DEFAULT_PRE_SCAN_WEEKS * 5


def list_recent_trade_dates(store: TimelineStore, *, limit: int = DEFAULT_TRADING_DAYS) -> list[str]:
    with store.connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT trade_date
            FROM daily_candles
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return sorted(row["trade_date"] for row in rows)


def compute_forward_performance(
    candles: list[dict[str, Any]],
    *,
    entry_date: str,
    entry_close: float,
) -> dict[str, Any]:
    """Measure outcome from signal-day close through last available bar."""
    empty = {
        "last_trade_date": None,
        "last_close": None,
        "trading_days_forward": 0,
        "return_to_last_pct": None,
        "return_1d_pct": None,
        "return_3d_pct": None,
        "return_5d_pct": None,
        "return_10d_pct": None,
        "return_20d_pct": None,
        "max_favorable_pct": None,
        "max_adverse_pct": None,
    }
    if not candles or entry_close <= 0:
        return empty

    forward = [c for c in candles if str(c["date"]) >= entry_date]
    if not forward:
        return empty

    last = forward[-1]
    last_close = float(last["close"])
    trading_days_forward = max(0, len(forward) - 1)

    highs = [float(c["high"]) for c in forward]
    lows = [float(c["low"]) for c in forward]

    def close_at_offset(offset: int) -> float | None:
        idx = offset  # forward[0] is entry day
        if idx < len(forward):
            return float(forward[idx]["close"])
        return None

    def return_pct(close_price: float | None) -> float | None:
        if close_price is None:
            return None
        return round((close_price - entry_close) / entry_close * 100, 4)

    return {
        "last_trade_date": str(last["date"]),
        "last_close": round(last_close, 4),
        "trading_days_forward": trading_days_forward,
        "return_to_last_pct": return_pct(last_close),
        "return_1d_pct": return_pct(close_at_offset(1)),
        "return_3d_pct": return_pct(close_at_offset(3)),
        "return_5d_pct": return_pct(close_at_offset(5)),
        "return_10d_pct": return_pct(close_at_offset(10)),
        "return_20d_pct": return_pct(close_at_offset(20)),
        "max_favorable_pct": round((max(highs) - entry_close) / entry_close * 100, 4),
        "max_adverse_pct": round((min(lows) - entry_close) / entry_close * 100, 4),
    }


def compute_daily_path(
    candles: list[dict[str, Any]],
    *,
    entry_date: str,
    entry_close: float,
) -> list[dict[str, Any]]:
    """Per-session OHLCV and returns from signal day through last bar."""
    if not candles or entry_close <= 0:
        return []

    forward = [c for c in candles if str(c["date"]) >= entry_date]
    path: list[dict[str, Any]] = []
    prev_close: float | None = None

    for offset, bar in enumerate(forward):
        close = float(bar["close"])
        daily_return_pct: float | None = None
        if prev_close is not None and prev_close > 0:
            daily_return_pct = round((close - prev_close) / prev_close * 100, 4)
        elif bar.get("daily_return_pct") is not None:
            daily_return_pct = round(float(bar["daily_return_pct"]), 4)

        path.append(
            {
                "date": str(bar["date"]),
                "day_offset": offset,
                "open": round(float(bar["open"]), 4),
                "high": round(float(bar["high"]), 4),
                "low": round(float(bar["low"]), 4),
                "close": close,
                "volume": int(bar.get("volume") or 0),
                "return_from_entry_pct": round((close - entry_close) / entry_close * 100, 4),
                "daily_return_pct": daily_return_pct,
            }
        )
        prev_close = close

    return path


def compute_pre_scan_path(
    candles: list[dict[str, Any]],
    *,
    signal_date: str,
    lookback_sessions: int = DEFAULT_PRE_SCAN_SESSIONS,
) -> list[dict[str, Any]]:
    """OHLCV for sessions before the signal (negative day_offset, -N … -1)."""
    if not candles or lookback_sessions <= 0:
        return []

    pre = [c for c in candles if str(c["date"]) < signal_date]
    window = pre[-lookback_sessions:]
    path: list[dict[str, Any]] = []

    for index, bar in enumerate(window):
        path.append(
            {
                "date": str(bar["date"]),
                "day_offset": index - len(window),
                "open": round(float(bar["open"]), 4),
                "high": round(float(bar["high"]), 4),
                "low": round(float(bar["low"]), 4),
                "close": round(float(bar["close"]), 4),
                "volume": int(bar.get("volume") or 0),
                "daily_return_pct": (
                    round(float(bar["daily_return_pct"]), 4)
                    if bar.get("daily_return_pct") is not None
                    else None
                ),
            }
        )

    return path


def flatten_pre_scan_rows(signal: dict[str, Any], pre_scan_path: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = {
        "signal_date": signal["trade_date"],
        "ticker": signal["ticker"],
        "pattern_type": signal["pattern_type"],
        "score": signal["score"],
    }
    return [{**base, **day} for day in pre_scan_path]


def summarize_by_pattern(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[float]] = {}
    for row in records:
        value = row.get("return_5d_pct")
        if value is None:
            continue
        buckets.setdefault(row["pattern_type"], []).append(float(value))

    summary: dict[str, dict[str, Any]] = {}
    for pattern, values in sorted(buckets.items()):
        winners = sum(1 for v in values if v > 0)
        summary[pattern] = {
            "count": len(values),
            "win_rate_5d_pct": round(winners / len(values) * 100, 2),
            "avg_return_5d_pct": round(sum(values) / len(values), 4),
            "median_return_5d_pct": round(sorted(values)[len(values) // 2], 4),
        }
    return summary


def summarize_by_field(
    records: list[dict[str, Any]],
    field: str,
    *,
    return_field: str = "return_5d_pct",
) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[float]] = {}
    for row in records:
        value = row.get(return_field)
        if value is None:
            continue
        key = str(row.get(field))
        buckets.setdefault(key, []).append(float(value))

    summary: dict[str, dict[str, Any]] = {}
    for key, values in sorted(buckets.items()):
        winners = sum(1 for v in values if v > 0)
        summary[key] = {
            "count": len(values),
            "win_rate_5d_pct": round(winners / len(values) * 100, 2),
            "avg_return_5d_pct": round(sum(values) / len(values), 4),
        }
    return summary


def score_band(score: float) -> str:
    if score >= 90:
        return "90+"
    if score >= 80:
        return "80-89"
    return "70-79"


def build_signal_id(signal: dict[str, Any]) -> str:
    return f"{signal['ticker']}|{signal['trade_date']}|{signal['pattern_type']}"


def flatten_daily_rows(signal: dict[str, Any], daily_path: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One CSV row per signal × forward session."""
    base = {
        "signal_date": signal["trade_date"],
        "ticker": signal["ticker"],
        "pattern_type": signal["pattern_type"],
        "score": signal["score"],
        "entry_close": signal.get("entry_close"),
    }
    rows: list[dict[str, Any]] = []
    for day in daily_path:
        rows.append({**base, **day})
    return rows


def enrich_signal_with_forward(
    store: TimelineStore,
    signal: dict[str, Any],
    *,
    global_max_date: str | None = None,
    pre_scan_sessions: int = DEFAULT_PRE_SCAN_SESSIONS,
) -> dict[str, Any]:
    ticker = signal["ticker"]
    trade_date = signal["trade_date"]
    entry_close = signal.get("close")
    if entry_close is None:
        candles_on_day = store.get_candles_for_ticker(ticker, from_date=trade_date, to_date=trade_date)
        entry_close = float(candles_on_day[0]["close"]) if candles_on_day else None

    to_date = global_max_date or store.stats().get("max_trade_date")
    history = store.get_candles_for_ticker(ticker, to_date=to_date)
    forward_candles = [c for c in history if str(c["date"]) >= trade_date]

    performance = compute_forward_performance(
        forward_candles,
        entry_date=trade_date,
        entry_close=float(entry_close) if entry_close is not None else 0.0,
    )
    daily_path = compute_daily_path(
        forward_candles,
        entry_date=trade_date,
        entry_close=float(entry_close) if entry_close is not None else 0.0,
    )
    pre_scan_path = compute_pre_scan_path(
        history,
        signal_date=trade_date,
        lookback_sessions=pre_scan_sessions,
    )

    details = signal.get("details") or {}
    return {
        "signal_id": build_signal_id(signal),
        "trade_date": trade_date,
        "ticker": ticker,
        "company_name": signal.get("company_name"),
        "sector": signal.get("sector"),
        "pattern_type": signal["pattern_type"],
        "score": float(signal["score"]),
        "pattern_score": details.get("pattern_score"),
        "macro_pass": bool(signal.get("macro_pass")),
        "triggered_today": bool(signal.get("triggered_today")),
        "setup_ready": bool(signal.get("setup_ready")),
        "entry_close": round(float(entry_close), 4) if entry_close is not None else None,
        "open": signal.get("open"),
        "high": signal.get("high"),
        "low": signal.get("low"),
        "close": signal.get("close"),
        "volume": signal.get("volume"),
        "fundamental_pass": (details.get("fundamental") or {}).get("pass"),
        "market_score_delta": (details.get("market") or {}).get("score_delta"),
        "details": details,
        "pre_scan_sessions": len(pre_scan_path),
        "pre_scan_path": pre_scan_path,
        "daily_path": daily_path,
        **performance,
    }


def collect_signals_for_date(
    store: TimelineStore,
    trade_date: str,
    *,
    min_score: float = DEFAULT_MIN_SCORE,
    run_scan: bool = True,
) -> list[dict[str, Any]]:
    if run_scan:
        run_scanner(trade_date=trade_date, store=store)

    rows, _total = store.query_pattern_signals(
        trade_date,
        min_score=min_score,
        limit=5000,
        offset=0,
    )
    return rows


def build_scanner_analysis_dataset(
    *,
    trading_days: int = DEFAULT_TRADING_DAYS,
    min_score: float = DEFAULT_MIN_SCORE,
    pre_scan_sessions: int = DEFAULT_PRE_SCAN_SESSIONS,
    run_scans: bool = True,
    store: TimelineStore | None = None,
    on_progress: Any | None = None,
) -> dict[str, Any]:
    db = store or get_store()
    stats = db.stats()
    scanned = db.list_scanner_dates(limit=max(trading_days, 365))
    scan_dates = sorted(scanned[-trading_days:]) if scanned else []
    global_max = stats.get("max_trade_date")

    records: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    pre_scan_rows: list[dict[str, Any]] = []
    total_signals_raw = 0

    for index, scan_date in enumerate(scan_dates):
        if on_progress:
            on_progress(
                {
                    "phase": "scan",
                    "scan_date": scan_date,
                    "date_index": index + 1,
                    "date_total": len(scan_dates),
                }
            )

        signals = collect_signals_for_date(
            db,
            scan_date,
            min_score=min_score,
            run_scan=run_scans,
        )
        total_signals_raw += len(signals)

        for sig in signals:
            if on_progress:
                on_progress(
                    {
                        "phase": "forward",
                        "scan_date": scan_date,
                        "ticker": sig["ticker"],
                        "date_index": index + 1,
                        "date_total": len(scan_dates),
                    }
                )
            records.append(
                enrich_signal_with_forward(
                    db,
                    sig,
                    global_max_date=global_max,
                    pre_scan_sessions=pre_scan_sessions,
                )
            )
            daily_rows.extend(flatten_daily_rows(records[-1], records[-1]["daily_path"]))
            pre_scan_rows.extend(flatten_pre_scan_rows(records[-1], records[-1]["pre_scan_path"]))

    return_pct_values = [r["return_to_last_pct"] for r in records if r.get("return_to_last_pct") is not None]
    return_5d_values = [r["return_5d_pct"] for r in records if r.get("return_5d_pct") is not None]
    winners = sum(1 for v in return_pct_values if v > 0)
    winners_5d = sum(1 for v in return_5d_values if v > 0)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "description": "Momentum scanner backtest with pre-scan context and forward returns",
        "filters": {
            "min_score": min_score,
            "pattern": "all",
            "sector": "all",
            "trading_days_window": trading_days,
            "pre_scan_sessions": pre_scan_sessions,
        },
        "data_range": {
            "scan_dates_from": scan_dates[0] if scan_dates else None,
            "scan_dates_to": scan_dates[-1] if scan_dates else None,
            "scan_dates": scan_dates,
            "db_max_trade_date": global_max,
            "db_min_trade_date": stats.get("min_trade_date"),
        },
        "summary": {
            "scan_days": len(scan_dates),
            "signals_min_score": len(records),
            "signals_before_dedup_note": "Multiple patterns per ticker-day allowed",
            "with_forward_returns": len(return_pct_values),
            "win_rate_to_last_pct": round(winners / len(return_pct_values) * 100, 2)
            if return_pct_values
            else None,
            "avg_return_to_last_pct": round(sum(return_pct_values) / len(return_pct_values), 4)
            if return_pct_values
            else None,
            "win_rate_5d_pct": round(winners_5d / len(return_5d_values) * 100, 2)
            if return_5d_values
            else None,
            "avg_return_5d_pct": round(sum(return_5d_values) / len(return_5d_values), 4)
            if return_5d_values
            else None,
            "daily_path_rows": len(daily_rows),
            "pre_scan_rows": len(pre_scan_rows),
            "by_pattern_5d": summarize_by_pattern(records),
            "by_macro_pass_5d": summarize_by_field(records, "macro_pass"),
            "by_triggered_5d": summarize_by_field(records, "triggered_today"),
            "by_score_band_5d": summarize_by_field(
                [{**r, "score_band": score_band(float(r["score"]))} for r in records],
                "score_band",
            ),
        },
        "records": records,
        "daily_rows": daily_rows,
        "pre_scan_rows": pre_scan_rows,
    }
    return manifest


REFINEMENT_SCHEMA_VERSION = "1.0"


def build_refinement_dataset(manifest: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Single JSON artifact for external analysis / scanner tuning."""
    summary = manifest.get("summary") or {}
    return {
        "schema_version": REFINEMENT_SCHEMA_VERSION,
        "purpose": (
            "Momentum scanner refinement dataset: each signal includes pattern details, "
            "5 weeks pre-scan OHLCV, and forward performance bars for tuning thresholds."
        ),
        "field_guide": {
            "signals[].pre_scan_path": "OHLCV before scan; day_offset -25..-1",
            "signals[].daily_path": "OHLCV from scan day forward; day_offset 0+",
            "signals[].details": "Raw pattern detector output (volume, trend, FO overlay, etc.)",
            "signals[].return_5d_pct": "Primary horizon for refinement (5 sessions after entry close)",
        },
        "generated_at": manifest.get("generated_at"),
        "filters": manifest.get("filters"),
        "data_range": manifest.get("data_range"),
        "summary": summary,
        "aggregates": {
            "by_pattern_5d": summary.get("by_pattern_5d"),
            "by_macro_pass_5d": summary.get("by_macro_pass_5d"),
            "by_triggered_5d": summary.get("by_triggered_5d"),
            "by_score_band_5d": summary.get("by_score_band_5d"),
        },
        "signal_count": len(records),
        "signals": records,
    }


LLM_SCHEMA_VERSION = "1.0-llm"

# Column order for compact row arrays (keeps JSON small for LLM context).
LLM_SIGNAL_COLUMNS = [
    "trade_date",
    "ticker",
    "sector",
    "pattern_type",
    "score",
    "pattern_score",
    "macro_pass",
    "triggered_today",
    "setup_ready",
    "fundamental_pass",
    "market_score_delta",
    "entry_close",
    "return_5d_pct",
    "return_10d_pct",
    "return_20d_pct",
    "return_to_last_pct",
    "max_favorable_pct",
    "max_adverse_pct",
    "trading_days_forward",
    "volume_ratio",
    "volume_zscore",
    "in_base",
    "gap_pct",
    "flagpole_pct",
    "base_depth_pct",
    "fo_multiplier",
]


def _scalar_feature(details: dict[str, Any], key: str) -> Any:
    val = details.get(key)
    if isinstance(val, dict):
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return round(float(val), 4) if isinstance(val, float) else val
    return val


def signal_to_llm_row(record: dict[str, Any]) -> list[Any]:
    details = record.get("details") or {}
    fundamental = details.get("fundamental") or {}
    fo = details.get("fo_overlay") or {}

    row_map = {
        "trade_date": record.get("trade_date"),
        "ticker": record.get("ticker"),
        "sector": record.get("sector"),
        "pattern_type": record.get("pattern_type"),
        "score": record.get("score"),
        "pattern_score": record.get("pattern_score"),
        "macro_pass": record.get("macro_pass"),
        "triggered_today": record.get("triggered_today"),
        "setup_ready": record.get("setup_ready"),
        "fundamental_pass": record.get("fundamental_pass"),
        "market_score_delta": record.get("market_score_delta"),
        "entry_close": record.get("entry_close"),
        "return_5d_pct": record.get("return_5d_pct"),
        "return_10d_pct": record.get("return_10d_pct"),
        "return_20d_pct": record.get("return_20d_pct"),
        "return_to_last_pct": record.get("return_to_last_pct"),
        "max_favorable_pct": record.get("max_favorable_pct"),
        "max_adverse_pct": record.get("max_adverse_pct"),
        "trading_days_forward": record.get("trading_days_forward"),
        "volume_ratio": _scalar_feature(details, "volume_ratio"),
        "volume_zscore": _scalar_feature(details, "volume_zscore"),
        "in_base": _scalar_feature(details, "in_base"),
        "gap_pct": _scalar_feature(details, "gap_pct"),
        "flagpole_pct": _scalar_feature(details, "flagpole_pct"),
        "base_depth_pct": _scalar_feature(details, "base_depth_pct"),
        "fo_multiplier": _scalar_feature(details, "fo_multiplier")
        if details.get("fo_multiplier") is not None
        else fo.get("multiplier"),
    }
    return [row_map.get(col) for col in LLM_SIGNAL_COLUMNS]


def _top_examples(records: list[dict[str, Any]], *, n: int = 15) -> dict[str, list[dict[str, Any]]]:
    ranked = [r for r in records if r.get("return_5d_pct") is not None]
    ranked.sort(key=lambda r: float(r["return_5d_pct"]), reverse=True)
    winners = ranked[:n]
    losers = ranked[-n:] if len(ranked) >= n else []

    def mini(rec: dict[str, Any]) -> dict[str, Any]:
        pre = rec.get("pre_scan_path") or []
        fwd = rec.get("daily_path") or []
        return {
            "signal_id": rec.get("signal_id"),
            "trade_date": rec.get("trade_date"),
            "ticker": rec.get("ticker"),
            "pattern_type": rec.get("pattern_type"),
            "score": rec.get("score"),
            "return_5d_pct": rec.get("return_5d_pct"),
            "pre_scan_last_5": pre[-5:],
            "forward_first_10": fwd[:11],
        }

    return {
        "top_5d_winners": [mini(r) for r in winners],
        "bottom_5d_losers": [mini(r) for r in losers],
    }


def build_llm_refinement_dataset(manifest: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compact dataset sized for LLM analysis (~1–2 MB, no full OHLCV paths)."""
    summary = manifest.get("summary") or {}
    sector_records = [
        {**r, "sector_key": (r.get("sector") or "unknown")[:40]} for r in records
    ]
    by_sector = summarize_by_field(sector_records, "sector_key")

    return {
        "schema_version": LLM_SCHEMA_VERSION,
        "purpose": (
            "LLM-friendly momentum scanner refinement export. "
            "Use aggregates + signal_rows for threshold tuning; see examples for chart context."
        ),
        "how_to_read": {
            "signal_columns": LLM_SIGNAL_COLUMNS,
            "signal_rows": "Each inner array aligns with signal_columns (same order).",
            "primary_metric": "return_5d_pct",
            "full_dataset_with_paths": "data/scanner_analysis/scanner_refinement_dataset.json",
        },
        "generated_at": manifest.get("generated_at"),
        "filters": manifest.get("filters"),
        "data_range": manifest.get("data_range"),
        "summary": {
            k: v
            for k, v in summary.items()
            if k
            not in {
                "daily_path_rows",
                "pre_scan_rows",
                "by_pattern_5d",
                "by_macro_pass_5d",
                "by_triggered_5d",
                "by_score_band_5d",
            }
        },
        "aggregates": {
            "by_pattern_5d": summary.get("by_pattern_5d"),
            "by_macro_pass_5d": summary.get("by_macro_pass_5d"),
            "by_triggered_5d": summary.get("by_triggered_5d"),
            "by_score_band_5d": summary.get("by_score_band_5d"),
            "by_sector_5d": by_sector,
        },
        "examples": _top_examples(records),
        "signal_count": len(records),
        "signal_columns": LLM_SIGNAL_COLUMNS,
        "signal_rows": [signal_to_llm_row(r) for r in records],
    }
