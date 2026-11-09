"""Chart payload analyses a past session but still draws the bars that followed."""

from __future__ import annotations

import math
from datetime import date, timedelta

from app.db.store import TimelineStore
from app.services.labs.grimes.engine import get_chart_payload

TOKEN = "NSE_EQ|AAA"
START = date(2026, 1, 5)
BARS = 220


def _seed(store: TimelineStore) -> list[str]:
    store.upsert_profiles(
        [{"instrument_token": TOKEN, "ticker": "AAA", "company_name": "AAA Ltd"}]
    )
    rows = []
    dates: list[str] = []
    day = START
    for i in range(BARS):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        close = 100 + i * 0.4 + 6 * math.sin(i / 7)
        rows.append(
            {
                "trade_date": day.isoformat(),
                "instrument_token": TOKEN,
                "open_price": close - 0.5,
                "high_price": close + 1.2,
                "low_price": close - 1.4,
                "close_price": close,
                "volume": 100_000 + (i % 11) * 5_000,
            }
        )
        dates.append(day.isoformat())
        day += timedelta(days=1)
    store.upsert_candles(rows)
    return dates


def test_past_session_chart_includes_later_bars(tmp_path) -> None:
    store = TimelineStore(tmp_path / "t.db")
    dates = _seed(store)
    as_of = dates[-30]

    payload = get_chart_payload("AAA", store=store, as_of=as_of)
    bar_dates = [c["date"] for c in payload["candles"]]

    # Signals stay anchored to the selected session…
    assert payload["as_of"] == as_of
    # …while the chart keeps drawing what happened next.
    assert bar_dates[-1] == dates[-1]
    assert as_of in bar_dates
    assert bar_dates == sorted(set(bar_dates))
    assert payload["ema20"][-1]["time"] == dates[-1]
    assert all(s["timestamp"] <= as_of for s in payload["history_setups"])


def test_latest_session_chart_ends_at_latest_bar(tmp_path) -> None:
    store = TimelineStore(tmp_path / "t.db")
    dates = _seed(store)

    payload = get_chart_payload("AAA", store=store, as_of=dates[-1])
    assert payload["as_of"] == dates[-1]
    assert payload["candles"][-1]["date"] == dates[-1]
