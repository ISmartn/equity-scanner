"""Stress, race, and correctness tests for the live-scan ingest, math, and journal."""

from __future__ import annotations

import gc
import json
import threading
import time
import tracemalloc
from datetime import datetime
from typing import Any

import pytest
from google.protobuf import json_format
from upstox_client.feeder.proto import MarketDataFeedV3_pb2 as pb

from app.db.store import TimelineStore
from app.services.live_scan.clocks import IST
from app.services.live_scan.context import SymbolContext
from app.services.live_scan.feed import decode_frame, iter_feed_items, parse_market_tick
from app.services.live_scan.hub import LiveScanHub
from app.services.live_scan.journal import CallJournal, advance_plan
from app.services.live_scan.ranker import burst_rvol, candle_plan, classify_oi, session_call
from app.services.live_scan.state import LiveBook, PathWindow
from app.services.live_scan.ticks import TickGuard, sane_atp, spike_band
from app.services.live_scan.volume_profile import VolumeProfile
from app.services.live_scan.writer import LiveScanWriter

CASH = "NSE_EQ|INE002A01018"
FUT = "NSE_FO|61697"


def _epoch(hour: int, minute: int, second: float = 0.0) -> float:
    return datetime(2026, 11, 5, hour, minute, int(second), int((second % 1) * 1e6), tzinfo=IST).timestamp()


def _context(symbol: str = "RELIANCE", cash: str = CASH, future: str | None = FUT, **extra: Any) -> SymbolContext:
    base: dict[str, Any] = dict(
        symbol=symbol,
        company_name=symbol,
        sector="Energy",
        cash_key=cash,
        future_key=future,
        future_expiry="2026-11-23" if future else None,
        avg_volume_20=1_000_000,
        prior_high=100.0,
        prior_low=90.0,
        prior_close=98.0,
        scanner_pivot=101.0,
        myb_level=120.0,
    )
    base.update(extra)
    return SymbolContext(**base)


