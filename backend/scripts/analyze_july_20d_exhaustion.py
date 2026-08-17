#!/usr/bin/env python3
"""July 20D pre-return exhaustion study → optimal max_20d_runup_pct.

Uses July quality_v1 pattern_signals + daily_candles forward paths.
Writes data/scanner_analysis/july_20d_exhaustion_report.json (+ .md summary).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT_DIR
from app.db.store import get_store
from app.services.scanner.analysis import compute_forward_performance
from app.services.scanner.quality import compute_quality_metrics
from app.services.scanner.timing import compute_pre_20d_return_pct

OUTPUT_DIR = ROOT_DIR / "data" / "scanner_analysis"
JULY_FROM = "2026-07-01"
JULY_TO = "2026-07-31"
HORIZONS = ("return_1d_pct", "return_5d_pct", "return_10d_pct", "return_20d_pct")

BUCKETS = [
    ("<0%", -1e9, 0.0),
    ("0–10%", 0.0, 10.0),
    ("10–15%", 10.0, 15.0),
    ("15–20%", 15.0, 20.0),
    ("20–25%", 20.0, 25.0),
    ("25–35%", 25.0, 35.0),
    ("35–50%", 35.0, 50.0),
    (">50%", 50.0, 1e9),
]


def _ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def _horizon_stats(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    vals = [float(r[field]) for r in rows if r.get(field) is not None]
    if not vals:
        return {"n": 0}
    wins = sum(1 for v in vals if v > 0)
    losses = [v for v in vals if v <= 0]
    gains = [v for v in vals if v > 0]
    gross_win = sum(gains) if gains else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    mfe = [float(r["max_favorable_pct"]) for r in rows if r.get("max_favorable_pct") is not None]
    mae = [float(r["max_adverse_pct"]) for r in rows if r.get("max_adverse_pct") is not None]
    return {
        "n": len(vals),
        "win_rate_pct": round(wins / len(vals) * 100, 2),
        "false_positive_rate_pct": round((1 - wins / len(vals)) * 100, 2),
        "avg_return_pct": round(float(np.mean(vals)), 4),
        "median_return_pct": round(float(np.median(vals)), 4),
        "profit_factor": (
            round(gross_win / gross_loss, 3) if gross_loss > 1e-9 else (None if not gains else 999.0)
        ),
        "avg_mfe_pct": round(float(np.mean(mfe)), 4) if mfe else None,
        "avg_mae_pct": round(float(np.mean(mae)), 4) if mae else None,
        "expectancy_pct": round(float(np.mean(vals)), 4),
    }


def _block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {h: _horizon_stats(rows, h) for h in HORIZONS}


def _bucket_label(pre: float) -> str:
    for name, lo, hi in BUCKETS:
        if lo <= pre < hi:
            return name
    return "other"


def main() -> int:
    db = get_store()
    signals = [
        s
        for s in db.list_pattern_signals_for_outcomes(
            trade_date_from=JULY_FROM,
            trade_date_to=JULY_TO,
            limit=50_000,
        )
    ]
    gmax = db.stats().get("max_trade_date")
    print(f"July signals: {len(signals)}  max_candle={gmax}", flush=True)

    cache: dict[str, list[dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []

    for i, signal in enumerate(signals):
        if i % 300 == 0:
            print(f"  {i}/{len(signals)}", flush=True)
        ticker = signal["ticker"]
        trade_date = signal["trade_date"]
        entry = signal.get("close")
        if entry is None:
            continue
        if ticker not in cache:
            cache[ticker] = db.get_candles_for_ticker(ticker, to_date=gmax)
        hist = cache[ticker]
        hist_t = [c for c in hist if str(c["date"]) <= trade_date][-280:]
        if len(hist_t) < 55:
            continue
        df = pd.DataFrame(
            [{k: c[k] for k in ("date", "open", "high", "low", "close", "volume")} for c in hist_t]
        )
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)

        details = signal.get("details") or {}
        pre = details.get("pre_20d_return_pct")
        if pre is None:
            pre = compute_pre_20d_return_pct(df)
        if pre is None:
            continue
        pre = float(pre)

        metrics = compute_quality_metrics(df)
        # EMA20 / EMA50 distance
        e20 = _ema(df["close"], 20)
        e50 = _ema(df["close"], 50)
        close = float(df["close"].iloc[-1])
        pct_ema20 = (
            (close / float(e20.iloc[-1]) - 1) * 100
            if len(df) >= 20 and pd.notna(e20.iloc[-1]) and float(e20.iloc[-1]) > 0
            else None
        )
        pct_ema50 = (
            (close / float(e50.iloc[-1]) - 1) * 100
            if len(df) >= 50 and pd.notna(e50.iloc[-1]) and float(e50.iloc[-1]) > 0
            else None
        )
        # Higher-low over last 10 vs prior 10 (pullback/consolidation structure)
        higher_low = None
        if len(df) >= 20:
            higher_low = float(df["low"].iloc[-10:].min()) > float(df["low"].iloc[-20:-10].min())

        perf = compute_forward_performance(
            [c for c in hist if str(c["date"]) >= trade_date],
            entry_date=trade_date,
            entry_close=float(entry),
        )
        # Need at least T+5 for primary cohort; keep rows with whatever horizons exist
        if perf.get("return_5d_pct") is None:
            continue

        rows.append(
            {
                **signal,
                "pre_20d_return_pct": round(pre, 4),
                "bucket": _bucket_label(pre),
                **metrics,
                "pct_above_ema20": round(pct_ema20, 3) if pct_ema20 is not None else None,
                "pct_above_ema50": round(pct_ema50, 3) if pct_ema50 is not None else None,
                "higher_low_10d": higher_low,
                **perf,
            }
        )

    print(f"Rows with ≥5d forward: {len(rows)}")
    triggered = [r for r in rows if r.get("triggered_today")]
    setups = [r for r in rows if not r.get("triggered_today")]

    # Bucket analysis (triggered primary)
    by_bucket: dict[str, Any] = {}
    for name, _, _ in BUCKETS:
        subset = [r for r in triggered if r["bucket"] == name]
        by_bucket[name] = {
            "n": len(subset),
            "horizons": _block(subset),
            "avg_rsi14": (
                round(float(np.mean([float(r["rsi14"]) for r in subset if r.get("rsi14") is not None])), 2)
                if any(r.get("rsi14") is not None for r in subset)
                else None
            ),
            "avg_rvol20": (
                round(float(np.mean([float(r["rvol20"]) for r in subset if r.get("rvol20") is not None])), 3)
                if any(r.get("rvol20") is not None for r in subset)
                else None
            ),
            "avg_pct_ema20": (
                round(
                    float(np.mean([float(r["pct_above_ema20"]) for r in subset if r.get("pct_above_ema20") is not None])),
                    3,
                )
                if any(r.get("pct_above_ema20") is not None for r in subset)
                else None
            ),
            "higher_low_rate_pct": (
                round(
                    sum(1 for r in subset if r.get("higher_low_10d")) / len(subset) * 100,
                    1,
                )
                if subset
                else None
            ),
        }

    # Threshold sweep on triggered: keep if pre_20d <= cap
    sweep_caps = [10, 12, 15, 18, 20, 22, 25, 30, 35]
    sweep: list[dict[str, Any]] = []
    base_trig = _block(triggered)
    for cap in sweep_caps:
        kept = [r for r in triggered if r["pre_20d_return_pct"] <= cap]
        b = _block(kept)
        h10 = b.get("return_10d_pct", {})
        h20 = b.get("return_20d_pct", {})
        h5 = b.get("return_5d_pct", {})
        base5 = base_trig.get("return_5d_pct", {})
        base10 = base_trig.get("return_10d_pct", {})
        base20 = base_trig.get("return_20d_pct", {})
        sweep.append(
            {
                "max_20d_runup_pct": cap,
                "n": len(kept),
                "retention_pct": round(len(kept) / len(triggered) * 100, 2) if triggered else None,
                "return_5d": h5,
                "return_10d": h10,
                "return_20d": h20,
                "delta_5d_wr": round(h5.get("win_rate_pct", 0) - base5.get("win_rate_pct", 0), 2)
                if h5.get("n")
                else None,
                "delta_5d_avg": round(h5.get("avg_return_pct", 0) - base5.get("avg_return_pct", 0), 4)
                if h5.get("n")
                else None,
                "delta_10d_wr": round(h10.get("win_rate_pct", 0) - base10.get("win_rate_pct", 0), 2)
                if h10.get("n")
                else None,
                "delta_10d_avg": round(h10.get("avg_return_pct", 0) - base10.get("avg_return_pct", 0), 4)
                if h10.get("n")
                else None,
                "delta_20d_wr": round(h20.get("win_rate_pct", 0) - base20.get("win_rate_pct", 0), 2)
                if h20.get("n")
                else None,
                "delta_20d_avg": round(h20.get("avg_return_pct", 0) - base20.get("avg_return_pct", 0), 4)
                if h20.get("n")
                else None,
            }
        )

    # Choose optimal: maximize (delta_10d_avg + delta_20d_avg) with retention >= 55% and n>=80
    candidates = [s for s in sweep if (s.get("retention_pct") or 0) >= 55 and (s.get("n") or 0) >= 80]
    if not candidates:
        candidates = [s for s in sweep if (s.get("n") or 0) >= 50]
    def score(s: dict[str, Any]) -> float:
        # Prefer long-horizon expectancy lift, then 5d, then win rate
        return (
            (s.get("delta_20d_avg") or 0) * 2
            + (s.get("delta_10d_avg") or 0) * 1.5
            + (s.get("delta_5d_avg") or 0)
            + (s.get("delta_10d_wr") or 0) * 0.02
        )

    optimal = max(candidates, key=score) if candidates else sweep[0]
    opt_cap = int(optimal["max_20d_runup_pct"])

    # Higher-low confirmation among extended names
    extended = [r for r in triggered if r["pre_20d_return_pct"] > opt_cap]
    extended_hl = [r for r in extended if r.get("higher_low_10d")]
    extended_no_hl = [r for r in extended if r.get("higher_low_10d") is False]

    # Filtered set: pre <= cap OR (pre > cap AND higher_low) — optional soft path
    hard_only = [r for r in triggered if r["pre_20d_return_pct"] <= opt_cap]
    hard_or_hl = [
        r
        for r in triggered
        if r["pre_20d_return_pct"] <= opt_cap
        or (r["pre_20d_return_pct"] > opt_cap and r.get("higher_low_10d"))
    ]

    # Also evaluate all-signals (incl setups) with same hard cap
    all_hard = [r for r in rows if r["pre_20d_return_pct"] <= opt_cap]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "from": JULY_FROM,
            "to": JULY_TO,
            "engine": "quality_v1",
            "signals_total": len(rows),
            "triggered": len(triggered),
            "setups": len(setups),
            "note": (
                "July was re-scanned with quality_v1 gates. Baseline = those triggered "
                "alerts without an additional max_20d_runup cap."
            ),
        },
        "baseline_triggered": _block(triggered),
        "baseline_all": _block(rows),
        "by_pre_20d_bucket_triggered": by_bucket,
        "threshold_sweep_triggered": sweep,
        "optimal": {
            "max_20d_runup_pct": opt_cap,
            "selection_rule": (
                "Maximize weighted long-horizon expectancy lift "
                "(2×Δ20d_avg + 1.5×Δ10d_avg + Δ5d_avg) with retention≥55% and n≥80"
            ),
            "sweep_row": optimal,
        },
        "comparison_triggered": {
            "baseline": {
                "n": len(triggered),
                "horizons": base_trig,
            },
            "filtered_hard_cap": {
                "n": len(hard_only),
                "retention_pct": round(len(hard_only) / len(triggered) * 100, 2) if triggered else None,
                "horizons": _block(hard_only),
            },
            "filtered_hard_or_higher_low": {
                "n": len(hard_or_hl),
                "retention_pct": round(len(hard_or_hl) / len(triggered) * 100, 2) if triggered else None,
                "horizons": _block(hard_or_hl),
                "note": "Allow extended names only if 10d lows are higher than prior 10d (pullback structure)",
            },
            "extended_rejected_profile": {
                "n": len(extended),
                "with_higher_low": _block(extended_hl),
                "without_higher_low": _block(extended_no_hl),
            },
        },
        "recommendation": {
            "max_20d_runup_pct": opt_cap,
            "allow_extended_with_higher_low": True,
            "rationale": (
                f"Cap hard reject above {opt_cap}% prior 20d run-up for triggered alerts; "
                "optionally keep extended names that still show a higher-low base (consolidation "
                "rather than parabolic extension)."
            ),
        },
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "july_20d_exhaustion_report.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Markdown summary
    def fmt_h(block: dict[str, Any], key: str) -> str:
        h = block.get(key) or {}
        if not h.get("n"):
            return "n/a"
        return (
            f"n={h['n']} WR={h.get('win_rate_pct')}% "
            f"avg={h.get('avg_return_pct')} med={h.get('median_return_pct')} "
            f"PF={h.get('profit_factor')} FP={h.get('false_positive_rate_pct')}%"
        )

    md_lines = [
        "# July 20D Pre-Return Exhaustion Study",
        "",
        f"Generated: {report['generated_at']}",
        f"Scope: {JULY_FROM} → {JULY_TO} (quality_v1). Triggered n={len(triggered)}.",
        "",
        "## Baseline (triggered, no extra 20d cap)",
        f"- T+5:  {fmt_h(base_trig, 'return_5d_pct')}",
        f"- T+10: {fmt_h(base_trig, 'return_10d_pct')}",
        f"- T+20: {fmt_h(base_trig, 'return_20d_pct')}",
        "",
        "## By prior 20D run-up bucket (triggered)",
        "| Bucket | n | T+5 WR | T+5 avg | T+10 WR | T+10 avg | T+20 WR | T+20 avg |",
        "|--------|---|--------|---------|---------|----------|---------|----------|",
    ]
    for name, _, _ in BUCKETS:
        b = by_bucket[name]
        h5 = b["horizons"].get("return_5d_pct") or {}
        h10 = b["horizons"].get("return_10d_pct") or {}
        h20 = b["horizons"].get("return_20d_pct") or {}
        md_lines.append(
            f"| {name} | {b['n']} | {h5.get('win_rate_pct')} | {h5.get('avg_return_pct')} | "
            f"{h10.get('win_rate_pct')} | {h10.get('avg_return_pct')} | "
            f"{h20.get('win_rate_pct')} | {h20.get('avg_return_pct')} |"
        )

    md_lines += [
        "",
        f"## Optimal cap: **{opt_cap}%**",
        "",
        "### Baseline vs filtered (triggered)",
        "| Set | n | ret% | T+5 WR/avg | T+10 WR/avg | T+20 WR/avg |",
        "|-----|---|------|------------|-------------|-------------|",
    ]
    for label, key in [
        ("Baseline", "baseline"),
        (f"Hard ≤{opt_cap}%", "filtered_hard_cap"),
        (f"≤{opt_cap}% or higher-low", "filtered_hard_or_higher_low"),
    ]:
        block = report["comparison_triggered"][key]
        hz = block["horizons"]
        h5, h10, h20 = hz.get("return_5d_pct") or {}, hz.get("return_10d_pct") or {}, hz.get("return_20d_pct") or {}
        ret = block.get("retention_pct", 100)
        md_lines.append(
            f"| {label} | {block['n']} | {ret} | "
            f"{h5.get('win_rate_pct')}/{h5.get('avg_return_pct')} | "
            f"{h10.get('win_rate_pct')}/{h10.get('avg_return_pct')} | "
            f"{h20.get('win_rate_pct')}/{h20.get('avg_return_pct')} |"
        )

    md_lines += [
        "",
        "## Recommendation",
        f"- Implement `MAX_20D_RUNUP_PCT = {opt_cap}` hard gate on **triggered** alerts.",
        "- Exception: allow above-cap triggers that still print a **higher low** (10d vs prior 10d).",
        "",
        f"JSON: `{json_path}`",
        "",
    ]
    md_path = OUTPUT_DIR / "july_20d_exhaustion_report.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    print("\n=== Bucket T+10 (triggered) ===")
    for name, _, _ in BUCKETS:
        b = by_bucket[name]
        h = b["horizons"].get("return_10d_pct") or {}
        print(f"  {name}: n={b['n']} WR={h.get('win_rate_pct')} avg={h.get('avg_return_pct')}")
    print(f"\n=== Optimal max_20d_runup_pct = {opt_cap}% ===")
    print(json.dumps(optimal, indent=2))
    print("\n=== Comparison (triggered) ===")
    for label, key in [
        ("BASE", "baseline"),
        ("HARD", "filtered_hard_cap"),
        ("HARD|HL", "filtered_hard_or_higher_low"),
    ]:
        block = report["comparison_triggered"][key]
        hz = block["horizons"]
        for hname in ("return_5d_pct", "return_10d_pct", "return_20d_pct"):
            print(f"  {label} {hname}: {hz.get(hname)}")
    print(f"\nWrote {json_path}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
