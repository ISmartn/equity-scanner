from __future__ import annotations

from datetime import datetime

from app.db.store import TimelineStore
from app.services.live_scan.clocks import (
    IST,
    hold_through_close,
    in_feed_window,
    in_opening_range,
    in_session,
    past_feed_end,
    required_daily_session,
    session_minute,
    session_progress,
)
from app.services.live_scan.volume_profile import VolumeProfile
from app.services.live_scan.context import SymbolContext, extract_pivot, load_context
from app.services.live_scan.feed import parse_market_tick
from app.services.live_scan.baskets import index_reads
from app.services.live_scan.journal import CallJournal
from app.services.live_scan.ranker import burst_rvol, level_state, rank_boards, session_call, session_rvol
from app.services.live_scan.state import LiveBook
from app.services.live_scan.history import CandleRequestBudget
from app.services.live_scan.universe import (
    FULL_MODE_KEY_LIMIT,
    FutureContract,
    UniverseSymbol,
    select_cash_symbols,
    select_front_futures,
    subscription_key_count,
)
from app.services.live_scan.writer import LiveScanWriter
from app.services.scanner.fo_overlay import _classify_quadrant


def _ts(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 11, 5, hour, minute, second, tzinfo=IST)


def _context() -> SymbolContext:
    return SymbolContext(
        symbol="RELIANCE",
        company_name="Reliance",
        sector="Energy",
        cash_key="NSE_EQ|INE002A01018",
        future_key="NSE_FO|61697",
        future_expiry="2026-11-23",
        avg_volume_20=1_000_000,
        prior_high=100.0,
        prior_low=90.0,
        prior_close=98.0,
        scanner_score=80,
        scanner_pattern="vcp",
        scanner_pivot=101.0,
        myb_level=120.0,
        myb_status="near",
        seeded_poi=10_000,
    )


def test_select_front_month_future():
    rows = [
        {
            "name": "RELIANCE INDUSTRIES LTD",
            "underlying_symbol": "RELIANCE",
            "underlying_type": "EQUITY",
            "instrument_type": "FUT",
            "segment": "NSE_FO",
            "instrument_key": "NSE_FO|55121",
            "expiry": 1_800_901_799_000,
            "weekly": False,
        },
        {
            "name": "RELIANCE INDUSTRIES LTD",
            "underlying_symbol": "RELIANCE",
            "underlying_type": "EQUITY",
            "instrument_type": "FUT",
            "segment": "NSE_FO",
            "instrument_key": "NSE_FO|61697",
            "expiry": 1_795_458_599_000,
            "weekly": False,
        },
        {
            "underlying_symbol": "NIFTY",
            "underlying_type": "INDEX",
            "instrument_type": "FUT",
            "segment": "NSE_FO",
            "instrument_key": "NSE_FO|61471",
            "expiry": 1_795_458_599_000,
            "weekly": True,
        },
    ]
    picked = select_front_futures(rows, {"RELIANCE"}, datetime(2026, 11, 5, tzinfo=IST).date())
    assert list(picked) == ["RELIANCE"]
    assert picked["RELIANCE"] == FutureContract(
        symbol="RELIANCE",
        instrument_key="NSE_FO|61697",
        expiry="2026-11-23",
        underlying_key=None,
    )


def test_parse_market_tick_full_feed():
    parsed = parse_market_tick(
        {
            "fullFeed": {
                "marketFF": {
                    "ltpc": {"ltp": 100.5, "cp": 99.0},
                    "marketOHLC": {
                        "ohlc": [
                            {"interval": "1d", "open": 98, "high": 101, "low": 97, "close": 100.5, "vol": "1500"},
                            {"interval": "I1", "vol": "40"},
                        ]
                    },
                    "atp": 100.1,
                    "vtt": "1500",
                    "oi": 20.0,
                }
            }
        }
    )
    assert parsed is not None
    assert parsed["ltp"] == 100.5
    assert parsed["prev_close"] == 99.0
    assert parsed["atp"] == 100.1
    assert parsed["vtt"] == 1500
    assert parsed["oi"] == 20.0
    assert parsed["day_high"] == 101
    assert parsed["minute_volume"] == 40

    index = parse_market_tick(
        {
            "fullFeed": {
                "indexFF": {
                    "ltpc": {"ltp": 24120.5, "cp": 24000.0},
                    "marketOHLC": {
                        "ohlc": [
                            {"interval": "1d", "open": 24010, "high": 24180, "low": 23990, "close": 24120.5},
                        ]
                    },
                }
            }
        }
    )
    assert index is not None
    assert index["ltp"] == 24120.5
    assert index["prev_close"] == 24000.0
    assert index["day_high"] == 24180
    assert index["atp"] is None


