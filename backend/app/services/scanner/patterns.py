from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .scoring import (
    HARD_EXTENSION_PRE_20D_PCT,
    MIN_CLOSE_POSITION_POCKET,
    MIN_VOLUME_Z_POCKET,
    MIN_VOLUME_Z_POWER_GAP,
    PREFERRED_VCP_BASE_DEPTH_PCT,
    TIGHT_RANGE_MAX_PCT,
    TIGHT_RANGE_NEAR_PIVOT_PCT,
    VCP_BREAKOUT_LOOKBACK,
    VCP_NEAR_PIVOT_PCT,
    min_score_for,
    vcp_base_depth_adjustment,
)
from .timing import compute_pre_20d_return_pct
from .trend_template import in_base_context
from .indicators import (
    atr,
    base_depth_pct,
    close_position_in_range,
    relative_volume,
    rolling_max,
    sma,
    volume_zscore,
)
from .quality import MAX_VOLUME_Z_POCKET, MIN_RVOL_POCKET

# Re-export for callers / tests that imported MIN_SCORES from patterns
from .scoring import MIN_SCORES  # noqa: F401


@dataclass
class PatternHit:
    pattern_type: str
    score: float
    triggered_today: bool
    setup_ready: bool
    details: dict[str, Any]


def _meets_min(pattern_type: str, score: float) -> bool:
    return score >= min_score_for(pattern_type)


def score_vcp(df: pd.DataFrame) -> PatternHit | None:
    """VCP two-stage: setup near pivot; trigger on pivot break + volume confirmation."""
    if len(df) < 60:
        return None

    depth = base_depth_pct(df, window=40)
    pre_20d = compute_pre_20d_return_pct(df)
    keep, depth_adj = vcp_base_depth_adjustment(depth, pre_20d_return_pct=pre_20d)
    if not keep:
        return None

    r20 = (df["high"].rolling(20).max() - df["low"].rolling(20).min()) / df["close"]
    r10 = (df["high"].rolling(10).max() - df["low"].rolling(10).min()) / df["close"]
    r5 = (df["high"].rolling(5).max() - df["low"].rolling(5).min()) / df["close"]

    last_r20 = float(r20.iloc[-1]) if pd.notna(r20.iloc[-1]) else 0
    last_r10 = float(r10.iloc[-1]) if pd.notna(r10.iloc[-1]) else 0
    last_r5 = float(r5.iloc[-1]) if pd.notna(r5.iloc[-1]) else 0

    contracting = last_r20 > last_r10 > last_r5 > 0
    if not contracting:
        return None

    price = float(df["close"].iloc[-1])
    pivot_high = float(df["high"].iloc[-VCP_BREAKOUT_LOOKBACK - 1 : -1].max())
    if pivot_high <= 0:
        return None

    breakout = price > pivot_high
    near_pivot = price >= pivot_high * (1.0 - VCP_NEAR_PIVOT_PCT / 100.0)
    if not (breakout or near_pivot):
        return None

    vol20 = df["volume"].rolling(20).mean()
    vol5 = df["volume"].rolling(5).mean()
    last_vol = float(df["volume"].iloc[-1])
    vol20_last = float(vol20.iloc[-1]) if pd.notna(vol20.iloc[-1]) else 0.0
    vol_dry = float(vol5.iloc[-1]) < vol20_last * 0.85 if vol20_last > 0 else False
    vol_confirm = last_vol >= vol20_last * 1.2 if vol20_last > 0 else False

    high_52w = float(rolling_max(df["high"], 252).iloc[-1]) if len(df) >= 252 else float(df["high"].max())
    near_high = price >= high_52w * 0.85 if high_52w > 0 else False

    contraction_score = min(40.0, (last_r20 - last_r5) / max(last_r20, 1e-6) * 100)
    vol_score = 20.0 if vol_dry else (10.0 if vol_confirm and breakout else 0.0)
    proximity_score = 25.0 if near_high else 10.0 if price >= high_52w * 0.75 else 0.0
    higher_lows = float(df["low"].iloc[-5:].min()) > float(df["low"].iloc[-20:-5].min())
    hl_score = 15.0 if higher_lows else 0.0

    score = contraction_score + vol_score + proximity_score + hl_score + depth_adj
    if depth is not None and depth <= PREFERRED_VCP_BASE_DEPTH_PCT:
        score += 5.0

    if not _meets_min("vcp", score):
        return None

    triggered_today = bool(breakout and vol_confirm)
    setup_ready = bool(not triggered_today and near_pivot)
    if not (triggered_today or setup_ready):
        # Breakout without vol confirmation still counts as confirmation (weaker)
        if breakout:
            triggered_today = True
            setup_ready = False
        else:
            return None

    stage = "late" if last_r5 < last_r10 * 0.6 else "mid"
    return PatternHit(
        pattern_type="vcp",
        score=round(min(score, 100.0), 1),
        triggered_today=triggered_today,
        setup_ready=setup_ready,
        details={
            "stage": stage,
            "range_20d_pct": round(last_r20 * 100, 2),
            "range_10d_pct": round(last_r10 * 100, 2),
            "range_5d_pct": round(last_r5 * 100, 2),
            "volume_dry": vol_dry,
            "volume_confirm": vol_confirm,
            "breakout": breakout,
            "near_pivot": near_pivot,
            "pivot_high": round(pivot_high, 2),
            "base_depth_pct": round(depth, 2) if depth is not None else None,
            "preferred_base_depth": depth is not None and depth <= PREFERRED_VCP_BASE_DEPTH_PCT,
            "pre_20d_return_pct": pre_20d,
        },
    )


