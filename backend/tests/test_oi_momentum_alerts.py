from __future__ import annotations

from app.services.oi_momentum.alert_log import ALERT_COOLDOWN_SEC, OiAlertDedup, PUT_DEDUP_BUCKET, compute_notify_tier


def test_compute_notify_tier_full_mild():
    alert, phase = compute_notify_tier(
        "mild",
        "full",
        rapid_put_surge=True,
        volume_confirmed=True,
    )
    assert alert == "mild"
    assert phase == "full"


def test_compute_notify_tier_early_partial():
    alert, phase = compute_notify_tier(
        "warming",
        "partial",
        rapid_put_surge=True,
        volume_confirmed=True,
    )
    assert alert == "mild"
    assert phase == "early"


def test_compute_notify_tier_neutral():
    alert, phase = compute_notify_tier(
        "neutral",
        "full",
        rapid_put_surge=False,
        volume_confirmed=False,
    )
    assert alert is None
    assert phase is None


def test_alert_dedup_blocks_repeat():
    dedup = OiAlertDedup()
    key = dedup.notify_key("NIFTY", "mild", "full", 22000.0, 5000)
    assert dedup.is_new("NIFTY", key, window_sec=30) is True
    assert dedup.is_new("NIFTY", key, window_sec=30) is False


def test_alert_dedup_resets_on_new_bucket():
    dedup = OiAlertDedup()
    key1 = dedup.notify_key("NIFTY", "mild", "full", 22000.0, 5000)
    key2 = dedup.notify_key("NIFTY", "mild", "full", 22000.0, 5000 + PUT_DEDUP_BUCKET)
    assert dedup.is_new("NIFTY", key1, window_sec=180) is True
    assert dedup.is_new("NIFTY", key2, window_sec=180) is False  # cooldown blocks
