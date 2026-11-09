from __future__ import annotations

import math
import random

import numpy as np
import pytest

from app.db.store import TimelineStore, _aligned_bars, _daily_history_stats
from app.services.live_scan.backtest import (
    BacktestParams,
    BacktestSymbol,
    Funnel,
    journal_scorecard,
    morning_context,
    run_backtest,
    simulate_symbol,
    target_sweep,
)
from app.services.live_scan.ranker import candle_plan, session_call, trend_side

_ITEM = BacktestSymbol(symbol="TEST", token="NSE_EQ|TEST", segment="fno")


def _dates(count: int) -> list[str]:
    from datetime import date, timedelta

    start = date(2026, 1, 1)
    return [(start + timedelta(days=offset)).isoformat() for offset in range(count)]


def _uptrend(count: int = 20) -> list[tuple[str, float, float, float, float]]:
    """A clean rising series: close above its average, positive 20-day trend, efficient path."""
    bars = []
    for index, day in enumerate(_dates(count)):
        close = 100.0 + index
        bars.append((day, close - 0.5, close + 1.0, close - 1.0, close))
    return bars


def _with_today(bars, today):
    day = _dates(len(bars) + 1)[-1]
    return [*bars, (day, *today)], day


def _params(day: str, **overrides) -> BacktestParams:
    return BacktestParams(start=day, end=day, **{"cost_pct": 0.0, **overrides}).checked()


def test_morning_context_matches_live_statistics() -> None:
    rng = random.Random(7)
    closes = [100.0]
    for _ in range(59):
        closes.append(closes[-1] * (1 + rng.uniform(-0.03, 0.03)))
    highs = [close * (1 + rng.uniform(0, 0.02)) for close in closes]
    lows = [close * (1 - rng.uniform(0, 0.02)) for close in closes]
    ctx = morning_context(np.array(highs), np.array(lows), np.array(closes))
    for t in (20, 33, 59):
        window = [
            {"high_price": highs[i], "low_price": lows[i], "close_price": closes[i]} for i in range(t - 1, t - 21, -1)
        ]
        live = _daily_history_stats(
            volumes=[1.0] * 20,
            closes=[row["close_price"] for row in window],
            highs=[row["high_price"] for row in window],
            lows=[row["low_price"] for row in window],
            prior_high=highs[t - 1],
            prior_low=lows[t - 1],
            prior_close=closes[t - 1],
            prior_date="x",
            bar_count=20,
            bars=_aligned_bars(window),
        )
        assert ctx["sma"][t] == pytest.approx(live["sma20"])
        assert ctx["trend"][t] == pytest.approx(live["trend_20_pct"])
        assert ctx["eff"][t] == pytest.approx(live["efficiency_20"])
        assert ctx["atr_pct"][t] == pytest.approx(live["atr_pct"])
        assert ctx["ret5"][t] == pytest.approx(live["return_5d_pct"])
        assert ctx["high20"][t] == pytest.approx(live["high_20"])
        assert ctx["low20"][t] == pytest.approx(live["low_20"])
    assert math.isnan(ctx["sma"][19])


def test_trend_side_is_the_session_call_rule() -> None:
    assert trend_side(110, 100, 5) == "buy"
    assert trend_side(90, 100, -5) == "sell"
    assert trend_side(110, 100, -1) is None
    assert trend_side(100, None, 5) is None
    quote = {
        "symbol": "X",
        "ltp": 99.0,
        "prev_close": 98.0,
        "sma20": 90.0,
        "trend_20_pct": 6.0,
        "efficiency_20": 0.5,
        "prior_high": 100.0,
        "prior_low": 96.0,
        "atr_pct": 3.0,
        "history_bars": 20,
    }
    call = session_call(quote, 0.5)
    plan = candle_plan("buy", 100.0, 96.0, atr=0.03 * 98.0)
    assert call["entry"] == round(plan["entry"], 2)
    assert call["stop"] == round(plan["stop"], 2)


def test_candle_plan_knobs_default_to_live_constants() -> None:
    assert candle_plan("buy", 100, 95, atr=5) == candle_plan("buy", 100, 95, atr=5, reward_r=2.0, swing_r=4.0)
    wide = candle_plan("buy", 100, 95, atr=5, reward_r=3.0)
    assert wide["exit"] == pytest.approx(115.0)