def score_high_tight_flag(df: pd.DataFrame) -> PatternHit | None:
    if len(df) < 25:
        return None

    pre_20d = compute_pre_20d_return_pct(df)
    window = df.iloc[-25:]
    pole_window = window.iloc[-20:]
    lowest = float(pole_window["low"].min())
    peak = float(pole_window["high"].max())
    if lowest <= 0:
        return None

    flagpole_pct = (peak - lowest) / lowest
    if flagpole_pct < 0.30 or flagpole_pct > 1.0:
        return None

    flag = df.iloc[-10:]
    flag_depth = (float(flag["high"].max()) - float(flag["low"].min())) / max(float(flag["low"].min()), 1e-6)
    if flag_depth > 0.10:
        return None

    # Hard extension reject unless shallow flag (scoring gate also applied in engine)
    if (
        pre_20d is not None
        and pre_20d > HARD_EXTENSION_PRE_20D_PCT
        and flag_depth * 100 > 10.0
    ):
        return None

    flag_high = float(flag["high"].max())
    flag_low = float(flag["low"].min())
    flag_mid = flag_low + (flag_high - flag_low) * 0.5
    closes_upper = float(flag["close"].mean()) >= flag_mid

    pole_vol = float(pole_window["volume"].mean())
    flag_vol = float(flag["volume"].mean())
    vol_contract = flag_vol < pole_vol * 0.7 if pole_vol > 0 else False

    score = 40.0
    score += min(30.0, flagpole_pct * 30)
    score += 15.0 if closes_upper else 0.0
    score += 15.0 if vol_contract else 0.0

    if not _meets_min("high_tight_flag", score):
        return None

    return PatternHit(
        pattern_type="high_tight_flag",
        score=round(min(score, 100.0), 1),
        triggered_today=closes_upper and vol_contract,
        setup_ready=not (closes_upper and vol_contract),
        details={
            "flagpole_pct": round(flagpole_pct * 100, 1),
            "flag_depth_pct": round(flag_depth * 100, 1),
            "volume_contracting": vol_contract,
            "pre_20d_return_pct": pre_20d,
        },
    )


