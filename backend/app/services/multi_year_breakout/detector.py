"""Detectors for multi-year breakout and ATH pullback strategies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

import pandas as pd

from ..scanner.filters import evaluate_liquidity
from ..scanner.indicators import close_position_in_range, ema, relative_volume, rsi, sma

StrategyId = Literal["multi_year_breakout", "ath_pullback", "custom"]
TrendFilter = Literal["all", "uptrend", "downtrend"]
MatchMode = Literal["at_least", "at_most", "band"]
MaType = Literal["sma", "ema"]

NEAR_BREAKOUT_PCT = 3.0
MAX_BREAKOUT_EXTENSION_PCT = 8.0
MIN_RVOL_BREAKOUT = 1.15
MIN_YEARS_SINCE_HIGH = 1.0
DEFAULT_ATH_PULLBACK_PCT = 15.0
MIN_BARS_ATH = 250
DEFAULT_SHORT_MA = 50
DEFAULT_LONG_MA = 200
DEFAULT_RSI_UP = 45.0
DEFAULT_RSI_DOWN = 50.0


@dataclass
class ScreenHit:
    strategy: StrategyId
    status: str
    score: float
    prior_high: float
    prior_high_date: str | None
    years_since_high: float | None
    close_price: float
    breakout_pct: float | None
    drop_from_ath_pct: float | None
    rvol20: float | None
    rsi14: float | None
    avg_turnover_inr: float | None
    details: dict[str, Any]


def _lookback_start(as_of: date, years: int) -> date:
    try:
        return as_of.replace(year=as_of.year - years)
    except ValueError:
        return as_of.replace(year=as_of.year - years, day=28)


def _size_tier(avg_turnover_inr: float | None) -> str | None:
    if avg_turnover_inr is None:
        return None
    # Liquidity proxy for Large / Mid / Small (company mcap not in local DB).
    cr = avg_turnover_inr / 10_000_000  # ₹ Cr
    if cr >= 50:
        return "large"
    if cr >= 10:
        return "mid"
    if cr >= 5:
        return "small"
    return "micro"


def _ma_series(close: pd.Series, window: int, ma_type: str) -> pd.Series:
    if (ma_type or "sma").lower() == "ema":
        return ema(close, window)
    return sma(close, window)


def classify_trend(
    df: pd.DataFrame,
    *,
    short_period: int = DEFAULT_SHORT_MA,
    long_period: int = DEFAULT_LONG_MA,
    ma_type: str = "sma",
    rsi_up: float = DEFAULT_RSI_UP,
    rsi_down: float = DEFAULT_RSI_DOWN,
) -> dict[str, Any]:
    """
    Classify trend regime using short/long MA stack + RSI confirmation.

    Uptrend:   close > long MA and short MA > long MA and RSI >= rsi_up
    Downtrend: close < long MA and short MA < long MA and RSI <= rsi_down
    Else:      sideways / mixed
    """
    close = df["close"].astype(float)
    need = max(int(long_period), int(short_period)) + 5
    if len(df) < need:
        return {
            "trend": "sideways",
            "label": "Insufficient history",
            "short_ma": None,
            "long_ma": None,
            "dist_short_ma_pct": None,
            "dist_long_ma_pct": None,
            "above_long_ma": None,
            "ma_stack_bullish": None,
            "rsi14": None,
            "short_period": int(short_period),
            "long_period": int(long_period),
            "ma_type": (ma_type or "sma").lower(),
        }

    short = _ma_series(close, int(short_period), ma_type)
    long = _ma_series(close, int(long_period), ma_type)
    short_val = float(short.iloc[-1]) if pd.notna(short.iloc[-1]) else None
    long_val = float(long.iloc[-1]) if pd.notna(long.iloc[-1]) else None
    price = float(close.iloc[-1])
    rsi14 = rsi(close, window=14)

    dist_short = ((price / short_val) - 1.0) * 100.0 if short_val and short_val > 0 else None
    dist_long = ((price / long_val) - 1.0) * 100.0 if long_val and long_val > 0 else None
    above_long = bool(long_val is not None and price > long_val)
    below_long = bool(long_val is not None and price < long_val)
    stack_bull = bool(short_val is not None and long_val is not None and short_val > long_val)
    stack_bear = bool(short_val is not None and long_val is not None and short_val < long_val)
    rsi_ok_up = rsi14 is not None and rsi14 >= float(rsi_up)
    rsi_ok_down = rsi14 is not None and rsi14 <= float(rsi_down)

    ma_label = f"{int(short_period)}/{int(long_period)} {(ma_type or 'sma').upper()}"
    if above_long and stack_bull and rsi_ok_up:
        trend = "uptrend"
        label = f"Uptrend (Above {int(long_period)} {(ma_type or 'sma').upper()})"
    elif below_long and stack_bear and rsi_ok_down:
        trend = "downtrend"
        label = f"Downtrend (Below {int(long_period)} {(ma_type or 'sma').upper()})"
    elif above_long and stack_bull:
        trend = "sideways"
        label = f"Mixed bullish stack ({ma_label})"
    elif below_long and stack_bear:
        trend = "sideways"
        label = f"Mixed bearish stack ({ma_label})"
    else:
        trend = "sideways"
        label = f"Sideways / mixed ({ma_label})"

    return {
        "trend": trend,
        "label": label,
        "short_ma": round(short_val, 4) if short_val is not None else None,
        "long_ma": round(long_val, 4) if long_val is not None else None,
        "dist_short_ma_pct": round(dist_short, 3) if dist_short is not None else None,
        "dist_long_ma_pct": round(dist_long, 3) if dist_long is not None else None,
        "above_long_ma": above_long if long_val is not None else None,
        "ma_stack_bullish": stack_bull if short_val is not None and long_val is not None else None,
        "rsi14": round(float(rsi14), 2) if rsi14 is not None else None,
        "short_period": int(short_period),
        "long_period": int(long_period),
        "ma_type": (ma_type or "sma").lower(),
        "rsi_up_threshold": float(rsi_up),
        "rsi_down_threshold": float(rsi_down),
    }


def detect_multi_year_breakout(
    df: pd.DataFrame,
    *,
    lookback_years: int = 3,
    near_pct: float = NEAR_BREAKOUT_PCT,
    max_extension_pct: float = MAX_BREAKOUT_EXTENSION_PCT,
    min_rvol: float = MIN_RVOL_BREAKOUT,
) -> ScreenHit | None:
    """Breakout / near setup vs prior N-year high (dormant ≥ 1 year)."""
    if lookback_years < 2 or len(df) < lookback_years * 180:
        return None

    last = df.iloc[-1]
    as_of = date.fromisoformat(str(last["date"])[:10])
    start = _lookback_start(as_of, lookback_years)

    hist = df.iloc[:-1]
    hist = hist[hist["date"].astype(str).str.slice(0, 10) >= start.isoformat()]
    if len(hist) < lookback_years * 160:
        return None

    prior_high = float(hist["high"].max())
    if prior_high <= 0:
        return None

    high_idx = hist["high"].astype(float).idxmax()
    prior_high_date = str(hist.loc[high_idx, "date"])[:10]
    try:
        phd = date.fromisoformat(prior_high_date)
        years_since = round((as_of - phd).days / 365.25, 2)
    except ValueError:
        years_since = None

    if years_since is None or years_since < MIN_YEARS_SINCE_HIGH:
        return None

    close = float(last["close"])
    prev_close = float(df.iloc[-2]["close"]) if len(df) >= 2 else close
    breakout_pct = (close / prior_high - 1.0) * 100.0
    drop_pct = (prior_high - close) / prior_high * 100.0
    close_pos = close_position_in_range(last)
    rvol = relative_volume(df["volume"], window=20)
    rsi14 = rsi(df["close"], window=14)

    liquidity = evaluate_liquidity(df)
    if not liquidity["pass"]:
        return None

    crossed_today = close > prior_high and prev_close <= prior_high
    already_above = close > prior_high and prev_close > prior_high
    near = close < prior_high and breakout_pct >= -near_pct

    if crossed_today:
        if breakout_pct > max_extension_pct:
            return None
        if rvol is not None and rvol < min_rvol:
            return None
        status = "breakout"
    elif near and not already_above:
        status = "near"
    else:
        return None

    base_years = min(float(lookback_years), years_since or 0.0)
    score = 35.0
    score += min(30.0, base_years * 10.0)
    if status == "breakout":
        score += 20.0
        score += min(10.0, max(0.0, 5.0 - abs(breakout_pct)) * 2)
        if rvol is not None:
            score += min(10.0, (rvol - 1.0) * 5.0)
    else:
        score += 8.0
        score += max(0.0, (near_pct + breakout_pct) / near_pct * 12.0)
    score += 5.0 if close_pos >= 0.7 else 0.0
    if status == "near" and rvol is not None and rvol >= 1.0:
        score += min(5.0, (rvol - 1.0) * 4.0)

    avg_turnover = liquidity.get("avg_turnover_inr")
    return ScreenHit(
        strategy="multi_year_breakout",
        status=status,
        score=round(min(100.0, score), 1),
        prior_high=round(prior_high, 4),
        prior_high_date=prior_high_date,
        years_since_high=years_since,
        close_price=round(close, 4),
        breakout_pct=round(breakout_pct, 4),
        drop_from_ath_pct=round(drop_pct, 4) if drop_pct >= 0 else 0.0,
        rvol20=round(float(rvol), 3) if rvol is not None else None,
        rsi14=round(float(rsi14), 2) if rsi14 is not None else None,
        avg_turnover_inr=round(float(avg_turnover), 2) if avg_turnover is not None else None,
        details={
            "lookback_start": start.isoformat(),
            "lookback_years": lookback_years,
            "bars_in_lookback": int(len(hist)),
            "close_position": round(close_pos, 3),
            "liquidity": liquidity,
            "size_tier": _size_tier(avg_turnover if isinstance(avg_turnover, (int, float)) else None),
            "crossed_today": bool(crossed_today),
            "near_threshold_pct": near_pct,
            "resistance_level": round(prior_high, 4),
        },
    )


def detect_ath_pullback(
    df: pd.DataFrame,
    *,
    pullback_pct: float = DEFAULT_ATH_PULLBACK_PCT,
    match_mode: str = "at_least",
    band_width_pct: float = 5.0,
    trend_filter: str = "all",
    short_ma_period: int = DEFAULT_SHORT_MA,
    long_ma_period: int = DEFAULT_LONG_MA,
    ma_type: str = "sma",
    rsi_up: float = DEFAULT_RSI_UP,
    rsi_down: float = DEFAULT_RSI_DOWN,
    require_liquidity: bool = True,
) -> ScreenHit | None:
    """
    Stocks pulled back from all-time high (available history) by at least X%.

    drop_from_ath_pct = (ATH - LTP) / ATH * 100

    match_mode:
      - at_least: drop >= pullback_pct  (default; down at least X% from ATH)
      - at_most:  drop <= pullback_pct  (legacy: within X% of ATH)
      - band:     abs(drop - pullback_pct) <= band_width_pct
    """
    need = max(MIN_BARS_ATH, int(long_ma_period) + 20)
    if len(df) < need:
        return None

    last = df.iloc[-1]
    as_of = date.fromisoformat(str(last["date"])[:10])
    ath = float(df["high"].max())
    if ath <= 0:
        return None

    high_idx = df["high"].astype(float).idxmax()
    ath_date = str(df.loc[high_idx, "date"])[:10]
    try:
        years_since = round((as_of - date.fromisoformat(ath_date)).days / 365.25, 2)
    except ValueError:
        years_since = None

    close = float(last["close"])
    drop_pct = (ath - close) / ath * 100.0
    if drop_pct < 0:
        drop_pct = 0.0

    mode = (match_mode or "at_least").lower()
    if mode == "band":
        lo = max(0.0, float(pullback_pct) - float(band_width_pct))
        hi = float(pullback_pct) + float(band_width_pct)
        if not (lo <= drop_pct <= hi):
            return None
    elif mode == "at_most":
        if drop_pct > float(pullback_pct):
            return None
    else:
        # at_least (default): discount from ATH must be >= X%
        if drop_pct < float(pullback_pct):
            return None

    trend_info = classify_trend(
        df,
        short_period=short_ma_period,
        long_period=long_ma_period,
        ma_type=ma_type,
        rsi_up=rsi_up,
        rsi_down=rsi_down,
    )
    want_trend = (trend_filter or "all").lower()
    if want_trend in ("uptrend", "downtrend") and trend_info.get("trend") != want_trend:
        return None

    liquidity = evaluate_liquidity(df)
    if require_liquidity and not liquidity["pass"]:
        return None

    rvol = relative_volume(df["volume"], window=20)
    rsi14 = trend_info.get("rsi14")
    if rsi14 is None:
        rsi14 = rsi(df["close"], window=14)
    close_pos = close_position_in_range(last)
    avg_turnover = liquidity.get("avg_turnover_inr")

    # Prefer constructive pullbacks: meet threshold, not free-fall, trend-aligned
    score = 35.0
    excess = drop_pct - float(pullback_pct)
    # Reward meeting the floor; gently penalize extreme dumps beyond +40pp
    score += min(20.0, max(0.0, 20.0 - abs(excess - 10.0)))
    if excess > 40:
        score -= min(15.0, (excess - 40.0) * 0.4)

    trend = trend_info.get("trend")
    if trend == "uptrend":
        score += 18.0
    elif trend == "downtrend":
        score += 8.0
    else:
        score += 4.0

    if rsi14 is not None:
        if trend == "uptrend" and 45 <= rsi14 <= 65:
            score += 12.0
        elif trend == "downtrend" and 25 <= rsi14 <= 45:
            score += 10.0
        elif 40 <= rsi14 <= 60:
            score += 6.0

    if rvol is not None and rvol >= 1.0:
        score += min(8.0, (rvol - 1.0) * 3.0)
    score += 4.0 if close_pos >= 0.55 else 0.0
    if years_since is not None and years_since >= 0.5:
        score += min(8.0, years_since * 2.0)

    return ScreenHit(
        strategy="ath_pullback",
        status="pullback",
        score=round(min(100.0, max(0.0, score)), 1),
        prior_high=round(ath, 4),
        prior_high_date=ath_date,
        years_since_high=years_since,
        close_price=round(close, 4),
        breakout_pct=round(-drop_pct, 4),
        drop_from_ath_pct=round(drop_pct, 4),
        rvol20=round(float(rvol), 3) if rvol is not None else None,
        rsi14=round(float(rsi14), 2) if rsi14 is not None else None,
        avg_turnover_inr=round(float(avg_turnover), 2) if avg_turnover is not None else None,
        details={
            "ath": round(ath, 4),
            "ath_date": ath_date,
            "pullback_pct_threshold": float(pullback_pct),
            "match_mode": mode,
            "band_width_pct": float(band_width_pct) if mode == "band" else None,
            "bars": int(len(df)),
            "close_position": round(close_pos, 3),
            "liquidity": liquidity,
            "size_tier": _size_tier(avg_turnover if isinstance(avg_turnover, (int, float)) else None),
            "trend": trend_info.get("trend"),
            "trend_label": trend_info.get("label"),
            "short_ma": trend_info.get("short_ma"),
            "long_ma": trend_info.get("long_ma"),
            "dist_short_ma_pct": trend_info.get("dist_short_ma_pct"),
            "dist_long_ma_pct": trend_info.get("dist_long_ma_pct"),
            "short_period": trend_info.get("short_period"),
            "long_period": trend_info.get("long_period"),
            "ma_type": trend_info.get("ma_type"),
        },
    )


# Back-compat alias used by older tests
MultiYearHit = ScreenHit
