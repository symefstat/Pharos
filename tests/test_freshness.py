"""Tests for the pure freshness logic (freshness_check.stale_feeds / format_alert)."""

from datetime import datetime, timedelta, timezone

from freshness_check import format_alert, stale_feeds

NOW = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)


def _ago(hours):
    return NOW - timedelta(hours=hours)


def test_flags_stale_and_empty_not_fresh():
    newest = {"ev": _ago(3), "chips": _ago(13), "biotech": None}
    out = {s["feed"]: s for s in stale_feeds(newest, NOW)}   # 6h × 2 = 12h threshold
    assert "ev" not in out                       # 3h old → fresh
    assert out["chips"]["age_hours"] == 13.0      # 13h > 12h → stale
    assert out["biotech"]["age_hours"] is None and "no rows" in out["biotech"]["reason"]


def test_threshold_boundary():
    assert stale_feeds({"a": _ago(12)}, NOW) == []                       # exactly 12h → not stale
    assert [s["feed"] for s in stale_feeds({"a": _ago(12.1)}, NOW)] == ["a"]  # just over → stale


def test_custom_interval():
    # daily feed (24h interval) → 48h threshold; 30h old is still fresh
    assert stale_feeds({"a": _ago(30)}, NOW, interval_hours=24) == []
    assert [s["feed"] for s in stale_feeds({"a": _ago(50)}, NOW, interval_hours=24)] == ["a"]


def test_format_alert_lists_feeds():
    txt = format_alert(
        [{"feed": "chips", "age_hours": 13.0, "reason": "newest row 13.0h old (> 12h threshold)"}],
        "2026-06-13 12:00 UTC")
    assert "chips" in txt and "freshness" in txt.lower() and "1 stalled" in txt