def score_pocket_pivot(df: pd.DataFrame) -> PatternHit | None:
    if len(df) < 55:
        return None

    pre_20d = compute_pre_20d_return_pct(df)
    if pre_20d is not None and pre_20d > HARD_EXTENSION_PRE_20D_PCT:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    up_day = float(last["close"]) >= float(last["open"]) or float(last["close"]) > float(prev["close"])

    hist = df.iloc[-11:-1]
    down_mask = hist["close"] < hist["close"].shift(1)
    down_vols = hist.loc[down_mask.fillna(False), "volume"]
    max_down_vol = float(down_vols.max()) if len(down_vols) else 0.0

    vol_ok = (
        float(last["volume"]) > max_down_vol
        if max_down_vol > 0
        else float(last["volume"]) > float(hist["volume"].mean())
    )
    if not (up_day and vol_ok):
        return None

    vol_z = volume_zscore(df["volume"], window=50)
    last_vol_z = float(vol_z.iloc[-1]) if pd.notna(vol_z.iloc[-1]) else None
    if last_vol_z is None or last_vol_z < MIN_VOLUME_Z_POCKET:
        return None

    rvol = relative_volume(df["volume"], window=20)
    # Soft preference only: extreme blow-offs are down-weighted, not hard-rejected here
    # (engine quality gates handle weak-close + climactic volume).

    in_base = in_base_context(df)
    close_pos = close_position_in_range(last)
    if close_pos < MIN_CLOSE_POSITION_POCKET:
        return None
    close_strong = close_pos >= 0.75

    score = 30.0
    score += 25.0 if in_base else 5.0
    score += 25.0 if close_strong else 15.0
    score += min(20.0, (float(last["volume"]) / max(max_down_vol, 1)) * 8)
    # Prefer sustained institutional volume (z ~1–2.5) over climactic spikes.
    if 1.0 <= last_vol_z < 2.5:
        score += 10.0
    elif 2.5 <= last_vol_z <= 3.5:
        score += 3.0
    if rvol is not None and rvol >= MIN_RVOL_POCKET:
        score += 5.0
    if last_vol_z > MAX_VOLUME_Z_POCKET:
        score -= 10.0

    if not _meets_min("pocket_pivot", score):
        return None

    return PatternHit(
        pattern_type="pocket_pivot",
        score=round(min(score, 100.0), 1),
        triggered_today=True,
        setup_ready=False,
        details={
            "in_base": in_base,
            "volume_ratio": round(float(last["volume"]) / max(max_down_vol, 1), 2),
            "volume_zscore": round(last_vol_z, 2),
            "rvol20": round(float(rvol), 3) if rvol is not None else None,
            "close_position": round(close_pos, 2),
            "pre_20d_return_pct": pre_20d,
        },
    )


def score_pocket_pivot_setup(df: pd.DataFrame) -> PatternHit | None:
    """Pre-trigger pocket: volume building but has not yet exceeded max down-day volume."""
    if len(df) < 55:
        return None

    pre_20d = compute_pre_20d_return_pct(df)
    if pre_20d is not None and pre_20d > HARD_EXTENSION_PRE_20D_PCT:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    up_or_flat = float(last["close"]) >= float(prev["close"]) * 0.995
    if not up_or_flat:
        return None

    hist = df.iloc[-11:-1]
    down_mask = hist["close"] < hist["close"].shift(1)
    down_vols = hist.loc[down_mask.fillna(False), "volume"]
    max_down_vol = float(down_vols.max()) if len(down_vols) else 0.0
    mean_down_vol = float(down_vols.mean()) if len(down_vols) else float(hist["volume"].mean())

    last_vol = float(last["volume"])
    # Building: above mean of down days, but not yet a full pocket pivot trigger
    if max_down_vol <= 0:
        return None
    if last_vol >= max_down_vol:
        return None
    if last_vol < mean_down_vol * 0.9:
        return None

    prior_3 = float(df["volume"].iloc[-4:-1].mean())
    building = last_vol > prior_3 * 1.1 if prior_3 > 0 else False
    if not building:
        return None

    in_base = in_base_context(df)
    close_pos = close_position_in_range(last)

    score = 40.0
    score += 25.0 if in_base else 5.0
    score += 15.0 if close_pos >= 0.5 else 0.0
    score += min(20.0, (last_vol / max(mean_down_vol, 1)) * 8)

    if not _meets_min("pocket_pivot_setup", score):
        return None

    return PatternHit(
        pattern_type="pocket_pivot_setup",
        score=round(min(score, 100.0), 1),
        triggered_today=False,
        setup_ready=True,
        details={
            "in_base": in_base,
            "volume_vs_mean_down": round(last_vol / max(mean_down_vol, 1), 2),
            "volume_vs_max_down": round(last_vol / max(max_down_vol, 1), 2),
            "close_position": round(close_pos, 2),
            "pre_20d_return_pct": pre_20d,
        },
    )