def _tick(ltp: float, vtt: int, **extra: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = {"ltp": ltp, "vtt": vtt, "prev_close": 98.0}
    parsed.update(extra)
    return parsed


def _apply(book: LiveBook, key: str, parsed: dict[str, Any], at: float) -> list[dict[str, Any]]:
    return book.apply_frame([(key, parsed)], at)


# --------------------------------------------------------------------- decode


def _full_feed_frame() -> bytes:
    response = pb.FeedResponse()
    response.currentTs = 1_762_317_000_000
    market = response.feeds[CASH].fullFeed.marketFF
    market.ltpc.ltp = 100.5
    market.ltpc.ltt = 1_762_316_999_500
    market.ltpc.ltq = 10
    market.ltpc.cp = 99.0
    market.atp = 100.1
    market.vtt = 1500
    market.oi = 0
    quote = market.marketLevel.bidAskQuote.add()
    quote.bidP, quote.askP, quote.bidQ, quote.askQ = 100.45, 100.55, 50, 70
    day = market.marketOHLC.ohlc.add()
    day.interval, day.open, day.high, day.low, day.close, day.vol = "1d", 98, 101, 97, 100.5, 1500
    minute = market.marketOHLC.ohlc.add()
    minute.interval, minute.vol = "I1", 40
    index = response.feeds["NSE_INDEX|Nifty 50"].fullFeed.indexFF
    index.ltpc.ltp = 24120.5
    index.ltpc.cp = 24000.0
    index_day = index.marketOHLC.ohlc.add()
    index_day.interval, index_day.open, index_day.high, index_day.low = "1d", 24010, 24180, 23990
    return response.SerializeToString()


def test_proto_fast_path_matches_dict_parser():
    raw = _full_feed_frame()
    _ts, fast = decode_frame(raw)
    message = json_format.MessageToDict(pb.FeedResponse.FromString(raw))
    slow = {key: parse_market_tick(feed) for key, feed in iter_feed_items(message)}
    assert dict(fast).keys() == slow.keys()
    for key, parsed in fast:
        reference = slow[key]
        for field in ("ltp", "prev_close", "atp", "vtt", "day_open", "day_high", "day_low", "minute_volume", "bid", "ask"):
            assert parsed[field] == reference[field], (key, field)
    cash = dict(fast)[CASH]
    assert cash["ltt"] == 1_762_316_999_500
    assert cash["oi"] is None
    assert dict(fast)["NSE_INDEX|Nifty 50"]["vtt"] is None


def test_proto_fast_path_is_faster_than_message_to_dict():
    raw = _full_feed_frame()
    rounds = 2_000
    started = time.perf_counter()
    for _ in range(rounds):
        decode_frame(raw)
    fast = time.perf_counter() - started
    started = time.perf_counter()
    for _ in range(rounds):
        message = json_format.MessageToDict(pb.FeedResponse.FromString(raw))
        for _key, feed in iter_feed_items(message):
            parse_market_tick(feed)
    slow = time.perf_counter() - started
    assert fast < slow


# ---------------------------------------------------------------- tick hygiene


def test_spike_is_quarantined_and_never_latches():
    book = LiveBook({"RELIANCE": _context()})
    _apply(book, CASH, _tick(99.5, 1000), _epoch(10, 0, 1))
    _apply(book, CASH, _tick(150.0, 1001), _epoch(10, 0, 2))
    _apply(book, CASH, _tick(99.6, 1002), _epoch(10, 0, 3))
    quote = book.export_quotes()[0]
    assert quote["ltp"] == 99.6
    assert quote["day_high"] < 100.0
    assert quote["latch_prev_high"] is False
    assert quote["latch_myb"] is False
    assert book.ingest_stats()["spikes_rejected"] == 1


def test_real_gap_is_confirmed_by_the_next_print():
    book = LiveBook({"RELIANCE": _context()})
    _apply(book, CASH, _tick(99.5, 1000), _epoch(10, 0, 1))
    _apply(book, CASH, _tick(106.0, 1100), _epoch(10, 0, 2))
    assert book.export_quotes()[0]["ltp"] == 99.5
    _apply(book, CASH, _tick(106.3, 1200), _epoch(10, 0, 3))
    quote = book.export_quotes()[0]
    assert quote["ltp"] == 106.3
    assert quote["latch_prev_high"] is True
    assert book.ingest_stats()["jumps_confirmed"] == 1


def test_spike_band_scales_with_atr():
    assert spike_band(None) == 0.03
    assert spike_band(1.0) == 0.015
    assert spike_band(6.0) == pytest.approx(0.036)
    assert spike_band(40.0) == 0.08
    guard = TickGuard(0.02, confirm=2)
    assert guard.check(100.0, 101.0)
    assert not guard.check(101.0, 110.0)
    assert guard.check(101.0, 110.5)


def test_out_of_order_frames_do_not_regress_price():
    book = LiveBook({"RELIANCE": _context()})
    newer = int(_epoch(10, 0, 5) * 1000)
    older = int(_epoch(10, 0, 2) * 1000)
    _apply(book, CASH, _tick(99.8, 1000, ltt=newer), _epoch(10, 0, 5))
    _apply(book, CASH, _tick(99.1, 990, ltt=older), _epoch(10, 0, 6))
    assert book.export_quotes()[0]["ltp"] == 99.8
    assert book.export_quotes()[0]["vtt"] == 1000
    assert book.ingest_stats()["out_of_order"] == 1


def test_exchange_time_buckets_the_minute_not_arrival_time():
    book = LiveBook({"RELIANCE": _context()})
    _apply(book, CASH, _tick(99.0, 1000, ltt=int(_epoch(10, 0, 1) * 1000)), _epoch(10, 0, 1))
    _apply(book, CASH, _tick(99.1, 1300, ltt=int(_epoch(10, 0, 59) * 1000)), _epoch(10, 1, 1))
    bars = _apply(book, CASH, _tick(99.2, 1400, ltt=int(_epoch(10, 1, 2) * 1000)), _epoch(10, 1, 2))
    assert bars[0]["minute_ts"] == "2026-11-05T10:00"
    assert bars[0]["volume"] == 300
    assert bars[0]["close_price"] == 99.1


def test_minute_bar_close_is_the_last_print_of_that_minute():
    book = LiveBook({"RELIANCE": _context()})
    _apply(book, CASH, _tick(99.0, 1000), _epoch(10, 0, 1))
    _apply(book, CASH, _tick(99.4, 1100), _epoch(10, 0, 50))
    bars = _apply(book, CASH, _tick(99.9, 1200), _epoch(10, 1, 5))
    assert bars[0]["close_price"] == 99.4


def test_minute_bar_carries_the_traded_open_high_and_low():
    book = LiveBook({"RELIANCE": _context()})
    _apply(book, CASH, _tick(99.0, 1000), _epoch(10, 0, 1))
    _apply(book, CASH, _tick(99.6, 1100), _epoch(10, 0, 10))
    _apply(book, CASH, _tick(100.5, 1100), _epoch(10, 0, 20))  # moved without volume: not an extreme
    _apply(book, CASH, _tick(98.7, 1200), _epoch(10, 0, 30))
    _apply(book, CASH, _tick(99.2, 1300), _epoch(10, 0, 50))
    bars = _apply(book, CASH, _tick(99.9, 1400), _epoch(10, 1, 5))
    assert (bars[0]["open_price"], bars[0]["high_price"], bars[0]["low_price"]) == (99.0, 99.6, 98.7)
    nxt = book.seal_minutes(_epoch(10, 2, 5))
    assert (nxt[0]["open_price"], nxt[0]["high_price"], nxt[0]["low_price"]) == (99.9, 99.9, 99.9)


def test_zero_volume_price_change_does_not_latch():
    book = LiveBook({"RELIANCE": _context()})
    _apply(book, CASH, _tick(99.5, 1000), _epoch(10, 0, 1))
    _apply(book, CASH, _tick(100.5, 1000), _epoch(10, 0, 2))
    quote = book.export_quotes()[0]
    assert quote["ltp"] == 100.5
    assert quote["latch_prev_high"] is False
    assert book.ingest_stats()["zero_volume_prints"] == 1


def test_pre_open_prints_do_not_latch_or_build_the_opening_range():
    book = LiveBook({"RELIANCE": _context()})
    _apply(book, CASH, _tick(99.0, 100), _epoch(9, 11, 0))
    _apply(book, CASH, _tick(101.0, 200), _epoch(9, 12, 0))
    quote = book.export_quotes()[0]
    assert quote["latch_prev_high"] is False
    assert quote["orb_high"] is None


def test_vwap_outside_the_day_range_is_ignored():
    assert sane_atp(100.0, 99.0, 101.0)
    assert not sane_atp(150.0, 99.0, 101.0)
    book = LiveBook({"RELIANCE": _context()})
    _apply(book, CASH, _tick(99.5, 1000, atp=99.4, day_low=99.0, day_high=100.0), _epoch(10, 0, 1))
    _apply(book, CASH, _tick(99.6, 1100, atp=12.0), _epoch(10, 0, 2))
    assert book.export_quotes()[0]["atp"] == 99.4
    assert book.ingest_stats()["atp_rejected"] == 1


# ------------------------------------------------------------ reconnect / gaps


def test_reconnect_gap_is_not_a_phantom_burst():
    book = LiveBook({"RELIANCE": _context()})
    vtt = 10_000
    for minute in range(10):
        for second in (5, 35):
            vtt += 500
            _apply(book, CASH, _tick(99.0 + minute * 0.01, vtt), _epoch(10, minute, second))
    before = book.export_quotes()[0]
    assert before["last_minute_volume"] == 1000

    book.mark_reconnect()
    vtt += 2_000_000  # Everything traded while the socket was down.
    bars = _apply(book, CASH, _tick(99.3, vtt), _epoch(10, 15, 10))
    after = book.export_quotes()[0]
    assert all(bar["volume"] < 10_000 for bar in bars)
    assert after["last_minute_volume"] is None
    assert max(after["minute_history"]) == 1000
    assert book.ingest_stats()["resyncs"] == 1

    vtt += 400
    _apply(book, CASH, _tick(99.31, vtt), _epoch(10, 15, 40))
    gap_bar = _apply(book, CASH, _tick(99.32, vtt + 600), _epoch(10, 16, 5))
    assert gap_bar[0]["source"] == "live_ws_partial"
    assert gap_bar[0]["volume"] == 400
    vtt += 600
    full = _apply(book, CASH, _tick(99.33, vtt + 700), _epoch(10, 17, 5))
    assert full[0]["source"] == "live_ws"
    assert book.export_quotes()[0]["last_minute_volume"] == 600


def test_reconnect_reseeds_session_high_from_exchange_day_high():
    book = LiveBook({"RELIANCE": _context()})
    _apply(book, CASH, _tick(99.0, 1000), _epoch(10, 0, 1))
    book.mark_reconnect()
    _apply(book, CASH, _tick(99.2, 5000, day_high=100.4), _epoch(10, 5, 1))
    quote = book.export_quotes()[0]
    assert quote["latch_prev_high"] is True
    assert quote["latch_orb"] is False


def test_simultaneous_candle_close_for_500_symbols():
    contexts = {
        f"S{i}": _context(symbol=f"S{i}", cash=f"NSE_EQ|S{i}", future=None) for i in range(500)
    }
    book = LiveBook(contexts)
    for i in range(500):
        key = f"NSE_EQ|S{i}"
        _apply(book, key, _tick(99.0, 1_000), _epoch(11, 20, 1))
        _apply(book, key, _tick(99.0 + i * 0.001, 1_000 + i + 1), _epoch(11, 20, 40))
    started = time.perf_counter()
    bars = book.seal_minutes(_epoch(11, 21, 3))
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert len(bars) == 500
    by_key = {bar["instrument_key"]: bar for bar in bars}
    for i in range(500):
        bar = by_key[f"NSE_EQ|S{i}"]
        assert bar["minute_ts"] == "2026-11-05T11:20"
        assert bar["volume"] == i + 1
        assert bar["close_price"] == pytest.approx(99.0 + i * 0.001)
    assert book.seal_minutes(_epoch(11, 21, 4)) == []
    assert elapsed_ms < 100.0
    late = _apply(book, "NSE_EQ|S1", _tick(99.5, 2_000), _epoch(11, 21, 30))
    assert late == []


# --------------------------------------------------------- concurrency (RCU)


def test_readers_see_coherent_views_while_the_writer_runs():
    contexts = {f"S{i}": _context(symbol=f"S{i}", cash=f"NSE_EQ|S{i}", future=None) for i in range(400)}
    book = LiveBook(contexts)
    keys = [f"NSE_EQ|S{i}" for i in range(400)]
    stop = threading.Event()
    errors: list[str] = []
    applied = [0]

    def writer() -> None:
        step = 0
        at = _epoch(10, 0, 0)
        while not stop.is_set():
            step += 1
            price = 100.0 + (step % 50) * 0.01
            frame = [(key, {"ltp": price, "vtt": 1000 + step, "atp": price, "day_high": price, "day_low": 99.0}) for key in keys[step % 4 :: 4]]
            book.apply_frame(frame, at + step * 0.01)
            applied[0] += len(frame)

    def reader() -> None:
        while not stop.is_set():
            view = book.view()
            frozen = {key: (v.ltp, v.vtt) for key, v in view.items()}
            for key, quote in view.items():
                if quote.ltp and not (quote.day_low <= quote.ltp <= quote.day_high):
                    errors.append(f"torn range {key}")
                if quote.ltp and quote.atp != quote.ltp:
                    errors.append(f"torn vwap {key}")
            time.sleep(0)
            if any((view[key].ltp, view[key].vtt) != frozen[key] for key in frozen):
                errors.append("published view mutated")

    threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(3)]
    for thread in threads:
        thread.start()
    time.sleep(1.0)
    stop.set()
    for thread in threads:
        thread.join()
    assert not errors, errors[:5]
    assert applied[0] > 10_000


