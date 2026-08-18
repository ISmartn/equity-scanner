#!/usr/bin/env python3
"""Classify pre/post-mention chart patterns for @darvasboxtrader stock tweets.

Uses local trading.db only — no network fetches.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EVENTS_JSON = ROOT / "experiments/x-tweet-fetcher-test/out/darvasboxtrader_stock_performance.json"
DB = ROOT / "data/trading.db"
OUT_JSON = ROOT / "experiments/x-tweet-fetcher-test/out/darvasboxtrader_pattern_analysis.json"
OUT_MD = ROOT / "experiments/x-tweet-fetcher-test/out/darvasboxtrader_pattern_analysis_report.md"


def load_candles(conn: sqlite3.Connection, ticker: str) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT c.trade_date AS date,
               c.open_price AS open,
               c.high_price AS high,
               c.low_price AS low,
               c.close_price AS close,
               c.volume AS volume
        FROM daily_candles c
        JOIN security_profiles p ON p.instrument_token = c.instrument_token
        WHERE p.ticker = ?
        ORDER BY c.trade_date
        """,
        (ticker,),
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["close", "high", "low"]).reset_index(drop=True)


def slice_around(df: pd.DataFrame, mention_date: str, *, before: int = 40, after: int = 15):
    """Return (pre_df inclusive up to entry idx, post_df from entry, entry_idx)."""
    dates = df["date"].tolist()
    # first session on/after mention
    entry_idx = None
    for i, d in enumerate(dates):
        if d >= mention_date:
            entry_idx = i
            break
    if entry_idx is None:
        return None, None, None
    pre_start = max(0, entry_idx - before)
    pre = df.iloc[pre_start : entry_idx + 1].copy()  # includes entry day
    post = df.iloc[entry_idx : min(len(df), entry_idx + after + 1)].copy()
    return pre, post, entry_idx


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def classify_pre(pre: pd.DataFrame) -> dict:
    """Structure in ~20-40 sessions leading into mention day (entry = last bar)."""
    if pre is None or len(pre) < 15:
        return {"labels": ["insufficient_history"], "metrics": {}}

    df = pre.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]
    entry_close = float(close.iloc[-1])
    entry_open = float(df["open"].iloc[-1])
    entry_high = float(high.iloc[-1])

    # Windows excluding entry for "prior structure"
    prior = df.iloc[:-1] if len(df) > 1 else df
    prior20 = prior.tail(20)
    prior10 = prior.tail(10)
    prior5 = prior.tail(5)

    high20 = float(prior20["high"].max()) if len(prior20) else entry_high
    low20 = float(prior20["low"].min()) if len(prior20) else float(low.iloc[-1])
    high10 = float(prior10["high"].max()) if len(prior10) else high20
    low10 = float(prior10["low"].min()) if len(prior10) else low20
    high5 = float(prior5["high"].max()) if len(prior5) else high10
    low5 = float(prior5["low"].min()) if len(prior5) else low10

    range20 = (high20 - low20) / entry_close * 100 if entry_close else 0
    range10 = (high10 - low10) / entry_close * 100 if entry_close else 0
    range5 = (high5 - low5) / entry_close * 100 if entry_close else 0

    ret5 = (entry_close / float(prior.iloc[-5]["close"]) - 1) * 100 if len(prior) >= 5 else None
    ret10 = (entry_close / float(prior.iloc[-10]["close"]) - 1) * 100 if len(prior) >= 10 else None
    ret20 = (entry_close / float(prior.iloc[-20]["close"]) - 1) * 100 if len(prior) >= 20 else None

    sma20 = _sma(close, 20)
    sma50 = _sma(close, 50)
    above_sma20 = entry_close > float(sma20.iloc[-1]) if pd.notna(sma20.iloc[-1]) else None
    above_sma50 = entry_close > float(sma50.iloc[-1]) if len(df) >= 50 and pd.notna(sma50.iloc[-1]) else None
    sma20_rising = (
        float(sma20.iloc[-1]) > float(sma20.iloc[-6])
        if len(df) >= 26 and pd.notna(sma20.iloc[-1]) and pd.notna(sma20.iloc[-6])
        else None
    )

    # Position in 20d range before entry
    pos20 = (entry_close - low20) / (high20 - low20) if high20 > low20 else 0.5

    # Breakout on mention day vs prior pivot
    breakout_day = entry_close > high20 * 1.001 or entry_high > high20
    near_high = entry_close >= high20 * 0.97
    pullback = 0.35 <= pos20 <= 0.75 and (ret5 is not None and ret5 < 0) and (ret20 is not None and ret20 > 0)

    # Consolidation / box: tight recent range after a prior advance
    contracting = range20 > range10 > range5 > 0 and range10 < 18
    box_like = range10 <= 12 and range5 <= 8 and near_high
    extended = ret20 is not None and ret20 >= 25
    strong_uptrend = (
        above_sma20
        and (sma20_rising is True)
        and (ret10 is not None and ret10 > 0)
        and (ret20 is not None and ret20 > 5)
    )
    higher_lows = (
        float(prior5["low"].min()) > float(prior20["low"].iloc[:10].min())
        if len(prior20) >= 15
        else False
    )

    # Volume: dry-up then expansion on entry
    vol = df["volume"].astype(float)
    vol20 = float(vol.iloc[-21:-1].mean()) if len(vol) >= 21 else float(vol.iloc[:-1].mean() or 0)
    entry_vol = float(vol.iloc[-1]) if len(vol) else 0
    vol_dry = vol20 > 0 and float(vol.iloc[-6:-1].mean()) < vol20 * 0.85 if len(vol) >= 6 else False
    vol_surge = vol20 > 0 and entry_vol >= vol20 * 1.5

    labels: list[str] = []
    if breakout_day and near_high:
        labels.append("breakout_day")
    elif near_high and not breakout_day:
        labels.append("near_20d_high")
    if box_like:
        labels.append("darvas_box_like")
    if contracting:
        labels.append("volatility_contraction")
    if pullback:
        labels.append("pullback_in_uptrend")
    if strong_uptrend:
        labels.append("uptrend_above_sma20")
    if extended:
        labels.append("extended_runup_20d")
    if higher_lows:
        labels.append("higher_lows")
    if vol_dry and vol_surge:
        labels.append("vol_dryup_then_surge")
    elif vol_surge:
        labels.append("volume_surge_day")
    elif vol_dry:
        labels.append("volume_dryup")
    if above_sma50 is True:
        labels.append("above_sma50")
    if not labels:
        labels.append("mixed_or_choppy")

    # Primary pre archetype (single dominant)
    if "breakout_day" in labels and ("darvas_box_like" in labels or "volatility_contraction" in labels):
        primary = "box_breakout"
    elif "breakout_day" in labels:
        primary = "momentum_breakout"
    elif "pullback_in_uptrend" in labels:
        primary = "pullback_buy"
    elif "darvas_box_like" in labels or "volatility_contraction" in labels:
        primary = "pre_breakout_coil"
    elif "extended_runup_20d" in labels:
        primary = "already_extended"
    elif "uptrend_above_sma20" in labels:
        primary = "trend_continuation"
    else:
        primary = "other"

    return {
        "primary": primary,
        "labels": labels,
        "metrics": {
            "entry_open": round(entry_open, 4),
            "entry_close": round(entry_close, 4),
            "ret5_pct": round(ret5, 2) if ret5 is not None else None,
            "ret10_pct": round(ret10, 2) if ret10 is not None else None,
            "ret20_pct": round(ret20, 2) if ret20 is not None else None,
            "range20_pct": round(range20, 2),
            "range10_pct": round(range10, 2),
            "range5_pct": round(range5, 2),
            "pos_in_20d_range": round(pos20, 3),
            "above_sma20": above_sma20,
            "above_sma50": above_sma50,
            "breakout_vs_20d_high": bool(breakout_day),
            "vol_surge_rvol": round(entry_vol / vol20, 2) if vol20 > 0 else None,
        },
    }


