"""Tests for watchlist alert matching + formatting (pure)."""

from analytics.watchlist import match_alerts, format_alerts


def test_match_entity_feed_and_technology():
    items = [("entity", "Nvidia"), ("feed", "Chips"), ("technology", "advanced-logic")]
    rows = [
        {"title": "Nvidia ships Blackwell", "url": "u1", "_feed_label": "AI & Energy", "companies": ["Nvidia"]},
        {"title": "TSMC 2nm node ramps", "url": "u2", "_feed_label": "Chips", "companies": ["TSMC"]},
        {"title": "Unrelated EV story", "url": "u3", "_feed_label": "EV", "companies": ["Rivian"]},
    ]
    transitions = [{"technology": "advanced-logic", "label": "Advanced logic (≤3nm)",
                    "dimension": "maturity", "from": "emerging", "to": "growth", "as_of": "2026-06-12"}]
    alerts = match_alerts(items, rows, transitions)
    types = {(a["type"], a["subject"]) for a in alerts}
    assert ("entity", "Nvidia") in types               # Nvidia story
    assert ("feed", "Chips") in types                   # TSMC story is in Chips feed
    assert ("technology", "Advanced logic (≤3nm)") in types  # 2nm matches the tech keywords
    assert ("transition", "Advanced logic (≤3nm)") in types  # stage transition
    # the unrelated EV story produced nothing
    assert all(a.get("url") != "u3" for a in alerts)


def test_match_skips_suspect_transitions():
    # A backward / unconfirmed / contested move is a watch-item, not a push-worthy
    # alert — even for a watched technology it must NOT produce a transition alert.
    items = [("technology", "advanced-logic")]
    suspect = [{"technology": "advanced-logic", "label": "Advanced logic (≤3nm)",
                "dimension": "maturity", "from": "growth", "to": "research",
                "as_of": "2026-06-13", "backward": True, "suspect": True}]
    alerts = match_alerts([], [], suspect)
    assert all(a["type"] != "transition" for a in alerts)


def test_match_dedups():
    items = [("entity", "Nvidia"), ("feed", "Chips")]
    rows = [{"title": "Nvidia x", "url": "u", "_feed_label": "Chips", "companies": ["Nvidia"]},
            {"title": "Nvidia x", "url": "u", "_feed_label": "Chips", "companies": ["Nvidia"]}]
    alerts = match_alerts(items, rows, [])
    # one entity alert + one feed alert (deduped on url), not four
    assert len([a for a in alerts if a["type"] == "entity"]) == 1
    assert len([a for a in alerts if a["type"] == "feed"]) == 1


def test_match_empty_items():
    assert match_alerts([], [{"title": "x", "companies": ["Nvidia"]}], []) == []


def test_format_alerts():
    out = format_alerts([
        {"type": "entity", "subject": "Nvidia", "feed": "Chips", "title": "ships GPU", "url": "http://x"},
        {"type": "transition", "subject": "GLP-1", "detail": "adoption early-adopters → early-majority"},
    ], as_of="2026-06-12")
    assert "Lodestar alerts (2)" in out
    assert "Nvidia" in out and "http://x" in out
    assert "stage transition" in out and "GLP-1" in out
    assert format_alerts([]) == ""
