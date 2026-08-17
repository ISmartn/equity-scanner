from __future__ import annotations

from app.services.news.event_study import event_session_date
from app.services.news.name_linker import normalize_company_name


def test_event_session_date_same_day_before_close() -> None:
    assert event_session_date("2026-08-11T10:30:00+05:30") == "2026-08-11"


def test_event_session_date_after_close_rolls_forward() -> None:
    assert event_session_date("2026-08-11T15:45:00+05:30") == "2026-08-12"


def test_event_session_date_friday_after_close_to_monday() -> None:
    assert event_session_date("2026-08-07T16:00:00+05:30") == "2026-08-10"


def test_normalize_company_name() -> None:
    assert normalize_company_name("Reliance Industries Limited") == "reliance"
    assert normalize_company_name("HDFC Bank Ltd") == "hdfc"