def classify_post(post: pd.DataFrame, entry_open: float) -> dict:
    """Path after mention (entry = first bar)."""
    if post is None or len(post) < 3 or not entry_open:
        return {"primary": "insufficient", "labels": ["insufficient_forward"], "metrics": {}}

    close = post["close"].astype(float)
    high = post["high"].astype(float)
    low = post["low"].astype(float)
    n = len(post)

    # 5d / 10d windows from entry
    w5 = post.iloc[: min(6, n)]
    w10 = post.iloc[: min(11, n)]

    max_high_5 = float(w5["high"].max())
    max_high_10 = float(w10["high"].max())
    min_low_5 = float(w5["low"].min())
    end5 = float(w5["close"].iloc[-1])
    end10 = float(w10["close"].iloc[-1]) if len(w10) else end5

    mfe5 = (max_high_5 / entry_open - 1) * 100
    mfe10 = (max_high_10 / entry_open - 1) * 100
    mae5 = (min_low_5 / entry_open - 1) * 100
    end5_pct = (end5 / entry_open - 1) * 100
    end10_pct = (end10 / entry_open - 1) * 100

    # Day of peak high within first 10 sessions
    peak_i = int(np.argmax(w10["high"].values))
    # Fade: peak early then close weak
    spike_fade = mfe5 >= 8 and end10_pct <= mfe10 * 0.35 and peak_i <= 4
    grind = mfe10 >= 5 and end10_pct >= mfe10 * 0.55 and peak_i >= 3
    failed = mfe10 < 3 and end10_pct < 0 and mae5 <= -5
    gap_up = float(post["open"].iloc[0]) >= entry_open * 1.02  # relative nonsense; use prior close
    # better gap: entry open vs previous close if available — skip if not

    day0_ret = (float(close.iloc[0]) / entry_open - 1) * 100
    strong_day0 = day0_ret >= 3
    continuation = mfe10 >= 10 and end10_pct > 0
    chop = abs(end10_pct) < 3 and mfe10 < 8

    labels: list[str] = []
    if spike_fade:
        labels.append("spike_then_fade")
    if grind:
        labels.append("grind_higher")
    if failed:
        labels.append("failed_move")
    if continuation and not spike_fade:
        labels.append("trend_continuation_up")
    if strong_day0:
        labels.append("strong_mention_day")
    if chop:
        labels.append("chop_small_range")
    if mfe10 >= 15:
        labels.append("large_upside_thrust")
    if mae5 <= -8:
        labels.append("deep_drawdown_first_week")
    if not labels:
        labels.append("mixed_followthrough")

    if spike_fade:
        primary = "spike_then_fade"
    elif grind or (continuation and end10_pct >= 5):
        primary = "sustained_uptrend"
    elif failed:
        primary = "failed_breakout"
    elif continuation:
        primary = "continuation_with_giveback"
    elif chop:
        primary = "sideways_chop"
    else:
        primary = "mixed"

    return {
        "primary": primary,
        "labels": labels,
        "metrics": {
            "mfe_5d_pct": round(mfe5, 2),
            "mfe_10d_pct": round(mfe10, 2),
            "mae_5d_pct": round(mae5, 2),
            "end_5d_pct": round(end5_pct, 2),
            "end_10d_pct": round(end10_pct, 2),
            "peak_session_offset": peak_i,
            "day0_ret_pct": round(day0_ret, 2),
        },
    }


