from __future__ import annotations

from typing import Sequence


def wilders_rsi(closes: Sequence[float], period: int) -> float | None:
    """Wilder's smoothed RSI for an arbitrary period.

    Needs at least ``period + 1`` closes. Returns None when insufficient data.
    """
    series = wilders_rsi_series(closes, period)
    if not series:
        return None
    return series[-1]


def wilders_rsi_series(closes: Sequence[float], period: int) -> list[float]:
    """Return Wilder RSI values for each bar starting at index ``period``."""
    if period < 1:
        raise ValueError("period must be >= 1")
    n = len(closes)
    if n < period + 1:
        return []

    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        change = float(closes[i]) - float(closes[i - 1])
        if change >= 0:
            gains += change
        else:
            losses -= change

    avg_gain = gains / period
    avg_loss = losses / period
    out: list[float] = []

    def _value(ag: float, al: float) -> float:
        if al == 0:
            return 100.0 if ag > 0 else 50.0
        rs = ag / al
        return 100.0 - (100.0 / (1.0 + rs))

    out.append(_value(avg_gain, avg_loss))

    for i in range(period + 1, n):
        change = float(closes[i]) - float(closes[i - 1])
        gain = change if change > 0 else 0.0
        loss = -change if change < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out.append(_value(avg_gain, avg_loss))

    return out


def rsi_status(value: float | None, *, overbought: float = 70.0, oversold: float = 30.0) -> str:
    if value is None:
        return "Warming"
    if value >= overbought:
        return "Overbought"
    if value <= oversold:
        return "Oversold"
    return "Neutral"
