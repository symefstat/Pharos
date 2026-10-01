"""Tests for the /api/forecasts endpoints — the resolve guard (only open,
judgment-kind forecasts are human-gradable via the API) and the payload shape
(no dead headline/tagline/state duplicates). Fake Supabase client; no network."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.forecasts as bf


# ── fake Supabase (predictions table only) ────────────────────────────────────

class _FakeQuery:
    def __init__(self, sb):
        self._sb = sb
        self._mode = "select"
        self._payload = None
        self._filters = []

    def select(self, *_a, **_k):
        self._mode = "select"
        return self

    def update(self, payload):
        self._mode = "update"
        self._payload = dict(payload)
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        rows = [r for r in self._sb.rows
                if all(r.get(c) == v for c, v in self._filters)]
        if self._mode == "update":
            self._sb.update_calls.append(
                {"payload": dict(self._payload), "filters": list(self._filters)})
            for r in rows:
                r.update(self._payload)
        return SimpleNamespace(data=[dict(r) for r in rows])


class FakeSupabase:
    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.update_calls = []

    def table(self, name):
        assert name == "predictions"
        return _FakeQuery(self)


@pytest.fixture()
def client():
    """Authenticated-admin client: resolve is admin-gated, so the guard-matrix
    tests run with the dependency satisfied; test_resolve_requires_admin pins
    the 401 for anonymous callers."""
    from backend.app.auth import require_admin

    app = FastAPI()
    app.include_router(bf.router)
    app.dependency_overrides[require_admin] = lambda: "admin"
    return TestClient(app)


@pytest.fixture()
def anon_client():
    app = FastAPI()
    app.include_router(bf.router)
    return TestClient(app)


@pytest.fixture()
def ledger(monkeypatch):
    fake = FakeSupabase([
        {"id": 1, "kind": "manual", "status": "open", "claim": "Z holds"},
        {"id": 2, "kind": "deal_flow", "status": "open", "claim": "3 deals"},
        {"id": 3, "kind": "manual", "status": "resolved", "outcome": "hit",
         "claim": "graded already"},
        {"id": 4, "kind": "price_move", "status": "resolved", "outcome": "miss",
         "claim": "auto, graded"},
    ])
    import db
    monkeypatch.setattr(db, "get_supabase", lambda: fake)
    return fake


# ── POST /api/forecasts/resolve — the guard ───────────────────────────────────

def test_resolve_requires_admin(anon_client, ledger):
    # A graded outcome is immutable — an anonymous write here would let anyone
    # permanently corrupt the public track record (launch review 2026-07-08).
    r = anon_client.post("/api/forecasts/resolve", json={"pred_id": 1, "outcome": "hit"})
    assert r.status_code == 401
    assert ledger.update_calls == []  # nothing written


def test_resolve_allows_open_manual(client, ledger):
    r = client.post("/api/forecasts/resolve", json={"pred_id": 1, "outcome": "hit"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert len(ledger.update_calls) == 1
    call = ledger.update_calls[0]
    assert call["payload"]["status"] == "resolved"
    assert call["payload"]["outcome"] == "hit"
    assert call["payload"]["resolution_note"] == "manually graded"
    # write re-checks openness (race guard) and targets exactly the requested row
    assert ("id", 1) in call["filters"] and ("status", "open") in call["filters"]
    # only resolution fields are written — never claim/confidence/horizon/params
    assert set(call["payload"]) == {"status", "outcome", "resolved_on", "resolution_note"}


def test_resolve_rejects_auto_kind(client, ledger):
    r = client.post("/api/forecasts/resolve", json={"pred_id": 2, "outcome": "hit"})
    assert r.status_code == 409
    assert "auto-graded" in r.json()["detail"]
    assert ledger.update_calls == []  # nothing written


def test_resolve_rejects_already_resolved_manual(client, ledger):
    r = client.post("/api/forecasts/resolve", json={"pred_id": 3, "outcome": "miss"})
    assert r.status_code == 409
    assert "locked" in r.json()["detail"]
    assert ledger.update_calls == []  # no regrading the record


def test_resolve_rejects_resolved_auto(client, ledger):
    r = client.post("/api/forecasts/resolve", json={"pred_id": 4, "outcome": "hit"})
    assert r.status_code == 409 and ledger.update_calls == []


def test_resolve_unknown_id_404(client, ledger):
    r = client.post("/api/forecasts/resolve", json={"pred_id": 999, "outcome": "hit"})
    assert r.status_code == 404 and "not found" in r.json()["detail"]
    assert ledger.update_calls == []


def test_resolve_bad_outcome_400(client, ledger):
    r = client.post("/api/forecasts/resolve", json={"pred_id": 1, "outcome": "won"})
    assert r.status_code == 400
    assert "outcome must be" in r.json()["detail"]
    assert ledger.update_calls == []


# ── GET /api/forecasts payload shape ─────────────────────────────────────────

def test_payload_drops_briefing_duplicates(monkeypatch):
    preds = [
        {"id": 1, "kind": "manual", "status": "open", "claim": "Z", "confidence": 0.75,
         "horizon": "long", "resolve_by": "2027-01-01"},
        {"id": 2, "kind": "deal_flow", "status": "resolved", "outcome": "hit",
         "confidence": 0.6, "made_on": "2026-06-01", "resolved_on": "2026-06-12"},
    ]
    monkeypatch.setattr(bf.data, "predictions", lambda: preds)
    out = bf.build_forecasts()
    # headline/tagline/state duplicated Briefing's calibration banner — dropped
    assert not {"headline", "tagline", "state"} & set(out)
    assert set(out) == {"summary", "track_record", "records_by_basis", "categories",
                        "calibration_bins", "calibration_verdict", "open_table",
                        "hero", "overdue", "resolved"}
    # the external/internal split reconciles: manual → external, deal_flow → internal
    assert out["records_by_basis"]["external"]["open"] == 1
    assert out["records_by_basis"]["internal"]["resolved"] == 1
    # open table keeps the auditor columns (Type = judgment vs auto, Horizon)
    assert out["open_table"][0]["Type"] == "judgment"
    assert out["open_table"][0]["Horizon"] == "long"
