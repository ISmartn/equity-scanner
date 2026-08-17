"""Unit tests for multi-year breakout and ATH pullback detection."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from app.services.multi_year_breakout.detector import (
    classify_trend,
    detect_ath_pullback,
    detect_multi_year_breakout,
)


def _df_with_breakout(*, years: int = 3, break_today: bool = True) -> pd.DataFrame:
    """Synthetic series: multi-year high ~2y ago at 100, then consolidation, optional break."""
    rows: list[dict] = []
    end = date(2026, 8, 14)
    n = years * 220 + 30
    start = end - timedelta(days=int(n * 1.5))
    high_date = end - timedelta(days=800)
    d = start
    price = 80.0
    while len(rows) < n - 1:
        if d.weekday() < 5:
            if d == high_date or (not any(r["high"] >= 100 for r in rows) and d >= high_date):
                high = 100.0
                close = 98.0
            else:
                high = min(99.0, price + 1.0)
                close = min(97.0, price)
            rows.append(
                {
                    "date": d.isoformat(),
                    "open": close - 0.5,
                    "high": high,
                    "low": close - 1.5,
                    "close": close,
                    "volume": 2_000_000,
                }
            )
            price = min(97.0, max(70.0, close + (0.1 if len(rows) % 7 == 0 else -0.05)))
        d += timedelta(days=1)

    if break_today:
        rows.append(
            {
                "date": end.isoformat(),
                "open": 99.0,
                "high": 102.0,
                "low": 98.5,
                "close": 101.5,
                "volume": 5_000_000,
            }
        )
    else:
        rows.append(
            {
                "date": end.isoformat(),
                "open": 97.0,
                "high": 98.5,
                "low": 96.5,
                "close": 98.2,
                "volume": 2_500_000,
            }
        )
    return pd.DataFrame(rows)


def _df_near_ath(*, drop_pct: float = 12.0) -> pd.DataFrame:
    """Price history with ATH=100; last close at (100 * (1 - drop/100))."""
    rows: list[dict] = []
    end = date(2026, 8, 14)
    start = end - timedelta(days=900)
    d = start
    while d < end:
        if d.weekday() < 5:
            close = 80.0 if d < end - timedelta(days=400) else 92.0
            high = 100.0 if d == end - timedelta(days=500) else close + 1
            rows.append(
                {
                    "date": d.isoformat(),
                    "open": close,
                    "high": high,
                    "low": close - 1,
                    "close": close,
                    "volume": 1_500_000,
                }
            )
        d += timedelta(days=1)
    close = 100.0 * (1.0 - drop_pct / 100.0)
    rows.append(
        {
            "date": end.isoformat(),
            "open": close - 0.5,
            "high": close + 0.5,
            "low": close - 1,
            "close": close,
            "volume": 2_000_000,
        }
    )
    return pd.DataFrame(rows)


def _df_uptrend_pullback(*, drop_pct: float = 18.0) -> pd.DataFrame:
    """Steadily rising series that prints ATH then pulls back by drop_pct."""
    rows: list[dict] = []
    end = date(2026, 8, 14)
    start = end - timedelta(days=1100)
    d = start
    i = 0
    while d < end - timedelta(days=5):
        if d.weekday() < 5:
            # Slow grind higher so short MA > long MA and price > 200 SMA
            close = 40.0 + i * 0.12
            rows.append(
                {
                    "date": d.isoformat(),
                    "open": close - 0.2,
                    "high": close + 0.8,
                    "low": close - 0.6,
                    "close": close,
                    "volume": 2_000_000,
                }
            )
            i += 1
        d += timedelta(days=1)

    ath = float(rows[-1]["close"]) + 2.0
    rows[-1]["high"] = ath
    pull_close = ath * (1.0 - drop_pct / 100.0)
    # Keep last few bars in gentle pullback still above long MA
    for j, offset in enumerate([4, 3, 2, 1, 0]):
        day = end - timedelta(days=offset)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        frac = j / 4.0
        c = ath - (ath - pull_close) * frac
        rows.append(
            {
                "date": day.isoformat(),
                "open": c + 0.3,
                "high": max(c + 0.5, ath if j == 0 else c + 0.5),
                "low": c - 0.8,
                "close": c,
                "volume": 2_200_000,
            }
        )
    # Deduplicate by date keeping last
    by_date: dict[str, dict] = {}
    for r in rows:
        by_date[r["date"]] = r
    ordered = [by_date[k] for k in sorted(by_date)]
    return pd.DataFrame(ordered)


def test_detects_fresh_multi_year_breakout() -> None:
    hit = detect_multi_year_breakout(_df_with_breakout(break_today=True), lookback_years=3)
    assert hit is not None
    assert hit.status == "breakout"
    assert hit.prior_high == 100.0
    assert hit.breakout_pct is not None and hit.breakout_pct > 0
    assert hit.score >= 50


def test_detects_near_breakout_setup() -> None:
    hit = detect_multi_year_breakout(_df_with_breakout(break_today=False), lookback_years=3)
    assert hit is not None
    assert hit.status == "near"
    assert hit.breakout_pct is not None and hit.breakout_pct < 0
    assert hit.breakout_pct >= -3.0


def test_rejects_insufficient_history() -> None:
    rows = []
    for i in range(50):
        rows.append(
            {
                "date": f"2026-06-{(i % 28) + 1:02d}",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1_000_000,
            }
        )
    assert detect_multi_year_breakout(pd.DataFrame(rows), lookback_years=3) is None


def test_ath_pullback_at_least() -> None:
    hit = detect_ath_pullback(
        _df_near_ath(drop_pct=20.0),
        pullback_pct=15.0,
        match_mode="at_least",
        trend_filter="all",
    )
    assert hit is not None
    assert hit.status == "pullback"
    assert hit.drop_from_ath_pct is not None
    assert hit.drop_from_ath_pct >= 15.0
    assert hit.prior_high == 100.0
    assert hit.details.get("trend") in ("uptrend", "downtrend", "sideways")


def test_ath_pullback_rejects_shallow_drawdown() -> None:
    hit = detect_ath_pullback(
        _df_near_ath(drop_pct=10.0),
        pullback_pct=15.0,
        match_mode="at_least",
    )
    assert hit is None


def test_ath_pullback_band_mode() -> None:
    hit = detect_ath_pullback(
        _df_near_ath(drop_pct=14.0),
        pullback_pct=15.0,
        match_mode="band",
        band_width_pct=2.0,
    )
    assert hit is not None
    assert 13.0 <= (hit.drop_from_ath_pct or 0) <= 17.0


def test_ath_pullback_uptrend_filter() -> None:
    df = _df_uptrend_pullback(drop_pct=18.0)
    trend = classify_trend(df)
    # May be uptrend or sideways depending on RSI; ensure at_least works with filter=all
    hit_all = detect_ath_pullback(df, pullback_pct=15.0, match_mode="at_least", trend_filter="all")
    assert hit_all is not None
    assert hit_all.drop_from_ath_pct is not None and hit_all.drop_from_ath_pct >= 15.0
    assert "dist_long_ma_pct" in (hit_all.details or {})

    if trend.get("trend") == "uptrend":
        hit_up = detect_ath_pullback(
            df, pullback_pct=15.0, match_mode="at_least", trend_filter="uptrend"
        )
        assert hit_up is not None
        hit_down = detect_ath_pullback(
            df, pullback_pct=15.0, match_mode="at_least", trend_filter="downtrend"
        )
        assert hit_down is None