def test_ingest_throughput_benchmark():
    contexts = {f"S{i}": _context(symbol=f"S{i}", cash=f"NSE_EQ|S{i}", future=f"NSE_FO|F{i}") for i in range(400)}
    book = LiveBook(contexts)
    keys = [key for i in range(400) for key in (f"NSE_EQ|S{i}", f"NSE_FO|F{i}")]
    frames = 300
    at = _epoch(10, 0, 0)
    started = time.perf_counter()
    for step in range(frames):
        price = 100.0 + (step % 40) * 0.01
        book.apply_frame([(key, {"ltp": price, "vtt": 1000 + step * 7, "oi": 5000 + step}) for key in keys], at + step * 0.2)
        if step % 5 == 0:
            book.seal_minutes(at + step * 0.2)
            book.close_window()
    elapsed = time.perf_counter() - started
    ticks_per_sec = frames * len(keys) / elapsed
    print(f"\ningest: {ticks_per_sec:,.0f} ticks/s over {frames * len(keys):,} ticks")
    assert ticks_per_sec > 20_000
    started = time.perf_counter()
    for _ in range(20):
        book.export_quotes()
    export_ms = (time.perf_counter() - started) / 20 * 1000.0
    print(f"export_quotes: {export_ms:.2f} ms for 400 symbols")
    assert export_ms < 50.0


