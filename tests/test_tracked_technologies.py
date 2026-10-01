"""Self-serve technology tracking: the merged registry (technologies.registry),
its consumption by the pure roll-up (tech_layer), and the admin-gated
/api/mot/technologies endpoints. Fake Supabase client; no network."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.mot as bm
from backend.app.mot import slugify_key
from backend.app.ratelimit import _limiter
from technologies import TECHNOLOGIES, TECH_BY_KEY, Technology, registry
from analytics.tech_layer import match_technologies, placements


# ── fake Supabase (tracked_technologies table) ─────────────────────────────────

class _FakeQuery:
    def __init__(self, sb):
        self._sb = sb
        self._mode = "select"
        self._payload = None
        self._filters = []

    def select(self, *_a, **_k):
        self._mode = "select"
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def upsert(self, payload, **_k):
        self._mode = "upsert"
        self._payload = dict(payload)
        return self

    def update(self, payload, **_k):
        self._mode = "update"
        self._payload = dict(payload)
        return self

    def execute(self):
        rows = self._sb.rows
        if self._mode == "upsert":
            for r in rows:
                if r.get("key") == self._payload.get("key"):
                    r.update(self._payload)
                    return SimpleNamespace(data=[dict(r)])
            row = {"archived": False, **self._payload}
            rows.append(row)
            return SimpleNamespace(data=[dict(row)])
        hit = [r for r in rows if all(r.get(c) == v for c, v in self._filters)]
        if self._mode == "update":
            for r in hit:
                r.update(self._payload)
        return SimpleNamespace(data=[dict(r) for r in hit])


class FakeSupabase:
    def __init__(self, rows=None, error=None):
        self.rows = [dict(r) for r in (rows or [])]
        self.error = error

    def table(self, name):
        assert name == "tracked_technologies"
        if self.error:
            raise self.error
        return _FakeQuery(self)


_EDGE_AI = {"key": "edge-ai-chips", "label": "Edge AI chips", "domain": "Chips",
            "keywords": ["edge ai", "npu", "on-device"], "archived": False}
_ARCHIVED = {"key": "old-tech", "label": "Old tech", "domain": "Chips",
             "keywords": ["oldkw"], "archived": True}


# ── registry merge ─────────────────────────────────────────────────────────────

def test_registry_without_client_is_static_only():
    assert registry(None) == list(TECHNOLOGIES)


def test_registry_merges_active_db_rows_after_static():
    reg = registry(FakeSupabase([_EDGE_AI]))
    assert len(reg) == len(TECHNOLOGIES) + 1
    t = reg[-1]
    assert isinstance(t, Technology)
    assert t.key == "edge-ai-chips" and t.label == "Edge AI chips" and t.domain == "Chips"
    assert t.keywords == ("edge ai", "npu", "on-device")     # coerced to a lowercased tuple


def test_registry_excludes_archived_rows():
    reg = registry(FakeSupabase([_EDGE_AI, _ARCHIVED]))
    keys = {t.key for t in reg}
    assert "edge-ai-chips" in keys and "old-tech" not in keys


def test_registry_skips_static_key_collisions_and_duplicates():
    hijack = {"key": "glp-1", "label": "Hijacked", "domain": "Chips",
              "keywords": ["x"], "archived": False}
    dupe = {**_EDGE_AI, "label": "Duplicate row"}
    reg = registry(FakeSupabase([hijack, _EDGE_AI, dupe]))
    assert len(reg) == len(TECHNOLOGIES) + 1                 # hijack + dupe skipped
    assert next(t for t in reg if t.key == "glp-1").label == TECH_BY_KEY["glp-1"].label
    assert next(t for t in reg if t.key == "edge-ai-chips").label == "Edge AI chips"


def test_registry_skips_rows_without_usable_keywords():
    reg = registry(FakeSupabase([{**_EDGE_AI, "keywords": ["  ", ""]}]))
    assert len(reg) == len(TECHNOLOGIES)


def test_registry_degrades_to_static_when_table_missing():
    err = Exception('relation "public.tracked_technologies" does not exist')
    assert registry(FakeSupabase(error=err)) == list(TECHNOLOGIES)


# ── merged registry drives the pure roll-up ────────────────────────────────────

def test_match_and_placements_consume_the_merged_registry():
    reg = registry(FakeSupabase([_EDGE_AI]))
    row = {"title": "Qualcomm ships a new NPU for on-device inference",
           "maturity_stage": "growth", "adoption_stage": "early-adopters",
           "companies": ["Qualcomm"]}
    assert "edge-ai-chips" in match_technologies(row, reg)
    assert "edge-ai-chips" not in match_technologies(row)     # static default unchanged
    plc = placements([row], reg)
    p = next(x for x in plc if x["tech"] == "edge-ai-chips")
    assert p["label"] == "Edge AI chips" and p["domain"] == "Chips"
    assert p["maturity"] == "growth" and p["articles"] == 1
    assert all(x["tech"] != "edge-ai-chips" for x in placements([row]))


# ── slugify ────────────────────────────────────────────────────────────────────

def test_slugify_key():
    assert slugify_key("Edge AI chips") == "edge-ai-chips"
    assert slugify_key("  Solid-State: Cooling!  ") == "solid-state-cooling"
    assert slugify_key("HBM memory") == "hbm-memory"          # collides with the static key
    assert slugify_key("***") == ""


# ── /api/mot/technologies router ───────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    _limiter.reset()
    yield
    _limiter.reset()


@pytest.fixture()
def fake(monkeypatch):
    fake = FakeSupabase([_EDGE_AI, _ARCHIVED])
    monkeypatch.setattr(bm.data, "_supabase", lambda: fake)
    return fake


@pytest.fixture()
def client():
    from backend.app.auth import require_admin

    app = FastAPI()
    app.include_router(bm.router)
    app.dependency_overrides[require_admin] = lambda: "admin"
    return TestClient(app)


@pytest.fixture()
def anon_client():
    app = FastAPI()
    app.include_router(bm.router)
    return TestClient(app)


def test_anonymous_writes_get_401(anon_client, fake):
    r = anon_client.post("/api/mot/technologies", json={
        "label": "Neuromorphic chips", "domain": "Chips", "keywords": ["neuromorphic"]})
    assert r.status_code == 401
    assert anon_client.delete("/api/mot/technologies/edge-ai-chips").status_code == 401
    # nothing written or archived
    assert len(fake.rows) == 2
    assert fake.rows[0]["archived"] is False


def test_add_technology_slugs_normalizes_and_writes(client, fake):
    r = client.post("/api/mot/technologies", json={
        "label": "  Neuromorphic chips  ", "domain": "Chips",
        "keywords": ["Neuromorphic", "  spiking neural ", "", "Neuromorphic"]})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    t = body["technology"]
    assert t["key"] == "neuromorphic-chips" and t["label"] == "Neuromorphic chips"
    assert t["keywords"] == ["neuromorphic", "spiking neural"]  # trimmed, lowercased, deduped
    row = next(x for x in fake.rows if x["key"] == "neuromorphic-chips")
    assert row["archived"] is False and row["domain"] == "Chips"


def test_add_validates_label_domain_and_keywords(client, fake):
    before = len(fake.rows)
    bad = [
        {"label": "x", "domain": "Chips", "keywords": ["k"]},            # label too short
        {"label": "y" * 61, "domain": "Chips", "keywords": ["k"]},       # label too long
        {"label": "Valid label", "domain": "Nonsense", "keywords": ["k"]},  # unknown domain
        {"label": "Valid label", "domain": "Chips", "keywords": []},     # no keywords
        {"label": "Valid label", "domain": "Chips", "keywords": [" "]},  # blank keywords
        {"label": "Valid label", "domain": "Chips",
         "keywords": [f"k{i}" for i in range(11)]},                      # too many keywords
        {"label": "!!!", "domain": "Chips", "keywords": ["k"]},          # slugs to nothing
    ]
    for payload in bad:
        assert client.post("/api/mot/technologies", json=payload).status_code == 400, payload
    assert len(fake.rows) == before


def test_add_rejects_static_and_active_db_collisions(client, fake):
    # "HBM memory" slugs to the static key hbm-memory
    r = client.post("/api/mot/technologies", json={
        "label": "HBM memory", "domain": "Chips", "keywords": ["hbm"]})
    assert r.status_code == 409
    # edge-ai-chips is an active DB row
    r = client.post("/api/mot/technologies", json={
        "label": "Edge AI chips", "domain": "Chips", "keywords": ["npu"]})
    assert r.status_code == 409


def test_readding_an_archived_key_revives_it(client, fake):
    r = client.post("/api/mot/technologies", json={
        "label": "Old Tech", "domain": "EV", "keywords": ["newkw"]})
    assert r.status_code == 200
    row = next(x for x in fake.rows if x["key"] == "old-tech")
    assert row["archived"] is False and row["keywords"] == ["newkw"] and row["domain"] == "EV"


def test_add_503_when_table_missing(client, monkeypatch):
    missing = FakeSupabase(error=Exception(
        'relation "public.tracked_technologies" does not exist'))
    monkeypatch.setattr(bm.data, "_supabase", lambda: missing)
    r = client.post("/api/mot/technologies", json={
        "label": "Neuromorphic chips", "domain": "Chips", "keywords": ["neuromorphic"]})
    assert r.status_code == 503
    assert "tracked_technologies.sql" in r.json()["detail"]


def test_delete_archives_softly(client, fake):
    r = client.delete("/api/mot/technologies/edge-ai-chips")
    assert r.status_code == 200 and r.json() == {"ok": True, "archived": "edge-ai-chips"}
    row = next(x for x in fake.rows if x["key"] == "edge-ai-chips")
    assert row["archived"] is True                            # soft delete — row kept


def test_delete_static_key_400_and_unknown_404(client, fake):
    assert client.delete("/api/mot/technologies/glp-1").status_code == 400
    assert client.delete("/api/mot/technologies/never-existed").status_code == 404
    assert client.delete("/api/mot/technologies/old-tech").status_code == 404  # already archived