def test_live_book_minute_bucket_and_breakout_latch():
    book = LiveBook({"RELIANCE": _context()})
    first = {
        "ltp": 99.5,
        "prev_close": 98.0,
        "atp": 99.2,
        "vtt": 1000,
        "day_open": 99.0,
        "day_high": 99.6,
        "day_low": 98.8,
    }
    assert book.apply("NSE_EQ|INE002A01018", first, _ts(9, 16)) is None
    assert (
        book.apply(
            "NSE_EQ|INE002A01018",
            {**first, "ltp": 99.8, "vtt": 1200, "day_high": 99.8},
            _ts(9, 16, 30),
        )
        is None
    )
    rolled = book.apply(
        "NSE_EQ|INE002A01018",
        {**first, "ltp": 100.4, "vtt": 1300, "day_high": 100.4},
        _ts(9, 17),
    )
    assert rolled is not None
    assert rolled["minute_ts"] == "2026-11-05T09:16"
    assert rolled["volume"] == 200

    book.apply(
        "NSE_EQ|INE002A01018",
        {**first, "ltp": 101.2, "vtt": 1600, "day_high": 101.2},
        _ts(9, 31),
    )
    quotes = book.export_quotes()
    assert quotes[0]["latch_prev_high"] is True
    assert quotes[0]["latch_pivot"] is True
    assert quotes[0]["orb_locked"] is True
    assert quotes[0]["minute_history"][:2] == [200, 100]
    # 09:18–09:30 printed nothing: those minutes are real zeros, and the last one is 09:30.
    assert quotes[0]["minute_history"][2:] == [0] * 13
    assert quotes[0]["last_minute_volume"] == 0


def test_futures_poi_seed_and_session_open_fallback():
    context = _context()
    context.seeded_poi = None
    book = LiveBook({"RELIANCE": context})
    book.apply("NSE_FO|61697", {"ltp": 102.0, "prev_close": 100.0, "oi": 11000, "vtt": 50}, _ts(9, 20))
    quote = book.export_quotes()[0]
    assert quote["fut_poi"] == 11000
    assert quote["fut_poi_source"] == "session_open"


def test_rank_boards_momentum_breakout_and_oi():
    quote = {
        "symbol": "RELIANCE",
        "company_name": "Reliance",
        "sector": "Energy",
        "ltp": 101.2,
        "prev_close": 98.0,
        "atp": 100.0,
        "day_high": 101.2,
        "day_low": 98.8,
        "vtt": 500_000,
        "avg_volume_20": 1_000_000,
        "last_minute_volume": 2000,
        "minute_history": [100, 100, 100, 100, 100, 2000],
        "on_last_scan": True,
        "scanner_score": 80,
        "scanner_pattern": "vcp",
        "scanner_pivot": 101.0,
        "prior_high": 100.0,
        "orb_high": 99.8,
        "orb_locked": True,
        "myb_level": 120.0,
        "myb_status": "near",
        "latch_prev_high": True,
        "latch_orb": True,
        "latch_pivot": True,
        "latch_myb": False,
        "fut_ltp": 102.0,
        "fut_prev_close": 100.0,
        "fut_oi": 12000,
        "fut_poi": 10000,
        "fut_poi_source": "prior_close",
        "future_key": "NSE_FO|61697",
        "future_expiry": "2026-11-23",
        "cash_key": "NSE_EQ|INE002A01018",
    }
    boards = rank_boards([quote], progress=0.5)
    momentum = boards["momentum"][0]
    assert momentum["on_last_scan"] is True
    assert momentum["session_rvol"] == 1.0
    assert momentum["burst_rvol"] == 20.0
    assert momentum["change_pct"] > 0

    breakout = boards["breakout"][0]
    assert breakout["state"] == "triggered"
    assert breakout["prior_high"]["state"] == "triggered"
    assert breakout["multi_year"]["state"] == "below"

    oi = boards["oi"][0]
    assert oi["quadrant"] == "long_buildup"
    assert oi["basis"] == 0.8
    assert oi["oi_change_pct"] == 20.0


