"""Compute tweet-mentioned technical indicators for Nifty / stock candles.

Indicators are ranked by how often @kyalashish mentions them; computable ones
get live readings from OHLC. Non-computable frameworks are returned as reference.
"""

from __future__ import annotations

import math
from typing import Any

from ..db.store import get_store
from . import nifty_candles

# Ranked from kyalashish_own_400.json analysis (tweet mention frequency).
INDICATOR_CATALOG: list[dict[str, Any]] = [
    {"id": "elliott_wave", "name": "Elliott Wave / Neo Wave", "rank": 1, "tweet_count": 86, "computable": False},
    {"id": "support_resistance", "name": "Support / Resistance", "rank": 2, "tweet_count": 78, "computable": True},
    {"id": "breakout", "name": "Breakout / Breakdown", "rank": 3, "tweet_count": 63, "computable": True},
    {"id": "price_action", "name": "Price Action", "rank": 4, "tweet_count": 58, "computable": True},
    {"id": "cas", "name": "CAS (Closing Auction)", "rank": 5, "tweet_count": 37, "computable": False},
    {"id": "time_cycle", "name": "Time Cycle (55-day)", "rank": 6, "tweet_count": 37, "computable": True},
    {"id": "gann", "name": "Gann", "rank": 7, "tweet_count": 21, "computable": False},
    {"id": "trap", "name": "Bear Trap / Bull Trap", "rank": 8, "tweet_count": 20, "computable": True},
    {"id": "volatility", "name": "Historical Volatility", "rank": 9, "tweet_count": 16, "computable": True},
    {"id": "volume_profile", "name": "Volume Profile (POC)", "rank": 10, "tweet_count": 16, "computable": True},
    {"id": "open_interest", "name": "Open Interest (OI)", "rank": 11, "tweet_count": 14, "computable": True},
    {"id": "kst", "name": "KST (Know Sure Thing)", "rank": 12, "tweet_count": 11, "computable": True},
    {"id": "bollinger", "name": "Bollinger Bands", "rank": 13, "tweet_count": 11, "computable": True},
    {"id": "options_greeks", "name": "Options Greeks", "rank": 14, "tweet_count": 10, "computable": False},
    {"id": "spreads", "name": "Spread Strategy", "rank": 15, "tweet_count": 10, "computable": False},
    {"id": "rsi", "name": "RSI", "rank": 16, "tweet_count": 7, "computable": True},
    {"id": "keltner", "name": "Keltner Channel", "rank": 17, "tweet_count": 6, "computable": True},
    {"id": "ak_indicator", "name": "AK Indicator", "rank": 18, "tweet_count": 6, "computable": False},
    {"id": "supertrend", "name": "Supertrend", "rank": 19, "tweet_count": 5, "computable": True},
    {"id": "candlestick", "name": "Candlestick Patterns", "rank": 20, "tweet_count": 5, "computable": True},
    {"id": "ichimoku", "name": "Ichimoku", "rank": 21, "tweet_count": 5, "computable": True},
    {"id": "moving_average", "name": "Moving Average (EMA/SMA)", "rank": 22, "tweet_count": 4, "computable": True},
    {"id": "fibonacci", "name": "Fibonacci", "rank": 23, "tweet_count": 3, "computable": True},
    {"id": "macd", "name": "MACD", "rank": 24, "tweet_count": 1, "computable": True},
]


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except (TypeError, ValueError):
        return None


def _sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period < 1 or len(values) < period:
        return out
    window = sum(values[:period])
    out[period - 1] = window / period
    for i in range(period, len(values)):
        window += values[i] - values[i - period]
        out[i] = window / period
    return out