def _plan_for(bars):
    """Entry, stop, target of the uptrend plan for the next session."""
    closes = np.array([bar[4] for bar in bars])
    ctx = morning_context(
        np.array([bar[2] for bar in bars] + [0.0]),
        np.array([bar[3] for bar in bars] + [0.0]),
        np.append(closes, 0.0),
    )
    t = len(bars)
    atr = ctx["atr_pct"][t] / 100.0 * closes[-1]
    return candle_plan("buy", bars[-1][2], bars[-1][3], atr=atr)


def test_cross_and_target_books_the_target() -> None:
    history = _uptrend()
    plan = _plan_for(history)
    entry, target = plan["entry"], plan["exit"]
    bars, day = _with_today(history, (entry - 0.5, target + 0.1, entry - 0.4, target))
    funnel = Funnel()
    trades = simulate_symbol(_ITEM, bars, _params(day), funnel)
    assert len(trades) == 1
    trade = trades[0]
    assert trade.fill_type == "level"
    assert trade.fill == pytest.approx(entry)
    assert trade.day_status == "target"
    assert trade.day_r == pytest.approx(2.0)
    assert not trade.ambiguous
    assert funnel.filled == 1


def test_stop_and_target_in_one_bar_books_the_stop() -> None:
    history = _uptrend()
    plan = _plan_for(history)
    bars, day = _with_today(history, (plan["entry"] + 0.01, plan["exit"] + 1, plan["stop"] - 1, plan["entry"]))
    trade = simulate_symbol(_ITEM, bars, _params(day), Funnel())[0]
    assert trade.day_status == "stopped"
    assert trade.ambiguous
    assert trade.alt_day_r is not None and trade.alt_day_r > 1.9


def test_gap_beyond_window_is_a_chase_unless_price_returns() -> None:
    history = _uptrend()
    plan = _plan_for(history)
    entry, risk = plan["entry"], plan["risk"]
    gap = entry + 0.6 * risk
    bars, day = _with_today(history, (gap, gap + 0.5, gap - 0.1, gap + 0.2))
    funnel = Funnel()
    assert simulate_symbol(_ITEM, bars, _params(day), funnel) == []
    assert funnel.chased_gap == 1

    bars, day = _with_today(history, (gap, gap + 0.5, entry - 0.2, entry + 0.3))
    trade = simulate_symbol(_ITEM, bars, _params(day), Funnel())[0]
    assert trade.fill_type == "pullback"
    assert trade.fill == pytest.approx(entry)
    assert trade.day_status == "closed"
    assert not trade.ambiguous

    # Closed back under the entry: maybe never re-crossed. Booked as a loss, flagged, no fill in the bound.
    bars, day = _with_today(history, (gap, gap + 0.5, entry - 0.5, entry - 0.3))
    trade = simulate_symbol(_ITEM, bars, _params(day), Funnel())[0]
    assert trade.day_r < 0
    assert trade.ambiguous
    assert trade.alt_day_r is None


def test_gap_inside_window_fills_at_the_open() -> None:
    history = _uptrend()
    plan = _plan_for(history)
    gap = plan["entry"] + 0.2 * plan["risk"]
    bars, day = _with_today(history, (gap, gap + 0.3, gap - 0.1, gap + 0.1))
    trade = simulate_symbol(_ITEM, bars, _params(day), Funnel())[0]
    assert trade.fill_type == "open"
    assert trade.fill == pytest.approx(gap)
    assert trade.day_r == pytest.approx(0.1 / abs(gap - plan["stop"]))


def test_no_cross_is_not_triggered_and_side_filter_skips() -> None:
    history = _uptrend()
    plan = _plan_for(history)
    bars, day = _with_today(history, (plan["entry"] - 1, plan["entry"] - 0.2, plan["entry"] - 1.5, plan["entry"] - 0.5))
    funnel = Funnel()
    assert simulate_symbol(_ITEM, bars, _params(day), funnel) == []
    assert funnel.not_triggered == 1
    funnel = Funnel()
    assert simulate_symbol(_ITEM, bars, _params(day, side="sell"), funnel) == []
    assert funnel.wrong_side == 1


def test_swing_leg_carries_to_a_later_target() -> None:
    history = _uptrend()
    plan = _plan_for(history)
    entry, swing = plan["entry"], plan["swing_exit"]
    bars, day = _with_today(history, (entry - 0.3, entry + 0.5, entry - 0.2, entry + 0.4))
    later = _dates(len(bars) + 2)[-2:]
    bars += [
        (later[0], entry + 0.4, entry + 1.0, entry + 0.1, entry + 0.8),
        (later[1], entry + 0.8, swing + 0.5, entry + 0.5, swing),
    ]
    trade = simulate_symbol(_ITEM, bars, _params(day), Funnel())[0]
    assert trade.day_status == "closed"
    assert trade.swing_status == "target"
    assert trade.swing_days == 2
    assert trade.swing_closed_on == later[1]
    assert trade.swing_r == pytest.approx((swing - entry) / plan["risk"])


