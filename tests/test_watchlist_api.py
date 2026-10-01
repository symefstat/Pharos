"""Tests for /api/watchlist (public read, admin-gated writes, term resolution)
and the Briefing "since your last visit" aggregation. Fake Supabase client;
no network. Follows tests/test_forecasts_api.py patterns."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.briefing as bb
import backend.app.watchlist as bw
from analytics.watchlist import find_watch_matches, resolve_term
from backend.app.briefing import count_since


# ── pure: term → (kind, value) resolution ─────────────────────────────────────

def test_resolve_term_technology_by_label_or_key():
    assert resolve_term("GLP-1 drugs") == ("technology", "glp-1")
    assert resolve_term("glp-1") == ("technology", "glp-1")
    assert resolve_term("  Advanced logic (≤3nm) ") == ("technology", "advanced-logic")


def test_resolve_term_feed_by_label():
    assert resolve_term("chips") == ("feed", "Chips")
    assert resolve_term("AI & Energy") == ("feed", "AI & Energy")


def test_resolve_term_entity_fallback_keeps_casing():
    assert resolve_term("  Nvidia ") == ("entity", "Nvidia")


def test_find_watch_matches_value_and_tech_label():
    items = [
        {"kind": "entity", "value": "Nvidia"},
        {"kind": "technology", "value": "glp-1"},
    ]
    assert find_watch_matches(items, "nvidia") == [("entity", "Nvidia")]
    # a technology matches by stored key OR display label
    assert find_watch_matches(items, "GLP-1 drugs") == [("technology", "glp-1")]
    assert find_watch_matches(items, "glp-1") == [("technology", "glp-1")]
    assert find_watch_matches(items, "unknown") == []


# ── pure: since-your-last-visit counts ────────────────────────────────────────

def test_count_since_counts_resolved_and_trustworthy_transitions():
    preds = [
        {"status": "resolved", "resolved_on": "2026-07-05"},          # after → counted
        {"status": "resolved", "resolved_on": "2026-06-01"},          # before → no
        {"status": "open", "resolved_on": None},                      # open → no
        {"status": "resolved", "resolved_on": None},                  # undated → no
    ]
    transitions = [
        {"as_of": "2026-07-06", "suspect": False},                    # counted
        {"as_of": "2026-07-06", "suspect": True},                     # suspect → no
        {"as_of": "2026-01-01"},                                      # before → no
    ]
    out = count_since(preds, transitions, "2026-07-01T08:00:00.000Z")
    assert out == {"resolved": 1, "transitions": 1}


def test_count_since_date_only_boundary_counts_as_new():
    # A date-only resolved_on on the visit day is treated as end-of-day: shown.
    preds = [{"status": "resolved", "resolved_on": "2026-07-01"}]
    assert count_since(preds, [], "2026-07-01T08:00:00Z")["resolved"] == 1


def test_count_since_empty_inputs():
    assert count_since([], [], "2026-07-01T00:00:00Z") == {"resolved": 0, "transitions": 0}


# ── fake Supabase (watchlist table only) ──────────────────────────────────────

class _FakeQuery:
    def __init__(self, sb):
        self._sb = sb
        self._mode = "select"
        self._payload = None
        self._filters = []

    def select(self, *_a, **_k):
        self._mode = "select"
        return self

    def order(self, *_a, **_k):
        return self

    def upsert(self, payload, **_k):
        self._mode = "upsert"
        self._payload = dict(payload)
        return self

    def delete(self):
        self._mode = "delete"
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def execute(self):
        if self._mode == "upsert":
            key = (self._payload["kind"], self._payload["value"])
            if not any((r["kind"], r["value"]) == key for r in self._sb.rows):
                self._sb.rows.append(
                    {"id": self._sb.next_id, "created_at": "2026-07-08T00:00:00Z",
                     **self._payload})
                self._sb.next_id += 1
            self._sb.upsert_calls.append(dict(self._payload))
            return SimpleNamespace(data=[])
        if self._mode == "delete":
            self._sb.delete_calls.append(list(self._filters))
            self._sb.rows = [
                r for r in self._sb.rows
                if not all(r.get(c) == v for c, v in self._filters)
            ]
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=[dict(r) for r in self._sb.rows])


class FakeSupabase:
    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.next_id = max([r.get("id", 0) for r in self.rows], default=0) + 1
        self.upsert_calls = []
        self.delete_calls = []

    def table(self, name):
        assert name == "watchlist"
        return _FakeQuery(self)


@pytest.fixture()
def fake(monkeypatch):
    fake = FakeSupabase([
        {"id": 1, "kind": "entity", "value": "Nvidia", "created_at": "2026-06-01T00:00:00Z"},
        {"id": 2, "kind": "technology", "value": "glp-1", "created_at": "2026-06-02T00:00:00Z"},
    ])
    import db

    monkeypatch.setattr(db, "get_supabase", lambda: fake)
    return fake


@pytest.fixture()
def client():
    """Authenticated-admin client (dependency override); anonymous gating is
    pinned by test_anonymous_writes_get_401."""
    from backend.app.auth import require_admin

    app = FastAPI()
    app.include_router(bw.router)
    app.dependency_overrides[require_admin] = lambda: "admin"
    return TestClient(app)


@pytest.fixture()
def anon_client():
    app = FastAPI()
    app.include_router(bw.router)
    return TestClient(app)


# ── GET /api/watchlist — public read ──────────────────────────────────────────

def test_get_watchlist_is_public(anon_client, fake, monkeypatch):
    monkeypatch.setattr(bw.data, "rows", lambda days=30: [])
    r = anon_client.get("/api/watchlist")
    assert r.status_code == 200
    items = r.json()["items"]
    assert [it["term"] for it in items] == ["Nvidia", "glp-1"]
    assert items[0]["added_on"] == "2026-06-01T00:00:00Z"
    # technologies expose their display label alongside the stored key
    assert items[1]["label"] == "GLP-1 drugs"
    # the additive moves field is always present (empty here — no classified rows)
    assert all(it["moves"] == [] for it in items)


def test_get_watchlist_carries_recent_entity_moves(anon_client, fake, monkeypatch):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(bw.data, "rows", lambda days=30: [
        {"title": "Nvidia opens platform", "url": "u1", "_feed_label": "Chips",
         "companies": ["Nvidia"], "strategic_move": "platform",
         "published_at": now, "business_impact": "material"},
        # no strategic move → must not surface
        {"title": "Nvidia earnings", "url": "u2", "_feed_label": "Chips",
         "companies": ["Nvidia"], "strategic_move": "none",
         "published_at": now, "business_impact": "material"},
    ])
    items = anon_client.get("/api/watchlist").json()["items"]
    by_term = {it["term"]: it for it in items}
    moves = by_term["Nvidia"]["moves"]
    assert [m["move"] for m in moves] == ["platform"]
    assert moves[0]["entity"] == "Nvidia" and moves[0]["url"] == "u1"
    # non-entity entries never carry moves
    assert by_term["glp-1"]["moves"] == []


def test_get_watchlist_moves_failure_is_non_fatal(anon_client, fake, monkeypatch):
    def _boom(days=30):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(bw.data, "rows", _boom)
    r = anon_client.get("/api/watchlist")
    assert r.status_code == 200
    assert all(it["moves"] == [] for it in r.json()["items"])


# ── POST / DELETE — the admin gate ────────────────────────────────────────────

def test_anonymous_writes_get_401(anon_client, fake):
    r = anon_client.post("/api/watchlist", json={"term": "TSMC"})
    assert r.status_code == 401
    r = anon_client.delete("/api/watchlist/Nvidia")
    assert r.status_code == 401
    # nothing written or removed
    assert fake.upsert_calls == [] and fake.delete_calls == []
    assert len(fake.rows) == 2


def test_add_entity(client, fake):
    r = client.post("/api/watchlist", json={"term": "  TSMC  "})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "item": {"kind": "entity", "term": "TSMC"}}
    assert {"kind": "entity", "value": "TSMC"} in fake.upsert_calls


def test_add_resolves_technology_label_to_key(client, fake):
    r = client.post("/api/watchlist", json={"term": "Solid-state batteries"})
    assert r.status_code == 200
    assert r.json()["item"] == {"kind": "technology", "term": "solid-state-batteries"}


def test_add_resolves_feed_label(client, fake):
    r = client.post("/api/watchlist", json={"term": "chips"})
    assert r.status_code == 200
    assert r.json()["item"] == {"kind": "feed", "term": "Chips"}


def test_add_validates_term_length(client, fake):
    assert client.post("/api/watchlist", json={"term": "   "}).status_code == 400
    assert client.post("/api/watchlist", json={"term": "x" * 81}).status_code == 400
    assert fake.upsert_calls == []


def test_delete_by_value(client, fake):
    r = client.delete("/api/watchlist/nvidia")  # case-insensitive
    assert r.status_code == 200 and r.json() == {"ok": True, "removed": 1}
    assert [("kind", "entity"), ("value", "Nvidia")] in fake.delete_calls
    assert all(row["value"] != "Nvidia" for row in fake.rows)


def test_delete_technology_by_label(client, fake):
    r = client.delete("/api/watchlist/GLP-1%20drugs")
    assert r.status_code == 200 and r.json()["removed"] == 1
    assert all(row["value"] != "glp-1" for row in fake.rows)


def test_delete_unknown_term_404(client, fake):
    r = client.delete("/api/watchlist/UnknownCo")
    assert r.status_code == 404
    assert fake.delete_calls == []


# ── GET /api/briefing/since ───────────────────────────────────────────────────

@pytest.fixture()
def since_client(monkeypatch):
    preds = [
        {"status": "resolved", "resolved_on": "2026-07-05"},
        {"status": "resolved", "resolved_on": "2026-05-01"},
    ]
    monkeypatch.setattr(bb.data, "predictions", lambda: preds)
    monkeypatch.setattr(bb.data, "_supabase", lambda: None)

    class FakeAnalyst:
        def __init__(self, _client):
            pass

        def transitions(self):
            return [
                {"as_of": "2026-07-06", "suspect": False},
                {"as_of": "2026-07-06", "suspect": True},
            ]

    import analytics.tech_layer as tl

    monkeypatch.setattr(tl, "TechAnalyst", FakeAnalyst)
    app = FastAPI()
    app.include_router(bb.router)
    return TestClient(app)


def test_briefing_since_counts(since_client):
    r = since_client.get("/api/briefing/since?ts=2026-07-01T00:00:00Z")
    assert r.status_code == 200
    assert r.json() == {"resolved": 1, "transitions": 1}


def test_briefing_since_rejects_garbage_ts(since_client):
    assert since_client.get("/api/briefing/since?ts=notadate").status_code == 400
    assert since_client.get("/api/briefing/since?ts=").status_code == 400