def _ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period < 1 or len(values) < period:
        return out
    k = 2 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]:
    n = len(closes)
    trs: list[float] = [0.0] * n
    for i in range(n):
        if i == 0:
            trs[i] = highs[i] - lows[i]
        else:
            trs[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    out: list[float | None] = [None] * n
    if n < period:
        return out
    atr = sum(trs[:period]) / period
    out[period - 1] = atr
    for i in range(period, n):
        atr = (atr * (period - 1) + trs[i]) / period
        out[i] = atr
    return out


def _wilders_rsi(closes: list[float], period: int = 14) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        ch = closes[i] - closes[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    avg_gain = gains / period
    avg_loss = losses / period

    def value(ag: float, al: float) -> float:
        if al == 0:
            return 100.0 if ag > 0 else 50.0
        rs = ag / al
        return 100 - 100 / (1 + rs)

    out[period] = value(avg_gain, avg_loss)
    for i in range(period + 1, n):
        ch = closes[i] - closes[i - 1]
        gain = ch if ch > 0 else 0.0
        loss = -ch if ch < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = value(avg_gain, avg_loss)
    return out


def _roc(closes: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    for i in range(period, len(closes)):
        prev = closes[i - period]
        if prev == 0:
            out[i] = 0.0
        else:
            out[i] = ((closes[i] - prev) / prev) * 100
    return out


def _signal(bias: str, detail: str, **metrics: Any) -> dict[str, Any]:
    return {"bias": bias, "detail": detail, "metrics": {k: v for k, v in metrics.items() if v is not None}}


def _analyze_support_resistance(highs: list[float], lows: list[float], closes: list[float]) -> dict[str, Any]:
    lookback = min(55, len(closes))
    window_h = highs[-lookback:]
    window_l = lows[-lookback:]
    resistance = max(window_h)
    support = min(window_l)
    close = closes[-1]
    mid = (resistance + support) / 2
    dist_sup = ((close - support) / support) * 100 if support else 0
    dist_res = ((resistance - close) / close) * 100 if close else 0
    if close >= resistance * 0.995:
        bias = "bullish"
        detail = f"Near/above {lookback}d resistance {resistance:.2f}"
    elif close <= support * 1.005:
        bias = "bearish"
        detail = f"Near/below {lookback}d support {support:.2f}"
    elif close >= mid:
        bias = "neutral_bull"
        detail = f"Above mid-range; support {support:.2f}, resistance {resistance:.2f}"
    else:
        bias = "neutral_bear"
        detail = f"Below mid-range; support {support:.2f}, resistance {resistance:.2f}"
    return _signal(bias, detail, support=round(support, 2), resistance=round(resistance, 2),
                   dist_to_support_pct=round(dist_sup, 2), dist_to_resistance_pct=round(dist_res, 2))


def _analyze_breakout(highs: list[float], lows: list[float], closes: list[float]) -> dict[str, Any]:
    if len(closes) < 21:
        return _signal("warming", "Need ≥21 bars for breakout scan")
    prior_high = max(highs[-21:-1])
    prior_low = min(lows[-21:-1])
    close = closes[-1]
    if close > prior_high:
        return _signal("bullish", f"Breakout above 20-bar high {prior_high:.2f}",
                       level=round(prior_high, 2), close=round(close, 2))
    if close < prior_low:
        return _signal("bearish", f"Breakdown below 20-bar low {prior_low:.2f}",
                       level=round(prior_low, 2), close=round(close, 2))
    return _signal("neutral", f"Range-bound between {prior_low:.2f} – {prior_high:.2f}",
                   level_high=round(prior_high, 2), level_low=round(prior_low, 2), close=round(close, 2))


def _analyze_price_action(opens: list[float], highs: list[float], lows: list[float], closes: list[float]) -> dict[str, Any]:
    o, h, l, c = opens[-1], highs[-1], lows[-1], closes[-1]
    body = abs(c - o)
    range_ = max(h - l, 1e-9)
    upper = h - max(o, c)
    lower = min(o, c) - l
    if body / range_ < 0.1:
        pattern = "Doji / indecision"
        bias = "neutral"
    elif c > o and lower > body * 1.5:
        pattern = "Hammer-like bullish rejection"
        bias = "bullish"
    elif c < o and upper > body * 1.5:
        pattern = "Shooting-star-like bearish rejection"
        bias = "bearish"
    elif c > o:
        pattern = "Bullish candle"
        bias = "bullish"
    else:
        pattern = "Bearish candle"
        bias = "bearish"
    # Higher high / higher low vs prior bar
    structure = "—"
    if len(closes) >= 2:
        if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
            structure = "Higher high + higher low"
            bias = "bullish"
        elif highs[-1] < highs[-2] and lows[-1] < lows[-2]:
            structure = "Lower high + lower low"
            bias = "bearish"
        else:
            structure = "Mixed structure"
    return _signal(bias, f"{pattern}; {structure}",
                   body_pct_of_range=round(100 * body / range_, 1), close=round(c, 2))


def _analyze_time_cycle(highs: list[float], lows: list[float], closes: list[float], dates: list[str]) -> dict[str, Any]:
    """Approximate 55-bar cycle: bars since significant swing low/high."""
    if len(closes) < 55:
        return _signal("warming", "Need ≥55 bars for 55-day cycle proxy")
    look = closes[-120:] if len(closes) >= 120 else closes
    offs = len(closes) - len(look)
    lo_i = min(range(len(look)), key=lambda i: look[i])
    hi_i = max(range(len(look)), key=lambda i: look[i])
    bars_since_low = len(closes) - 1 - (offs + lo_i)
    bars_since_high = len(closes) - 1 - (offs + hi_i)
    cycle = 55
    near_low = abs(bars_since_low - cycle) <= 5 or bars_since_low % cycle <= 5
    near_high = abs(bars_since_high - cycle) <= 5 or bars_since_high % cycle <= 5
    if near_low and bars_since_low <= bars_since_high:
        bias = "bullish"
        detail = f"~{bars_since_low} bars since swing low (55-cycle zone)"
    elif near_high:
        bias = "bearish"
        detail = f"~{bars_since_high} bars since swing high (55-cycle zone)"
    else:
        bias = "neutral"
        detail = f"{bars_since_low} bars since low, {bars_since_high} since high"
    return _signal(
        bias,
        detail,
        bars_since_swing_low=bars_since_low,
        bars_since_swing_high=bars_since_high,
        cycle_length=cycle,
        last_date=dates[-1] if dates else None,
    )


def _analyze_trap(opens: list[float], highs: list[float], lows: list[float], closes: list[float]) -> dict[str, Any]:
    if len(closes) < 5:
        return _signal("warming", "Need more bars for trap detection")
    # Bear trap: prior day breaks low, then closes back above prior open/close
    if lows[-1] < min(lows[-4:-1]) and closes[-1] > opens[-1] and closes[-1] > closes[-2]:
        return _signal("bullish", "Possible bear trap: flushed lows then recovered")
    if highs[-1] > max(highs[-4:-1]) and closes[-1] < opens[-1] and closes[-1] < closes[-2]:
        return _signal("bearish", "Possible bull trap: spiked highs then failed")
    return _signal("neutral", "No clear trap pattern on last bar")


def _analyze_volatility(closes: list[float]) -> dict[str, Any]:
    if len(closes) < 22:
        return _signal("warming", "Need ≥22 closes for HV")
    rets = []
    for i in range(1, len(closes)):
        if closes[i - 1] != 0:
            rets.append(math.log(closes[i] / closes[i - 1]))
    window = rets[-21:]
    mean = sum(window) / len(window)
    var = sum((r - mean) ** 2 for r in window) / len(window)
    hv = math.sqrt(var) * math.sqrt(252) * 100
    # Compare to prior 21d window if available
    bias = "neutral"
    detail = f"21d annualized HV ≈ {hv:.1f}%"
    if len(rets) >= 42:
        prev = rets[-42:-21]
        pmean = sum(prev) / len(prev)
        pvar = sum((r - pmean) ** 2 for r in prev) / len(prev)
        phv = math.sqrt(pvar) * math.sqrt(252) * 100
        if hv < phv * 0.85:
            bias = "compressing"
            detail = f"HV compressing {hv:.1f}% vs prior {phv:.1f}% (expansion risk)"
        elif hv > phv * 1.15:
            bias = "expanding"
            detail = f"HV expanding {hv:.1f}% vs prior {phv:.1f}%"
        else:
            detail = f"HV stable {hv:.1f}% (prior {phv:.1f}%)"
    return _signal(bias, detail, hv_21d_pct=round(hv, 2))


def _analyze_volume_profile(closes: list[float], volumes: list[float]) -> dict[str, Any]:
    n = min(60, len(closes))
    if n < 10:
        return _signal("warming", "Need more bars for volume profile")
    c = closes[-n:]
    v = volumes[-n:]
    lo, hi = min(c), max(c)
    if hi <= lo:
        return _signal("neutral", "Flat range — no POC")
    bins = 24
    width = (hi - lo) / bins
    hist = [0.0] * bins
    for price, vol in zip(c, v):
        idx = min(bins - 1, int((price - lo) / width))
        hist[idx] += max(vol, 1.0)
    poc_i = max(range(bins), key=lambda i: hist[i])
    poc = lo + (poc_i + 0.5) * width
    close = closes[-1]
    dist = ((close - poc) / poc) * 100 if poc else 0
    if abs(dist) < 0.4:
        bias = "neutral"
        detail = f"Price at Volume Profile POC ≈ {poc:.2f}"
    elif close > poc:
        bias = "bullish"
        detail = f"Price above POC {poc:.2f} (+{dist:.1f}%)"
    else:
        bias = "bearish"
        detail = f"Price below POC {poc:.2f} ({dist:.1f}%)"
    return _signal(bias, detail, poc=round(poc, 2), dist_to_poc_pct=round(dist, 2))


def _analyze_oi(ois: list[float | None], closes: list[float]) -> dict[str, Any]:
    valid = [(i, o) for i, o in enumerate(ois) if o is not None and o > 0]
    if len(valid) < 3:
        return _signal("unavailable", "OI not available for this series (typical for equity daily)")
    _, last_oi = valid[-1]
    _, prev_oi = valid[-2]
    chg = ((last_oi - prev_oi) / prev_oi) * 100 if prev_oi else 0
    price_up = closes[-1] >= closes[-2]
    if price_up and chg > 1:
        bias = "bullish"
        detail = f"OI rising with price (+{chg:.1f}%) — fresh longs"
    elif (not price_up) and chg > 1:
        bias = "bearish"
        detail = f"OI rising into weakness (+{chg:.1f}%) — fresh shorts"
    elif price_up and chg < -1:
        bias = "neutral_bear"
        detail = f"OI falling on bounce ({chg:.1f}%) — short covering"
    elif (not price_up) and chg < -1:
        bias = "neutral_bull"
        detail = f"OI falling on dip ({chg:.1f}%) — long unwinding"
    else:
        bias = "neutral"
        detail = f"OI little changed ({chg:+.1f}%)"
    return _signal(bias, detail, oi=round(last_oi, 0), oi_change_pct=round(chg, 2))


def _analyze_kst(closes: list[float]) -> dict[str, Any]:
    # Classic KST: ROC(10,15,20,30) SMA(10,10,10,15) then signal SMA(9)
    if len(closes) < 50:
        return _signal("warming", "Need ≥50 bars for KST")
    r1 = _roc(closes, 10)
    r2 = _roc(closes, 15)
    r3 = _roc(closes, 20)
    r4 = _roc(closes, 30)
    s1 = _sma([x or 0 for x in r1], 10)
    s2 = _sma([x or 0 for x in r2], 10)
    s3 = _sma([x or 0 for x in r3], 10)
    s4 = _sma([x or 0 for x in r4], 15)
    kst: list[float | None] = [None] * len(closes)
    for i in range(len(closes)):
        if None in (s1[i], s2[i], s3[i], s4[i]):
            continue
        kst[i] = (s1[i] or 0) * 1 + (s2[i] or 0) * 2 + (s3[i] or 0) * 3 + (s4[i] or 0) * 4
    signal = _sma([x or 0 for x in kst], 9)
    kv, sv = kst[-1], signal[-1]
    if kv is None or sv is None:
        return _signal("warming", "KST still seeding")
    if kv > sv and (kst[-2] or 0) <= (signal[-2] or 0):
        bias = "bullish"
        detail = "KST crossed above signal — momentum up"
    elif kv < sv and (kst[-2] or 0) >= (signal[-2] or 0):
        bias = "bearish"
        detail = "KST crossed below signal — momentum down"
    elif kv > sv:
        bias = "bullish"
        detail = "KST above signal"
    else:
        bias = "bearish"
        detail = "KST below signal"
    return _signal(bias, detail, kst=round(kv, 2), signal=round(sv, 2))


def _analyze_bollinger(closes: list[float], period: int = 20, mult: float = 2.0) -> dict[str, Any]:
    if len(closes) < period:
        return _signal("warming", f"Need ≥{period} bars for Bollinger")
    mid = _sma(closes, period)
    m = mid[-1]
    if m is None:
        return _signal("warming", "Bollinger mid unavailable")
    window = closes[-period:]
    var = sum((x - m) ** 2 for x in window) / period
    std = math.sqrt(var)
    upper, lower = m + mult * std, m - mult * std
    c = closes[-1]
    width = ((upper - lower) / m) * 100 if m else 0
    if c >= upper:
        bias = "overbought"
        detail = f"Above upper band {upper:.2f}"
    elif c <= lower:
        bias = "oversold"
        detail = f"Below lower band {lower:.2f}"
    elif abs(c - m) / m < 0.002:
        bias = "neutral"
        detail = f"At mid Bollinger {m:.2f} (watch for spring)"
    elif c > m:
        bias = "neutral_bull"
        detail = f"Above mid band {m:.2f}"
    else:
        bias = "neutral_bear"
        detail = f"Below mid band {m:.2f}"
    return _signal(bias, detail, middle=round(m, 2), upper=round(upper, 2), lower=round(lower, 2),
                   bandwidth_pct=round(width, 2), close=round(c, 2))


def _analyze_rsi(closes: list[float], period: int = 14) -> dict[str, Any]:
    series = _wilders_rsi(closes, period)
    v = series[-1]
    if v is None:
        return _signal("warming", f"Need ≥{period + 1} bars for RSI")
    if v >= 70:
        bias = "overbought"
    elif v <= 30:
        bias = "oversold"
    elif v >= 55:
        bias = "bullish"
    elif v <= 45:
        bias = "bearish"
    else:
        bias = "neutral"
    return _signal(bias, f"RSI({period}) = {v:.1f}", rsi=round(v, 1), period=period)


def _analyze_keltner(highs: list[float], lows: list[float], closes: list[float],
                     ema_period: int = 20, atr_period: int = 10, mult: float = 1.5) -> dict[str, Any]:
    mid = _ema(closes, ema_period)
    atr = _atr(highs, lows, closes, atr_period)
    m, a = mid[-1], atr[-1]
    if m is None or a is None:
        return _signal("warming", "Need more bars for Keltner")
    upper, lower = m + mult * a, m - mult * a
    c = closes[-1]
    if c > upper:
        bias = "bullish"
        detail = f"Keltner breakout above {upper:.2f}"
    elif c < lower:
        bias = "bearish"
        detail = f"Keltner breakdown below {lower:.2f}"
    elif c > m:
        bias = "neutral_bull"
        detail = f"Inside channel, above mid {m:.2f}"
    else:
        bias = "neutral_bear"
        detail = f"Inside channel, below mid {m:.2f}"
    return _signal(bias, detail, middle=round(m, 2), upper=round(upper, 2), lower=round(lower, 2), close=round(c, 2))


def _analyze_supertrend(highs: list[float], lows: list[float], closes: list[float],
                        period: int = 10, mult: float = 3.0) -> dict[str, Any]:
    atr = _atr(highs, lows, closes, period)
    n = len(closes)
    if n < period + 2 or atr[period] is None:
        return _signal("warming", "Need more bars for Supertrend")
    st = [0.0] * n
    direction = [1] * n  # 1 = bull, -1 = bear
    for i in range(period, n):
        a = atr[i]
        if a is None:
            continue
        mid = (highs[i] + lows[i]) / 2
        basic_upper = mid + mult * a
        basic_lower = mid - mult * a
        if i == period:
            st[i] = basic_lower
            direction[i] = 1
            continue
        prev_st = st[i - 1]
        prev_dir = direction[i - 1]
        if prev_dir == 1:
            lower = max(basic_lower, prev_st) if closes[i - 1] > prev_st else basic_lower
            if closes[i] < lower:
                direction[i] = -1
                st[i] = basic_upper
            else:
                direction[i] = 1
                st[i] = lower
        else:
            upper = min(basic_upper, prev_st) if closes[i - 1] < prev_st else basic_upper
            if closes[i] > upper:
                direction[i] = 1
                st[i] = basic_lower
            else:
                direction[i] = -1
                st[i] = upper
    d = direction[-1]
    level = st[-1]
    if d == 1 and direction[-2] == -1:
        bias = "bullish"
        detail = f"Supertrend flipped bull at {level:.2f}"
    elif d == -1 and direction[-2] == 1:
        bias = "bearish"
        detail = f"Supertrend flipped bear at {level:.2f}"
    elif d == 1:
        bias = "bullish"
        detail = f"Price above Supertrend {level:.2f}"
    else:
        bias = "bearish"
        detail = f"Price below Supertrend {level:.2f}"
    return _signal(bias, detail, level=round(level, 2), trend="up" if d == 1 else "down")


def _analyze_candlestick(opens: list[float], highs: list[float], lows: list[float], closes: list[float]) -> dict[str, Any]:
    o, h, l, c = opens[-1], highs[-1], lows[-1], closes[-1]
    body = abs(c - o)
    rng = max(h - l, 1e-9)
    patterns = []
    if body / rng < 0.12:
        patterns.append("Doji")
    if c > o and (min(o, c) - l) > body * 2 and (h - max(o, c)) < body * 0.5:
        patterns.append("Hammer")
    if c < o and (h - max(o, c)) > body * 2 and (min(o, c) - l) < body * 0.5:
        patterns.append("Shooting Star")
    if len(closes) >= 2:
        if closes[-2] < opens[-2] and c > o and c >= opens[-2] and o <= closes[-2]:
            patterns.append("Bullish Engulfing")
        if closes[-2] > opens[-2] and c < o and c <= opens[-2] and o >= closes[-2]:
            patterns.append("Bearish Engulfing")
    if not patterns:
        return _signal("neutral", "No classic pattern on last candle")
    bullish = any(p in patterns for p in ("Hammer", "Bullish Engulfing"))
    bearish = any(p in patterns for p in ("Shooting Star", "Bearish Engulfing"))
    if bullish and not bearish:
        bias = "bullish"
    elif bearish and not bullish:
        bias = "bearish"
    else:
        bias = "neutral"
    return _signal(bias, ", ".join(patterns), patterns=patterns)


def _analyze_ichimoku(highs: list[float], lows: list[float], closes: list[float]) -> dict[str, Any]:
    if len(closes) < 52:
        return _signal("warming", "Need ≥52 bars for Ichimoku")

    def mid_hl(period: int, end: int) -> float:
        h = max(highs[end - period + 1 : end + 1])
        l = min(lows[end - period + 1 : end + 1])
        return (h + l) / 2

    i = len(closes) - 1
    tenkan = mid_hl(9, i)
    kijun = mid_hl(26, i)
    span_a = (tenkan + kijun) / 2
    span_b = mid_hl(52, i)
    c = closes[-1]
    cloud_top = max(span_a, span_b)
    cloud_bot = min(span_a, span_b)
    if c > cloud_top and tenkan > kijun:
        bias = "bullish"
        detail = "Above cloud with Tenkan > Kijun"
    elif c < cloud_bot and tenkan < kijun:
        bias = "bearish"
        detail = "Below cloud with Tenkan < Kijun"
    else:
        bias = "neutral"
        detail = "Inside / mixed cloud structure"
    return _signal(bias, detail, tenkan=round(tenkan, 2), kijun=round(kijun, 2),
                   cloud_top=round(cloud_top, 2), cloud_bot=round(cloud_bot, 2), close=round(c, 2))


def _analyze_ma(closes: list[float]) -> dict[str, Any]:
    if len(closes) < 50:
        return _signal("warming", "Need ≥50 bars for MA stack")
    ema20 = _ema(closes, 20)[-1]
    ema50 = _ema(closes, 50)[-1]
    sma20 = _sma(closes, 20)[-1]
    c = closes[-1]
    if None in (ema20, ema50, sma20):
        return _signal("warming", "MA values seeding")
    if c > ema20 > ema50:
        bias = "bullish"
        detail = "Price > EMA20 > EMA50 (uptrend stack)"
    elif c < ema20 < ema50:
        bias = "bearish"
        detail = "Price < EMA20 < EMA50 (downtrend stack)"
    else:
        bias = "neutral"
        detail = "Mixed MA alignment"
    return _signal(bias, detail, ema20=round(ema20, 2), ema50=round(ema50, 2),
                   sma20=round(sma20, 2), close=round(c, 2))


def _analyze_fibonacci(highs: list[float], lows: list[float], closes: list[float]) -> dict[str, Any]:
    look = min(60, len(closes))
    swing_high = max(highs[-look:])
    swing_low = min(lows[-look:])
    rng = swing_high - swing_low
    if rng <= 0:
        return _signal("neutral", "No swing range for Fibonacci")
    levels = {
        "0.0": swing_high,
        "0.382": swing_high - 0.382 * rng,
        "0.5": swing_high - 0.5 * rng,
        "0.618": swing_high - 0.618 * rng,
        "1.0": swing_low,
    }
    c = closes[-1]
    nearest_name = min(levels.keys(), key=lambda k: abs(levels[k] - c))
    nearest = levels[nearest_name]
    dist = abs(c - nearest) / c * 100 if c else 0
    if c > levels["0.382"]:
        bias = "bullish"
    elif c < levels["0.618"]:
        bias = "bearish"
    else:
        bias = "neutral"
    return _signal(
        bias,
        f"Nearest Fib {nearest_name} @ {nearest:.2f} ({dist:.2f}% away)",
        swing_high=round(swing_high, 2),
        swing_low=round(swing_low, 2),
        nearest_level=nearest_name,
        nearest_price=round(nearest, 2),
        levels={k: round(v, 2) for k, v in levels.items()},
    )


def _analyze_macd(closes: list[float]) -> dict[str, Any]:
    if len(closes) < 35:
        return _signal("warming", "Need ≥35 bars for MACD")
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line: list[float | None] = [None] * len(closes)
    for i in range(len(closes)):
        if ema12[i] is not None and ema26[i] is not None:
            macd_line[i] = (ema12[i] or 0) - (ema26[i] or 0)
    filled = [x or 0.0 for x in macd_line]
    signal = _ema(filled, 9)
    # Only meaningful after ema26 seeds
    m, s = macd_line[-1], signal[-1]
    if m is None or s is None or ema26[-1] is None:
        return _signal("warming", "MACD seeding")
    hist = m - s
    if m > s and (macd_line[-2] or 0) <= (signal[-2] or 0):
        bias = "bullish"
        detail = "MACD bullish cross"
    elif m < s and (macd_line[-2] or 0) >= (signal[-2] or 0):
        bias = "bearish"
        detail = "MACD bearish cross"
    elif hist > 0:
        bias = "bullish"
        detail = "MACD above signal"
    else:
        bias = "bearish"
        detail = "MACD below signal"
    return _signal(bias, detail, macd=round(m, 2), signal=round(s, 2), histogram=round(hist, 2))


def _manual(name: str, note: str) -> dict[str, Any]:
    return _signal(
        "manual",
        note,
        note=f"{name} is discretionary / requires options or wave labeling — shown from tweet ranking only",
    )


def analyze_bars(bars: list[dict[str, Any]], *, rsi_period: int = 14) -> list[dict[str, Any]]:
    if len(bars) < 5:
        raise ValueError("Need at least 5 bars for analysis")

    opens = [_f(b["open"]) or 0.0 for b in bars]
    highs = [_f(b["high"]) or 0.0 for b in bars]
    lows = [_f(b["low"]) or 0.0 for b in bars]
    closes = [_f(b["close"]) or 0.0 for b in bars]
    volumes = [_f(b.get("volume")) or 0.0 for b in bars]
    ois = [_f(b.get("oi")) for b in bars]
    dates = [str(b.get("date") or b.get("ts") or "") for b in bars]

    compute = {
        "support_resistance": lambda: _analyze_support_resistance(highs, lows, closes),
        "breakout": lambda: _analyze_breakout(highs, lows, closes),
        "price_action": lambda: _analyze_price_action(opens, highs, lows, closes),
        "time_cycle": lambda: _analyze_time_cycle(highs, lows, closes, dates),
        "trap": lambda: _analyze_trap(opens, highs, lows, closes),
        "volatility": lambda: _analyze_volatility(closes),
        "volume_profile": lambda: _analyze_volume_profile(closes, volumes),
        "open_interest": lambda: _analyze_oi(ois, closes),
        "kst": lambda: _analyze_kst(closes),
        "bollinger": lambda: _analyze_bollinger(closes),
        "rsi": lambda: _analyze_rsi(closes, rsi_period),
        "keltner": lambda: _analyze_keltner(highs, lows, closes),
        "supertrend": lambda: _analyze_supertrend(highs, lows, closes),
        "candlestick": lambda: _analyze_candlestick(opens, highs, lows, closes),
        "ichimoku": lambda: _analyze_ichimoku(highs, lows, closes),
        "moving_average": lambda: _analyze_ma(closes),
        "fibonacci": lambda: _analyze_fibonacci(highs, lows, closes),
        "macd": lambda: _analyze_macd(closes),
        "elliott_wave": lambda: _manual("Elliott Wave / Neo Wave", "Wave labeling is discretionary — use with price structure"),
        "cas": lambda: _manual("CAS", "NSE Closing Auction Session — expiry-day options effect, not OHLC-derivable"),
        "gann": lambda: _manual("Gann", "Gann angles/levels require manual chart geometry"),
        "options_greeks": lambda: _manual("Options Greeks", "Needs options chain (delta/gamma/theta/vega)"),
        "spreads": lambda: _manual("Spread Strategy", "Trade structure choice — not a price indicator"),
        "ak_indicator": lambda: _manual("AK Indicator", "Proprietary Waves Strategy tool — not publicly computable"),
    }

    results: list[dict[str, Any]] = []
    for meta in INDICATOR_CATALOG:
        iid = meta["id"]
        reading = compute[iid]()
        results.append({
            **meta,
            "bias": reading["bias"],
            "detail": reading["detail"],
            "metrics": reading.get("metrics") or {},
        })
    return results


def _bias_score(bias: str) -> int:
    table = {
        "bullish": 2,
        "neutral_bull": 1,
        "oversold": 1,
        "compressing": 0,
        "neutral": 0,
        "warming": 0,
        "manual": 0,
        "unavailable": 0,
        "expanding": 0,
        "overbought": -1,
        "neutral_bear": -1,
        "bearish": -2,
    }
    return table.get(bias, 0)


def analyze_symbol(
    symbol: str,
    *,
    timeframe: str = "daily",
    limit: int = 300,
    rsi_period: int = 14,
) -> dict[str, Any]:
    symbol_u = symbol.strip().upper()
    store = get_store()

    if symbol_u in {"NIFTY", "NIFTY50", "NIFTY 50"}:
        tf = timeframe if timeframe in {"1m", "3m", "5m", "10m", "daily"} else "daily"
        payload = nifty_candles.nifty_candles(tf, limit=limit)
        candles = payload["candles"]
        bars = [
            {
                "date": c.get("ts"),
                "ts": c.get("ts"),
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c.get("volume") or 0,
                "oi": c.get("oi"),
            }
            for c in candles
        ]
        label = payload.get("instrument_label") or "Nifty 50"
        instrument = payload.get("instrument_token") or "NSE_INDEX|Nifty 50"
        source = "index_candles"
        used_tf = tf
    else:
        # Stocks: daily candles from timeline DB
        rows = store.get_candles_for_ticker(symbol_u)
        if not rows:
            profile = store.get_profile_by_ticker(symbol_u)
            if not profile:
                raise ValueError(f"Unknown symbol '{symbol_u}' — try NIFTY or a ticker in daily_candles")
            raise ValueError(f"No daily candles for {symbol_u}")
        bars = [
            {
                "date": r["date"],
                "ts": r["date"],
                "open": r["open"],
                "high": r["high"],
                "low": r["low"],
                "close": r["close"],
                "volume": r.get("volume") or 0,
                "oi": None,
            }
            for r in rows[-limit:]
        ]
        profile = store.get_profile_by_ticker(symbol_u) or {}
        label = profile.get("company_name") or symbol_u
        instrument = profile.get("instrument_token") or symbol_u
        source = "daily_candles"
        used_tf = "daily"

    if len(bars) < 5:
        raise ValueError(f"Insufficient bars ({len(bars)}) for {symbol_u}")

    indicators = analyze_bars(bars, rsi_period=rsi_period)
    computable = [i for i in indicators if i["computable"] and i["bias"] not in {"manual", "unavailable", "warming"}]
    score = sum(_bias_score(i["bias"]) for i in computable)
    if score >= 6:
        overall = "bullish"
    elif score <= -6:
        overall = "bearish"
    elif score >= 2:
        overall = "lean_bullish"
    elif score <= -2:
        overall = "lean_bearish"
    else:
        overall = "mixed"

    last = bars[-1]
    return {
        "symbol": symbol_u,
        "label": label,
        "instrument_token": instrument,
        "timeframe": used_tf,
        "source": source,
        "bar_count": len(bars),
        "last_bar": {
            "ts": last.get("ts") or last.get("date"),
            "open": last["open"],
            "high": last["high"],
            "low": last["low"],
            "close": last["close"],
            "volume": last.get("volume"),
        },
        "overall_bias": overall,
        "bias_score": score,
        "rsi_period": rsi_period,
        "catalog_source": "kyalashish_own_400 indicator mention ranking",
        "indicators": indicators,
    }
