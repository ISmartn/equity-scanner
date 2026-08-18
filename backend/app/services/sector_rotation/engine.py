"""Sector rotation scan: RRG, stealth accumulation, price action, surety."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from ...db.store import TimelineStore, get_store
from .indicators_ext import (
    adx,
    atr,
    cmf,
    ema,
    ensure_ohlcv_frame,
    linreg_slope,
    obv,
    sma,
)
from .synthetic import build_synthetic_ohlcv, constituent_day_returns
from .universe import (
    BENCHMARK_KEY,
    BENCHMARK_NAME,
    SectorUniverseItem,
    all_constituent_tickers,
    all_universe_items,
)

logger = logging.getLogger(__name__)

LOOKBACK_BARS = 520  # ~2y trading days
MIN_BARS = 120


def _index_to_frame(rows: list[dict[str, Any]]) -> pd.DataFrame | None:
    if not rows:
        return None
    df = pd.DataFrame(rows)
    # index candles use `ts`
    if "ts" in df.columns and "date" not in df.columns:
        df = df.rename(columns={"ts": "date"})
    try:
        return ensure_ohlcv_frame(df)
    except ValueError:
        return None


def _load_benchmark(store: TimelineStore) -> pd.DataFrame | None:
    rows = store.get_index_candles(BENCHMARK_KEY, "daily", limit=LOOKBACK_BARS)
    return _index_to_frame(rows)


def _load_equity_frames(
    store: TimelineStore,
    tickers: list[str],
) -> dict[str, pd.DataFrame]:
    """Bulk-load recent daily OHLCV for tickers → {TICKER: frame}."""
    profiles: dict[str, str] = {}
    with store.connection() as conn:
        if tickers:
            placeholders = ",".join("?" for _ in tickers)
            rows = conn.execute(
                f"""
                SELECT ticker, instrument_token
                FROM security_profiles
                WHERE ticker IN ({placeholders})
                """,
                [t.upper() for t in tickers],
            ).fetchall()
            profiles = {str(r["ticker"]).upper(): str(r["instrument_token"]) for r in rows}

    if not profiles:
        return {}

    tokens = list(profiles.values())
    token_to_ticker = {v: k for k, v in profiles.items()}
    by_ticker: dict[str, list[dict[str, Any]]] = {t: [] for t in profiles}

    # Chunk IN lists
    chunk = 300
    with store.connection() as conn:
        for i in range(0, len(tokens), chunk):
            part = tokens[i : i + chunk]
            ph = ",".join("?" for _ in part)
            sql = f"""
                SELECT instrument_token, trade_date AS date,
                       open_price AS open, high_price AS high,
                       low_price AS low, close_price AS close, volume
                FROM daily_candles
                WHERE instrument_token IN ({ph})
                ORDER BY instrument_token ASC, trade_date ASC
            """
            for row in conn.execute(sql, part).fetchall():
                ticker = token_to_ticker.get(str(row["instrument_token"]))
                if not ticker:
                    continue
                by_ticker[ticker].append(dict(row))

    out: dict[str, pd.DataFrame] = {}
    for ticker, rows in by_ticker.items():
        if len(rows) < MIN_BARS:
            continue
        # Keep last LOOKBACK_BARS only (already chronological)
        if len(rows) > LOOKBACK_BARS:
            rows = rows[-LOOKBACK_BARS:]
        try:
            out[ticker] = ensure_ohlcv_frame(pd.DataFrame(rows))
        except ValueError:
            continue
    return out


def _resolve_tickers(store: TimelineStore, item: SectorUniverseItem) -> list[str]:
    tickers = [t.upper() for t in item.tickers]
    if item.profile_sector:
        with store.connection() as conn:
            rows = conn.execute(
                """
                SELECT ticker FROM security_profiles
                WHERE sector = ? AND ingest_skip = 0
                ORDER BY ticker
                """,
                (item.profile_sector,),
            ).fetchall()
        for r in rows:
            t = str(r["ticker"]).upper()
            if t not in tickers:
                tickers.append(t)
    return tickers


def _sector_frame(
    store: TimelineStore,
    item: SectorUniverseItem,
    equity_cache: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame | None, dict[str, pd.DataFrame], str]:
    """Return (ohlcv, constituents_used, source_label).

    Official indices prefer cached index OHLC for the sector series, but always
    attach equity constituents when tickers resolve (for breadth / drill-down).
    """
    tickers = _resolve_tickers(store, item)
    parts = {t: equity_cache[t] for t in tickers if t in equity_cache}

    if item.category == "Official" and item.instrument_key:
        rows = store.get_index_candles(item.instrument_key, "daily", limit=LOOKBACK_BARS)
        frame = _index_to_frame(rows)
        if frame is not None and len(frame) >= MIN_BARS:
            return frame, parts, "index_candles"

    synth = build_synthetic_ohlcv(parts)
    return synth, parts, "synthetic"


def compute_rrg(
    sector_close: pd.Series,
    benchmark_close: pd.Series,
) -> pd.DataFrame:
    """JdK-style RS-Ratio / RS-Momentum; chronological index preserved."""
    aligned = pd.concat(
        [sector_close.rename("sector"), benchmark_close.rename("bench")],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 80:
        return pd.DataFrame()

    rs_raw = (aligned["sector"] / aligned["bench"]) * 100.0
    rs_ratio = 100.0 + ((sma(rs_raw, 10) / sma(rs_raw, 60)) - 1.0) * 100.0
    rs_mom = 100.0 + ((rs_ratio / rs_ratio.shift(10)) - 1.0) * 100.0
    out = pd.DataFrame({"rs_ratio": rs_ratio, "rs_momentum": rs_mom}, index=aligned.index)
    return out.dropna()


def _quadrant(rs_ratio: float, rs_mom: float) -> str:
    if rs_ratio >= 100 and rs_mom >= 100:
        return "Leading"
    if rs_ratio >= 100 and rs_mom < 100:
        return "Weakening"
    if rs_ratio < 100 and rs_mom < 100:
        return "Lagging"
    return "Improving"


def _next_probable_trend(quadrant: str) -> str:
    return {
        "Leading": "Bullish Continuation",
        "Weakening": "Reversal to Bearish",
        "Lagging": "Downtrend",
        "Improving": "Bottoming / Next Bullish",
    }.get(quadrant, "Downtrend")


_CLOCKWISE_NEXT = {
    "Leading": "Weakening",
    "Weakening": "Lagging",
    "Lagging": "Improving",
    "Improving": "Leading",
}
_COUNTER_NEXT = {v: k for k, v in _CLOCKWISE_NEXT.items()}


def _rotation_insight(quadrant: str, rrg: pd.DataFrame, lookback: int = 5) -> dict[str, Any]:
    """Infer early rotation from the recent RRG trail (JdK clockwise cycle)."""
    empty = {
        "rotation_path": None,
        "rotation_bias": "flat",
        "rotation_note": "Insufficient trail",
        "rs_ratio_delta_5d": None,
        "rs_momentum_delta_5d": None,
    }
    if len(rrg) < lookback:
        return empty

    a = rrg.iloc[-lookback]
    b = rrg.iloc[-1]
    d_r = float(b["rs_ratio"] - a["rs_ratio"])
    d_m = float(b["rs_momentum"] - a["rs_momentum"])
    thr = 0.25  # material move on JdK scale (~100 center)

    # Clockwise cues by quadrant (classic RRG rotation)
    clockwise = {
        "Leading": d_m <= -thr,  # mom fades → Weakening
        "Weakening": d_r <= -thr,  # RS fades → Lagging
        "Lagging": d_m >= thr,  # mom rises → Improving
        "Improving": d_r >= thr,  # RS rises → Leading
    }
    counter = {
        "Leading": d_m >= thr,  # mom re-accelerating inside Leading
        "Weakening": d_m >= thr,  # mom turns up → back to Leading
        "Lagging": d_m <= -thr,  # mom worsens inside Lagging
        "Improving": d_r <= -thr,  # RS stalls → back to Lagging
    }

    target = None
    bias = "flat"
    if clockwise.get(quadrant):
        target = _CLOCKWISE_NEXT[quadrant]
        bias = "clockwise"
    elif counter.get(quadrant):
        target = _COUNTER_NEXT[quadrant]
        bias = "counter"

    path = f"{quadrant} → {target}" if target else None

    if quadrant == "Leading" and bias == "clockwise":
        note = (
            f"Momentum fading ({d_m:+.1f}); still Leading until Mom < 100 "
            f"(then Weakening)"
        )
    elif quadrant == "Leading" and bias == "counter":
        note = f"Momentum rising ({d_m:+.1f}); Leading strengthening"
    elif quadrant == "Weakening" and bias == "clockwise":
        note = f"RS fading ({d_r:+.1f}); rotating toward Lagging"
    elif quadrant == "Weakening" and bias == "counter":
        note = f"Momentum turning up ({d_m:+.1f}); may return to Leading"
    elif quadrant == "Lagging" and bias == "clockwise":
        note = f"Momentum rising ({d_m:+.1f}); rotating toward Improving"
    elif quadrant == "Lagging" and bias == "counter":
        note = f"Momentum still falling ({d_m:+.1f}); Lagging deepening"
    elif quadrant == "Improving" and bias == "clockwise":
        note = f"RS rising ({d_r:+.1f}); rotating toward Leading"
    elif quadrant == "Improving" and bias == "counter":
        note = f"RS stalling ({d_r:+.1f}); may slip back to Lagging"
    elif abs(d_r) < thr and abs(d_m) < thr:
        note = "Trail flat — no clear rotation yet"
    else:
        note = f"RS {d_r:+.1f} · Mom {d_m:+.1f} over ~{lookback}d trail"

    return {
        "rotation_path": path,
        "rotation_bias": bias,
        "rotation_note": note,
        "rs_ratio_delta_5d": round(d_r, 2),
        "rs_momentum_delta_5d": round(d_m, 2),
    }


def _trend_label(quadrant: str, insight: dict[str, Any]) -> str:
    """Quadrant baseline, overridden when trail shows early rotation."""
    path = insight.get("rotation_path")
    bias = insight.get("rotation_bias")
    if path and bias == "clockwise":
        return f"Rotating {path}"
    if path and bias == "counter":
        return f"Reversing {path}"
    return _next_probable_trend(quadrant)


def _heading_degrees(rrg: pd.DataFrame, lookback: int = 5) -> float | None:
    if len(rrg) < lookback + 1:
        return None
    a = rrg.iloc[-(lookback + 1)]
    b = rrg.iloc[-1]
    dx = float(b["rs_ratio"] - a["rs_ratio"])
    dy = float(b["rs_momentum"] - a["rs_momentum"])
    if dx == 0 and dy == 0:
        return None
    return float(math.degrees(math.atan2(dy, dx)))


def _positive_rrg_slope(rrg: pd.DataFrame) -> bool:
    if len(rrg) < 6:
        return False
    return float(rrg["rs_ratio"].iloc[-1]) > float(rrg["rs_ratio"].iloc[-6])


def detect_stealth(df: pd.DataFrame) -> bool:
    if len(df) < 260:
        return False
    adx_s, _, _ = adx(df, 14)
    atr14 = atr(df, 14)
    atr_pct = (atr14 / df["close"].replace(0, np.nan)) * 100.0
    quiet = False
    if pd.notna(adx_s.iloc[-1]) and float(adx_s.iloc[-1]) < 22:
        quiet = True
    hist = atr_pct.dropna().iloc[-252:]
    if len(hist) >= 60:
        p25 = float(hist.quantile(0.25))
        if pd.notna(atr_pct.iloc[-1]) and float(atr_pct.iloc[-1]) <= p25:
            quiet = True
    if not quiet:
        return False

    obv_s = obv(df["close"], df["volume"])
    slope = linreg_slope(obv_s, 10)
    cmf20 = cmf(df, 20)
    if pd.isna(slope.iloc[-1]) or pd.isna(cmf20.iloc[-1]):
        return False
    return float(slope.iloc[-1]) > 0 and float(cmf20.iloc[-1]) > 0.08


def detect_price_action(df: pd.DataFrame) -> bool:
    if len(df) < 60:
        return False
    close = df["close"]
    ema20 = ema(close, 20)
    sma50 = sma(close, 50)
    adx_s, plus_di, minus_di = adx(df, 14)
    vol_sma = sma(df["volume"], 20)
    last = -1
    if any(pd.isna(x.iloc[last]) for x in (ema20, sma50, adx_s, plus_di, minus_di, vol_sma)):
        return False
    breakout = float(close.iloc[last]) > float(ema20.iloc[last]) and float(close.iloc[last]) > float(
        sma50.iloc[last]
    )
    trend = float(adx_s.iloc[last]) >= 25 and float(plus_di.iloc[last]) > float(minus_di.iloc[last])
    vol_ok = float(df["volume"].iloc[last]) > 1.3 * float(vol_sma.iloc[last])
    return bool(breakout and trend and vol_ok)


def _breadth_above_50sma(constituents: dict[str, pd.DataFrame], as_of: pd.Timestamp) -> float | None:
    if not constituents:
        return None
    above = 0
    total = 0
    for frame in constituents.values():
        sub = frame.loc[:as_of]
        if len(sub) < 55:
            continue
        ma = sma(sub["close"], 50)
        if pd.isna(ma.iloc[-1]):
            continue
        total += 1
        if float(sub["close"].iloc[-1]) > float(ma.iloc[-1]):
            above += 1
    if total == 0:
        return None
    return round(100.0 * above / total, 1)


def surety_score(
    *,
    quadrant: str,
    positive_slope: bool,
    df: pd.DataFrame,
    breadth_pct: float | None,
) -> int:
    score = 0.0
    # RRG alignment (30)
    if quadrant == "Leading" and positive_slope:
        score += 30
    elif quadrant == "Improving" and positive_slope:
        score += 25
    elif quadrant == "Improving":
        score += 18
    elif quadrant == "Leading":
        score += 22
    elif quadrant == "Weakening":
        score += 10

    close = df["close"]
    e20 = ema(close, 20)
    s50 = sma(close, 50)
    s200 = sma(close, 200)
    if pd.notna(e20.iloc[-1]) and float(close.iloc[-1]) > float(e20.iloc[-1]):
        score += 8
    if pd.notna(e20.iloc[-1]) and pd.notna(s50.iloc[-1]) and float(e20.iloc[-1]) > float(s50.iloc[-1]):
        score += 9
    if pd.notna(s50.iloc[-1]) and pd.notna(s200.iloc[-1]) and float(s50.iloc[-1]) > float(s200.iloc[-1]):
        score += 8

    cmf20 = cmf(df, 20)
    obv_s = obv(close, df["volume"])
    obv_ema = ema(obv_s, 20)
    if pd.notna(cmf20.iloc[-1]) and float(cmf20.iloc[-1]) > 0.15:
        score += 15
    elif pd.notna(cmf20.iloc[-1]) and float(cmf20.iloc[-1]) > 0.05:
        score += 8
    if pd.notna(obv_ema.iloc[-1]) and float(obv_s.iloc[-1]) > float(obv_ema.iloc[-1]):
        score += 10

    if breadth_pct is not None:
        score += max(0.0, min(20.0, breadth_pct / 100.0 * 20.0))

    return int(round(min(100.0, max(0.0, score))))


def _analyze_sector(
    item: SectorUniverseItem,
    sector_df: pd.DataFrame,
    constituents: dict[str, pd.DataFrame],
    benchmark: pd.DataFrame,
    source: str,
) -> dict[str, Any] | None:
    if sector_df is None or len(sector_df) < MIN_BARS:
        return None
    rrg = compute_rrg(sector_df["close"], benchmark["close"])
    if rrg.empty:
        return None

    rs_ratio = float(rrg["rs_ratio"].iloc[-1])
    rs_mom = float(rrg["rs_momentum"].iloc[-1])
    quadrant = _quadrant(rs_ratio, rs_mom)
    as_of = sector_df.index[-1]
    prev = sector_df["close"].iloc[-2] if len(sector_df) > 1 else sector_df["close"].iloc[-1]
    close = float(sector_df["close"].iloc[-1])
    daily_chg = (close / float(prev) - 1.0) * 100.0 if float(prev) else 0.0

    trail = rrg.tail(5)
    sparkline = [round(float(x), 2) for x in trail["rs_ratio"].tolist()]
    trail_points = [
        {"rs_ratio": round(float(r.rs_ratio), 2), "rs_momentum": round(float(r.rs_momentum), 2)}
        for r in trail.itertuples()
    ]

    breadth = _breadth_above_50sma(constituents, as_of)
    stealth = detect_stealth(sector_df)
    price_action = detect_price_action(sector_df)
    pos_slope = _positive_rrg_slope(rrg)
    score = surety_score(
        quadrant=quadrant,
        positive_slope=pos_slope,
        df=sector_df,
        breadth_pct=breadth,
    )
    rotation = _rotation_insight(quadrant, rrg)

    day_rets = constituent_day_returns(constituents, as_of)
    top_gainer = top_laggard = None
    if day_rets:
        day_rets_sorted = sorted(day_rets, key=lambda x: x["change_pct"], reverse=True)
        best = day_rets_sorted[0]
        worst = day_rets_sorted[-1]
        top_gainer = f"{best['ticker']} ({best['change_pct']:+.1f}%)"
        top_laggard = f"{worst['ticker']} ({worst['change_pct']:+.1f}%)"

    return {
        "name": item.name,
        "category": item.category,
        "source": source,
        "current_close": round(close, 2),
        "daily_change_pct": round(daily_chg, 2),
        "rs_ratio": round(rs_ratio, 2),
        "rs_momentum": round(rs_mom, 2),
        "quadrant": quadrant,
        "next_probable_trend": _trend_label(quadrant, rotation),
        "heading_deg": _heading_degrees(rrg),
        "rotation_path": rotation["rotation_path"],
        "rotation_bias": rotation["rotation_bias"],
        "rotation_note": rotation["rotation_note"],
        "rs_ratio_delta_5d": rotation["rs_ratio_delta_5d"],
        "rs_momentum_delta_5d": rotation["rs_momentum_delta_5d"],
        "is_stealth_accumulation": stealth,
        "is_price_action_confirmed": price_action,
        "surety_score": score,
        "breadth_pct_above_50sma": breadth,
        "sparkline_5d": sparkline,
        "trail_5d": trail_points,
        "constituents_summary": {
            "count": len(constituents) or None,
            "top_gainer": top_gainer,
            "top_laggard": top_laggard,
        },
        "as_of": as_of.strftime("%Y-%m-%d"),
    }


def get_sector_constituents(
    sector_name: str,
    *,
    store: TimelineStore | None = None,
) -> dict[str, Any]:
    """Return constituent stock performance for a sector / theme name."""
    db = store or get_store()
    item = next((i for i in all_universe_items() if i.name.lower() == sector_name.lower()), None)
    if item is None:
        raise ValueError(f"Unknown sector: {sector_name}")

    tickers = _resolve_tickers(db, item)
    equity_cache = _load_equity_frames(db, tickers)
    sector_df, constituents, source = _sector_frame(db, item, equity_cache)
    if sector_df is None and constituents:
        sector_df = build_synthetic_ohlcv(constituents)
        source = "synthetic"

    as_of = None
    sector_ret_1d = None
    if sector_df is not None and len(sector_df) >= 2:
        as_of = sector_df.index[-1]
        prev = float(sector_df["close"].iloc[-2])
        last = float(sector_df["close"].iloc[-1])
        if prev > 0:
            sector_ret_1d = (last / prev - 1.0) * 100.0

    names: dict[str, str | None] = {}
    with db.connection() as conn:
        if constituents:
            ph = ",".join("?" for _ in constituents)
            for row in conn.execute(
                f"SELECT ticker, company_name FROM security_profiles WHERE ticker IN ({ph})",
                list(constituents.keys()),
            ).fetchall():
                names[str(row["ticker"]).upper()] = row["company_name"]

    rows: list[dict[str, Any]] = []
    for ticker, frame in constituents.items():
        sub = frame.loc[:as_of] if as_of is not None else frame
        if len(sub) < 2:
            continue
        close = float(sub["close"].iloc[-1])
        prev = float(sub["close"].iloc[-2])
        chg_1d = (close / prev - 1.0) * 100.0 if prev > 0 else None
        chg_5d = None
        chg_20d = None
        if len(sub) >= 6 and float(sub["close"].iloc[-6]) > 0:
            chg_5d = (close / float(sub["close"].iloc[-6]) - 1.0) * 100.0
        if len(sub) >= 21 and float(sub["close"].iloc[-21]) > 0:
            chg_20d = (close / float(sub["close"].iloc[-21]) - 1.0) * 100.0
        ma50 = sma(sub["close"], 50)
        above_50 = None
        if len(sub) >= 50 and pd.notna(ma50.iloc[-1]):
            above_50 = close > float(ma50.iloc[-1])
        vs_sector = None
        if chg_1d is not None and sector_ret_1d is not None:
            vs_sector = chg_1d - sector_ret_1d
        rows.append(
            {
                "ticker": ticker,
                "company_name": names.get(ticker),
                "close": round(close, 2),
                "change_1d_pct": round(chg_1d, 2) if chg_1d is not None else None,
                "change_5d_pct": round(chg_5d, 2) if chg_5d is not None else None,
                "change_20d_pct": round(chg_20d, 2) if chg_20d is not None else None,
                "vs_sector_1d_pct": round(vs_sector, 2) if vs_sector is not None else None,
                "above_50sma": above_50,
            }
        )

    rows.sort(key=lambda r: (r.get("change_1d_pct") is None, -(r.get("change_1d_pct") or 0)))
    return {
        "sector": item.name,
        "category": item.category,
        "source": source,
        "as_of": as_of.strftime("%Y-%m-%d") if as_of is not None else None,
        "sector_change_1d_pct": round(sector_ret_1d, 2) if sector_ret_1d is not None else None,
        "count": len(rows),
        "constituents": rows,
    }


def run_sector_rotation_scan(
    *,
    store: TimelineStore | None = None,
) -> dict[str, Any]:
    db = store or get_store()
    benchmark = _load_benchmark(db)
    if benchmark is None or len(benchmark) < MIN_BARS:
        raise RuntimeError(
            "Nifty 50 daily index candles unavailable. Sync via /api/nifty/sync first."
        )

    needed = all_constituent_tickers()
    # Also pull profile-sector expansions
    for item in all_universe_items():
        needed.extend(_resolve_tickers(db, item))
    needed = sorted(set(needed))
    equity_cache = _load_equity_frames(db, needed)

    sectors: list[dict[str, Any]] = []
    for item in all_universe_items():
        try:
            frame, constituents, source = _sector_frame(db, item, equity_cache)
            row = (
                _analyze_sector(item, frame, constituents, benchmark, source)
                if frame is not None
                else None
            )
            if row:
                sectors.append(row)
        except Exception:
            logger.exception("Sector rotation failed for %s", item.name)

    sectors.sort(key=lambda r: r.get("surety_score") or 0, reverse=True)
    leading = sum(1 for s in sectors if s["quadrant"] == "Leading")
    improving = sum(1 for s in sectors if s["quadrant"] == "Improving")
    stealth_n = sum(1 for s in sectors if s["is_stealth_accumulation"])
    pa_n = sum(1 for s in sectors if s["is_price_action_confirmed"])

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "benchmark": BENCHMARK_NAME,
        "benchmark_as_of": benchmark.index[-1].strftime("%Y-%m-%d"),
        "sectors": sectors,
        "summary": {
            "total": len(sectors),
            "leading": leading,
            "improving": improving,
            "stealth_accumulation": stealth_n,
            "price_action_confirmed": pa_n,
        },
    }