def _history_quote(**overrides):
    quote = {
        "symbol": "RELIANCE",
        "company_name": "Reliance",
        "sector": "Energy",
        "ltp": 102.0,
        "prev_close": 100.0,
        "atp": 101.0,
        "vtt": 500_000,
        "avg_volume_20": 1_000_000,
        "last_minute_volume": None,
        "minute_history": [],
        "sma20": 90.0,
        "prior_high": 101.0,
        "prior_low": 94.0,
        "trend_20_pct": 8.0,
        "return_5d_pct": 3.0,
        "history_bars": 20,
        "on_last_scan": True,
        "fut_ltp": 0,
        "fut_prev_close": 0,
        "fut_oi": 0,
        "fut_poi": None,
    }
    quote.update(overrides)
    return quote


def test_session_call_buy_sell_and_stand_aside():
    buy = session_call(_history_quote(), 0.5)
    assert buy["stance"] == "buy"
    assert buy["stance_label"] == "Buy"
    assert "20-day average" in buy["reason"]
    assert buy["entry"] == 101.0
    assert buy["stop"] == 94.0
    assert buy["exit"] == 115.0
    assert buy["swing_exit"] == 129.0
    assert buy["swing_basis"] == "multi_r"

    sell = session_call(
        _history_quote(
            ltp=97.0,
            prev_close=100.0,
            atp=99.0,
            sma20=110.0,
            trend_20_pct=-6.0,
            prior_low=98.0,
            prior_high=104.0,
        ),
        0.5,
    )
    assert sell["stance"] == "sell"
    assert sell["stance_label"] == "Sell"

    aside = session_call(_history_quote(ltp=99.0, atp=99.5), 0.5)
    assert aside["stance"] == "wait"
    assert aside["stance_label"] == "Wait"
    assert aside["entry"] == 101.0
    assert aside["stop"] == 94.0
    assert aside["exit"] == 115.0
    assert "yesterday's high" in aside["reason"]

    green_ticks = session_call(_history_quote(ltp=100.4, atp=100.2), 0.5)
    assert green_ticks["stance"] == "wait"
    assert green_ticks["entry"] == 101.0

    late = session_call(_history_quote(ltp=110.0), 0.5)
    assert late["stance"] == "stand_aside"
    assert late["plan_phase"] == "late"
    assert "Do not chase" in late["reason"]

    nifty = session_call(
        _history_quote(
            symbol="NIFTY",
            kind="index",
            ltp=24120.0,
            prev_close=24000.0,
            atp=0,
            vtt=0,
            avg_volume_20=None,
            sma20=23000.0,
            prior_high=24100.0,
            prior_low=23800.0,
            trend_20_pct=4.0,
        ),
        0.5,
    )
    assert nifty["stance"] == "buy"
    assert nifty["entry"] == 24100.0
    assert nifty["stop"] == 23800.0
    assert nifty["exit"] == 24700.0

    thin = session_call(_history_quote(history_bars=4), 0.5)
    assert thin["stance"] == "stand_aside"
    assert thin["reason"] == "Not enough daily history for a call"

    blocked = session_call(
        _history_quote(fut_ltp=98.0, fut_prev_close=100.0, fut_oi=12_000, fut_poi=10_000),
        0.5,
    )
    assert blocked["stance"] == "stand_aside"
    assert "short build-up" in blocked["reason"]


def _stock(symbol: str, change_pct: float) -> dict:
    prev = 100.0
    return {
        "symbol": symbol,
        "kind": "equity",
        "ltp": prev * (1 + change_pct / 100.0),
        "prev_close": prev,
    }