def score_inside_bar_cluster(df: pd.DataFrame) -> PatternHit | None:
    if len(df) < 8:
        return None

    pre_20d = compute_pre_20d_return_pct(df)
    if pre_20d is not None and pre_20d > HARD_EXTENSION_PRE_20D_PCT:
        return None

    atr10 = atr(df, 10)
    if pd.isna(atr10.iloc[-1]):
        return None

    mother = df.iloc[-4]
    bar1 = df.iloc[-3]
    bar2 = df.iloc[-2]
    last = df.iloc[-1]

    mother_range = float(mother["high"]) - float(mother["low"])
    if mother_range <= float(atr10.iloc[-4]) * 1.5:
        return None
    if float(mother["close"]) <= float(mother["open"]):
        return None

    inside1 = float(bar1["high"]) < float(mother["high"]) and float(bar1["low"]) > float(mother["low"])
    inside2 = float(bar2["high"]) < float(bar1["high"]) and float(bar2["low"]) > float(bar1["low"])
    if not (inside1 and inside2):
        return None

    cluster_vol = (float(bar1["volume"]) + float(bar2["volume"])) / 2
    mother_vol = float(mother["volume"])
    vol_ok = cluster_vol < mother_vol

    triggered = float(last["high"]) > float(mother["high"])
    setup = not triggered

    score = 55.0
    score += 15.0 if vol_ok else 0.0
    score += 30.0 if triggered else 10.0

    if not _meets_min("inside_bar_cluster", score):
        return None

    mother_date = str(mother["date"]) if "date" in mother.index else ""
    return PatternHit(
        pattern_type="inside_bar_cluster",
        score=round(min(score, 100.0), 1),
        triggered_today=triggered,
        setup_ready=setup,
        details={
            "inside_bars": 2,
            "mother_date": mother_date,
            "volume_contracting": vol_ok,
            "pre_20d_return_pct": pre_20d,
        },
    )


def score_power_gap(df: pd.DataFrame) -> PatternHit | None:
    if len(df) < 55:
        return None

    pre_20d = compute_pre_20d_return_pct(df)
    if pre_20d is not None and pre_20d > HARD_EXTENSION_PRE_20D_PCT:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    vol_sma20 = float(df["volume"].iloc[-21:-1].mean())

    gap_up = float(last["open"]) >= float(prev["high"]) * 1.03
    huge_vol = float(last["volume"]) >= vol_sma20 * 2.5 if vol_sma20 > 0 else False
    close_pos = close_position_in_range(last)
    strong_close = close_pos >= 0.85

    vol_z = volume_zscore(df["volume"], window=50)
    last_vol_z = float(vol_z.iloc[-1]) if pd.notna(vol_z.iloc[-1]) else None

    sma50_val = float(sma(df["close"], 50).iloc[-1]) if len(df) >= 50 else float(last["close"])
    not_extended = float(last["close"]) <= sma50_val * 1.25 if sma50_val > 0 else True

    if not (gap_up and huge_vol and strong_close):
        return None
    if last_vol_z is None or last_vol_z < MIN_VOLUME_Z_POWER_GAP:
        return None

    score = 50.0
    score += 20.0 if not_extended else 0.0
    score += min(30.0, (float(last["volume"]) / max(vol_sma20, 1)) * 5)
    if last_vol_z >= 2.0:
        score += 5.0

    if not _meets_min("power_gap", score):
        return None

    return PatternHit(
        pattern_type="power_gap",
        score=round(min(score, 100.0), 1),
        triggered_today=True,
        setup_ready=False,
        details={
            "peg_confirmed": False,
            "gap_pct": round((float(last["open"]) / float(prev["high"]) - 1) * 100, 2),
            "volume_ratio": round(float(last["volume"]) / max(vol_sma20, 1), 2),
            "volume_zscore": round(last_vol_z, 2),
            "close_position": round(close_pos, 2),
            "not_extended": not_extended,
            "pre_20d_return_pct": pre_20d,
        },
    )