def test_memory_is_flat_under_sustained_load():
    contexts = {f"S{i}": _context(symbol=f"S{i}", cash=f"NSE_EQ|S{i}", future=None) for i in range(200)}
    book = LiveBook(contexts)
    keys = [f"NSE_EQ|S{i}" for i in range(200)]
    journal = CallJournal("2026-11-05")
    at = _epoch(10, 0, 0)

    def run(start: int, steps: int) -> None:
        for step in range(start, start + steps):
            now = at + step * 0.5
            price = 99.0 + (step % 30) * 0.05
            book.apply_frame([(key, {"ltp": price, "vtt": 1000 + step * 3}) for key in keys], now)
            if step % 2 == 0:
                book.seal_minutes(now)
                book.close_window()
                journal.advance([], "t", windows=book.drain_windows())
                book.export_quotes()

    run(0, 400)
    gc.collect()
    tracemalloc.start()
    baseline, _ = tracemalloc.get_traced_memory()
    run(400, 1_200)
    gc.collect()
    current, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    growth_kb = (current - baseline) / 1024
    print(f"\nmemory growth over 240k ticks: {growth_kb:.0f} KiB")
    assert growth_kb < 1024


def test_window_backlog_is_bounded_when_the_reader_stalls():
    book = LiveBook({"RELIANCE": _context()})
    for step in range(1_000):
        _apply(book, CASH, _tick(99.0 + (step % 3) * 0.01, 1000 + step), _epoch(10, 0, 0) + step * 0.01)
        book.close_window()
    windows = book.drain_windows()
    assert len(windows) <= 240
    assert book.ingest_stats()["windows_dropped"] > 0


# -------------------------------------------------------------------- journal


