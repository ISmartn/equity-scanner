"""Order Flow: session rules, the market file encoder, and the Upstox parsers. Offline."""

from __future__ import annotations

import datetime as dt

from app.services.order_flow.collector import load_universe
from app.services.order_flow.market_file import encode_series, leg_row
from app.services.order_flow.provider import parse_candles, parse_option_chain
from app.services.order_flow.session import (
    IST,
    filter_live_expiries,
    is_expiry_settled,
    is_market_session_time,
    latest_trading_session_date,
)


def ist(year: int, month: int, day: int, hour: int, minute: int = 0) -> float:
    return dt.datetime(year, month, day, hour, minute, tzinfo=IST).timestamp() * 1000


# ── Session rules ─────────────────────────────────────────────────────────


def test_session_open_during_market_hours_only() -> None:
    assert is_market_session_time(ist(2026, 11, 13, 10))
    assert not is_market_session_time(ist(2026, 11, 13, 8))
    assert not is_market_session_time(ist(2026, 11, 14, 10))  # Saturday
    assert not is_market_session_time(ist(2026, 11, 10, 10))  # Diwali holiday


def test_latest_session_rolls_back_before_open_and_on_closed_days() -> None:
    assert latest_trading_session_date(ist(2026, 11, 13, 10)) == "2026-11-13"
    assert latest_trading_session_date(ist(2026, 11, 13, 8)) == "2026-11-12"
    assert latest_trading_session_date(ist(2026, 11, 15, 10)) == "2026-11-13"


def test_expiries_settle_at_the_derivatives_close_on_their_own_date() -> None:
    assert is_expiry_settled("2026-11-12", ist(2026, 11, 13, 10))
    assert not is_expiry_settled("2026-11-24", ist(2026, 11, 13, 10))
    assert not is_expiry_settled("2026-11-13", ist(2026, 11, 13, 15, 39))
    assert is_expiry_settled("2026-11-13", ist(2026, 11, 13, 15, 41))


def test_filter_live_expiries_drops_settled_duplicates_and_bad_dates() -> None:
    live = filter_live_expiries(["2026-11-10", "2026-11-24", "2026-11-24", "soon"], ist(2026, 11, 13, 10))
    assert live == ["2026-11-24"]


# ── Market file ───────────────────────────────────────────────────────────


def _leg(oi: float, volume: float = 0, ltp: float = 10.0) -> dict:
    return {"ltp": ltp, "oi": oi, "volume": volume, "prevClose": 9.0, "prevOi": oi - 1, "iv": 20.0, "delta": 0.5}


def test_leg_without_oi_or_volume_is_dropped_unless_kept_idle() -> None:
    assert leg_row(100, 0, _leg(oi=0)) is None
    assert leg_row(100, 0, _leg(oi=0), keep_idle=True) is not None


def test_series_orders_rows_by_strike_then_side_and_picks_nearest_atm() -> None:
    chain = {
        "expiry": "2026-11-24",
        "at": 1.0,
        "spot": 101.2,
        "prevClose": 100.0,
        "atm": None,
        "strikes": [
            {"strike": 105.0, "call": _leg(oi=5), "put": None},
            {"strike": 100.0, "call": _leg(oi=3), "put": _leg(oi=4)},
        ],
    }
    series = encode_series({"symbol": "TEST", "kind": "stock", "lot": 10}, chain, 1234.4)
    assert series is not None
    assert [row[:2] for row in series["r"]] == [[100.0, 0], [100.0, 1], [105.0, 0]]
    assert series["atm"] == 100.0
    assert series["ks"] == [100.0, 105.0]
    assert series["t"] == 1234


def test_series_without_a_priced_spot_is_skipped() -> None:
    assert encode_series({"symbol": "X", "kind": "stock", "lot": 1}, {"spot": 0, "strikes": []}, 0) is None


# ── Upstox parsers ────────────────────────────────────────────────────────


def test_option_chain_maps_upstox_fields_to_the_contract() -> None:
    payload = {
        "data": [
            {
                "strike_price": 1340,
                "underlying_spot_price": 1341.5,
                "call_options": {
                    "market_data": {"ltp": 20, "close_price": 18, "oi": 500, "prev_oi": 450, "volume": 900, "bid_price": 19.9, "ask_price": 20.1, "bid_qty": 10, "ask_qty": 20},
                    "option_greeks": {"iv": 21.5, "delta": 0.55},
                },
                "put_options": {"market_data": {"ltp": 0, "oi": 0, "volume": 0}},
            }
        ]
    }
    chain = parse_option_chain(payload, expiry="2026-11-24", at=5.0, prev_close=1339.7)
    assert chain["spot"] == 1341.5
    assert chain["prevClose"] == 1339.7
    call = chain["strikes"][0]["call"]
    assert (call["ltp"], call["prevClose"], call["oi"], call["prevOi"], call["iv"], call["delta"]) == (20, 18, 500, 450, 21.5, 0.55)
    assert chain["strikes"][0]["put"]["oi"] == 0