def test_index_read_spots_a_narrow_drop_and_a_broad_rise():
    heavy_down = [
        _stock("HDFCBANK", -2.0),
        _stock("RELIANCE", -1.0),
        *[_stock(symbol, 0.4) for symbol in ("INFY", "TCS", "ITC", "LT", "SBIN", "AXISBANK", "MARUTI", "TITAN")],
    ]
    narrow = index_reads(heavy_down, {"NIFTY": [row["symbol"] for row in heavy_down]})["NIFTY"]
    assert narrow["tone"] == "narrow_drop"
    assert narrow["breadth_up"] == 8
    assert narrow["breadth_down"] == 2
    assert narrow["weighted_change_pct"] < 0
    assert narrow["drags"][0]["symbol"] == "HDFCBANK"
    assert "heavyweights" in narrow["read"]

    broad = index_reads(
        [_stock(symbol, 0.8) for symbol in ("HDFCBANK", "RELIANCE", "INFY", "TCS", "ITC")],
        {"SENSEX": ["HDFCBANK", "RELIANCE", "INFY", "TCS", "ITC"]},
    )["SENSEX"]
    assert broad["tone"] == "broad_rise"
    assert broad["breadth_up"] == 5
    assert broad["leaders"][0]["symbol"] == "HDFCBANK"


def test_rvol_and_level_helpers():
    assert session_rvol(250_000, 1_000_000, 0.25) == 1.0
    assert session_rvol(100, None, 0.5) is None
    assert burst_rvol(500, [100, 100, 100, 100, 100, 500]) == 5.0
    assert level_state(100.0, 100.2, False) == "testing"
    assert level_state(99.0, 100.2, True) == "triggered"
    assert _classify_quadrant(price_up=False, oi_up=True, oi_down=False) == "short_buildup"


def _plan(symbol: str, ltp: float, *, side: str = "buy") -> dict:
    if side == "buy":
        entry, stop, exit_price = 100.0, 94.0, 112.0
    else:
        entry, stop, exit_price = 100.0, 106.0, 88.0
    return {
        "symbol": symbol,
        "company_name": symbol,
        "kind": "equity",
        "stance": "wait" if ltp < entry and side == "buy" else side,
        "ltp": ltp,
        "entry": entry,
        "stop": stop,
        "exit": exit_price,
    }


def test_journal_follows_entry_to_target_stop_or_cancel():
    journal = CallJournal("2026-11-06")
    journal.advance([_plan("RELIANCE", 97.0)], "2026-11-06T09:20:00")
    waiting = journal.rows()[0]
    assert waiting["status"] == "pending"
    assert waiting["result_pct"] is None

    journal.advance([_plan("RELIANCE", 101.0)], "2026-11-06T09:30:00")
    opened = journal.rows()[0]
    assert opened["status"] == "open"
    assert opened["result_pct"] == 1.0
    assert opened["entry"] == 100.0

    journal.advance([{**_plan("RELIANCE", 113.0), "entry": 101.0}], "2026-11-06T10:00:00")
    hit = journal.rows()[0]
    assert hit["status"] == "target"
    assert hit["entry"] == 100.0
    assert hit["result_pct"] == 12.0

    journal.advance([_plan("RELIANCE", 90.0)], "2026-11-06T10:05:00")
    assert journal.rows()[0]["status"] == "target"

    # First seen already through the entry: the fill is the price seen, not the level.
    journal.advance([_plan("TCS", 101.0)], "2026-11-06T09:30:00")
    journal.advance([_plan("TCS", 93.0)], "2026-11-06T10:10:00")
    stopped = next(row for row in journal.rows() if row["symbol"] == "TCS")
    assert stopped["status"] == "stopped"
    assert stopped["fill_price"] == 101.0
    assert stopped["result_pct"] == -6.93

    journal.advance([_plan("INFY", 97.0)], "2026-11-06T09:20:00")
    journal.advance([_plan("INFY", 93.0)], "2026-11-06T09:40:00")
    cancelled = next(row for row in journal.rows() if row["symbol"] == "INFY")
    assert cancelled["status"] == "cancelled"
    assert cancelled["result_pct"] is None

    summary = journal.summary()
    assert summary["target"] == 1
    assert summary["stopped"] == 1
    assert summary["cancelled"] == 1
    assert summary["win_rate_pct"] == 50.0


