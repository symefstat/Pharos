"""Tests for /api/home — the landing page's cheap cached payload. Pure helpers
plus the route with a fake data layer; no network."""

from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.home as bh


def test_pulse_counts_window_and_feeds():
    rows = [
        {"published_at": "2026-07-07", "_feed_label": "EV"},
        {"published_at": "2026-07-06", "_feed_label": "Chips"},
        {"published_at": "2026-06-01", "_feed_label": "EV"},   # outside 7d
        {"published_at": "2026-07-05"},                          # no feed label
    ]
    out = bh.pulse_counts(rows, today=date(2026, 7, 8))
    assert out["articles_7d"] == 3
    assert out["feeds_active"] == 2  # EV + Chips; None excluded


def test_brief_teaser_shapes():
    assert bh.brief_teaser(None) is None
    assert bh.brief_teaser({"strategic_read": None}) is None
    row = {"as_of": "2026-07-08", "strategic_read": {
        "bottom_line": "Power is the bottleneck.", "confidence": "high",
        "signals": [{"title": "Sig A"}, {"title": "Sig B"}]}}
    t = bh.brief_teaser(row)
    assert t == {"as_of": "2026-07-08", "bottom_line": "Power is the bottleneck.",
                 "confidence": "high", "signal_count": 2, "top_signal": "Sig A"}


def test_home_route_degrades_and_reconciles(monkeypatch):
    preds = [
        {"kind": "manual", "status": "resolved", "outcome": "hit", "confidence": 0.8},
        {"kind": "deal_flow", "status": "open", "confidence": 0.6},
    ]
    monkeypatch.setattr(bh.data, "predictions", lambda: preds)
    monkeypatch.setattr(bh.data, "rows", lambda days=30: [])
    monkeypatch.setattr(bh.data, "falsifier_events", lambda: [])
    monkeypatch.setattr(bh, "_latest_brief", lambda: None)
    monkeypatch.setattr(bh, "_tech_teaser", lambda: {"on_curve": 0, "watching": 0})

    app = FastAPI()
    app.include_router(bh.router)
    out = TestClient(app).get("/api/home").json()

    assert out["today"] is None                      # no brief yet → clean page
    assert out["record"]["external"]["resolved"] == 1
    assert out["record"]["open"] == 1 and out["record"]["total"] == 2
    assert out["pulse"] == {"articles_7d": 0, "feeds_active": 0}
    assert out["falsifier_events"] == 0