def test_costs_come_off_every_trade() -> None:
    history = _uptrend()
    plan = _plan_for(history)
    entry, target = plan["entry"], plan["exit"]
    bars, day = _with_today(history, (entry - 0.5, target + 0.1, entry - 0.4, target))
    gross = simulate_symbol(_ITEM, bars, _params(day), Funnel())[0]
    net = simulate_symbol(_ITEM, bars, _params(day, cost_pct=0.1), Funnel())[0]
    assert net.day_r == pytest.approx(gross.day_r - 0.001 * entry / plan["risk"])
    assert net.day_pct == pytest.approx(gross.day_pct - 0.1)


def test_target_sweep_reproduces_the_booked_target() -> None:
    history = _uptrend()
    plan = _plan_for(history)
    bars, day = _with_today(history, (plan["entry"] - 0.5, plan["exit"] + 0.1, plan["entry"] - 0.4, plan["exit"]))
    trades = simulate_symbol(_ITEM, bars, _params(day), Funnel())
    sweep = {row["reward_r"]: row for row in target_sweep(trades, 0.0)}
    assert sweep[2.0]["avg_r"] == pytest.approx(trades[0].day_r, abs=1e-3)
    assert sweep[1.0]["avg_r"] == pytest.approx(1.0, abs=1e-3)


def _session_path(day: str, legs: list[tuple[int, float]]) -> list[tuple[str, float, float, float, float]]:
    """A full 09:15–15:29 minute path walking linearly between (minute index, price) waypoints."""
    points = legs
    prices: list[float] = []
    for (start_index, start_price), (end_index, end_price) in zip(points, points[1:]):
        steps = max(1, end_index - start_index)
        prices.extend(start_price + (end_price - start_price) * k / steps for k in range(steps))
    while len(prices) < 375:
        prices.append(points[-1][1])
    path = []
    for index, price in enumerate(prices[:375]):
        hh, mm = divmod(9 * 60 + 15 + index, 60)
        path.append((f"{day}T{hh:02d}:{mm:02d}", price, price + 0.01, price - 0.01, price))
    return path


def test_minute_replay_resolves_the_order_inside_an_ambiguous_day() -> None:
    history = _uptrend()
    plan = _plan_for(history)
    entry, stop, target = plan["entry"], plan["stop"], plan["exit"]
    day_bar = (entry + 0.01, target + 0.5, stop - 0.5, entry)
    bars, day = _with_today(history, day_bar)

    open_at = entry - 0.3
    target_first = _session_path(day, [(0, open_at), (60, target + 0.5), (200, stop - 0.5), (374, entry)])
    stop_first = _session_path(
        day, [(0, open_at), (30, entry + 0.3), (60, stop - 0.5), (200, target + 0.5), (374, entry)]
    )

    daily = simulate_symbol(_ITEM, bars, _params(day), Funnel())[0]
    assert daily.ambiguous and daily.day_status == "stopped"

    funnel = Funnel()
    won = simulate_symbol(_ITEM, bars, _params(day), funnel, minutes=lambda _d: target_first)[0]
    assert won.resolution == "minute"
    assert won.day_status == "target"
    assert not won.ambiguous
    # Minutes step past the entry, so the fill is the first print through it, a little above.
    assert won.day_r == pytest.approx(2.0, abs=0.05)
    assert won.fill >= plan["entry"]
    assert funnel.minute_resolved == 1

    lost = simulate_symbol(_ITEM, bars, _params(day), Funnel(), minutes=lambda _d: stop_first)[0]
    assert lost.day_status == "stopped"
    assert lost.swing_status == "stopped"
    assert lost.day_r == pytest.approx(-1.0, abs=0.02)


def test_minute_replay_drops_a_plan_stopped_before_its_entry() -> None:
    history = _uptrend()
    plan = _plan_for(history)
    entry, stop = plan["entry"], plan["stop"]
    bars, day = _with_today(history, (entry - 0.5, entry + 0.5, stop - 0.5, entry))
    path = _session_path(day, [(0, entry - 0.5), (100, stop - 0.5), (300, entry + 0.5), (374, entry)])
    funnel = Funnel()
    assert simulate_symbol(_ITEM, bars, _params(day), funnel, minutes=lambda _d: path) == []
    assert funnel.cancelled_intraday == 1
    assert funnel.filled == 0