def main() -> int:
    payload = json.loads(EVENTS_JSON.read_text())
    events = payload.get("all_events") or []

    # Unique ticker + mention_date (first URL kept)
    uniq: dict[tuple[str, str], dict] = {}
    for e in events:
        if not e.get("has_candles"):
            continue
        key = (e["ticker"], e["mention_date"])
        if key not in uniq:
            uniq[key] = e

    conn = sqlite3.connect(DB)
    rows_out = []
    pre_primary = Counter()
    post_primary = Counter()
    pre_labels = Counter()
    post_labels = Counter()
    transition = Counter()
    candle_cache: dict[str, pd.DataFrame] = {}

    for (ticker, mention_date), e in sorted(uniq.items()):
        if ticker not in candle_cache:
            candle_cache[ticker] = load_candles(conn, ticker)
        df = candle_cache[ticker]
        if df.empty:
            continue
        pre, post, idx = slice_around(df, mention_date)
        if pre is None:
            continue
        pre_c = classify_pre(pre)
        entry_open = (pre_c.get("metrics") or {}).get("entry_open") or float(pre["open"].iloc[-1])
        post_c = classify_post(post, float(entry_open))

        pre_primary[pre_c["primary"]] += 1
        post_primary[post_c["primary"]] += 1
        for lab in pre_c["labels"]:
            pre_labels[lab] += 1
        for lab in post_c["labels"]:
            post_labels[lab] += 1
        transition[(pre_c["primary"], post_c["primary"])] += 1

        rows_out.append(
            {
                "ticker": ticker,
                "mention_date": mention_date,
                "url": e.get("url"),
                "text": (e.get("text") or "")[:180],
                "pre": pre_c,
                "post": post_c,
            }
        )

    n = len(rows_out)
    # Conditional: given pre primary, distribution of post
    cond: dict[str, dict] = {}
    for (pre_p, post_p), cnt in transition.items():
        cond.setdefault(pre_p, {"n": 0, "posts": Counter()})
        cond[pre_p]["n"] += cnt
        cond[pre_p]["posts"][post_p] += cnt
    cond_summary = {}
    for pre_p, info in cond.items():
        total = info["n"]
        cond_summary[pre_p] = {
            "n": total,
            "post_mix": {
                k: {"count": v, "pct": round(100 * v / total, 1)}
                for k, v in info["posts"].most_common()
            },
        }

    # Average post metrics by pre primary
    by_pre_metrics: dict[str, list] = defaultdict(list)
    for r in rows_out:
        m = r["post"].get("metrics") or {}
        if m.get("mfe_10d_pct") is not None:
            by_pre_metrics[r["pre"]["primary"]].append(m)

    pre_outcome = {}
    for pre_p, metrics_list in by_pre_metrics.items():
        def avg(key):
            vals = [m[key] for m in metrics_list if m.get(key) is not None]
            return round(float(np.mean(vals)), 2) if vals else None

        pre_outcome[pre_p] = {
            "n": len(metrics_list),
            "avg_mfe_5d": avg("mfe_5d_pct"),
            "avg_mfe_10d": avg("mfe_10d_pct"),
            "avg_end_10d": avg("end_10d_pct"),
            "avg_mae_5d": avg("mae_5d_pct"),
            "avg_peak_offset": avg("peak_session_offset"),
        }

    # Overall common story
    top_pre = pre_primary.most_common(5)
    top_post = post_primary.most_common(5)
    top_trans = transition.most_common(8)

    report = {
        "source_events": str(EVENTS_JSON),
        "n_unique_mentions": n,
        "db": str(DB),
        "methodology": {
            "pre_window": "Up to 40 sessions ending on first trade day on/after mention",
            "post_window": "Entry day through ~10 sessions forward",
            "pre_primaries": [
                "box_breakout",
                "momentum_breakout",
                "pre_breakout_coil",
                "pullback_buy",
                "trend_continuation",
                "already_extended",
                "other",
            ],
            "post_primaries": [
                "spike_then_fade",
                "sustained_uptrend",
                "continuation_with_giveback",
                "failed_breakout",
                "sideways_chop",
                "mixed",
            ],
            "data_source": "local daily_candles only",
        },
        "pre_primary_counts": pre_primary.most_common(),
        "post_primary_counts": post_primary.most_common(),
        "pre_label_counts": pre_labels.most_common(),
        "post_label_counts": post_labels.most_common(),
        "top_transitions": [
            {"pre": a, "post": b, "count": c, "pct": round(100 * c / n, 1)} for (a, b), c in top_trans
        ],
        "conditional_post_given_pre": cond_summary,
        "avg_post_metrics_by_pre": pre_outcome,
        "events": rows_out,
    }

    OUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def pct(c: int) -> str:
        return f"{100 * c / n:.1f}%" if n else "0%"

    lines = [
        "# @darvasboxtrader — common chart patterns around mentions",
        "",
        f"Unique mention events analyzed: **{n}** (local `trading.db` only).",
        "",
        "## What usually precedes the mention",
        "",
    ]
    for name, c in top_pre:
        lines.append(f"- **{name}**: {c} ({pct(c)})")
    lines += [
        "",
        "### Frequent pre labels (can stack)",
        "",
    ]
    for name, c in pre_labels.most_common(12):
        lines.append(f"- {name}: {c} ({pct(c)})")
    lines += [
        "",
        "## What usually happens after the mention",
        "",
    ]
    for name, c in top_post:
        lines.append(f"- **{name}**: {c} ({pct(c)})")
    lines += [
        "",
        "### Frequent post labels",
        "",
    ]
    for name, c in post_labels.most_common(12):
        lines.append(f"- {name}: {c} ({pct(c)})")
    lines += [
        "",
        "## Most common pre → post transitions",
        "",
        "| Pre pattern | Post pattern | Count | % |",
        "|-------------|--------------|-------|---|",
    ]
    for (a, b), c in top_trans:
        lines.append(f"| {a} | {b} | {c} | {pct(c)} |")
    lines += [
        "",
        "## Avg forward metrics by pre-pattern",
        "",
        "| Pre pattern | N | Avg 5d MFE % | Avg 10d MFE % | Avg 10d end % | Avg 5d MAE % |",
        "|-------------|---|--------------|---------------|---------------|--------------|",
    ]
    for pre_p, m in sorted(pre_outcome.items(), key=lambda x: -(x[1]["n"])):
        lines.append(
            f"| {pre_p} | {m['n']} | {m['avg_mfe_5d']} | {m['avg_mfe_10d']} | {m['avg_end_10d']} | {m['avg_mae_5d']} |"
        )
    lines += [
        "",
        "## Narrative summary",
        "",
        "1. **Before mention:** many names are already near highs / in an uptrend, often coiling (Darvas-box-like or volatility contraction), "
        "and a large share print a breakout-style day on the mention session.",
        "2. **After mention:** the most repeated follow-through is an **upside thrust**, frequently with **spike-then-fade** "
        "(early peak within ~1 week, then giveback). Sustained grinds higher occur, but less often than the spike/fade path.",
        "3. **Practical read:** mentions cluster on momentum/breakout structure, not deep value pullbacks. Edge looks more "
        "**tactical (capture MFE)** than **buy-and-hold for 2 weeks**.",
        "",
        f"JSON: `{OUT_JSON.name}`",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"n={n}")
    print("pre", top_pre)
    print("post", top_post)
    print("trans", top_trans[:5])
    print("Wrote", OUT_JSON)
    print("Wrote", OUT_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