def test_journal_round_trip(tmp_path):
    store = TimelineStore(tmp_path / "journal.db")
    journal = CallJournal("2026-11-06")
    journal.advance([_plan("SBIN", 99.0, side="sell")], "2026-11-06T09:20:00")
    journal.advance([_plan("SBIN", 88.0, side="sell")], "2026-11-06T11:00:00")
    assert store.upsert_live_call_journal(journal.persist_rows()) == 1
    restored = CallJournal("2026-11-06")
    restored.load(store.list_live_call_journal("2026-11-06"))
    row = restored.rows()[0]
    assert row["status"] == "target"
    assert row["side"] == "sell"
    assert row["fill_price"] == 99.0
    assert row["result_pct"] == 11.11


def test_required_daily_session_is_the_last_completed_close():
    assert required_daily_session(datetime(2026, 11, 6, 10, 43, tzinfo=IST)) == "2026-11-05"
    assert required_daily_session(datetime(2026, 11, 6, 16, 0, tzinfo=IST)) == "2026-11-06"
    assert required_daily_session(datetime(2026, 11, 7, 11, 0, tzinfo=IST)) == "2026-11-06"


def test_muhurat_session_replaces_the_sunday_close():
    sunday_open = datetime(2026, 11, 8, 14, 25, tzinfo=IST)
    before = datetime(2026, 11, 8, 10, 0, tzinfo=IST)
    done = datetime(2026, 11, 8, 15, 40, tzinfo=IST)
    midpoint = datetime(2026, 11, 8, 14, 55, tzinfo=IST)
    saturday = datetime(2026, 11, 7, 14, 25, tzinfo=IST)

    assert in_feed_window(sunday_open)
    assert hold_through_close(sunday_open)
    assert not past_feed_end(sunday_open)
    assert in_session(sunday_open.timestamp())
    assert in_opening_range(sunday_open)
    assert session_minute(sunday_open.timestamp()) == 5
    assert session_minute(datetime(2026, 11, 8, 14, 20, tzinfo=IST).timestamp()) == 0

    assert not in_feed_window(before)
    assert not in_session(before.timestamp())
    assert past_feed_end(done)
    assert not hold_through_close(done)
    assert not in_session(done.timestamp())
    assert abs(session_progress(midpoint) - 0.5) < 0.02
    assert abs(VolumeProfile.default().expected_fraction(midpoint.timestamp()) - 0.5) < 0.02

    assert required_daily_session(datetime(2026, 11, 8, 14, 0, tzinfo=IST)) == "2026-11-06"
    assert required_daily_session(done) == "2026-11-08"
    assert required_daily_session(datetime(2026, 11, 9, 10, 0, tzinfo=IST)) == "2026-11-08"

    assert not in_feed_window(saturday)
    assert not hold_through_close(saturday)
    assert session_minute(datetime(2026, 11, 6, 9, 20, tzinfo=IST).timestamp()) == 5


def test_tickers_missing_daily_session(tmp_path):
    store = TimelineStore(tmp_path / "gap.db")
    store.upsert_profiles(
        [
            {
                "instrument_token": "NSE_EQ|AAA",
                "ticker": "RELIANCE",
                "company_name": "Reliance",
                "sector": "Energy",
                "isin": "AAA",
                "series": "EQ",
            },
            {
                "instrument_token": "NSE_EQ|BBB",
                "ticker": "TCS",
                "company_name": "TCS",
                "sector": "IT",
                "isin": "BBB",
                "series": "EQ",
            },
            {
                "instrument_token": "NSE_EQ|CCC",
                "ticker": "INFY",
                "company_name": "Infy",
                "sector": "IT",
                "isin": "CCC",
                "series": "EQ",
            },
        ]
    )
    store.upsert_candles(
        [
            {
                "trade_date": "2026-11-05",
                "instrument_token": "NSE_EQ|AAA",
                "close_price": 100,
                "volume": 1,
                "source": "upstox",
            },
            {
                "trade_date": "2026-11-03",
                "instrument_token": "NSE_EQ|BBB",
                "close_price": 50,
                "volume": 1,
                "source": "upstox",
            },
        ]
    )
    missing = store.tickers_missing_daily_session(
        ["NSE_EQ|AAA", "NSE_EQ|BBB", "NSE_EQ|CCC"],
        "2026-11-05",
    )
    assert missing == ["INFY", "TCS"]


def test_session_progress_is_clamped():
    assert session_progress(_ts(9, 0)) == 0.02
    assert session_progress(_ts(15, 30)) == 1.0