def _call(symbol: str, ltp: float, *, stance: str = "wait", side: str = "buy", stale: bool = False) -> dict[str, Any]:
    if side == "buy":
        entry, stop, exit_price = 100.0, 95.0, 110.0
    else:
        entry, stop, exit_price = 100.0, 105.0, 90.0
    return {
        "symbol": symbol,
        "company_name": symbol,
        "kind": "equity",
        "stance": stance,
        "ltp": ltp,
        "entry": entry,
        "stop": stop,
        "exit": exit_price,
        "stale": stale,
    }


def _window(first: float, high: float, low: float, last: float) -> PathWindow:
    return PathWindow(first=first, high=high, low=low, last=last)


def test_one_wick_through_entry_and_stop_is_scored_as_a_loss():
    journal = CallJournal("2026-11-05")
    journal.advance([_call("A", 98.0)], "t0")
    journal.advance([], "t1", windows=[{"A": _window(98.0, 100.5, 94.0, 97.0)}])
    row = journal.rows()[0]
    assert row["status"] == "stopped"
    assert row["fill_price"] == 100.0
    assert row["result_pct"] == -5.0


def test_one_window_through_stop_and_target_assumes_the_stop():
    journal = CallJournal("2026-11-05")
    journal.advance([_call("A", 98.0)], "t0")
    journal.advance([], "t1", windows=[{"A": _window(99.0, 101.0, 99.0, 101.0)}])
    assert journal.rows()[0]["status"] == "open"
    journal.advance([], "t2", windows=[{"A": _window(101.0, 111.0, 94.0, 105.0)}])
    row = journal.rows()[0]
    assert row["status"] == "stopped"
    assert row["result_pct"] == -5.0


def test_wick_between_samples_is_not_missed():
    journal = CallJournal("2026-11-05")
    journal.advance([_call("A", 98.0)], "t0")
    journal.advance([], "t1", windows=[{"A": _window(99.0, 101.0, 99.0, 101.0)}])
    journal.advance([], "t2", windows=[{"A": _window(101.0, 110.2, 101.0, 104.0)}])
    row = journal.rows()[0]
    assert row["status"] == "target"
    assert row["result_pct"] == 10.0


def test_gap_through_entry_fills_at_the_first_print():
    journal = CallJournal("2026-11-05")
    journal.advance([_call("A", 98.0)], "t0")
    journal.advance([], "t1", windows=[{"A": _window(102.0, 103.0, 101.5, 102.5)}])
    row = journal.rows()[0]
    assert row["status"] == "open"
    assert row["fill_price"] == 102.0
    assert row["result_pct"] == pytest.approx(0.49, abs=0.01)


def test_gap_through_stop_fills_at_the_first_print():
    journal = CallJournal("2026-11-05")
    journal.advance([_call("A", 98.0)], "t0")
    journal.advance([], "t1", windows=[{"A": _window(99.0, 100.5, 99.0, 100.2)}])
    journal.advance([], "t2", windows=[{"A": _window(93.0, 93.5, 92.5, 93.0)}])
    row = journal.rows()[0]
    assert row["status"] == "stopped"
    assert row["result_pct"] == -7.0


def test_late_blocked_and_stale_plans_are_not_back_filled():
    journal = CallJournal("2026-11-05")
    journal.advance([_call("LATE", 103.0, stance="stand_aside")], "t0")
    journal.advance([_call("BLOCKED", 100.5, stance="wait")], "t0")
    journal.advance([_call("STALE", 98.0, stale=True)], "t0")
    journal.advance([_call("BELOW_STOP", 94.0)], "t0")
    assert journal.rows() == []
    journal.advance([_call("CONFIRMED", 100.8, stance="buy")], "t1")
    row = journal.rows()[0]
    assert row["status"] == "open"
    assert row["fill_price"] == 100.8


def test_nothing_moves_outside_the_session():
    journal = CallJournal("2026-11-05")
    journal.advance([_call("A", 98.0)], "t0", tradable=False)
    assert journal.rows() == []


def test_session_end_closes_open_and_cancels_pending():
    journal = CallJournal("2026-11-05")
    journal.advance([_call("OPEN", 98.0), _call("WAIT", 97.0)], "t0")
    journal.advance([], "t1", windows=[{"OPEN": _window(99.0, 102.0, 99.0, 102.0)}])
    assert journal.close_session("t2") == 2
    rows = {row["symbol"]: row for row in journal.rows()}
    assert rows["OPEN"]["status"] == "closed"
    assert rows["OPEN"]["result_pct"] == 2.0
    assert rows["OPEN"]["swing_status"] == "open"
    assert rows["OPEN"]["swing_status_label"] == "Carried"
    assert rows["OPEN"]["swing_exit"] == 120.0
    assert rows["WAIT"]["status"] == "cancelled"
    assert rows["WAIT"]["swing_status"] == "cancelled"
    summary = journal.summary()
    assert summary["closed"] == 1
    assert summary["win_rate_pct"] == 100.0
    journal.advance([_call("NEW", 98.0)], "t3")
    assert "NEW" not in {row["symbol"] for row in journal.rows()}


