from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from mtf_rsi.models import candle_bucket_start
from mtf_rsi.rsi import rsi_status, wilders_rsi

IST = ZoneInfo("Asia/Kolkata")


def test_wilders_rsi_insufficient_data():
    assert wilders_rsi([1, 2, 3], 14) is None


def test_wilders_rsi_constant_prices():
    closes = [100.0] * 30
    assert wilders_rsi(closes, 14) == 50.0


def test_wilders_rsi_monotonic_up():
    closes = [float(i) for i in range(1, 40)]
    value = wilders_rsi(closes, 14)
    assert value is not None
    assert value == 100.0


def test_rsi_status_tags():
    assert rsi_status(75) == "Overbought"
    assert rsi_status(25) == "Oversold"
    assert rsi_status(50) == "Neutral"
    assert rsi_status(None) == "Warming"


def test_candle_bucket_aligns_to_915():
    ts = datetime(2026, 3, 17, 9, 17, 30, tzinfo=IST)
    assert candle_bucket_start(ts, 1) == datetime(2026, 3, 17, 9, 17, tzinfo=IST)
    assert candle_bucket_start(ts, 3) == datetime(2026, 3, 17, 9, 15, tzinfo=IST)
    assert candle_bucket_start(ts, 5) == datetime(2026, 3, 17, 9, 15, tzinfo=IST)

    ts2 = datetime(2026, 3, 17, 9, 21, 0, tzinfo=IST)
    assert candle_bucket_start(ts2, 5) == datetime(2026, 3, 17, 9, 20, tzinfo=IST)
    assert candle_bucket_start(ts2, 10) == datetime(2026, 3, 17, 9, 15, tzinfo=IST)
    assert candle_bucket_start(ts2, 15) == datetime(2026, 3, 17, 9, 15, tzinfo=IST)