def score_tight_range_near_pivot(df: pd.DataFrame) -> PatternHit | None:
    """Anticipatory: 5–10d range < 5% and close within 5% of local pivot high."""
    if len(df) < 30:
        return None

    pre_20d = compute_pre_20d_return_pct(df)
    if pre_20d is not None and pre_20d > HARD_EXTENSION_PRE_20D_PCT:
        return None

    price = float(df["close"].iloc[-1])
    best: PatternHit | None = None

    for window in (5, 8, 10):
        segment = df.iloc[-window:]
        seg_high = float(segment["high"].max())
        seg_low = float(segment["low"].min())
        if seg_low <= 0 or price <= 0:
            continue
        range_pct = (seg_high - seg_low) / price * 100.0
        if range_pct > TIGHT_RANGE_MAX_PCT:
            continue

        # Pivot = max high of prior 20 sessions excluding today
        lookback = df.iloc[-21:-1]
        if lookback.empty:
            continue
        pivot = float(lookback["high"].max())
        if pivot <= 0:
            continue
        dist_pct = abs(pivot - price) / pivot * 100.0
        if dist_pct > TIGHT_RANGE_NEAR_PIVOT_PCT:
            continue
        if price > pivot * 1.01:
            # Already clearly broken out — leave to trigger patterns
            continue

        vol20 = float(df["volume"].iloc[-21:-1].mean())
        vol_dry = float(segment["volume"].mean()) < vol20 * 0.9 if vol20 > 0 else False

        score = 50.0
        score += min(25.0, (TIGHT_RANGE_MAX_PCT - range_pct) * 5)
        score += min(15.0, (TIGHT_RANGE_NEAR_PIVOT_PCT - dist_pct) * 3)
        score += 10.0 if vol_dry else 0.0

        if not _meets_min("tight_range_near_pivot", score):
            continue

        hit = PatternHit(
            pattern_type="tight_range_near_pivot",
            score=round(min(score, 100.0), 1),
            triggered_today=False,
            setup_ready=True,
            details={
                "range_window": window,
                "range_pct": round(range_pct, 2),
                "distance_to_pivot_pct": round(dist_pct, 2),
                "pivot_high": round(pivot, 2),
                "volume_dry": vol_dry,
                "pre_20d_return_pct": pre_20d,
            },
        )
        if best is None or hit.score > best.score:
            best = hit

    return best