def test_swing_survives_the_close_and_resolves_next_session(tmp_path):
    store = TimelineStore(tmp_path / "swing.db")
    journal = CallJournal("2026-11-05")
    journal.advance([_call("A", 98.0, stance="buy"), _call("B", 98.0, stance="buy")], "t0")
    journal.advance(
        [],
        "t1",
        windows=[{"A": _window(99.0, 102.0, 99.0, 102.0), "B": _window(99.0, 111.0, 99.0, 111.0)}],
    )
    assert journal.close_session("t2") == 1
    store.upsert_live_call_journal(journal.persist_rows())

    nxt = CallJournal("2026-11-06")
    nxt.load(store.list_live_call_journal("2026-11-06"))
    carried = {row["symbol"]: row for row in nxt.rows()}
    assert carried["A"]["status"] == "closed"
    assert carried["A"]["result_pct"] == 2.0
    assert carried["A"]["swing_status"] == "open"
    assert carried["B"]["status"] == "target"
    assert carried["B"]["swing_status"] == "open"
    nxt.advance(
        [],
        "t3",
        windows=[{"A": _window(102.0, 121.0, 101.0, 120.0), "B": _window(111.0, 112.0, 93.0, 94.0)}],
    )
    done = {row["symbol"]: row for row in nxt.rows()}
    assert done["A"]["status"] == "closed"
    assert done["A"]["result_pct"] == 2.0
    assert done["A"]["swing_status"] == "target"
    assert done["A"]["swing_result_pct"] == 20.0
    assert done["B"]["status"] == "target"
    assert done["B"]["result_pct"] == 10.0
    assert done["B"]["swing_status"] == "stopped"
    assert done["B"]["swing_result_pct"] == -5.0


def test_restart_reload_is_idempotent(tmp_path):
    store = TimelineStore(tmp_path / "restart.db")
    journal = CallJournal("2026-11-05")
    journal.advance([_call("A", 98.0), _call("B", 98.0, side="sell", stance="sell")], "t0")
    journal.advance([], "t1", windows=[{"A": _window(99.0, 101.0, 99.0, 101.0)}])
    store.upsert_live_call_journal(journal.take_flush(10.0, force=True))

    for attempt in range(3):
        restored = CallJournal("2026-11-05")
        restored.load(store.list_live_call_journal("2026-11-05"))
        restored.advance([_call("A", 101.0, stance="buy"), _call("B", 98.0, side="sell", stance="sell")], f"r{attempt}")
        store.upsert_live_call_journal(restored.take_flush(100.0 + attempt, force=True))
    rows = store.list_live_call_journal("2026-11-05")
    assert len(rows) == 2
    by_symbol = {row["symbol"]: row for row in rows}
    assert by_symbol["A"]["status"] == "open"
    assert by_symbol["A"]["fill_price"] == 100.0
    assert by_symbol["B"]["fill_price"] == 98.0


def test_flush_sends_only_changed_rows():
    journal = CallJournal("2026-11-05")
    journal.advance([_call("A", 98.0), _call("B", 97.0)], "t0")
    assert len(journal.take_flush(100.0)) == 2
    journal.advance([_call("A", 98.1), _call("B", 97.1)], "t1")
    assert journal.take_flush(103.0) == []
    journal.advance([_call("A", 100.5), _call("B", 97.2)], "t2")
    changed = journal.take_flush(106.0)
    assert [row["symbol"] for row in changed] == ["A"]
    assert {row["symbol"] for row in journal.take_flush(120.0)} == {"B"}


def test_advance_plan_reports_last_price_only_updates_as_unchanged():
    record = {
        "status": "pending", "side": "buy", "entry": 100.0, "stop": 95.0, "exit_price": 110.0,
    }
    assert advance_plan(record, 98.0, "t") is False
    assert advance_plan(record, 100.0, "t") is True


# --------------------------------------------------------------------- writer


class _FlakyStore:
    def __init__(self) -> None:
        self.fail = True
        self.batches: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []

    def upsert_live_batch(self, bars: list[dict[str, Any]], journal: list[dict[str, Any]]) -> tuple[int, int]:
        if self.fail:
            self.fail = False
            raise RuntimeError("database is locked")
        self.batches.append((bars, journal))
        return len(bars), len(journal)


def _plan_row(symbol: str, status: str) -> dict[str, Any]:
    return {"session_date": "2026-11-05", "symbol": symbol, "side": "buy", "status": status}


def test_writer_coalesces_journal_and_survives_a_failed_write():
    store = _FlakyStore()
    writer = LiveScanWriter(store)  # type: ignore[arg-type]
    writer.enqueue_journal([_plan_row("A", "pending")])
    writer.enqueue_journal([_plan_row("A", "open")])
    writer._drain_once(block=False)
    assert writer.failures == 1
    writer.enqueue_journal([_plan_row("A", "target")])
    writer._drain_once(block=False)
    assert len(store.batches) == 1
    assert [row["status"] for row in store.batches[0][1]] == ["target"]
    writer.enqueue_journal([_plan_row("B", "open")])
    writer._drain_once(block=False)
    assert writer.failures == 1