def test_candles_are_read_as_close_and_oi_in_ascending_order() -> None:
    payload = {
        "data": {
            "candles": [
                ["2026-11-13T09:16:00+05:30", 1, 1, 1, 1343.4, 10, 128570000],
                ["2026-11-13T09:15:00+05:30", 1, 1, 1, 1334.6, 10, 128394000],
                ["2026-11-13T09:17:00+05:30", 1, 1, 1, 0, 10, 1],  # no price: dropped
            ]
        }
    }
    candles = parse_candles(payload)
    assert [c["close"] for c in candles] == [1334.6, 1343.4]
    assert candles[0]["at"] < candles[1]["at"]


def test_universe_loads_every_priced_underlying() -> None:
    universe = load_universe()
    assert len(universe) == 217
    assert {u["symbol"] for u in universe} >= {"NIFTY", "RELIANCE"}


# ── The trigger log ───────────────────────────────────────────────────────


def _signal(**over):
    row = {
        "id": "RELIANCE:1000", "symbol": "RELIANCE", "kind": "buy", "state": "active", "triggeredAt": 2000.0,
        "entryLow": 1400.0, "entryHigh": 1410.0, "stop": 1400.0, "target": {"name": "R1", "price": 1440.0},
        "staleAt": None, "staleReason": None, "context": {"strength": 0.8, "buildUp": "LONG_BUILD"},
    }
    row.update(over)
    return row


def test_signal_log_records_and_keeps_a_stale_trigger_stale(tmp_path) -> None:
    from app.services.order_flow.signal_log import SignalLog

    log = SignalLog(tmp_path)
    assert log.upsert("2026-11-26", [_signal()], now_ms=5)["added"] == 1
    # The same trigger again changes nothing.
    assert log.upsert("2026-11-26", [_signal()], now_ms=6) == {"added": 0, "updated": 0, "total": 1}
    stale = _signal(state="stale", staleAt=3000.0, staleReason="Stop broken at 1399.00")
    assert log.upsert("2026-11-26", [stale], now_ms=7)["updated"] == 1
    # An older, still-active copy arriving late must not bring it back.
    log.upsert("2026-11-26", [_signal()], now_ms=8)
    [row] = log.read("2026-11-26")["signals"]
    assert row["state"] == "stale" and row["staleReason"].startswith("Stop broken")
    assert row["recordedAt"] == 5 and row["updatedAt"] == 7
    assert log.dates() == [{"date": "2026-11-26", "count": 1}]


def test_signal_log_candles_never_shrink(tmp_path) -> None:
    from app.services.order_flow.signal_log import SignalLog

    log = SignalLog(tmp_path)
    log.upsert("2026-11-26", [_signal()])
    log.put_candles("2026-11-26", "RELIANCE", [[1, 1400.0, 10.0], [2, 1401.0, 11.0]])
    log.put_candles("2026-11-26", "RELIANCE", [[1, 1400.0, 10.0]])
    assert log.read("2026-11-26", with_candles=True)["candles"]["RELIANCE"] == [[1, 1400.0, 10.0], [2, 1401.0, 11.0]]


def test_signal_routes_validate_and_round_trip(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routes import order_flow as routes
    from app.services.order_flow.signal_log import SignalLog

    log = SignalLog(tmp_path)
    monkeypatch.setattr(routes, "get_signal_log", lambda: log)
    client = TestClient(app)
    ok = client.post("/api/order-flow/signals", json={"date": "2026-11-26", "signals": [_signal()]})
    assert ok.status_code == 200 and ok.json()["added"] == 1
    assert client.post("/api/order-flow/signals", json={"date": "../x", "signals": []}).status_code == 422
    assert client.post("/api/order-flow/signals", json={"date": "2026-11-26", "signals": [_signal(kind="hold")]}).status_code == 422
    assert client.put("/api/order-flow/signals/2026-11-26/candles/RELIANCE", json={"candles": [[1, 2, 3]]}).status_code == 200
    got = client.get("/api/order-flow/signals/2026-11-26?candles=1").json()
    assert got["count"] == 1 and got["candles"]["RELIANCE"] == [[1.0, 2.0, 3.0]]
    assert client.get("/api/order-flow/signals/dates").json() == [{"date": "2026-11-26", "count": 1}]
    assert client.get("/api/order-flow/signals/not-a-date").status_code == 400
