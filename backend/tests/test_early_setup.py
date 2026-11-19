"""Setup watchlist: base detection, the daily state machine, the fitted score, live states and alerts."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.db.store import TimelineStore
from app.services.early_setup import repo
from app.services.early_setup.features import FEATURES, add_forward_outcomes, compute_feature_frame
from app.services.early_setup.live import SetupAlerter, rank_watch, rank_watchlist
from app.services.early_setup.model import default_weights, fit, load_weights, save_weights, score_frame, score_row
from app.services.early_setup.report import watchlist_report
from app.services.early_setup.repo import WatchEntry
from app.services.early_setup.watchlist import GRACE_SESSIONS, advance_entry, update_watchlist

RAMP = 170
BASE = 20
PIVOT = 101.0


def _dates(count: int) -> list[str]:
    return [day.date().isoformat() for day in pd.bdate_range("2025-01-01", periods=count)]


def _base_bars(extra: list[tuple[float, float, float, float]] | None = None) -> pd.DataFrame:
    """A steady climb from 80 to 100, then 20 quiet sessions under a 101.0 high."""
    rows: list[dict] = []
    for i in range(RAMP):
        close = 80.0 + 20.0 * i / RAMP
        rows.append({"open": close - 0.1, "high": close + 0.4, "low": close - 0.5, "close": close, "volume": 1_000_000})
    for i in range(BASE):
        close = 99.0 + (0.5 if i % 2 else 0.0)
        high = PIVOT if i == 2 else close + 0.6
        rows.append({"open": close - 0.1, "high": high, "low": close - 0.7, "close": close, "volume": 600_000})
    for open_, high, low, close in extra or []:
        rows.append({"open": open_, "high": high, "low": low, "close": close, "volume": 2_500_000})
    frame = pd.DataFrame(rows)
    frame.insert(0, "date", _dates(len(frame)))
    return frame


def _downtrend_bars() -> pd.DataFrame:
    rows = []
    for i in range(RAMP + BASE):
        close = 200.0 - 0.4 * i
        rows.append({"open": close + 0.1, "high": close + 0.5, "low": close - 0.5, "close": close, "volume": 1_000_000})
    frame = pd.DataFrame(rows)
    frame.insert(0, "date", _dates(len(frame)))
    return frame


# ------------------------------------------------------------------ features


def test_quiet_base_under_its_high_is_a_candidate() -> None:
    frame = compute_feature_frame(_base_bars())
    last = frame.iloc[-1]
    assert bool(last["candidate"]) is True
    assert last["pivot"] == pytest.approx(PIVOT)
    assert 0 < last["dist_to_pivot_pct"] < 3
    assert last["base_low"] < last["close"]
    assert last["vol_dryup"] < 1.0  # base volume is lighter than the climb


def test_breakout_day_and_downtrend_are_not_candidates() -> None:
    broke = compute_feature_frame(_base_bars([(100.0, 103.0, 99.8, 102.5)]))
    assert bool(broke.iloc[-1]["broke_today"]) is True
    assert bool(broke.iloc[-1]["candidate"]) is False
    assert not compute_feature_frame(_downtrend_bars())["candidate"].any()


def test_features_do_not_look_ahead() -> None:
    bars = _base_bars([(100.0, 103.0, 99.8, 102.5), (102.5, 106.0, 102.0, 105.5)])
    full = compute_feature_frame(bars)
    cut = compute_feature_frame(bars.iloc[:-2].reset_index(drop=True))
    at = len(cut) - 1
    for name in (*FEATURES, "pivot", "base_low"):
        left, right = full.iloc[at][name], cut.iloc[at][name]
        assert (pd.isna(left) and pd.isna(right)) or left == pytest.approx(right), name
    assert bool(full.iloc[at]["candidate"]) == bool(cut.iloc[at]["candidate"])


def test_relative_strength_and_oi_use_their_inputs() -> None:
    bars = _base_bars()
    dates = bars["date"].tolist()
    bench = pd.Series(np.linspace(110.0, 100.0, len(dates)), index=dates)  # index falls while the stock climbs
    oi = pd.DataFrame(
        {"oi": np.linspace(1_000.0, 2_000.0, len(dates)), "instrument_key": "FUT1"}, index=dates
    )
    frame = compute_feature_frame(bars, bench_close=bench, oi=oi)
    assert frame.iloc[-1]["rs_pctile"] > 0.5
    assert frame.iloc[-1]["oi_build"] > 0  # OI grew while price sat still
    rolled = oi.copy()
    rolled.loc[dates[-3:], "instrument_key"] = "FUT2"
    assert pd.isna(compute_feature_frame(bars, oi=rolled).iloc[-1]["oi_build"])


def test_forward_outcomes_fill_at_pivot_or_gap_open() -> None:
    held = [(100.0, 103.0, 99.8, 102.5)] + [(103.0, 104.5, 102.5, 104.0)] * 12
    frame = add_forward_outcomes(compute_feature_frame(_base_bars(held)))
    row = frame.iloc[RAMP + BASE - 1]
    assert row["label"] == 1.0
    assert row["trigger_offset"] == 1.0
    assert row["fill"] == pytest.approx(PIVOT)  # opened under the pivot, so the stop-entry fills at it
    assert row["trigger_close"] == pytest.approx(102.5)
    assert row["fwd5_pct"] == pytest.approx((104.0 / PIVOT - 1.0) * 100.0)

    gapped = [(102.0, 103.0, 101.5, 102.5)] + [(103.0, 104.5, 102.5, 104.0)] * 6
    row = add_forward_outcomes(compute_feature_frame(_base_bars(gapped))).iloc[RAMP + BASE - 1]
    assert row["fill"] == pytest.approx(102.0)  # gap over the pivot fills at the open, not at the pivot

    faded = [(100.0, 101.4, 99.0, 99.2)] + [(99.2, 99.9, 98.6, 99.0)] * 6
    row = add_forward_outcomes(compute_feature_frame(_base_bars(faded))).iloc[RAMP + BASE - 1]
    assert row["label"] == 0.0  # poked through, never held 2% above
    assert row["trigger_offset"] == 1.0

    # The newest rows have no complete horizon, so they stay unlabelled.
    assert pd.isna(add_forward_outcomes(compute_feature_frame(_base_bars())).iloc[-1]["label"])


# ------------------------------------------------------------- state machine


def _entry(**changes) -> WatchEntry:
    values = dict(ticker="AAA", pivot=101.0, stop=98.0, first_seen="2025-09-01", last_seen="2025-09-01",
                  last_checked="2025-09-01", last_close=99.5, score=30.0, first_score=30.0, dirty=False)
    values.update(changes)
    return WatchEntry(**values)


def _bar(open_, high, low, close, *, candidate=True, pivot=101.0, base_low=98.0) -> dict:
    row = {name: np.nan for name in FEATURES}
    row.update(open=open_, high=high, low=low, close=close, candidate=candidate, pivot=pivot, base_low=base_low,
               dist_to_pivot_pct=(pivot - close) / pivot * 100.0)
    return row


def test_entry_triggers_when_the_high_crosses_the_pivot() -> None:
    entry = _entry()
    advance_entry(entry, _bar(100.0, 102.0, 99.5, 101.6), "2025-09-02", default_weights())
    assert (entry.status, entry.resolved_date) == ("triggered", "2025-09-02")
    assert entry.resolved_price == pytest.approx(101.0)
    assert entry.resolved_close == pytest.approx(101.6)

    gap = _entry()
    advance_entry(gap, _bar(102.4, 103.0, 102.0, 102.8), "2025-09-02", default_weights())
    assert gap.resolved_price == pytest.approx(102.4)


def test_entry_fails_under_the_stop_even_if_it_later_spikes() -> None:
    entry = _entry()
    advance_entry(entry, _bar(97.5, 101.5, 97.0, 100.0), "2025-09-02", default_weights())
    assert entry.status == "failed"  # opened under the stop: the base broke first
    closed_under = _entry()
    advance_entry(closed_under, _bar(99.0, 99.4, 97.2, 97.6), "2025-09-02", default_weights())
    assert closed_under.status == "failed"


def test_entry_refreshes_then_expires_after_drifting_out() -> None:
    entry = _entry()
    advance_entry(entry, _bar(99.5, 100.4, 99.0, 100.0, pivot=100.8, base_low=98.6), "2025-09-02", default_weights())
    assert entry.status == "active"
    assert (entry.pivot, entry.stop, entry.days_in_base, entry.last_seen) == (100.8, 98.6, 2, "2025-09-02")
    for offset in range(GRACE_SESSIONS + 1):
        advance_entry(entry, _bar(99.0, 99.6, 98.8, 99.2, candidate=False), f"2025-09-{3 + offset:02d}", default_weights())
    assert entry.status == "expired"
    assert entry.last_seen == "2025-09-02"


def test_entry_ignores_a_bar_it_already_saw() -> None:
    entry = _entry()
    advance_entry(entry, _bar(100.0, 102.0, 99.5, 101.6), "2025-09-01", default_weights())
    assert entry.status == "active" and entry.dirty is False


# ---------------------------------------------------------------- end to end


def _store_with(tmp_path, tickers: dict[str, pd.DataFrame]) -> TimelineStore:
    store = TimelineStore(tmp_path / "setups.db")
    store.upsert_profiles(
        [{"instrument_token": f"NSE_EQ|{name}", "ticker": name, "company_name": f"{name} Ltd", "sector": "Tech"} for name in tickers]
    )
    _add_bars(store, tickers)
    return store


def _add_bars(store: TimelineStore, tickers: dict[str, pd.DataFrame]) -> None:
    candles = []
    for name, frame in tickers.items():
        for row in frame.to_dict("records"):
            candles.append(
                {"trade_date": row["date"], "instrument_token": f"NSE_EQ|{name}", "open_price": row["open"],
                 "high_price": row["high"], "low_price": row["low"], "close_price": row["close"], "volume": row["volume"]}
            )
    store.upsert_candles(candles)


def test_watchlist_lists_the_base_then_marks_the_breakout(tmp_path) -> None:
    quiet = _base_bars()
    store = _store_with(tmp_path, {"BASE": quiet, "FADE": quiet, "DOWN": _downtrend_bars()})

    first = update_watchlist(store=store)
    assert first["status"] == "updated"
    active = {entry.ticker: entry for entry in repo.list_entries(status="active", timeframe="daily", store=store)}
    assert set(active) == {"BASE", "FADE"}
    assert active["BASE"].pivot == pytest.approx(PIVOT)
    assert active["BASE"].score is not None

    assert update_watchlist(store=store)["status"] == "current"  # rerun on the same day changes nothing
    assert len(repo.list_entries(status=None, timeframe="daily", store=store)) == 2

    # Two more sessions arrive before the next run: BASE breaks out on the second, FADE loses its low on the first.
    next_days = _dates(RAMP + BASE + 2)[-2:]
    more_base = pd.DataFrame(
        [{"date": next_days[0], "open": 99.4, "high": 100.2, "low": 99.0, "close": 99.8, "volume": 600_000},
         {"date": next_days[1], "open": 100.0, "high": 103.0, "low": 99.8, "close": 102.5, "volume": 2_500_000}]
    )
    more_fade = pd.DataFrame(
        [{"date": next_days[0], "open": 98.8, "high": 99.0, "low": 96.0, "close": 96.4, "volume": 2_000_000},
         {"date": next_days[1], "open": 96.4, "high": 97.0, "low": 95.5, "close": 96.0, "volume": 900_000}]
    )
    down = _downtrend_bars()
    more_down = pd.DataFrame(
        [{"date": day, "open": 120.0, "high": 120.5, "low": 119.5, "close": 120.0, "volume": 1_000_000} for day in next_days]
    )
    assert len(down)  # DOWN keeps trading so the sessions count as full
    _add_bars(store, {"BASE": more_base, "FADE": more_fade, "DOWN": more_down})

    second = update_watchlist(store=store)
    assert second["sessions"] == 2  # the missed session was replayed, not skipped
    by_ticker = {entry.ticker: entry for entry in repo.list_entries(status=None, timeframe="daily", store=store)}
    assert by_ticker["BASE"].status == "triggered"
    assert by_ticker["BASE"].resolved_date == next_days[1]
    assert by_ticker["BASE"].resolved_price == pytest.approx(by_ticker["BASE"].pivot)
    assert by_ticker["BASE"].days_in_base == 2
    assert (by_ticker["FADE"].status, by_ticker["FADE"].resolved_date) == ("failed", next_days[0])

    report = watchlist_report(store=store)
    assert report["counts"] == {"active": 0, "triggered": 1, "failed": 1, "expired": 0}
    assert report["pivot_crossed_pct"] == 50.0
    assert report["held_above_pivot_pct"] == 50.0
    assert report["after_breakout"]["avg_lead_pct"] == pytest.approx((102.5 / PIVOT - 1.0) * 100.0, abs=0.01)
    assert report["median_sessions_to_cross"] == 2.0


def test_rebuild_replays_history_into_the_same_result(tmp_path) -> None:
    bars = _base_bars([(100.0, 103.0, 99.8, 102.5)])
    store = _store_with(tmp_path, {"BASE": bars, "DOWN": _downtrend_bars().assign(date=_dates(RAMP + BASE))})
    start = bars["date"].iloc[RAMP + 10]
    result = update_watchlist(from_date=start, rebuild=True, store=store)
    assert result["status"] == "updated" and result["sessions"] > 5
    entries = repo.list_entries(status=None, timeframe="daily", store=store)
    assert [entry.status for entry in entries if entry.ticker == "BASE"] == ["triggered"]
    again = update_watchlist(from_date=start, rebuild=True, store=store)
    assert again["counts"] == result["counts"]


def test_empty_database_reports_no_data(tmp_path) -> None:
    assert update_watchlist(store=TimelineStore(tmp_path / "empty.db"))["status"] == "no_data"


# ------------------------------------------------------------------- scoring


def test_leaders_in_a_hot_group_and_a_healthy_market_score_higher() -> None:
    weights = default_weights()
    good = score_row({"pct_from_52w_high": 2.0, "group_heat": 15.0, "market_breadth": 75.0, "sector_accel": -2.0}, weights)
    poor = score_row({"pct_from_52w_high": 35.0, "group_heat": -8.0, "market_breadth": 35.0, "sector_accel": 4.0}, weights)
    assert good["score"] > 60 > 40 > poor["score"]
    assert good["contributions"]["pct_from_52w_high"] > 0 > poor["contributions"]["pct_from_52w_high"]
    assert score_row({}, weights)["score"] == 50.0  # nothing known scores as the average setup
    # Readings that flipped between periods in the real data carry no weight until a fit says otherwise.
    assert score_row({"tightness_pctile": 0.01, "vol_dryup": 0.2}, weights)["score"] == 50.0


def test_row_and_frame_scores_agree() -> None:
    frame = compute_feature_frame(_base_bars())
    weights = default_weights()
    last = frame.iloc[-1]
    assert score_frame(frame.tail(1), weights).iloc[0] == pytest.approx(score_row(last, weights)["score"], abs=0.06)


def _synthetic_dataset(rows: int = 4000, signal: float = 1.0) -> pd.DataFrame:
    """Trades whose result depends on two features and on nothing else."""
    rng = np.random.default_rng(7)
    data = {name: rng.normal(size=rows) for name in FEATURES}
    data["trade_ret_pct"] = signal * (-1.2 * data["dist_to_pivot_pct"] + 0.8 * data["rs_pctile"]) + rng.normal(scale=4.0, size=rows)
    frame = pd.DataFrame(data)
    days = _dates(200)
    frame["date"] = [days[i * 200 // rows] for i in range(rows)]
    return frame


def test_fit_recovers_the_signal_and_reports_held_out_numbers(tmp_path) -> None:
    weights = fit(_synthetic_dataset())
    features = weights["features"]
    assert features["dist_to_pivot_pct"]["weight"] < -0.8
    assert features["rs_pctile"]["weight"] > 0.5
    assert abs(features["vol_dryup"]["weight"]) < 0.25  # noise stays near zero
    metrics = weights["metrics"]
    assert metrics["train_to"] < metrics["test_from"]  # split by date, no overlap
    test = metrics["test"]
    assert test["verdict"] == "ranks"
    assert test["top_fifth"]["avg_pct"] > test["rest"]["avg_pct"]
    assert test["spread_low_pct"] > 0

    path = save_weights(weights, "2026-01-01T00:00:00+00:00", tmp_path / "weights.json")
    loaded = load_weights(path)
    assert loaded["fitted"] is True
    assert loaded["features"]["rs_pctile"]["weight"] == pytest.approx(features["rs_pctile"]["weight"])
    assert loaded["spread"] == pytest.approx(weights["spread"])
    assert load_weights(tmp_path / "missing.json")["fitted"] is False

    # A score of 50 is the average setup, and the two paths to a score agree.
    data = _synthetic_dataset()
    scores = score_frame(data, weights)
    assert 45 < scores.mean() < 55
    assert scores.iloc[0] == pytest.approx(score_row(data.iloc[0], weights)["score"], abs=0.06)


def test_fit_finds_nothing_in_noise_and_says_so() -> None:
    weights = fit(_synthetic_dataset(signal=0.0))
    assert weights["metrics"]["test"]["verdict"] == "no_evidence"  # the interval straddles zero


def test_weights_file_from_before_a_feature_was_added_still_loads(tmp_path) -> None:
    import json

    weights = fit(_synthetic_dataset())
    del weights["features"]["group_heat"]
    path = tmp_path / "old.json"
    path.write_text(json.dumps(weights))
    loaded = load_weights(path)
    assert loaded["fitted"] is True
    assert loaded["features"]["group_heat"]["weight"] == 0.0


def test_fit_refuses_too_little_data() -> None:
    with pytest.raises(ValueError, match="At least 500"):
        fit(_synthetic_dataset(rows=200))


# ---------------------------------------------------------------------- live


def _quote(ltp: float, **changes) -> dict:
    quote = {"symbol": "AAA", "company_name": "AAA Ltd", "ltp": ltp, "watch_pivot": 101.0, "watch_stop": 98.0,
             "watch_score": 42.0, "watch_days": 6, "day_open": 99.5, "day_high": max(ltp, 99.8), "atr_pct": 2.0,
             "vtt": 500_000.0, "avg_volume_20": 1_000_000.0, "segment": "cash", "last_tick_at": 1000.0}
    quote.update(changes)
    return quote


@pytest.mark.parametrize(
    ("quote", "progress", "state"),
    [
        (_quote(98.5), 0.5, "waiting"),
        (_quote(99.6), 0.5, "near"),
        (_quote(100.9), 0.5, "testing"),
        (_quote(101.5), 0.25, "breakout"),  # 500k traded against 250k expected: 2× pace
        (_quote(101.5), 0.9, "crossed_light"),  # same volume late in the day is light
        (_quote(101.5, avg_volume_20=None), 0.25, "crossed_light"),  # unknown pace is not confirmation
        (_quote(103.5, day_open=103.0), 0.25, "gapped"),
        (_quote(104.5), 0.25, "extended"),
        (_quote(97.9), 0.5, "failed"),
    ],
)
def test_live_state_against_the_pivot(quote: dict, progress: float, state: str) -> None:
    row = rank_watch(quote, progress)
    assert row is not None and row["state"] == state


def test_stocks_off_the_watchlist_are_left_out_and_urgent_rows_come_first() -> None:
    assert rank_watch(_quote(100.0, watch_pivot=None), 0.5) is None
    rows = rank_watchlist(
        [_quote(98.5, symbol="FAR"), _quote(101.5, symbol="BREAK"), _quote(100.9, symbol="TEST"), {"symbol": "X", "ltp": 5.0}],
        0.25,
    )
    assert [row["symbol"] for row in rows] == ["BREAK", "TEST", "FAR"]
    assert rank_watch(_quote(100.9), 0.5, now=1100.0)["stale"] is True


def test_alerter_sends_each_state_once_per_session() -> None:
    sent: list[str] = []
    alerter = SetupAlerter("2026-11-17", sender=lambda text: sent.append(text) or True, persist=False)
    testing = rank_watch(_quote(100.9), 0.5)
    breakout = rank_watch(_quote(101.5), 0.25)

    assert alerter.observe([testing], tradable=False) == []  # outside market hours
    assert [alert["state"] for alert in alerter.observe([testing], tradable=True)] == ["testing"]
    assert alerter.observe([testing], tradable=True) == []
    assert [alert["state"] for alert in alerter.observe([breakout], tradable=True)] == ["breakout"]
    assert alerter.observe([breakout, testing], tradable=True) == []
    assert alerter.observe([rank_watch(_quote(99.0), 0.5)], tradable=True) == []  # "near" is not an alert

    alerter.start()
    alerter.stop()
    assert len(sent) == 2 and alerter.delivered == 2
    assert "AAA" in sent[0] and "pivot 101.00" in sent[0]


def test_alerter_skips_stale_quotes_and_restores_what_was_sent() -> None:
    alerter = SetupAlerter("2026-11-17", sender=lambda text: True, seen={("AAA", "breakout")}, persist=False)
    assert alerter.observe([rank_watch(_quote(101.5), 0.25)], tradable=True) == []  # sent before a restart
    assert alerter.observe([rank_watch(_quote(100.9), 0.5)], tradable=True) == []  # testing after a break is noise
    stale = rank_watch(_quote(97.9, symbol="BBB"), 0.5, now=5000.0)
    assert alerter.observe([stale], tradable=True) == []


def test_alerts_are_recorded_once(tmp_path) -> None:
    store = TimelineStore(tmp_path / "alerts.db")
    alert = {"session_date": "2026-11-17", "ticker": "AAA", "state": "breakout", "price": 101.5, "pivot": 101.0,
             "stop": 98.0, "session_rvol": 2.0, "message": "AAA — Breaking out on volume"}
    assert repo.record_alert(alert, store) is True
    assert repo.record_alert(alert, store) is False
    repo.mark_alert_delivered("2026-11-17", "AAA", "breakout", store)
    rows = repo.list_alerts(session_date="2026-11-17", store=store)
    assert len(rows) == 1 and rows[0]["delivered"] == 1
    assert repo.alert_keys("2026-11-17", store) == {("AAA", "breakout")}


# ------------------------------------------------------------- review fixes


def test_update_stops_at_the_last_completed_session(tmp_path, monkeypatch) -> None:
    bars = _base_bars()
    store = _store_with(tmp_path, {"BASE": bars, "DOWN": _downtrend_bars()})
    yesterday, today = bars["date"].iloc[-2], bars["date"].iloc[-1]
    # The newest bar belongs to a session that is still trading.
    monkeypatch.setattr("app.services.live_scan.clocks.required_daily_session", lambda *args: yesterday)
    assert update_watchlist(store=store)["processed_through"] == yesterday
    # After the close the same bar is final and gets processed once.
    monkeypatch.setattr("app.services.live_scan.clocks.required_daily_session", lambda *args: today)
    assert update_watchlist(store=store)["processed_through"] == today
    assert update_watchlist(through=today, store=store)["status"] == "current"


def test_exit_rules_never_flatter_the_trade() -> None:
    from app.services.early_setup.trades import simulate_exit

    #        day0   day1   day2   day3
    opens = [100.0, 101.0, 96.0, 97.0]
    highs = [101.6, 101.5, 97.0, 98.0]
    lows = [99.0, 100.5, 95.0, 96.5]
    closes = [101.5, 101.0, 95.5, 97.5]
    flat = [100.0] * 20

    def run(rule: str, stop: float, **kw):
        return simulate_exit(rule, opens + flat, highs + flat, lows + flat, closes + flat, 0, 101.0, stop, **kw)

    assert run("hold5", 97.0) == (96.0, 2, "stop")  # gap under the stop exits at the open, not the stop
    assert run("hold5", 99.5) == (99.5, 0, "stop")  # entry-day low under the stop counts as stopped
    assert run("hold5", 90.0) == (100.0, 5, "time")
    assert run("hold10", 90.0) == (100.0, 10, "time")
    # Twice the risk above the fill: 101 + 2 × 0.4 = 101.8. Never reached, so the stop on day 1 decides.
    assert run("target2r", 100.6) == (100.6, 0, "stop")
    assert simulate_exit("target2r", [100.0, 103.0], [101.2, 104.0], [100.9, 102.5], [101.1, 103.5], 0, 101.0, 100.5) == (103.0, 1, "target")
    # Trailing: out on the first close under the average, never on the entry day itself.
    average = np.array([200.0, 100.0, 100.0, 100.0] + [100.0] * 20)
    assert run("trail10", 90.0, average=average) == (95.5, 2, "trail")
    # Too few bars after the entry: no result yet, not a guess.
    assert simulate_exit("hold5", opens, highs, lows, closes, 0, 101.0, 90.0) is None
    assert simulate_exit("hold5", opens, highs, lows, closes, 0, 101.0, 97.0) == (96.0, 2, "stop")  # but a stop already hit is known


def test_account_view_caps_positions_and_takes_the_best_scores() -> None:
    from app.services.early_setup.trades import portfolio

    trades = [
        {"entry": 0, "exit": 5, "ret_pct": 10.0, "score": 90.0},
        {"entry": 0, "exit": 5, "ret_pct": -50.0, "score": 10.0},  # same day, lower score: no free slot
        {"entry": 6, "exit": 8, "ret_pct": -10.0, "score": 50.0},
    ]
    result = portfolio(trades, max_positions=1)
    assert (result["trades_taken"], result["skipped"]) == (2, 1)
    assert result["return_pct"] == pytest.approx((1.10 * 0.90 - 1.0) * 100.0, abs=0.01)
    assert result["max_drawdown_pct"] == pytest.approx(-10.0, abs=0.01)
    assert portfolio(trades, max_positions=2)["trades_taken"] == 3
    assert portfolio([], max_positions=5)["return_pct"] is None


def test_report_compares_exit_rules_after_costs(tmp_path) -> None:
    held = [(100.0, 103.0, 99.8, 102.5)] + [(103.0, 104.5, 102.5, 104.0)] * 12
    bars = _base_bars(held)
    store = _store_with(tmp_path, {"BASE": bars, "DOWN": _downtrend_bars().assign(date=_dates(RAMP + BASE))})
    update_watchlist(through=bars["date"].iloc[-1], from_date=bars["date"].iloc[RAMP + BASE - 1], rebuild=True, store=store)
    report = watchlist_report(cost_pct=0.25, store=store)
    exits = {row["rule"]: row for row in report["exits"]}
    assert exits["hold5"]["avg_pct"] == pytest.approx((104.0 / PIVOT - 1.0) * 100.0 - 0.25, abs=0.01)
    assert exits["hold10"]["trades"] == 1 and exits["hold10"]["stopped_pct"] == 0.0
    assert exits["target2r"]["trades"] == 1
    assert exits["trail20"]["still_open"] == 1  # 12 sessions is not enough to finish a trailing exit
    assert exits["hold5"]["portfolio"]["trades_taken"] == 1
    assert report["main_rule"] == "hold10"
    assert {row["state"] for row in report["by_health"]} == {"green", "amber", "red"}
    assert sum(row["trades"] for row in report["by_health"]) == 1  # the trade is filed under the evening-before state
    assert watchlist_report(timeframe="weekly", store=store)["timeframe"] == "weekly"


# ------------------------------------------------------------------- filings


def _announcement(seq: str, symbol: str, subject: str, text: str, at: str = "18-Nov-2026 10:15:00") -> dict:
    return {"seq_id": seq, "symbol": symbol, "sm_name": f"{symbol} Limited", "desc": subject, "attchmntText": text,
            "an_dt": at, "exchdisstime": at, "attchmntFile": f"https://example.invalid/{seq}.pdf"}


@pytest.mark.parametrize(
    ("subject", "text", "category"),
    [
        ("Bagging/Receiving of orders or contracts", "has received an order worth Rs 450 crore", "orders"),
        ("Updates", "The Company has received a Letter of Award from NHAI", "orders"),
        ("Outcome of Board Meeting", "approved the unaudited financial results for the quarter", "results"),
        ("Outcome of Board Meeting", "approved raising of funds through QIP", "capital"),
        ("Outcome of Board Meeting", "took note of the minutes", "board"),
        ("Acquisition", "acquisition of 51% stake in XYZ Private Limited", "deal"),
        ("Disclosure under SEBI Takeover Regulations", "Substantial Acquisition of Shares and Takeovers", "stake"),
        ("Credit Rating", "CRISIL has reaffirmed the rating", "rating"),
        ("Declaration of NAV", "NAV as on date", None),
        ("Copy of Newspaper Publication", "financial results published in newspapers", None),
        ("Analysts/Institutional Investor Meet/Con. Call Updates", "schedule of meeting on acquisition", None),
        ("General Updates", "change in the name of the registrar's office", None),
        ("Corporate Insolvency Resolution Process", "intimation of the upcoming 67th meeting of the Committee of Creditors", None),
        ("Corporate Insolvency Resolution Process", "NCLT order for commencement of liquidation", "regulatory"),
    ],
)
def test_filings_are_sorted_into_news_and_paperwork(subject: str, text: str, category) -> None:
    from app.services.early_setup.filings import classify

    assert classify(subject, text) == category


def test_fresh_filing_on_a_watchlist_stock_alerts_once(tmp_path) -> None:
    from datetime import datetime

    from app.services.early_setup.filings import ingest, parse_announcement
    from app.services.live_scan.clocks import IST

    store = TimelineStore(tmp_path / "filings.db")
    repo.save_entries([_entry(ticker="AAA", dirty=True)], store)
    rows = [
        _announcement("1", "AAA", "Bagging/Receiving of orders or contracts", "received an order worth Rs 450 crore"),
        _announcement("2", "BBB", "Acquisition", "acquisition of a 51% stake"),  # not on the watchlist
        _announcement("3", "AAA", "Declaration of NAV", "nav"),  # paperwork
        _announcement("4", "AAA", "Credit Rating", "rating reaffirmed", at="18-Nov-2026 08:00:00"),  # hours old
        {"seq_id": "5", "symbol": "AAA", "desc": "Acquisition", "an_dt": "not a date"},  # malformed
    ]
    assert parse_announcement(rows[0])["filed_at"] == "2026-11-18T10:15:00+05:30"
    sent: list[str] = []
    now = datetime(2026, 11, 18, 10, 16, tzinfo=IST)

    result = ingest(rows, now=now, store=store, sender=lambda text: sent.append(text) or True, scope="watchlist")
    assert result == {"seen": 5, "material": 3, "new": 3, "alerted": 1}
    assert "AAA — Filing: Order win" in sent[0] and "pivot 101.00" in sent[0]

    again = ingest(rows, now=now, store=store, sender=lambda text: sent.append(text) or True, scope="watchlist")
    assert again["new"] == 0 and len(sent) == 1  # the same filing never alerts twice

    stored = {row["seq_id"]: row for row in repo.list_filings(since="2026-11-18T00:00:00+05:30", store=store)}
    assert set(stored) == {"1", "2", "4"}
    assert (stored["1"]["alerted"], stored["1"]["delivered"], stored["4"]["alerted"]) == (1, 1, 0)
    assert repo.known_filing_ids(["1", "3", "9"], store) == {"1"}

    everything = ingest(
        [_announcement("6", "CCC", "Acquisition", "acquisition of a plant")], now=now, store=store,
        sender=lambda text: sent.append(text) or False, scope="all",
    )
    assert everything["alerted"] == 1 and "On the setup watchlist" not in sent[-1]


def test_events_are_parsed_and_looked_up_by_date(tmp_path) -> None:
    from app.services.early_setup.filings import parse_event

    store = TimelineStore(tmp_path / "events.db")
    event = parse_event({"symbol": "M&M", "date": "20-Nov-2026", "purpose": "Financial Results", "bm_desc": "results"})
    assert event == {"ticker": "M_M", "event_date": "2026-11-20", "purpose": "Financial Results", "detail": "results"}
    assert parse_event({"symbol": "AAA", "date": "soon"}) is None
    repo.save_events([event, event], store)
    assert list(repo.upcoming_events("2026-11-18", "2026-11-23", store)) == ["M_M"]
    assert repo.upcoming_events("2026-11-21", "2026-11-25", store) == {}


# ------------------------------------------------------------ NSE data files

BHAV = """SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER
AAA, EQ, 18-Nov-2026, 100.00, 101.00, 103.00, 99.50, 102.40, 102.50, 101.80, 500000, 5090.00, 12000, 260000, 52.00
M&M, EQ, 18-Nov-2026, 3000.00, 3010.00, 3050.00, 2990.00, 3040.00, 3042.00, 3020.00, 900000, 27180.00, 40000, 540000, 60.00
BBB, BE, 18-Nov-2026, 50.16, 50.16, 50.16, 47.82, 47.90, 47.90, 48.32, 3068, 1.48, 44, -, -
1018GS2026, GS, 18-Nov-2026, 110.02, 113.85, 113.85, 113.85, 113.85, 113.85, 113.85, 100, 0.11, 1, 100, 100.00
"""
INDEX_CLOSE = """Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Points Change,Change(%),Volume
Nifty 50,18-11-2026,25323.15,25390.8,25141.8,25227.95,-159.45,-0.63,1
Nifty Bank,18-11-2026,57000,57100,56800,56900,-10,-0.02,1
"""


def test_daily_price_file_is_parsed_with_delivery() -> None:
    from app.services.early_setup import nse

    day, rows = nse.parse_bhavcopy(BHAV)
    assert day == "2026-11-18"
    by = {row["ticker"]: row for row in rows}
    assert set(by) == {"AAA", "M_M", "BBB"}  # government securities are left out; M&M takes its internal name
    assert (by["AAA"]["close"], by["AAA"]["volume"], by["AAA"]["deliv_pct"]) == (102.5, 500000.0, 52.0)
    assert by["BBB"]["deliv_pct"] is None  # trade-for-trade is all delivery by rule, so its share says nothing
    assert nse.parse_index_close(INDEX_CLOSE)["close"] == 25227.95
    assert nse.parse_index_close(INDEX_CLOSE, "Nifty Midcap 100") is None
    assert nse.is_data(BHAV) and not nse.is_data("<html>Access Denied</html>") and not nse.is_data(None)


def test_large_deals_separate_churn_from_one_sided_buys(tmp_path) -> None:
    from app.services.early_setup import nse

    text = (
        "Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n"
        "18-NOV-2026,AAA,AAA Ltd,FAST TRADER LLP,BUY,1000000,114.03,-\n"
        "18-NOV-2026,AAA,AAA Ltd,FAST  TRADER LLP,SELL,1000000,114.10,-\n"
        "18-NOV-2026,AAA,AAA Ltd,PATIENT FUND,BUY,400000,113.50,-\n"
        "18-NOV-2026,BBB,BBB Ltd,PATIENT FUND,SELL,90000,40.00,-\n"
    )
    deals = nse.mark_churn(nse.parse_deals(text, "bulk"))
    assert [deal["churn"] for deal in deals] == [1, 1, 0, 0]  # the same client on both sides is in-and-out trading
    assert nse.parse_deals("Date,Symbol\nNO RECORDS,\n", "block") == []
    store = TimelineStore(tmp_path / "deals.db")
    repo.save_deals(deals, store)
    repo.save_deals(deals, store)  # loading the same file twice changes nothing
    buys = repo.one_sided_buys("2026-11-01", store)
    assert list(buys) == ["AAA"] and buys["AAA"][0]["client"] == "PATIENT FUND"


@pytest.mark.parametrize(
    ("subject", "kind", "factor"),
    [
        ("Bonus 1:1", "bonus", 0.5),
        ("Bonus 3:2", "bonus", 0.4),
        ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", "split", 0.2),
        ("Face Value Split (Sub-Division) - From Rs 5/- Per Share To Re 1/- Per Share", "split", 0.2),
        ("Scheme Of Arrangement - Bonus Ncrps 46:1", "bonus", None),  # preference shares: the price does not change
        ("Interim Dividend - Rs 150 Per Share", "dividend", None),
        ("Annual General Meeting", "other", None),
    ],
)
def test_corporate_action_factor(subject: str, kind: str, factor) -> None:
    from app.services.early_setup.nse import action_factor

    found_kind, found = action_factor(subject)
    assert found_kind == kind
    assert found == (pytest.approx(factor) if factor is not None else None)


def test_reference_lists_are_parsed() -> None:
    from app.services.early_setup import nse

    assert nse.parse_ban("Securities in Ban For Trade Date 19-NOV-2026:\n1,KAYNES\n2,M&M\n") == [
        {"ticker": "KAYNES", "flag": "fo_ban", "detail": "In the F&O ban"},
        {"ticker": "M_M", "flag": "fo_ban", "detail": "In the F&O ban"},
    ]
    asm = nse.parse_asm({"longterm": {"data": [{"symbol": "AAA", "asmSurvIndicator": "Stage I"}]}, "shortterm": {"data": []}})
    assert asm == [{"ticker": "AAA", "flag": "asm_long", "detail": "Long-term surveillance Stage I"}]
    assert nse.parse_industries("Company Name,Industry,Symbol,Series,ISIN Code\nAAA Ltd,Chemicals,AAA,EQ,INE0\n") == [
        {"ticker": "AAA", "industry": "Chemicals", "company_name": "AAA Ltd"}
    ]
    actions = nse.parse_actions([{"symbol": "AAA", "series": "EQ", "exDate": "04-Nov-2026", "subject": "Bonus 1:1"}, {"symbol": "X"}])
    assert actions == [{"ticker": "AAA", "ex_date": "2026-11-04", "subject": "Bonus 1:1", "kind": "bonus", "factor": 0.5}]


def test_one_day_of_history_loads_once_and_never_overwrites(tmp_path) -> None:
    from datetime import date

    from app.services.early_setup import market_data, nse

    class FakeNse:
        async def text(self, url: str) -> str | None:
            # NSE answers any date with its latest file, as it does for a holiday.
            return INDEX_CLOSE if "ind_close_all" in url else BHAV

    store = TimelineStore(tmp_path / "day.db")
    store.upsert_profiles([{"instrument_token": f"NSE_EQ|{name}", "ticker": name} for name in ("AAA", "M_M")])
    load = lambda day: nse.run(market_data._load_day(FakeNse(), day, repo.ensure_schema(store), candles=True, index=True))
    assert load(date(2026, 11, 18)) == {"delivery": 2, "candles": 2, "index": 1}
    assert load(date(2026, 11, 18)) == {"delivery": 2, "candles": 0, "index": 0}  # nothing is written twice
    assert load(date(2026, 11, 15)) is None  # the file's own date is another day: not this session's data
    assert repo.delivery_days(store) == {"2026-11-18"}
    assert repo.load_delivery("2026-11-01", "2026-11-30", store)["AAA"].to_dict() == {"2026-11-18": 52.0}
    assert repo.index_days(store) == {"2026-11-18"}
    assert repo.load_benchmark("2026-11-01", "2026-11-30", store).to_dict() == {"2026-11-18": 25227.95}


# ------------------------------------------------ splits, bonuses and breaks


def _long(tickers: dict[str, list[tuple[float, float]]]) -> pd.DataFrame:
    """(open, close) pairs per ticker as the long candle frame the loaders return."""
    rows = []
    for ticker, bars in tickers.items():
        for day, (open_, close) in zip(_dates(len(bars)), bars):
            rows.append({"ticker": ticker, "date": day, "open": open_, "high": max(open_, close) + 1, "low": min(open_, close) - 1, "close": close, "volume": 1000.0})
    return pd.DataFrame(rows)


def test_bonus_is_adjusted_only_where_the_prices_are_raw() -> None:
    from app.services.early_setup.candles import adjust_for_actions

    days = _dates(4)
    raw = _long({"RAW": [(200.0, 202.0), (202.0, 204.0), (101.0, 103.0), (103.0, 104.0)],
                 "DONE": [(100.0, 101.0), (101.0, 102.0), (101.0, 103.0), (103.0, 104.0)]})
    actions = [{"ticker": name, "ex_date": days[2], "factor": 0.5} for name in ("RAW", "DONE", "MISSING")]
    adjusted, applied = adjust_for_actions(raw, actions)
    assert applied == 1  # DONE shows no jump on the ex-date, so it is already adjusted
    fixed = adjusted[adjusted["ticker"] == "RAW"]
    assert fixed["close"].tolist() == [101.0, 102.0, 103.0, 104.0]
    assert fixed["volume"].tolist() == [2000.0, 2000.0, 1000.0, 1000.0]  # twice the shares before the bonus
    assert adjusted[adjusted["ticker"] == "DONE"]["close"].tolist() == [101.0, 102.0, 103.0, 104.0]
    # A small bonus (1:10) on already-adjusted prices must not be applied a second time.
    assert adjust_for_actions(_long({"X": [(100.0, 100.0), (100.0, 101.0)]}), [{"ticker": "X", "ex_date": days[1], "factor": 10 / 11}])[1] == 0


def test_unlisted_price_breaks_are_closed() -> None:
    from app.services.early_setup.candles import heal_breaks, market_proxy

    frame = _long({"DEMERGED": [(300.0, 300.0), (300.0, 306.0), (150.0, 153.0), (153.0, 154.0)],
                   "NORMAL": [(100.0, 100.0), (100.0, 95.0), (88.0, 90.0), (90.0, 91.0)]})
    healed, breaks = heal_breaks(frame)
    assert breaks == 1  # a 12% fall is a market move and is left alone
    assert healed[healed["ticker"] == "DEMERGED"]["close"].round(2).tolist() == [147.06, 150.0, 153.0, 154.0]
    assert healed[healed["ticker"] == "NORMAL"]["close"].tolist() == [100.0, 95.0, 90.0, 91.0]
    proxy = market_proxy(healed)
    assert len(proxy) == 3 and proxy.iloc[-1] > 0


def test_entry_made_before_a_split_follows_the_new_price_scale() -> None:
    from app.services.early_setup.watchlist import _match_price_scale

    frame = pd.DataFrame({"date": ["2025-09-01"], "close": [49.75]}).set_index("date", drop=False)
    entry = _entry(pivot=101.0, stop=98.0, last_close=99.5, last_checked="2025-09-01")
    _match_price_scale(entry, frame)  # history was halved by a 1:1 bonus after the entry was stored
    assert (entry.pivot, entry.stop, entry.last_close) == (50.5, 49.0, 49.75)
    assert entry.dirty is True
    same = _entry(last_close=99.5, last_checked="2025-09-01")
    _match_price_scale(same, frame.assign(close=99.6))
    assert same.pivot == 101.0 and same.dirty is False


# ------------------------------------------------- market health and groups


def test_market_health_states() -> None:
    from app.services.early_setup.breadth import health_state

    assert health_state(65.0, -3.0) == "green"
    assert health_state(52.0, 4.0) == "green"  # above half and improving
    assert health_state(52.0, -1.0) == "amber"
    assert health_state(45.0, -8.0) == "red"  # under half and falling fast
    assert health_state(35.0, 6.0) == "red"
    assert health_state(None, None) == "amber"


def test_breadth_and_group_heat_come_from_all_stocks(tmp_path) -> None:
    from app.services.early_setup.watchlist import build_frames

    quiet = _base_bars()
    broke = _base_bars([(100.0, 103.0, 99.8, 102.5)]).iloc[1:].assign(date=quiet["date"].tolist())
    tickers = {f"UP{i}": quiet for i in range(4)} | {"HOT1": broke, "HOT2": broke, "DOWN": _downtrend_bars()}
    store = _store_with(tmp_path, tickers)
    repo.save_industries(
        [{"ticker": name, "industry": "Chemicals", "company_name": None} for name in tickers if name != "DOWN"], store
    )
    frames = build_frames(quiet["date"].iloc[-1], quiet["date"].iloc[-1], store=store)
    today = frames.health.iloc[-1]
    assert today["stocks"] == 7
    assert today["pct_above_50"] == pytest.approx(6 / 7 * 100.0)
    assert today["new_highs"] == 2 and today["state"] == "green"
    row = frames.by_ticker["UP0"].iloc[-1]
    assert row["market_breadth"] == pytest.approx(6 / 7 * 100.0)
    assert (row["group_members"], row["group_broke"]) == (6, 2)
    assert row["group_heat"] == pytest.approx((2 / 6 - 2 / 7) * 100.0)  # the group against the whole market
    assert pd.isna(frames.by_ticker["DOWN"].iloc[-1]["group_heat"])  # no industry on record
    assert frames.meta["UP0"]["sector"] == "Chemicals"  # the NSE industry replaces the profile's sector


def test_delivery_share_feeds_two_readings() -> None:
    bars = _base_bars()
    dates = bars["date"].tolist()
    share = pd.Series([40.0] * (len(dates) - 5) + [70.0] * 5, index=dates)
    last = compute_feature_frame(bars, delivery=share).iloc[-1]
    assert last["deliv_pct_5d"] == pytest.approx(70.0)
    assert last["deliv_trend"] == pytest.approx(70.0 - (55 * 40.0 + 5 * 70.0) / 60.0)
    assert pd.isna(compute_feature_frame(bars).iloc[-1]["deliv_pct_5d"])  # no file loaded: unknown, not zero


# ------------------------------------------------------------- weekly list


def test_weekly_base_is_flagged_and_listed_beside_the_daily_one(tmp_path) -> None:
    frame = compute_feature_frame(_base_bars())
    last = frame.iloc[-1]
    assert bool(last["w_candidate"]) is True
    assert last["w_pivot"] == pytest.approx(PIVOT)  # the ten-week high, set 18 sessions ago
    assert last["w_stop"] <= last["base_low"]  # three weeks of lows, so at or under the 10-day low
    spiked = compute_feature_frame(_base_bars([(100.0, 103.0, 99.8, 100.4)]))
    assert bool(spiked.iloc[-1]["w_candidate"]) is False  # a high made this week is a spike, not a ceiling

    store = _store_with(tmp_path, {"BASE": _base_bars(), "DOWN": _downtrend_bars()})
    result = update_watchlist(store=store)
    assert result["counts_by_list"]["weekly"] == {"active": 1}
    weekly = repo.list_entries(status="active", timeframe="weekly", store=store)[0]
    assert (weekly.ticker, weekly.timeframe, weekly.pivot) == ("BASE", "weekly", PIVOT)
    assert weekly.public()["timeframe"] == "weekly"
    assert repo.latest_health(store)["trade_date"] == result["processed_through"]


# ----------------------------------------------------------- pre-open scan


def _auction(stamp: str, prices: dict[str, tuple[float, float]]) -> dict:
    return {
        "timestamp": stamp,
        "data": [
            {"metadata": {"symbol": symbol, "series": "EQ", "iep": price, "previousClose": 99.5, "finalQuantity": qty}}
            for symbol, (price, qty) in prices.items()
        ],
    }


def test_opening_auction_flags_setups_at_their_pivot(tmp_path) -> None:
    from datetime import datetime

    from app.services.early_setup import preopen
    from app.services.live_scan.clocks import IST

    store = TimelineStore(tmp_path / "preopen.db")
    features = {"avg_volume_20": 1_000_000.0, "atr20_pct": 2.0}
    repo.save_entries(
        [
            _entry(ticker="OVER", features=features, dirty=True),
            _entry(ticker="GAP", features=features, dirty=True),
            _entry(ticker="NEAR", features=features, dirty=True),
            _entry(ticker="FAR", features=features, dirty=True),
            _entry(ticker="BROKEN", features=features, dirty=True),
            _entry(ticker="OVER", timeframe="weekly", features=features, dirty=True),  # same pivot: one event
            _entry(ticker="NEAR", timeframe="weekly", pivot=104.0, features=features, dirty=True),
        ],
        store,
    )
    prices = {"OVER": (101.6, 20_000), "GAP": (104.0, 50_000), "NEAR": (100.4, 5_000), "FAR": (99.0, 100), "BROKEN": (97.0, 900), "M&M": (3000.0, 10)}
    now = datetime(2026, 11, 18, 9, 9, tzinfo=IST)
    sent: list[str] = []
    send = lambda text: sent.append(text) or True

    stale = preopen.apply(_auction("17-Nov-2026 09:08:03", prices), now, store=store, sender=send)
    assert stale["status"] == "not_ready" and not sent  # yesterday's auction is never acted on
    early = preopen.apply(_auction("18-Nov-2026 09:03:00", prices), now, store=store, sender=send)
    assert early["status"] == "not_ready"

    done = preopen.apply(_auction("18-Nov-2026 09:08:03", prices), now, store=store, sender=send)
    assert (done["status"], done["hits"], done["new"], done["delivered"]) == ("done", 4, 4, True)
    rows = repo.load_preopen("2026-11-18", store)
    assert {key: row["state"] for key, row in rows.items()} == {
        ("OVER", "daily"): "preopen_above",
        ("GAP", "daily"): "preopen_gap",
        ("NEAR", "daily"): "preopen_near",
        ("BROKEN", "daily"): "preopen_fail",
    }
    assert rows[("OVER", "daily")]["qty_pct"] == 2.0  # the auction matched 2% of a normal day's volume
    assert len(sent) == 1 and sent[0].startswith("Pre-open 09:08") and "OVER: set to open above the pivot" in sent[0]
    assert preopen.done_today(now, store) is True

    again = preopen.apply(_auction("18-Nov-2026 09:08:03", prices), now, store=store, sender=send)
    assert again["new"] == 0 and len(sent) == 1  # a second reading sends nothing new
    assert preopen.in_window(now) and not preopen.in_window(now.replace(hour=9, minute=20))
    assert not preopen.in_window(datetime(2026, 11, 21, 9, 9, tzinfo=IST))  # Saturday


# ------------------------------------------------------------ filing size


def test_rupee_amounts_and_size_rules() -> None:
    from app.services.early_setup import sizing

    text = (
        "The Company has received an order worth Rs. 450 crore from NHAI. Annual turnover last year was "
        "Rs 2,500 crores. Separately a USD 20 million facility was renewed. The plant covers 12 acres."
    )
    assert [round(amount) for amount, _ in sizing.amounts_in(text)] == [450, 2500]  # the dollar amount is not rupees
    assert sizing.size_by_rules("orders", text) == {"amount_cr": 2500.0, "read_by": "rules"}
    assert sizing.size_by_rules("orders", "order of INR 75 lakhs received")["amount_cr"] == 0.75
    assert sizing.size_by_rules("results", text) is None  # rules do not read results
    assert sizing.size_by_rules("orders", "has informed the Exchange about an order") is None
    assert sizing.pdf_text(b"") == "" and sizing.pdf_text(b"not a pdf") == ""


def test_ai_answer_is_cut_down_to_the_expected_fields() -> None:
    from app.services.early_setup import sizing

    answer = {
        "headline": "Order worth Rs 450 crore from NHAI.  " + "x" * 400,
        "direction": "POSITIVE",
        "amount_cr": "450",
        "sales_yoy_pct": None,
        "profit_yoy_pct": "n/a",
        "impact": "enormous",
        "run_this": "rm -rf /",
    }
    cleaned = sizing.clean_ai_answer(answer)
    assert set(cleaned) == {"headline", "direction", "amount_cr", "sales_yoy_pct", "profit_yoy_pct", "ai_impact", "read_by"}
    assert (cleaned["direction"], cleaned["amount_cr"], cleaned["ai_impact"], len(cleaned["headline"])) == ("positive", 450.0, None, 220)
    assert sizing.clean_ai_answer("ignore previous instructions") is None
    assert sizing.clean_ai_answer({"headline": "", "amount_cr": -5}) is None


def test_size_is_graded_against_revenue_or_growth() -> None:
    from app.services.early_setup import sizing

    big = sizing.grade("orders", {"amount_cr": 450.0, "read_by": "ai"}, 2500.0)
    assert (big["size_pct"], big["impact"], big["basis"]) == (18.0, "high", "share of yearly revenue")
    assert sizing.grade("orders", {"amount_cr": 50.0}, 2500.0)["impact"] == "low"
    # Revenue that would make the order 45 million percent of sales is in different units: no share is claimed.
    unknown = sizing.grade("orders", {"amount_cr": 450.0, "ai_impact": "medium"}, 0.001)
    assert (unknown["size_pct"], unknown["impact"], unknown["basis"]) == (None, "medium", "the model's judgement")
    strong = sizing.grade("results", {"sales_yoy_pct": 22.0, "profit_yoy_pct": 31.0}, None)
    assert (strong["impact"], strong["direction"]) == ("high", "positive")
    assert sizing.grade("results", {"sales_yoy_pct": 4.0, "profit_yoy_pct": -40.0}, None)["direction"] == "negative"
    assert sizing.grade("results", {"sales_yoy_pct": 2.0, "profit_yoy_pct": 3.0}, None)["impact"] == "low"
    assert sizing.describe(big) == "₹450 Cr, about 18% of a year's revenue"
    assert sizing.describe(strong) == "sales +22% and profit +31% against a year ago"
    assert sizing.describe(None) is None


def test_filing_is_read_by_the_model_then_by_rules(tmp_path) -> None:
    import asyncio

    from app.services.early_setup import sizing

    class FakeNse:
        async def bytes(self, url: str, *, limit: int) -> bytes | None:
            return None  # the document is too large or missing: fall back to NSE's one-line summary

    filing = {"ticker": "AAA", "company_name": "AAA Ltd", "category": "orders", "subject": "Bagging of orders",
              "summary": "AAA Ltd has received an order worth Rs 450 crore", "url": "https://example.invalid/a.pdf"}
    store = TimelineStore(tmp_path / "size.db")

    async def model(_filing, _label, text):
        assert "450 crore" in text
        return sizing.clean_ai_answer({"headline": "Order worth ₹450 Cr from NHAI", "direction": "positive", "amount_cr": 450, "impact": "high"})

    async def broken(_filing, _label, _text):
        raise RuntimeError("model down")

    read = lambda ask: asyncio.run(sizing.size_filing(filing, "Order win", FakeNse(), store=store, ask_ai=ask))
    by_model = read(model)
    assert (by_model["read_by"], by_model["amount_cr"], by_model["impact"], by_model["headline"]) == ("ai", 450.0, "high", "Order worth ₹450 Cr from NHAI")
    by_rules = read(broken)  # a failed model call still yields the amount
    assert (by_rules["read_by"], by_rules["amount_cr"], by_rules["impact"]) == ("rules", 450.0, None)
    assert asyncio.run(sizing.size_filing({**filing, "summary": "", "url": None}, "Order win", FakeNse(), store=store)) is None


def test_sized_filing_alert_carries_the_number_and_small_news_is_skipped(tmp_path) -> None:
    from datetime import datetime

    from app.services.early_setup.filings import ingest
    from app.services.live_scan.clocks import IST

    store = TimelineStore(tmp_path / "sized.db")
    repo.save_entries([_entry(ticker="AAA", dirty=True)], store)
    now = datetime(2026, 11, 18, 10, 16, tzinfo=IST)
    rows = [
        _announcement("1", "AAA", "Bagging/Receiving of orders or contracts", "received an order"),
        _announcement("2", "BBB", "Bagging/Receiving of orders or contracts", "received an order"),
        _announcement("3", "CCC", "Bagging/Receiving of orders or contracts", "received an order"),
    ]
    sizes = {
        "1": {"amount_cr": 450.0, "size_pct": 18.0, "impact": "high", "headline": "Order worth ₹450 Cr from NHAI"},
        "2": {"amount_cr": 2.0, "size_pct": 0.1, "impact": "low", "headline": "Small repeat order"},
    }

    def sizer(filing: dict) -> dict | None:
        if filing["seq_id"] == "3":
            raise TimeoutError("document too slow")
        return sizes[filing["seq_id"]]

    sent: list[str] = []
    result = ingest(rows, now=now, store=store, sender=lambda text: sent.append(text) or True, scope="all", sizer=sizer)
    assert result["alerted"] == 2  # BBB's order is small and BBB is not on the watchlist
    assert "AAA — Filing: Order win (high impact)" in sent[0]
    assert "Order worth ₹450 Cr from NHAI" in sent[0] and "₹450 Cr, about 18% of a year's revenue" in sent[0]
    assert sent[1].startswith("CCC — Filing: Order win\n")  # unreadable in time: still alerted, without a size
    stored = {row["seq_id"]: row for row in repo.list_filings(since="2026-11-18T00:00:00+05:30", store=store)}
    assert (stored["1"]["impact"], stored["1"]["sized"], stored["2"]["impact"], stored["3"]["sized"]) == ("high", 1, "low", 0)
    assert [row["seq_id"] for row in repo.filings_to_size(5, store)] == ["3"]


# ------------------------------------------------- what followed past filings


def test_reaction_starts_from_the_first_tradable_price() -> None:
    from datetime import datetime

    from app.services.early_setup.filings import reaction
    from app.services.live_scan.clocks import IST

    dates = _dates(9)  # 2025-01-01 (a Wednesday) onwards
    opens = [100.0, 100.0, 110.0, 112.0, 112.0, 113.0, 114.0, 115.0, 121.0]
    closes = [100.0, 100.0, 111.0, 112.0, 113.0, 114.0, 115.0, 116.0, 122.0]
    # What stocks of this stock's liquidity group did from each day: average % gap at the open, average %
    # close to close, average % over the next five sessions from the open and from the close, then the
    # medians of those two.
    typical = {(day, 2): (0.5, 0.0, 0.0, 0.0, 0.0, 0.0) for day in dates}
    typical[(dates[2], 2)] = (0.5, 1.0, 1.4, 1.0, 9.3, 0.2)
    bench = (typical, [2.0] * len(dates))
    at = lambda day, hour, minute=0: datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00").replace(tzinfo=IST)

    evening = reaction(at(dates[1], 18), dates, opens, closes, *bench)  # after the close: the next session shows it
    assert (evening["timing"], evening["session"]) == ("after_close", dates[2])
    assert evening["gap_pct"] == pytest.approx(10.0) and evening["react_pct"] == pytest.approx(11.0)
    assert evening["gap_rel_pct"] == pytest.approx(9.5) and evening["react_rel_pct"] == pytest.approx(10.0)
    assert evening["after5_pct"] == pytest.approx((116.0 / 110.0 - 1) * 100)  # from the open you could buy at
    # The median stock from that open: +0.4% in the session, then +1% once in the next five closes.
    assert evening["after5_rel_pct"] == pytest.approx((116.0 / 110.0 - 1) * 100 - 1.4)
    # Ahead of the peers' average (+1.4%), behind their median (+9.3%): the two answer different questions.
    assert evening["beat"] is False

    midday = reaction(at(dates[2], 11, 30), dates, opens, closes, *bench)
    assert midday["timing"] == "market_hours"
    assert midday["after5_pct"] == pytest.approx((116.0 / 111.0 - 1) * 100)  # from that day's close, the cautious stand-in
    assert midday["after5_rel_pct"] == pytest.approx((116.0 / 111.0 - 1) * 100 - 1.0)  # against peers bought at that close
    assert midday["beat"] is True

    morning = reaction(at(dates[2], 8), dates, opens, closes, *bench)
    assert (morning["timing"], morning["after5_pct"]) == ("before_open", pytest.approx((116.0 / 110.0 - 1) * 100))

    weekend = reaction(at("2025-01-04", 12), dates, opens, closes, *bench)  # Saturday: Monday is the first session
    assert (weekend["timing"], weekend["session"]) == ("after_close", "2025-01-06")
    assert "after5_pct" not in reaction(at(dates[6], 18), dates, opens, closes, *bench)  # too recent to measure
    assert reaction(at("2024-12-25", 18), dates, opens, closes, *bench) is None  # before the candles start
    unplaced = reaction(at(dates[1], 18), dates, opens, closes, typical, [float("nan")] * len(dates))
    assert "after5_pct" in unplaced and "after5_rel_pct" not in unplaced  # too little history to pick its peers
    assert "after5_rel_pct" not in reaction(at(dates[1], 18), dates, opens, closes)  # no yardstick given


def test_typical_moves_are_measured_and_quoted_only_with_enough_cases(tmp_path) -> None:
    from datetime import datetime, timedelta

    from app.services.early_setup import filings
    from app.services.live_scan.clocks import IST

    today = datetime.now(IST).date()
    days = [day.date().isoformat() for day in pd.bdate_range(end=today - timedelta(days=1), periods=30)]
    bars = pd.DataFrame(
        {"date": days, "open": [100.0] * 30, "high": [112.0] * 30, "low": [99.0] * 30, "close": [100.0] * 10 + [110.0] * 20, "volume": [1e6] * 30}
    )
    flat = bars.assign(close=100.0)
    # Nine quiet peers of the same liquidity: with AAA they average a tenth of its move.
    store = _store_with(tmp_path, {"AAA": bars} | {f"FLAT{i}": flat for i in range(9)})
    filed = f"{days[9]}T18:00:00+05:30"  # the evening before the 10% jump
    repo.save_filings(
        [{"seq_id": str(i), "ticker": "AAA", "category": "orders", "subject": "Order", "filed_at": filed, "published_at": filed} for i in range(3)],
        store,
    )
    table = filings.rebuild_impact(store, days=120)
    orders = next(row for row in table["rows"] if row["category"] == "orders")
    assert orders["filings"] == 1  # three filings of one kind on one day are one event
    assert orders["avg_react_rel_pct"] == pytest.approx(9.0) and orders["avg_gap_rel_pct"] == pytest.approx(0.0)
    assert orders["avg_after5_rel_pct"] == pytest.approx(9.0)  # bought at the next open: +10% against +1% for its peers
    assert orders["positive_after5_pct"] == 100.0
    assert filings.load_impact(store)["rows"][0]["category"] == "results"
    assert filings.typical_move("orders", store) is None  # one case is not a pattern worth quoting
    text = filings.filing_alert_text(
        {"ticker": "AAA", "category": "orders", "subject": "Order", "filed_at": filed, "summary": "x"},
        None,
        typical={"avg_after5_rel_pct": 1.4, "measured": 212},
    )
    assert "moved +1.4% against similar stocks over 5 sessions on average (212 cases)" in text


# ------------------------------------------------- live: two lists and notes


def test_weekly_setup_gets_its_own_row_unless_it_is_the_same_pivot() -> None:
    weekly = {"pivot": 104.0, "stop": 96.0, "score": 60.0, "days": 9, "first_seen": "2026-11-02"}
    rows = rank_watchlist([_quote(103.95, watch_weekly=weekly)], 0.25)
    # One price, two pivots: through the daily one on volume, and just under the weekly one.
    assert [(row["list"], row["state"]) for row in rows] == [("daily", "breakout"), ("weekly", "testing")]
    assert rows[1]["pivot"] == 104.0 and rows[1]["days_in_base"] == 9

    same = rank_watchlist([_quote(100.9, watch_weekly={**weekly, "pivot": 101.0, "stop": 97.0})], 0.5)
    assert len(same) == 1 and same[0]["list"] == "daily" and same[0]["also_weekly"] is True
    assert rank_watch(_quote(100.9), 0.5, weekly=True) is None  # not on the weekly list

    sent: list[str] = []
    alerter = SetupAlerter(
        "2026-11-17", sender=lambda text: sent.append(text) or True, persist=False,
        notes={"AAA": ["Long-term surveillance Stage I", "Financial Results on 2026-11-19"]},
    )
    raised = alerter.observe(rows, tradable=True)
    assert [alert["state"] for alert in raised] == ["breakout", "weekly_testing"]  # each list alerts on its own key
    assert "AAA — Testing the pivot (weekly base)" in raised[1]["message"]
    assert raised[1]["message"].endswith("Note: Long-term surveillance Stage I\nNote: Financial Results on 2026-11-19")
    assert alerter.observe(rows, tradable=True) == []
    assert alerter.observe(same, tradable=True) == []  # testing the daily pivot after its break was alerted is noise
    fresh = SetupAlerter("2026-11-17", sender=lambda text: True, persist=False)
    both = fresh.observe(same, tradable=True)
    assert [alert["state"] for alert in both] == ["testing"] and "(weekly and daily base)" in both[0]["message"]


def test_alert_notes_gather_flags_events_and_large_buys(tmp_path) -> None:
    from app.services.early_setup.live import watch_notes

    store = TimelineStore(tmp_path / "notes.db")
    repo.replace_flags(["fo_ban"], [{"ticker": "AAA", "flag": "fo_ban", "detail": "In the F&O ban"}], store)
    repo.replace_flags(["asm_long", "asm_short"], [{"ticker": "BBB", "flag": "asm_long", "detail": "Long-term surveillance Stage I"}], store)
    repo.replace_flags(["fo_ban"], [], store)  # a new snapshot replaces the old list: AAA is out of the ban
    repo.save_events([{"ticker": "BBB", "event_date": "2026-11-19", "purpose": "Financial Results", "detail": ""},
                      {"ticker": "CCC", "event_date": "2026-12-25", "purpose": "Ex-bonus", "detail": ""}], store)
    repo.save_deals([{"trade_date": "2026-11-16", "ticker": "CCC", "client": "PATIENT FUND", "side": "BUY", "quantity": 400000.0, "price": 10.0, "kind": "bulk", "churn": 0}], store)
    notes = watch_notes("2026-11-18", store)
    assert notes == {
        "BBB": ["Long-term surveillance Stage I", "Financial Results on 2026-11-19"],
        "CCC": ["Large buy by Patient Fund on 2026-11-16 (400,000 shares)"],
    }