def test_writer_batches_a_minute_rollover_in_one_transaction(tmp_path):
    store = TimelineStore(tmp_path / "batch.db")
    writer = LiveScanWriter(store)
    bars = [
        {"instrument_key": f"NSE_EQ|S{i}", "minute_ts": "2026-11-05T10:00", "volume": i + 1, "close_price": 100.0}
        for i in range(500)
    ]
    writer.enqueue_minutes(bars)
    writer.enqueue_journal([{**_plan_row("A", "open"), "kind": "equity", "entry": 100.0, "stop": 95.0,
                             "exit_price": 110.0, "opened_at": "t", "updated_at": "t", "fill_price": 100.2}])
    writer.stop()
    assert writer.minute_rows == 500
    assert writer.journal_rows == 1
    assert store.list_live_call_journal("2026-11-05")[0]["fill_price"] == 100.2


# ------------------------------------------------------------------------ hub


def test_hub_ignores_frames_from_a_retired_connection(tmp_path):
    hub = LiveScanHub(writer=LiveScanWriter(TimelineStore(tmp_path / "hub.db")))
    hub._book = LiveBook({"RELIANCE": _context(), "NIFTY": _context("NIFTY", "NSE_INDEX|Nifty 50", None, kind="index")})
    hub._conn_epoch = 3
    raw = _full_feed_frame()
    hub._on_raw(2, raw)
    assert hub._stale_frames == 1
    assert len(hub._frames) == 0
    hub._on_raw(3, raw)
    hub._frames.append((3, time.time(), None))
    hub._drain_frames(hub._book)
    assert hub._book.export_quotes()[0]["ltp"] == 100.5
    assert hub._book.ingest_stats()["resyncs"] == 1


def test_snapshot_json_is_valid_and_encoded_once_per_cycle(tmp_path):
    hub = LiveScanHub(writer=LiveScanWriter(TimelineStore(tmp_path / "snap.db")))
    hub._book = LiveBook({"RELIANCE": _context()})
    _apply(hub._book, CASH, _tick(99.5, 1000), time.time())
    hub._publish_once()
    first = json.loads(hub.snapshot_json("all", 50))
    assert first["calls"][0]["symbol"] == "RELIANCE"
    assert "pipeline" in first["status"]
    assert first["status"]["writer"]["dropped"] == 0
    hub.snapshot_json("all", 50)
    assert len(hub._encoded) == 1
    hub._publish_once()
    hub.snapshot_json("all", 50)
    assert hub._encoded_seq == hub._ranked_seq
    with pytest.raises(ValueError):
        hub.snapshot_json("nope", 10)


# ----------------------------------------------------------------------- math


def test_volume_profile_is_u_shaped():
    profile = VolumeProfile.default()
    at_930 = profile.expected_fraction(_epoch(9, 30))
    at_1230 = profile.expected_fraction(_epoch(12, 30))
    assert 0.09 < at_930 < 0.13
    assert at_930 > 15 / 375 * 2
    assert profile.expected_fraction(_epoch(15, 31)) == 1.0
    assert profile.minute_intensity(0) > 3 * profile.minute_intensity(180)
    assert profile.minute_intensity(374) > 2 * profile.minute_intensity(180)
    assert 0.0 < at_1230 < 1.0


def test_volume_profile_calibration_shrinks_toward_the_prior():
    flat = {f"2026-10-{day:02d}": {i: 100.0 for i in range(375)} for day in range(1, 11)}
    partial = {"2026-10-20": {i: 1e9 for i in range(100)}}
    calibrated = VolumeProfile.calibrated({**flat, **partial})
    assert calibrated.sessions == 10
    default = VolumeProfile.default()
    assert default.minute_intensity(180) < calibrated.minute_intensity(180) < 1.0
    assert VolumeProfile.calibrated({}).sessions == 0


def test_burst_is_read_against_time_of_day():
    profile = VolumeProfile.default()
    minutes = list(range(355, 375))
    history = [int(1000 * profile.minute_intensity(m)) for m in minutes]
    weights = [profile.minute_intensity(m) for m in minutes]
    raw = burst_rvol(history[-1], history)
    normalised = burst_rvol(history[-1], history, weights)
    assert raw is not None and raw > 1.3
    assert normalised == pytest.approx(1.0, abs=0.02)


def test_flat_price_with_rising_oi_is_neutral_not_short_buildup():
    assert classify_oi(0.2, 8.0) == "neutral"
    assert classify_oi(-1.0, 8.0) == "short_buildup"
    assert classify_oi(1.0, 8.0) == "long_buildup"
    assert classify_oi(-1.0, -8.0) == "long_unwinding"


