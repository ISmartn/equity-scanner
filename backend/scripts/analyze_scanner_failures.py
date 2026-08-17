#!/usr/bin/env python3
"""Winner vs loser Day-T feature analysis for momentum scanner false positives.

Computes forward returns (T+1..T+5), MFE/MAE, and Day-T technical/volume profiles.
Tests candidate quality filters and writes a JSON report for codebase tuning.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT_DIR
from app.db.store import get_store
from app.services.scanner.analysis import compute_forward_performance
from app.services.scanner.indicators import close_position_in_range, sma, volume_zscore
from app.services.scanner.scoring import passes_posthoc_quality_filters

OUTPUT_DIR = ROOT_DIR / "data" / "scanner_analysis"
REPORT_NAME = "failure_pattern_analysis.json"

# Primary horizon for winner/loser split
PRIMARY_HORIZON = "return_5d_pct"
HORIZONS = ("return_1d_pct", "return_2d_pct", "return_3d_pct", "return_5d_pct")


def _rsi(close: pd.Series, window: int = 14) -> float | None:
    if len(close) < window + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    last_gain = float(gain.iloc[-1]) if pd.notna(gain.iloc[-1]) else None
    last_loss = float(loss.iloc[-1]) if pd.notna(loss.iloc[-1]) else None
    if last_gain is None or last_loss is None:
        return None
    if last_loss == 0:
        return 100.0
    rs = last_gain / last_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _rvol(volume: pd.Series, window: int = 20) -> float | None:
    if len(volume) < window + 1:
        return None
    avg = float(volume.iloc[-(window + 1) : -1].mean())
    if avg <= 0:
        return None
    return round(float(volume.iloc[-1]) / avg, 3)


def _upper_wick_ratio(row: pd.Series) -> float | None:
    high = float(row["high"])
    low = float(row["low"])
    open_ = float(row["open"])
    close = float(row["close"])
    span = high - low
    if span <= 0:
        return None
    body_top = max(open_, close)
    return round((high - body_top) / span, 3)


def _pct_above(price: float, level: float | None) -> float | None:
    if level is None or level <= 0:
        return None
    return round((price / level - 1.0) * 100.0, 3)


def day_t_features(df: pd.DataFrame) -> dict[str, Any]:
    """Compute Day-T technical / volume features from bars ending on signal date."""
    if len(df) < 50:
        return {}
    last = df.iloc[-1]
    close = float(last["close"])
    sma50 = sma(df["close"], 50)
    sma150 = sma(df["close"], 150) if len(df) >= 150 else None
    sma200 = sma(df["close"], 200) if len(df) >= 200 else None
    vol_z = volume_zscore(df["volume"], 50)
    last_vol_z = float(vol_z.iloc[-1]) if pd.notna(vol_z.iloc[-1]) else None
    pre_20 = None
    if len(df) >= 21:
        prior = float(df["close"].iloc[-21])
        if prior > 0:
            pre_20 = round((close / prior - 1.0) * 100.0, 3)
    signal_day = None
    if len(df) >= 2:
        prior = float(df["close"].iloc[-2])
        if prior > 0:
            signal_day = round((close / prior - 1.0) * 100.0, 3)

    high_52 = float(df["high"].iloc[-252:].max()) if len(df) >= 60 else float(df["high"].max())
    low_52 = float(df["low"].iloc[-252:].min()) if len(df) >= 60 else float(df["low"].min())

    return {
        "rsi14": _rsi(df["close"], 14),
        "rvol20": _rvol(df["volume"], 20),
        "volume_z50": round(last_vol_z, 3) if last_vol_z is not None else None,
        "close_position": round(close_position_in_range(last), 3),
        "upper_wick_ratio": _upper_wick_ratio(last),
        "pct_above_sma50": _pct_above(close, float(sma50.iloc[-1]) if pd.notna(sma50.iloc[-1]) else None),
        "pct_above_sma150": _pct_above(
            close, float(sma150.iloc[-1]) if sma150 is not None and pd.notna(sma150.iloc[-1]) else None
        ),
        "pct_above_sma200": _pct_above(
            close, float(sma200.iloc[-1]) if sma200 is not None and pd.notna(sma200.iloc[-1]) else None
        ),
        "pre_20d_return_pct": pre_20,
        "signal_day_return_pct": signal_day,
        "pct_of_52w_high": round(close / high_52 * 100, 2) if high_52 > 0 else None,
        "pct_above_52w_low": _pct_above(close, low_52),
    }


def _forward_with_2d(candles: list[dict], entry_date: str, entry_close: float) -> dict[str, Any]:
    perf = compute_forward_performance(candles, entry_date=entry_date, entry_close=entry_close)
    # analysis module may not expose 2d; compute from path
    forward = [c for c in candles if str(c["date"]) > entry_date]
    if len(forward) >= 2 and entry_close > 0:
        perf["return_2d_pct"] = round((float(forward[1]["close"]) / entry_close - 1.0) * 100.0, 4)
    else:
        perf["return_2d_pct"] = None
    # MDD proxy over first 5 sessions from entry close
    path = forward[:5]
    if path and entry_close > 0:
        trough = min(float(c["low"]) for c in path)
        peak = max(float(c["high"]) for c in path)
        perf["mdd_5d_pct"] = round((trough / entry_close - 1.0) * 100.0, 4)
        perf["runup_5d_pct"] = round((peak / entry_close - 1.0) * 100.0, 4)
    else:
        perf["mdd_5d_pct"] = None
        perf["runup_5d_pct"] = None
    return perf


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    arr = np.array(values, dtype=float)
    return {
        "n": int(len(arr)),
        "mean": round(float(arr.mean()), 4),
        "median": round(float(np.median(arr)), 4),
        "p25": round(float(np.percentile(arr, 25)), 4),
        "p75": round(float(np.percentile(arr, 75)), 4),
    }


def _group_profile(rows: list[dict[str, Any]], feature_keys: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"n": len(rows)}
    for key in feature_keys:
        vals = [float(r[key]) for r in rows if r.get(key) is not None and not math.isnan(float(r[key]))]
        out[key] = _stats(vals)
    return out


def _horizon_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    block: dict[str, Any] = {}
    for h in HORIZONS:
        vals = [float(r[h]) for r in rows if r.get(h) is not None]
        if not vals:
            block[h] = {"n": 0}
            continue
        wins = sum(1 for v in vals if v > 0)
        mfe = [float(r["max_favorable_pct"]) for r in rows if r.get("max_favorable_pct") is not None]
        mae = [float(r["max_adverse_pct"]) for r in rows if r.get("max_adverse_pct") is not None]
        mdd = [float(r["mdd_5d_pct"]) for r in rows if r.get("mdd_5d_pct") is not None]
        expectancy = float(np.mean(vals))
        block[h] = {
            "n": len(vals),
            "win_rate_pct": round(wins / len(vals) * 100, 2),
            "avg_return_pct": round(expectancy, 4),
            "median_return_pct": round(float(np.median(vals)), 4),
            "avg_mfe_pct": round(float(np.mean(mfe)), 4) if mfe else None,
            "avg_mae_pct": round(float(np.mean(mae)), 4) if mae else None,
            "avg_mdd_5d_pct": round(float(np.mean(mdd)), 4) if mdd else None,
            "expectancy_pct": round(expectancy, 4),
            "rr_proxy": (
                round(abs(float(np.mean(mfe)) / float(np.mean(mae))), 3)
                if mfe and mae and abs(float(np.mean(mae))) > 1e-9
                else None
            ),
        }
    return block


def candidate_filters() -> dict[str, Any]:
    """Named filter predicates tested for before/after lift."""

    def base(row: dict[str, Any]) -> bool:
        return True

    def current_refined(row: dict[str, Any]) -> bool:
        return passes_posthoc_quality_filters(row)

    def reject_overbought(row: dict[str, Any]) -> bool:
        rsi = row.get("rsi14")
        if rsi is not None and rsi > 75:
            return False
        pct50 = row.get("pct_above_sma50")
        if pct50 is not None and pct50 > 20:
            return False
        return True

    def require_rvol(row: dict[str, Any]) -> bool:
        rvol = row.get("rvol20")
        vz = row.get("volume_z50")
        # Accept either RVOL>=1.5 or volume z>=1.0 (institutional participation)
        if rvol is not None and rvol >= 1.5:
            return True
        if vz is not None and vz >= 1.0:
            return True
        # setups (not triggered) can pass with softer volume
        if not row.get("triggered_today"):
            return True
        return False

    def reject_upper_wick(row: dict[str, Any]) -> bool:
        wick = row.get("upper_wick_ratio")
        close_pos = row.get("close_position")
        # shooting-star / exhaustion: large upper wick + weak close
        if wick is not None and wick >= 0.45 and close_pos is not None and close_pos < 0.55:
            return False
        return True

    def reject_extended_chase(row: dict[str, Any]) -> bool:
        pre = row.get("pre_20d_return_pct")
        day = row.get("signal_day_return_pct")
        if pre is not None and pre > 25:
            return False
        if day is not None and day > 8 and (pre is not None and pre > 12):
            return False
        return True

    def require_macro(row: dict[str, Any]) -> bool:
        return bool(row.get("macro_pass"))

    def prefer_setup_or_confirmed(row: dict[str, Any]) -> bool:
        # Prefer setup_ready; if triggered, require strong close + volume
        if row.get("setup_ready") and not row.get("triggered_today"):
            return True
        if row.get("triggered_today"):
            close_pos = row.get("close_position")
            if close_pos is not None and close_pos < 0.65:
                return False
            return require_rvol(row) and reject_upper_wick(row)
        return True

    def proposed_v1(row: dict[str, Any]) -> bool:
        """SIMPLE quality gates shipped in quality.py."""
        from app.services.scanner.quality import passes_quality_gates

        metrics = {
            "close_position": row.get("close_position"),
            "upper_wick_ratio": row.get("upper_wick_ratio"),
            "volume_z50": row.get("volume_z50"),
            "rvol20": row.get("rvol20"),
            "rsi14": row.get("rsi14"),
            "pct_above_sma50": row.get("pct_above_sma50"),
        }
        details = {
            "base_depth_pct": (row.get("details") or {}).get("base_depth_pct"),
            "pre_20d_return_pct": row.get("pre_20d_return_pct"),
            "close_position": row.get("close_position"),
            "volume_zscore": row.get("volume_z50"),
        }
        keep, _ = passes_quality_gates(
            pattern_type=str(row.get("pattern_type") or ""),
            triggered_today=bool(row.get("triggered_today")),
            metrics=metrics,
            details=details,
        )
        return keep

    def proposed_v2(row: dict[str, Any]) -> bool:
        """Stricter: SIMPLE + macro_pass required for triggers."""
        if not proposed_v1(row):
            return False
        if row.get("triggered_today") and not row.get("macro_pass"):
            return False
        return True

    return {
        "baseline_all": base,
        "current_refined": current_refined,
        "reject_overbought": reject_overbought,
        "require_rvol_on_trigger": require_rvol,
        "reject_upper_wick": reject_upper_wick,
        "reject_extended_chase": reject_extended_chase,
        "require_macro": require_macro,
        "prefer_setup_or_confirmed": prefer_setup_or_confirmed,
        "proposed_v1_simple_quality": proposed_v1,
        "proposed_v2_macro_triggers": proposed_v2,
    }


def main() -> int:
    db = get_store()
    signals = db.list_pattern_signals_for_outcomes(limit=50_000)
    global_max = db.stats().get("max_trade_date")
    print(f"Signals: {len(signals)}  max_trade_date={global_max}")

    candle_cache: dict[str, list[dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []
    feature_keys = [
        "rsi14",
        "rvol20",
        "volume_z50",
        "close_position",
        "upper_wick_ratio",
        "pct_above_sma50",
        "pct_above_sma150",
        "pct_above_sma200",
        "pre_20d_return_pct",
        "signal_day_return_pct",
        "pct_of_52w_high",
        "pct_above_52w_low",
        "score",
    ]

    for i, signal in enumerate(signals):
        if i % 400 == 0:
            print(f"  feature+forward {i}/{len(signals)}", flush=True)
        ticker = signal["ticker"]
        trade_date = signal["trade_date"]
        entry_close = signal.get("close")
        if entry_close is None:
            continue
        if ticker not in candle_cache:
            candle_cache[ticker] = db.get_candles_for_ticker(ticker, to_date=global_max)
        history = candle_cache[ticker]
        # bars up to and including signal day for Day-T features
        hist_to_t = [c for c in history if str(c["date"]) <= trade_date]
        if len(hist_to_t) < 50:
            continue
        df = pd.DataFrame(
            [
                {
                    "date": c["date"],
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"]),
                    "volume": float(c["volume"]),
                }
                for c in hist_to_t[-280:]
            ]
        )
        feats = day_t_features(df)
        forward = [c for c in history if str(c["date"]) >= trade_date]
        perf = _forward_with_2d(forward, trade_date, float(entry_close))
        if perf.get(PRIMARY_HORIZON) is None:
            continue
        details = signal.get("details") or {}
        rows.append(
            {
                **signal,
                **feats,
                **perf,
                "score": float(signal.get("score") or 0),
                "timing_class": details.get("timing_class"),
                "volume_zscore_detail": details.get("volume_zscore"),
            }
        )

    print(f"Rows with 5d outcomes + features: {len(rows)}")

    winners = [r for r in rows if float(r[PRIMARY_HORIZON]) > 0]
    losers = [r for r in rows if float(r[PRIMARY_HORIZON]) <= 0]

    # Threshold slice diagnostics
    slices: dict[str, Any] = {}
    slice_defs = [
        ("rsi14>75", lambda r: r.get("rsi14") is not None and r["rsi14"] > 75),
        ("rsi14>70", lambda r: r.get("rsi14") is not None and r["rsi14"] > 70),
        ("rsi14<=65", lambda r: r.get("rsi14") is not None and r["rsi14"] <= 65),
        ("pct_above_sma50>20", lambda r: r.get("pct_above_sma50") is not None and r["pct_above_sma50"] > 20),
        ("pct_above_sma50>15", lambda r: r.get("pct_above_sma50") is not None and r["pct_above_sma50"] > 15),
        ("pct_above_sma50<=10", lambda r: r.get("pct_above_sma50") is not None and r["pct_above_sma50"] <= 10),
        ("rvol20<1.2", lambda r: r.get("rvol20") is not None and r["rvol20"] < 1.2),
        ("rvol20>=1.5", lambda r: r.get("rvol20") is not None and r["rvol20"] >= 1.5),
        ("rvol20>=2.0", lambda r: r.get("rvol20") is not None and r["rvol20"] >= 2.0),
        ("volume_z50<0.5", lambda r: r.get("volume_z50") is not None and r["volume_z50"] < 0.5),
        ("volume_z50>=1.0", lambda r: r.get("volume_z50") is not None and r["volume_z50"] >= 1.0),
        ("upper_wick>=0.45", lambda r: r.get("upper_wick_ratio") is not None and r["upper_wick_ratio"] >= 0.45),
        ("close_pos<0.55", lambda r: r.get("close_position") is not None and r["close_position"] < 0.55),
        ("close_pos>=0.70", lambda r: r.get("close_position") is not None and r["close_position"] >= 0.70),
        ("pre_20d>25", lambda r: r.get("pre_20d_return_pct") is not None and r["pre_20d_return_pct"] > 25),
        ("pre_20d>15", lambda r: r.get("pre_20d_return_pct") is not None and r["pre_20d_return_pct"] > 15),
        ("pre_20d<=10", lambda r: r.get("pre_20d_return_pct") is not None and r["pre_20d_return_pct"] <= 10),
        ("signal_day>8", lambda r: r.get("signal_day_return_pct") is not None and r["signal_day_return_pct"] > 8),
        ("macro_pass=True", lambda r: bool(r.get("macro_pass"))),
        ("macro_pass=False", lambda r: not bool(r.get("macro_pass"))),
        ("triggered=True", lambda r: bool(r.get("triggered_today"))),
        ("setup_ready=True", lambda r: bool(r.get("setup_ready"))),
        ("wick_exhaustion", lambda r: (
            r.get("upper_wick_ratio") is not None
            and r["upper_wick_ratio"] >= 0.45
            and r.get("close_position") is not None
            and r["close_position"] < 0.55
        )),
    ]
    for name, pred in slice_defs:
        subset = [r for r in rows if pred(r)]
        slices[name] = _horizon_block(subset).get(PRIMARY_HORIZON, {"n": 0})

    by_pattern: dict[str, Any] = {}
    for r in rows:
        by_pattern.setdefault(r["pattern_type"], []).append(r)
    pattern_profiles = {
        k: {
            "all": _horizon_block(v),
            "winners_n": sum(1 for x in v if float(x[PRIMARY_HORIZON]) > 0),
            "losers_n": sum(1 for x in v if float(x[PRIMARY_HORIZON]) <= 0),
        }
        for k, v in sorted(by_pattern.items())
    }

    # Filter experiments
    filters = candidate_filters()
    filter_results: dict[str, Any] = {}
    baseline_n = len(rows)
    for name, pred in filters.items():
        kept = [r for r in rows if pred(r)]
        block = _horizon_block(kept)
        h5 = block.get(PRIMARY_HORIZON, {})
        filter_results[name] = {
            "n": len(kept),
            "retention_pct": round(len(kept) / baseline_n * 100, 2) if baseline_n else None,
            "horizons": block,
            "delta_vs_baseline_5d": {
                "win_rate_pct": (
                    round(h5["win_rate_pct"] - _horizon_block(rows)[PRIMARY_HORIZON]["win_rate_pct"], 2)
                    if h5.get("win_rate_pct") is not None
                    else None
                ),
                "avg_return_pct": (
                    round(h5["avg_return_pct"] - _horizon_block(rows)[PRIMARY_HORIZON]["avg_return_pct"], 4)
                    if h5.get("avg_return_pct") is not None
                    else None
                ),
                "n": len(kept) - baseline_n,
            },
        }

    # Dominant failure modes ranked by loser enrichment
    failure_modes = []
    for name, pred in slice_defs:
        in_slice = [r for r in rows if pred(r)]
        if len(in_slice) < 30:
            continue
        loser_rate = sum(1 for r in in_slice if float(r[PRIMARY_HORIZON]) <= 0) / len(in_slice)
        base_loser = len(losers) / len(rows) if rows else 0
        failure_modes.append(
            {
                "slice": name,
                "n": len(in_slice),
                "loser_rate_pct": round(loser_rate * 100, 2),
                "base_loser_rate_pct": round(base_loser * 100, 2),
                "enrichment": round(loser_rate / base_loser, 3) if base_loser else None,
                "avg_return_5d_pct": round(float(np.mean([float(r[PRIMARY_HORIZON]) for r in in_slice])), 4),
            }
        )
    failure_modes.sort(key=lambda x: (x["enrichment"] or 0), reverse=True)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "primary_horizon": PRIMARY_HORIZON,
        "sample": {
            "signals_with_5d": len(rows),
            "winners_5d": len(winners),
            "losers_5d": len(losers),
            "win_rate_5d_pct": round(len(winners) / len(rows) * 100, 2) if rows else None,
            "date_from": min(r["trade_date"] for r in rows) if rows else None,
            "date_to": max(r["trade_date"] for r in rows) if rows else None,
        },
        "forward_performance_all": _horizon_block(rows),
        "winner_day_t_profile": _group_profile(winners, feature_keys),
        "loser_day_t_profile": _group_profile(losers, feature_keys),
        "feature_deltas_winner_minus_loser": {
            k: {
                "winner_mean": (_group_profile(winners, feature_keys).get(k) or {}).get("mean"),
                "loser_mean": (_group_profile(losers, feature_keys).get(k) or {}).get("mean"),
                "delta": round(
                    ((_group_profile(winners, feature_keys).get(k) or {}).get("mean") or 0)
                    - ((_group_profile(losers, feature_keys).get(k) or {}).get("mean") or 0),
                    4,
                )
                if (_group_profile(winners, feature_keys).get(k) or {}).get("mean") is not None
                and (_group_profile(losers, feature_keys).get(k) or {}).get("mean") is not None
                else None,
            }
            for k in feature_keys
        },
        "slice_diagnostics_5d": slices,
        "dominant_failure_modes": failure_modes[:15],
        "by_pattern": pattern_profiles,
        "filter_experiments": filter_results,
        "recommendation": {
            "preferred_filter": "proposed_v1_simple_quality",
            "rationale": (
                "Do NOT reject high RSI (winners are slightly more overbought — this is momentum). "
                "Reject weak trigger closes (close_position < 0.65), climactic volume without "
                "conviction (volume_z >= 3.5 and close < 0.75), and deep VCP bases (> 25%). "
                "Prefer moderate RVOL (z ~1–2.5) via scoring, not hard volume blow-off cuts."
            ),
        },
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / REPORT_NAME
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Console summary
    print("\n=== Forward performance (all) ===")
    print(json.dumps(report["forward_performance_all"], indent=2))
    print("\n=== Top failure modes (loser enrichment) ===")
    for fm in failure_modes[:10]:
        print(
            f"  {fm['slice']}: n={fm['n']} loser_rate={fm['loser_rate_pct']}% "
            f"enrich={fm['enrichment']} avg5d={fm['avg_return_5d_pct']}"
        )
    print("\n=== Filter experiments (5d) ===")
    for name, fr in filter_results.items():
        h5 = fr["horizons"].get(PRIMARY_HORIZON, {})
        print(
            f"  {name}: n={fr['n']} ret={fr['retention_pct']}% "
            f"win={h5.get('win_rate_pct')}% avg={h5.get('avg_return_pct')} "
            f"Δwin={fr['delta_vs_baseline_5d'].get('win_rate_pct')} "
            f"Δavg={fr['delta_vs_baseline_5d'].get('avg_return_pct')}"
        )
    print(f"\nWrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