def test_a_late_feed_is_not_a_full_session() -> None:
    from app.services.live_scan.backtest import full_session

    day = "2026-11-06"
    path = _session_path(day, [(0, 100.0), (374, 100.0)])
    assert full_session(path)
    assert not full_session(path[80:])


def test_minute_ohlc_round_trips_through_the_store(tmp_path) -> None:
    store = TimelineStore(tmp_path / "m.db")
    store.upsert_live_minute_bars(
        [
            {"instrument_key": "NSE_EQ|X", "minute_ts": "2026-11-06T09:15", "volume": 10, "close_price": 101.0,
             "open_price": 100.0, "high_price": 102.0, "low_price": 99.0},
            {"instrument_key": "NSE_EQ|X", "minute_ts": "2026-11-06T09:16", "volume": 10, "close_price": 101.0},
        ]
    )
    assert store.live_minute_ohlc("NSE_EQ|X", "2026-11-06") == [("2026-11-06T09:15", 100.0, 102.0, 99.0, 101.0)]
    assert store.live_minute_ohlc_dates("2026-11-01", "2026-11-30") == {"2026-11-06"}


def test_a_running_session_is_not_a_finished_day() -> None:
    from datetime import datetime

    from app.services.live_scan.backtest import last_completed_session
    from app.services.live_scan.clocks import IST

    monday = datetime(2026, 11, 9, 14, 0, tzinfo=IST)
    assert last_completed_session(monday) < "2026-11-09"
    assert last_completed_session(monday.replace(hour=16)) == "2026-11-09"


def test_params_are_validated() -> None:
    with pytest.raises(ValueError):
        BacktestParams(start="2026-02-01", end="2026-01-01").checked()
    with pytest.raises(ValueError):
        BacktestParams(start="2026-01-01", end="2026-02-01", segment="index").checked()
    with pytest.raises(ValueError):
        BacktestParams(start="2026-01-01", end="2026-02-01", reward_r=3, swing_r=2).checked()


def test_journal_scorecard_converts_results_to_r() -> None:
    rows = [
        {"session_date": "2026-11-06", "symbol": "A", "side": "buy", "status": "target", "entry": 100.0,
         "fill_price": 100.0, "stop": 98.0, "result_pct": 4.0, "swing_status": "target", "swing_result_pct": 8.0,
         "segment": "fno"},
        {"session_date": "2026-11-06", "symbol": "B", "side": "sell", "status": "stopped", "entry": 50.0,
         "fill_price": 50.0, "stop": 51.0, "result_pct": -2.0, "swing_status": "stopped", "swing_result_pct": -2.0,
         "segment": "cash"},
        {"session_date": "2026-11-08", "symbol": "C", "side": "buy", "status": "cancelled", "entry": 10.0,
         "stop": 9.0, "result_pct": None, "segment": None, "kind": "equity"},
    ]
    card = journal_scorecard(rows, cost_pct=0.0)
    assert card["funnel"] == {"plans": 3, "pending": 0, "open": 0, "cancelled": 1, "resolved": 2}
    assert card["day"]["avg_r"] == pytest.approx(0.5)
    assert card["swing"]["total_r"] == pytest.approx(3.0)
    assert card["sessions"] == 2
    assert journal_scorecard(rows, cost_pct=0.0, segment="cash")["day"]["trades"] == 1


def test_run_backtest_reads_the_store(tmp_path) -> None:
    store = TimelineStore(tmp_path / "bt.db")
    history = _uptrend(40)
    plan_bars = history[:30]
    plan = _plan_for(plan_bars)
    day = history[30][0]
    bars = plan_bars + [(day, plan["entry"] - 0.5, plan["exit"] + 0.1, plan["entry"] - 0.4, plan["exit"])]
    store.upsert_candles(
        [
            {
                "trade_date": bar[0],
                "instrument_token": _ITEM.token,
                "open_price": bar[1],
                "high_price": bar[2],
                "low_price": bar[3],
                "close_price": bar[4],
                "volume": 1000,
                "daily_return_pct": 0.0,
                "source": "upstox",
            }
            for bar in bars
        ]
    )
    result = run_backtest(BacktestParams(start=day, end=day, cost_pct=0.0), store=store, universe=[_ITEM])
    assert result["day"]["trades"] == 1
    assert result["day"]["statuses"] == {"target": 1}
    assert result["curve"]["final_r"] == pytest.approx(2.0)
    assert result["trades"][0]["symbol"] == "TEST"
    assert {group["key"] for group in result["breakdowns"]} >= {"side", "efficiency", "year"}
