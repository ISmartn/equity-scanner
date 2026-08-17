"""Tests for candle ingest fallback and auto-skip logic."""

from __future__ import annotations

from app.services.candle_ingestion import (
    _ingest_skip_reason,
    _is_transient_ingest_error,
    _should_auto_skip,
    _upstox_invalid_instrument,
    parse_ingest_error_log,
)


def test_upstox_invalid_instrument_detection() -> None:
    exc = Exception('Upstox API error [400]: {"errorCode":"UDAPI100011","message":"Invalid Instrument key"}')
    assert _upstox_invalid_instrument(exc) is True


def test_should_not_auto_skip_on_nse_session_error() -> None:
    msg = "NSE returned HTML instead of JSON for JBCHEPHARM (session expired or rate limited)."
    assert _is_transient_ingest_error(msg) is True
    assert _should_auto_skip(msg, prior_error_count=0) is False
    assert _should_auto_skip(msg, prior_error_count=2) is False


def test_should_auto_skip_on_repeat_failure() -> None:
    assert _should_auto_skip("symbol delisted on NSE", prior_error_count=1) is True


def test_should_not_auto_skip_first_transient() -> None:
    assert _should_auto_skip("timeout connecting to upstox", prior_error_count=0) is False


def test_ingest_skip_reason_mapping() -> None:
    assert _ingest_skip_reason("UDAPI100011 Invalid Instrument key") == "upstox_invalid_instrument"
    assert _ingest_skip_reason("unexpected mimetype: text/html") == "nse_blocked_or_delisted"


def test_parse_ingest_error_log_counts(tmp_path) -> None:
    log = tmp_path / "errors.log"
    log.write_text(
        "2026-07-17T07:02:22.916016+00:00\terror\tJBCHEPHARM\tUpstox invalid\n"
        "2026-07-17T07:03:00.000000+00:00\terror\tJBCHEPHARM\tNSE failed\n"
        "2026-07-17T07:04:00.000000+00:00\tskip\tSKIL\tmarked ingest_skip\n",
        encoding="utf-8",
    )
    parsed = parse_ingest_error_log(log)
    assert parsed["error"] == {"JBCHEPHARM"}
    assert parsed["error_counts"]["JBCHEPHARM"] == 2
