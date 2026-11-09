"""Persist / reuse Grimes scans by latest candle date."""

from __future__ import annotations

from app.db.store import TimelineStore
from app.services.labs.grimes.engine import ENGINE_VERSION, get_or_run_grimes_scan


def _payload(trade_date: str, ticker: str, *, score: int = 80) -> dict:
    return {
        "timestamp": "2026-09-04T10:00:00+00:00",
        "universe_size": 1,
        "analyzed": 1,
        "workers": 1,
        "engine_version": ENGINE_VERSION,
        "source": "scan",
        "summary": {
            "trend_bull": 1,
            "trend_bear": 0,
            "range": 0,
            "squeeze": 0,
            "climax": 0,
            "pullbacks": 1,
            "squeezes": 0,
            "mean_reversion": 0,
            "high_quality": 1,
        },
        "results": [
            {
                "ticker": ticker,
                "instrument_key": f"NSE_EQ|{ticker}",
                "kind": "equity",
                "company_name": ticker,
                "as_of": trade_date,
                "price": 100.0,
                "regime": "TREND_BULL",
                "swing_trend": "up",
                "ma_stack": "bull",
                "weekly_aligned": True,
                "weekly_ema_up": True,
                "squeeze": False,
                "setup_type": "TREND_PULLBACK",
                "setup_group": "Continuation",
                "setup_side": "long",
                "setup_flags": None,
                "active_setups": [],
                "quality_score": score,
                "volatility_rank": 40.0,
                "atr": 2.0,
                "pivot_count": 8,
            }
        ],
    }


def test_replace_and_load_roundtrip(tmp_path) -> None:
    store = TimelineStore(tmp_path / "t.db")
    store.replace_grimes_scan("2026-09-03", _payload("2026-09-03", "AAA"), engine_version=ENGINE_VERSION)
    loaded = store.load_grimes_summary("2026-09-03", engine_version=ENGINE_VERSION)
    assert loaded is not None
    assert loaded["source"] == "db"
    assert loaded["analyzed"] == 1
    assert loaded["results"][0]["ticker"] == "AAA"
    assert loaded["summary"]["pullbacks"] == 1


def test_reuse_same_date_without_rerun(tmp_path) -> None:
    store = TimelineStore(tmp_path / "t.db")
    store.upsert_candles(
        [
            {
                "trade_date": "2026-09-03",
                "instrument_token": "NSE_EQ|AAA",
                "open_price": 1,
                "high_price": 1,
                "low_price": 1,
                "close_price": 1,
                "volume": 1,
            }
        ]
    )
    calls: list[str] = []

    def runner(*, store, as_of=None):  # noqa: ARG001
        calls.append("run")
        return _payload("2026-09-03", "AAA")

    first = get_or_run_grimes_scan(store=store, runner=runner)
    second = get_or_run_grimes_scan(store=store, runner=runner)
    assert first["source"] == "scan"
    assert second["source"] == "db"
    assert second["results"][0]["ticker"] == "AAA"
    assert calls == ["run"]


def test_new_candle_date_runs_again_not_previous_day(tmp_path) -> None:
    store = TimelineStore(tmp_path / "t.db")
    store.upsert_candles(
        [
            {
                "trade_date": "2026-09-03",
                "instrument_token": "NSE_EQ|AAA",
                "open_price": 1,
                "high_price": 1,
                "low_price": 1,
                "close_price": 1,
                "volume": 1,
            }
        ]
    )
    get_or_run_grimes_scan(store=store, runner=lambda **_: _payload("2026-09-03", "OLD"))
    store.upsert_candles(
        [
            {
                "trade_date": "2026-09-04",
                "instrument_token": "NSE_EQ|AAA",
                "open_price": 2,
                "high_price": 2,
                "low_price": 2,
                "close_price": 2,
                "volume": 1,
            }
        ]
    )
    calls: list[str] = []

    def runner(*, store, as_of=None):  # noqa: ARG001
        calls.append("run")
        return _payload("2026-09-04", "NEW")

    out = get_or_run_grimes_scan(store=store, runner=runner)
    assert calls == ["run"]
    assert out["trade_date"] == "2026-09-04"
    assert out["results"][0]["ticker"] == "NEW"
    yesterday = store.load_grimes_summary("2026-09-03", engine_version=ENGINE_VERSION)
    assert yesterday is not None
    assert yesterday["results"][0]["ticker"] == "OLD"


def test_refresh_overwrites_same_date(tmp_path) -> None:
    store = TimelineStore(tmp_path / "t.db")
    store.upsert_candles(
        [
            {
                "trade_date": "2026-09-04",
                "instrument_token": "NSE_EQ|AAA",
                "open_price": 1,
                "high_price": 1,
                "low_price": 1,
                "close_price": 1,
                "volume": 1,
            }
        ]
    )
    get_or_run_grimes_scan(store=store, runner=lambda **_: _payload("2026-09-04", "OLD", score=10))
    out = get_or_run_grimes_scan(
        refresh=True,
        store=store,
        runner=lambda **_: _payload("2026-09-04", "NEW", score=90),
    )
    assert out["source"] == "scan"
    assert out["results"][0]["ticker"] == "NEW"
    loaded = store.load_grimes_summary("2026-09-04", engine_version=ENGINE_VERSION)
    assert loaded is not None
    assert loaded["results"][0]["ticker"] == "NEW"


def _candle(date: str, token: str = "NSE_EQ|AAA") -> dict:
    return {
        "trade_date": date,
        "instrument_token": token,
        "open_price": 1,
        "high_price": 1,
        "low_price": 1,
        "close_price": 1,
        "volume": 1,
    }


def test_select_historical_date_loads_that_run(tmp_path) -> None:
    store = TimelineStore(tmp_path / "t.db")
    store.upsert_candles([_candle("2026-09-03"), _candle("2026-09-04")])
    get_or_run_grimes_scan(
        trade_date="2026-09-03",
        refresh=True,
        store=store,
        runner=lambda **_: _payload("2026-09-03", "OLD"),
    )
    get_or_run_grimes_scan(
        trade_date="2026-09-04",
        store=store,
        runner=lambda **_: _payload("2026-09-04", "NEW"),
    )
    calls: list[str] = []

    def runner(**_kwargs):
        calls.append("run")
        return _payload("2026-09-03", "SHOULD_NOT")

    out = get_or_run_grimes_scan(trade_date="2026-09-03", store=store, runner=runner)
    assert calls == []
    assert out["trade_date"] == "2026-09-03"
    assert out["source"] == "db"
    assert out["results"][0]["ticker"] == "OLD"
    assert store.list_grimes_dates() == ["2026-09-04", "2026-09-03"]


def test_missing_historical_date_does_not_autorun(tmp_path) -> None:
    store = TimelineStore(tmp_path / "t.db")
    store.upsert_candles([_candle("2026-09-03"), _candle("2026-09-04")])
    get_or_run_grimes_scan(
        trade_date="2026-09-04",
        store=store,
        runner=lambda **_: _payload("2026-09-04", "NEW"),
    )
    calls: list[str] = []
    out = get_or_run_grimes_scan(
        trade_date="2026-09-03",
        store=store,
        runner=lambda **k: calls.append("run") or _payload("2026-09-03", "X"),
    )
    assert calls == []
    assert out["has_run"] is False
    assert out["results"] == []
    assert out["trade_date"] == "2026-09-03"