def test_extract_pivot_from_scanner_details():
    assert extract_pivot('{"pivot_high": 250.5, "stage": "coil"}') == 250.5
    assert extract_pivot({"pivot_high_20d": 10}) == 10.0
    assert extract_pivot({}) is None


def test_context_and_writer_round_trip(tmp_path):
    from app.services.live_scan.universe import UniverseSymbol

    store = TimelineStore(tmp_path / "live.db")
    store.upsert_profiles(
        [
            {
                "instrument_token": "NSE_EQ|INE002A01018",
                "ticker": "RELIANCE",
                "company_name": "Reliance",
                "sector": "Energy",
                "isin": "INE002A01018",
                "series": "EQ",
            }
        ]
    )
    store.upsert_candles(
        [
            {
                "trade_date": "2026-11-03",
                "instrument_token": "NSE_EQ|INE002A01018",
                "open_price": 90,
                "high_price": 100,
                "low_price": 89,
                "close_price": 98,
                "volume": 1_000_000,
                "daily_return_pct": 1.0,
                "source": "upstox",
            },
            {
                "trade_date": "2026-11-04",
                "instrument_token": "NSE_EQ|INE002A01018",
                "open_price": 98,
                "high_price": 101,
                "low_price": 97,
                "close_price": 99,
                "volume": 1_200_000,
                "daily_return_pct": 1.0,
                "source": "upstox",
            },
        ]
    )
    run_id = store.create_scanner_run("2026-11-04")
    store.insert_pattern_signals(
        [
            {
                "run_id": run_id,
                "trade_date": "2026-11-04",
                "ticker": "RELIANCE",
                "pattern_type": "vcp",
                "macro_pass": True,
                "score": 82,
                "triggered_today": False,
                "setup_ready": True,
                "details": {"pivot_high": 101.5},
            }
        ]
    )
    myb_run = store.create_myb_run("2026-11-04", lookback_years=5)
    store.insert_myb_signals(
        [
            {
                "run_id": myb_run,
                "trade_date": "2026-11-04",
                "ticker": "RELIANCE",
                "status": "near",
                "lookback_years": 5,
                "prior_high": 140,
                "close_price": 99,
                "score": 70,
            }
        ]
    )
    store.upsert_futures_oi_daily(
        [
            {
                "trade_date": "2026-11-04",
                "instrument_key": "NSE_FO|61697",
                "symbol": "RELIANCE",
                "expiry": "2026-11-23",
                "oi": 15000,
                "poi": 14000,
                "ltp": 100,
                "prev_close": 99,
            }
        ]
    )

    universe = [
        UniverseSymbol(
            symbol="RELIANCE",
            company_name="Reliance",
            sector="Energy",
            cash_key="NSE_EQ|INE002A01018",
            future_key="NSE_FO|61697",
            future_expiry="2026-11-23",
        )
    ]
    context = load_context(universe, before_date="2026-11-05", store=store)["RELIANCE"]
    assert context.prior_high == 101
    assert context.prior_close == 99
    assert context.avg_volume_20 == 1_100_000
    assert context.history_bars == 2
    assert context.sma20 == 98.5
    assert context.trend_20_pct is not None and round(context.trend_20_pct, 2) == 1.02
    assert context.scanner_pivot == 101.5
    assert context.myb_level == 140
    assert context.seeded_poi == 15000
    assert context.on_last_scan is True
    assert context.days_to_expiry == 18

    rolled_universe = [
        UniverseSymbol(
            symbol="RELIANCE",
            company_name="Reliance",
            sector="Energy",
            cash_key="NSE_EQ|INE002A01018",
            future_key="NSE_FO|99999",
            future_expiry="2026-12-28",
        )
    ]
    rolled = load_context(rolled_universe, before_date="2026-11-05", store=store)["RELIANCE"]
    assert rolled.seeded_poi is None

    writer = LiveScanWriter(store)
    writer.enqueue_minute(
        {
            "instrument_key": "NSE_EQ|INE002A01018",
            "minute_ts": "2026-11-05T09:16",
            "volume": 300,
            "close_price": 100.4,
            "source": "live_ws",
        }
    )
    writer.enqueue_session(
        {
            "trade_date": "2026-11-05",
            "candles": [
                {
                    "trade_date": "2026-11-05",
                    "instrument_token": "NSE_EQ|INE002A01018",
                    "open_price": 99,
                    "high_price": 102,
                    "low_price": 98,
                    "close_price": 101,
                    "volume": 5000,
                    "daily_return_pct": 2.02,
                    "source": "live_ws",
                }
            ],
            "futures_oi": [
                {
                    "trade_date": "2026-11-05",
                    "instrument_key": "NSE_FO|61697",
                    "symbol": "RELIANCE",
                    "expiry": "2026-11-23",
                    "oi": 16000,
                    "poi": 15000,
                    "ltp": 102,
                    "prev_close": 100,
                }
            ],
        }
    )
    writer.stop()

    with store.connection() as conn:
        minute = conn.execute("SELECT volume, close_price FROM live_minute_bars").fetchone()
        candle = conn.execute(
            "SELECT source, close_price FROM daily_candles WHERE trade_date = '2026-11-05'"
        ).fetchone()
        oi = conn.execute(
            "SELECT oi, poi FROM futures_oi_daily WHERE trade_date = '2026-11-05'"
        ).fetchone()
    assert minute["volume"] == 300
    assert candle["source"] == "live_ws"
    assert candle["close_price"] == 101
    assert oi["oi"] == 16000
    assert oi["poi"] == 15000
    assert writer.session_flushes == 1