def score_darvas_pre_setup(df: pd.DataFrame) -> PatternHit | None:
    """Darvas-style pre-setup: uptrend + coil near highs (influencer-calibrated).

    Matches the recurring pre-mention structure from @darvasboxtrader analysis:
    higher lows, above rising SMA20, volatility contraction / box near 20d high.
    Setup when coiling under pivot; trigger when today's close breaks the prior 20d high.
    """
    if len(df) < 40:
        return None

    pre_20d = compute_pre_20d_return_pct(df)
    if pre_20d is not None and pre_20d > HARD_EXTENSION_PRE_20D_PCT:
        return None

    close = df["close"]
    high = df["high"]
    low = df["low"]
    price = float(close.iloc[-1])
    if price <= 0:
        return None

    prior = df.iloc[:-1]
    if len(prior) < 25:
        return None

    # Higher lows (10 vs prior 10)
    recent_low = float(low.iloc[-10:].min())
    prior_low = float(low.iloc[-20:-10].min())
    higher_lows = recent_low > prior_low
    if not higher_lows:
        return None

    sma20 = sma(close, 20)
    sma20_last = float(sma20.iloc[-1]) if pd.notna(sma20.iloc[-1]) else None
    sma20_prev = float(sma20.iloc[-6]) if len(df) >= 26 and pd.notna(sma20.iloc[-6]) else None
    if sma20_last is None or price < sma20_last:
        return None
    sma20_rising = sma20_prev is not None and sma20_last > sma20_prev

    high20_prior = float(prior["high"].iloc[-20:].max())
    low20_prior = float(prior["low"].iloc[-20:].min())
    high10_prior = float(prior["high"].iloc[-10:].max())
    low10_prior = float(prior["low"].iloc[-10:].min())
    high5_prior = float(prior["high"].iloc[-5:].max())
    low5_prior = float(prior["low"].iloc[-5:].min())

    if high20_prior <= 0:
        return None

    range20 = (high20_prior - low20_prior) / price * 100.0
    range10 = (high10_prior - low10_prior) / price * 100.0
    range5 = (high5_prior - low5_prior) / price * 100.0
    contracting = range20 > range10 > range5 > 0
    box_like = range10 <= 12.0 and range5 <= 8.0
    if not (contracting or box_like):
        return None

    # Near highs: within 3% of prior 20d high (or mild breakout today)
    dist_below_pct = (high20_prior - price) / high20_prior * 100.0
    near_high = price >= high20_prior * 0.97
    breakout_today = price > high20_prior
    if not (near_high or breakout_today):
        return None
    # Too extended above pivot already — late for a pre-setup
    if price > high20_prior * 1.04:
        return None

    vol20 = float(df["volume"].iloc[-21:-1].mean())
    vol5 = float(df["volume"].iloc[-6:-1].mean()) if len(df) >= 6 else vol20
    vol_dry = vol20 > 0 and vol5 < vol20 * 0.85
    today_vol = float(df["volume"].iloc[-1])
    vol_surge = vol20 > 0 and today_vol >= vol20 * 1.5

    score = 45.0
    if contracting:
        score += min(20.0, (range20 - range5) * 0.8)
    elif box_like:
        score += 12.0
    # Closer to pivot = better
    if breakout_today:
        score += 12.0
    else:
        score += min(15.0, max(0.0, (3.0 - max(dist_below_pct, 0.0)) * 5.0))
    score += 10.0  # higher lows already required
    score += 8.0 if sma20_rising else 3.0
    score += 10.0 if vol_dry else 0.0
    if breakout_today and vol_surge:
        score += 5.0
    if box_like and near_high:
        score += 5.0

    if not _meets_min("darvas_pre_setup", score):
        return None

    triggered_today = bool(breakout_today)
    setup_ready = not triggered_today

    return PatternHit(
        pattern_type="darvas_pre_setup",
        score=round(min(score, 100.0), 1),
        triggered_today=triggered_today,
        setup_ready=setup_ready,
        details={
            "stage": "breakout" if triggered_today else "coil",
            "higher_lows": True,
            "sma20_rising": sma20_rising,
            "volatility_contraction": contracting,
            "darvas_box_like": box_like,
            "range_20d_pct": round(range20, 2),
            "range_10d_pct": round(range10, 2),
            "range_5d_pct": round(range5, 2),
            "pivot_high_20d": round(high20_prior, 2),
            "distance_to_pivot_pct": round(dist_below_pct, 2),
            "volume_dry": vol_dry,
            "volume_surge": vol_surge,
            "pre_20d_return_pct": pre_20d,
            "source": "darvasboxtrader_pre_setup_calibration",
        },
    )


PATTERN_SCORERS = (
    score_vcp,
    score_high_tight_flag,
    score_pocket_pivot,
    score_pocket_pivot_setup,
    score_inside_bar_cluster,
    score_power_gap,
    score_tight_range_near_pivot,
    score_darvas_pre_setup,
)

PATTERN_TYPES = tuple(s.__name__.removeprefix("score_") for s in PATTERN_SCORERS)


def scan_symbol_patterns(df: pd.DataFrame, macro_pass: bool) -> list[PatternHit]:
    del macro_pass  # soft overlay applied in scoring.compose_signal_scores
    hits: list[PatternHit] = []
    for scorer in PATTERN_SCORERS:
        hit = scorer(df)
        if hit:
            hits.append(hit)
    # Avoid double-counting pocket trigger + setup on same bar
    types = {h.pattern_type for h in hits}
    if "pocket_pivot" in types and "pocket_pivot_setup" in types:
        hits = [h for h in hits if h.pattern_type != "pocket_pivot_setup"]
    return hits
