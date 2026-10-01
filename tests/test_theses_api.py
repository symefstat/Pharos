"""Tests for /api/theses (the private thesis book — EVERY endpoint admin-gated,
including reads), following tests/test_watchlist_api.py patterns. Fake Supabase
client; no network."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.theses as bt


# ── fake Supabase (theses + thesis_events tables) ─────────────────────────────

class _FakeQuery:
    def __init__(self, sb, table):
        self._sb = sb
        self._table = table
        self._mode = "select"
        self._payload = None
        self._filters = []

    def select(self, *_a, **_k):
        self._mode = "select"
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def in_(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def insert(self, payload, **_k):
        self._mode = "insert"
        self._payload = dict(payload)
        return self

    def update(self, payload, **_k):
        self._mode = "update"
        self._payload = dict(payload)
        return self

    def _rows(self):
        return self._sb.tables[self._table]

    def execute(self):
        if self._mode == "insert":
            row = {"id": self._sb.next_id, "confirmer": None, "archived": False,
                   "created_at": "2026-07-08T00:00:00Z", **self._payload}
            self._sb.next_id += 1
            self._rows().append(row)
            return SimpleNamespace(data=[dict(row)])
        if self._mode == "update":
            hit = [r for r in self._rows()
                   if all(r.get(c) == v for c, v in self._filters)]
            for r in hit:
                r.update(self._payload)
            return SimpleNamespace(data=[dict(r) for r in hit])
        rows = [r for r in self._rows()
                if all(r.get(c) == v for c, v in self._filters)]
        return SimpleNamespace(data=[dict(r) for r in rows])


class FakeSupabase:
    def __init__(self, theses=None, events=None):
        self.tables = {"theses": [dict(r) for r in (theses or [])],
                       "thesis_events": [dict(r) for r in (events or [])]}
        self.next_id = max([r.get("id", 0) for r in self.tables["theses"]], default=0) + 1

    def table(self, name):
        assert name in self.tables
        return _FakeQuery(self, name)


_THESES = [
    {"id": 1, "claim": "EU stablecoin rails consolidate",
     "falsifier": "Tether gains MiCA authorization by Q4 2026",
     "confirmer": "Circle expands EURC issuance",
     "created_at": "2026-07-01T00:00:00Z", "archived": False},
    {"id": 2, "claim": "Old thesis", "falsifier": "whatever", "confirmer": None,
     "created_at": "2026-06-01T00:00:00Z", "archived": True},   # archived → hidden
]

_EVENTS = [
    {"id": 10, "thesis_id": 1, "matched": "Tether gains MiCA authorization by Q4 2026",
     "label": "falsifies", "article_url": "https://x/tether-mica",
     "article_title": "Tether receives MiCA authorization", "published_at": "2026-07-07",
     "score": 0.83, "detected_at": "2026-07-08T06:00:00Z"},
]


@pytest.fixture()
def fake(monkeypatch):
    fake = FakeSupabase(theses=_THESES, events=_EVENTS)
    monkeypatch.setattr(bt.data, "_supabase", lambda: fake)
    return fake


@pytest.fixture()
def client():
    """Authenticated-admin client (dependency override); anonymous gating is
    pinned by test_anonymous_gets_401_everywhere."""
    from backend.app.auth import require_admin

    app = FastAPI()
    app.include_router(bt.router)
    app.dependency_overrides[require_admin] = lambda: "admin"
    return TestClient(app)


@pytest.fixture()
def anon_client():
    app = FastAPI()
    app.include_router(bt.router)
    return TestClient(app)


# ── the admin gate: the thesis book is PRIVATE — even reads are gated ─────────

def test_anonymous_gets_401_everywhere(anon_client, fake):
    assert anon_client.get("/api/theses").status_code == 401
    assert anon_client.get("/api/theses/events").status_code == 401
    assert anon_client.post("/api/theses", json={
        "claim": "c", "falsifier": "f"}).status_code == 401
    assert anon_client.delete("/api/theses/1").status_code == 401
    # nothing written or archived
    assert len(fake.tables["theses"]) == 2
    assert fake.tables["theses"][0]["archived"] is False


# ── GET /api/theses ───────────────────────────────────────────────────────────

def test_list_returns_active_theses_only(client, fake):
    r = client.get("/api/theses")
    assert r.status_code == 200
    theses = r.json()["theses"]
    assert [t["id"] for t in theses] == [1]      # the archived one is hidden
    assert theses[0]["claim"] == "EU stablecoin rails consolidate"
    assert theses[0]["falsifier"] == "Tether gains MiCA authorization by Q4 2026"
    assert theses[0]["confirmer"] == "Circle expands EURC issuance"
    assert "archived" not in theses[0]           # internal flag, not part of the shape


# ── GET /api/theses/events ────────────────────────────────────────────────────

def test_events_joined_with_thesis_claim_and_labeled(client, fake):
    r = client.get("/api/theses/events")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    e = body["events"][0]
    assert e["thesis_id"] == 1
    assert e["claim"] == "EU stablecoin rails consolidate"
    assert e["label"] == "falsifies"
    assert e["article_url"] == "https://x/tether-mica"
    assert e["score"] == 0.83


# ── POST /api/theses ──────────────────────────────────────────────────────────

def test_add_thesis(client, fake):
    r = client.post("/api/theses", json={
        "claim": "  Grid storage outgrows gas peakers  ",
        "falsifier": "US peaker additions exceed storage additions in 2027",
        "confirmer": "Two major utilities cancel peaker projects citing storage",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    t = body["thesis"]
    assert t["claim"] == "Grid storage outgrows gas peakers"   # trimmed
    assert t["id"] == 3
    assert any(row["claim"] == "Grid storage outgrows gas peakers"
               for row in fake.tables["theses"])


def test_add_thesis_confirmer_optional(client, fake):
    r = client.post("/api/theses", json={"claim": "c" * 10, "falsifier": "f" * 10})
    assert r.status_code == 200
    assert r.json()["thesis"]["confirmer"] is None


def test_add_validates_lengths(client, fake):
    before = len(fake.tables["theses"])
    assert client.post("/api/theses", json={
        "claim": "   ", "falsifier": "f"}).status_code == 400
    assert client.post("/api/theses", json={
        "claim": "c", "falsifier": "x" * 301}).status_code == 400
    assert client.post("/api/theses", json={
        "claim": "c", "falsifier": "f", "confirmer": "x" * 301}).status_code == 400
    assert len(fake.tables["theses"]) == before


def test_add_503_when_tables_missing(client, monkeypatch):
    class MissingTableSupabase:
        def table(self, name):
            raise Exception('relation "public.theses" does not exist')

    monkeypatch.setattr(bt.data, "_supabase", lambda: MissingTableSupabase())
    r = client.post("/api/theses", json={"claim": "c", "falsifier": "f"})
    assert r.status_code == 503
    assert "theses.sql" in r.json()["detail"]


# ── DELETE /api/theses/{id} — soft archive ────────────────────────────────────

def test_delete_archives_softly(client, fake):
    r = client.delete("/api/theses/1")
    assert r.status_code == 200 and r.json() == {"ok": True, "archived": 1}
    row = next(t for t in fake.tables["theses"] if t["id"] == 1)
    assert row["archived"] is True               # still in the table — soft delete
    # and it disappears from the book
    assert client.get("/api/theses").json()["theses"] == []


def test_delete_unknown_thesis_404(client, fake):
    assert client.delete("/api/theses/999").status_code == 404