def test_non_fno_names_stop_at_the_full_mode_key_cap():
    fno = [
        UniverseSymbol("AAA", None, None, "NSE_EQ|AAA", "NSE_FO|AAA", "2026-11-26", segment="fno"),
        UniverseSymbol("BBB", None, None, "NSE_EQ|BBB", None, None, segment="fno"),
    ]
    assert subscription_key_count(fno) == 3
    room = FULL_MODE_KEY_LIMIT - subscription_key_count(fno)
    candidates = [
        {"ticker": "AAA", "instrument_token": "NSE_EQ|AAA", "avg_volume": 9},
        {"ticker": "CASH1", "instrument_token": "NSE_EQ|C1", "avg_volume": 8},
        {"ticker": "CASH2", "instrument_token": "NSE_EQ|C2", "avg_volume": 7},
        {"ticker": "cash1", "instrument_token": "NSE_EQ|DUP", "avg_volume": 6},
    ]
    chosen = select_cash_symbols(candidates, exclude={"AAA"}, room=1)
    assert [row["ticker"] for row in chosen] == ["CASH1"]
    assert room < FULL_MODE_KEY_LIMIT


def test_liquid_cash_profiles_skip_thin_names(tmp_path):
    store = TimelineStore(tmp_path / "cash.db")
    store.upsert_profiles(
        [
            {"instrument_token": "NSE_EQ|LIQ", "ticker": "LIQUID", "company_name": "Liquid", "sector": "X", "isin": "L", "series": "EQ"},
            {"instrument_token": "NSE_EQ|THIN", "ticker": "THIN", "company_name": "Thin", "sector": "X", "isin": "T", "series": "EQ"},
        ]
    )
    bars = []
    for day in range(1, 13):
        bars.append(
            {
                "trade_date": f"2026-10-{day:02d}",
                "instrument_token": "NSE_EQ|LIQ",
                "close_price": 100,
                "volume": 1000 + day,
                "source": "upstox",
            }
        )
    bars.append(
        {
            "trade_date": "2026-10-01",
            "instrument_token": "NSE_EQ|THIN",
            "close_price": 10,
            "volume": 5_000_000,
            "source": "upstox",
        }
    )
    store.upsert_candles(bars)
    rows = store.liquid_cash_profiles("2026-11-06", 10)
    assert [row["ticker"] for row in rows] == ["LIQUID"]


def test_candle_budget_blocks_a_second_burst_inside_the_window():
    budget = CandleRequestBudget(limit=1000, window_sec=1800)
    assert budget.grant(800, now=10.0) == 800
    assert budget.grant(800, now=20.0) == 200
    assert budget.grant(10, now=30.0) == 0
    assert budget.grant(10, now=10.0 + 1800) == 10


def test_cash_segment_is_kept_on_the_session_call():
    call = session_call(_history_quote(segment="cash"), 0.5)
    assert call["segment"] == "cash"
    assert session_call(_history_quote(), 0.5)["segment"] == "fno"