def _quote(**overrides: Any) -> dict[str, Any]:
    quote: dict[str, Any] = {
        "symbol": "RELIANCE",
        "ltp": 101.5,
        "prev_close": 100.0,
        "atp": 101.0,
        "vtt": 500_000,
        "avg_volume_20": 1_000_000,
        "sma20": 90.0,
        "prior_high": 101.0,
        "prior_low": 94.0,
        "trend_20_pct": 8.0,
        "history_bars": 20,
    }
    quote.update(overrides)
    return quote


def test_plan_risk_is_bounded_by_atr():
    narrow = candle_plan("buy", 100.0, 99.8, atr=2.0)
    assert narrow is not None and narrow["basis"] == "atr_floor"
    assert narrow["stop"] == 99.0 and narrow["exit"] == 102.0
    assert narrow["swing_exit"] == 104.0 and narrow["swing_basis"] == "multi_r"
    wide = candle_plan("buy", 100.0, 90.0, atr=2.0)
    assert wide is not None and wide["basis"] == "atr_cap"
    assert wide["stop"] == 97.0 and wide["exit"] == 106.0
    assert wide["swing_exit"] == 120.0 and wide["swing_basis"] == "candle"
    spread_floor = candle_plan("sell", 100.0, 100.3, atr=0.2, spread=0.5)
    assert spread_floor is not None and spread_floor["stop"] == 102.0
    call = session_call(_quote(atr_pct=2.0, prior_low=100.8), 0.5)
    assert call["stop_basis"] == "atr_floor"
    assert call["stop"] == 100.0


def test_choppy_twenty_day_path_stands_aside():
    call = session_call(_quote(efficiency_20=0.08), 0.5)
    assert call["stance"] == "stand_aside"
    assert "range" in call["reason"]
    assert session_call(_quote(efficiency_20=0.5), 0.5)["stance"] == "buy"


def test_wide_spread_holds_a_break_on_wait():
    call = session_call(_quote(spread_pct=0.8), 0.5)
    assert call["stance"] == "wait"
    assert "spread" in call["reason"]


def test_expiry_week_oi_does_not_block_a_break():
    supply = dict(fut_ltp=98.0, fut_prev_close=100.0, fut_oi=12_000, fut_poi=10_000)
    assert session_call(_quote(**supply), 0.5)["stance"] == "stand_aside"
    rolled = session_call(_quote(**supply, days_to_expiry=1), 0.5)
    assert rolled["stance"] == "buy"
    assert rolled["rollover_week"] is True


def test_stale_quote_is_flagged_for_the_journal():
    now = time.time()
    fresh = session_call(_quote(last_tick_at=now - 2), 0.5, now)
    stale = session_call(_quote(last_tick_at=now - 120), 0.5, now)
    never = session_call(_quote(last_tick_at=None), 0.5, now)
    assert fresh["stale"] is False
    assert stale["stale"] is True
    assert never["stale"] is True


def test_live_feed_eod_candle_is_provisional(tmp_path):
    store = TimelineStore(tmp_path / "eod.db")
    store.upsert_profiles([
        {"instrument_token": "NSE_EQ|AAA", "ticker": "AAA", "company_name": "A", "sector": "X", "isin": "AAA", "series": "EQ"}
    ])
    store.upsert_candles([
        {"trade_date": "2026-11-04", "instrument_token": "NSE_EQ|AAA", "close_price": 100, "volume": 1, "source": "upstox"},
        {"trade_date": "2026-11-05", "instrument_token": "NSE_EQ|AAA", "close_price": 101, "volume": 1, "source": "live_ws"},
    ])
    assert store.tickers_missing_daily_session(["NSE_EQ|AAA"], "2026-11-05") == ["AAA"]
    assert store.get_last_trade_dates()["NSE_EQ|AAA"] == "2026-11-04"


def test_history_stats_use_median_volume_atr_and_efficiency(tmp_path):
    store = TimelineStore(tmp_path / "stats.db")
    rows = []
    for day in range(1, 21):
        close = 100.0 + day
        rows.append({
            "trade_date": f"2026-10-{day:02d}",
            "instrument_token": "NSE_EQ|AAA",
            "open_price": close - 0.5,
            "high_price": close + 1.0,
            "low_price": close - 1.0,
            "close_price": close,
            "volume": 50_000_000 if day == 10 else 1_000_000,
            "source": "upstox",
        })
    store.upsert_candles(rows)
    stats = store.live_scan_candle_stats(["NSE_EQ|AAA"], "2026-11-01")["NSE_EQ|AAA"]
    assert stats["avg_volume_20"] == 1_000_000
    assert stats["efficiency_20"] == pytest.approx(1.0)
    assert stats["atr_pct"] == pytest.approx(2.0 / 120.0 * 100.0, rel=0.01)
