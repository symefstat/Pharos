"""Tests for /api/ledger — the public ledger payload (shape, honesty fields,
per-technology grouping) and the ledger digest (deterministic over the same
rows, different after any row change, recomputable from the delivered JSON).
Fake data layer; no network, no Supabase writes."""

import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app.ledger as bl


# ── fixture ledger — one of every interesting shape ───────────────────────────

PREDS = [
    {  # resolved calibrated deal-flow call (locked threshold + basis)
        "id": 1, "fingerprint": "bbb1", "kind": "deal_flow", "subject": "Semiconductors",
        "claim": "Semiconductors sees ≥3 more material deals within ~1 month",
        "status": "resolved", "outcome": "hit", "confidence": 0.6,
        "made_on": "2026-05-01", "resolve_by": "2026-05-31", "resolved_on": "2026-05-20",
        "resolution_note": "4 ≥ 3 material deals", "horizon": "short",
        "params": {"threshold": 3, "window_days": 30,
                   "threshold_basis": "calibrated-p60 (trailing 30 × 30d windows)"},
    },
    {  # resolved quarantined price call — in the ledger, flagged
        "id": 2, "fingerprint": "aaa2", "kind": "price_move", "subject": "NVDA",
        "claim": "NVIDIA stock continues up — low-signal momentum call",
        "status": "resolved", "outcome": "miss", "confidence": 0.5,
        "made_on": "2026-04-01", "resolve_by": "2026-06-30", "resolved_on": "2026-06-30",
        "resolution_note": "-2.1% point-to-point", "horizon": "short",
        "params": {"symbol": "NVDA", "direction": "up", "threshold": 5.0},
    },
    {  # open anchored stage-transition call (the new kind)
        "id": 3, "fingerprint": "ccc3", "kind": "stage_advance_tech", "subject": "solid-state-batteries",
        "claim": "Solid-state batteries advances maturity from ‘growth’ to ‘dominant-design’ "
                 "(anchored display stage, confirmed) within ~1 quarter",
        "status": "open", "outcome": None, "confidence": 0.62,
        "made_on": "2026-06-15", "resolve_by": "2026-09-13", "resolved_on": None,
        "resolution_note": None, "horizon": "short",
        "params": {"dimension": "maturity", "from_stage": "growth", "from_index": 2,
                   "to_stage": "dominant-design", "to_index": 3, "upside_share": 0.4,
                   "label": "Solid-state batteries"},
    },
    {  # resolved stage-transition history for the same tech
        "id": 4, "fingerprint": "ddd4", "kind": "stage_advance_tech", "subject": "solid-state-batteries",
        "claim": "Solid-state batteries advances maturity from ‘emerging’ to ‘growth’ "
                 "(anchored display stage, confirmed) within ~1 quarter",
        "status": "resolved", "outcome": "hit", "confidence": 0.58,
        "made_on": "2026-02-01", "resolve_by": "2026-05-02", "resolved_on": "2026-04-10",
        "resolution_note": "maturity ‘growth’ held for 2 consecutive snapshots by 2026-04-10",
        "horizon": "short",
        "params": {"dimension": "maturity", "from_stage": "emerging", "from_index": 1,
                   "to_stage": "growth", "to_index": 2, "label": "Solid-state batteries"},
    },
    {  # open judgment call
        "id": 5, "fingerprint": "eee5", "kind": "manual", "subject": "capital",
        "claim": "Consolidation wave continues — wrong if: no major deal by Q4",
        "status": "open", "outcome": None, "confidence": 0.75,
        "made_on": "2026-06-01", "resolve_by": "2027-06-01", "resolved_on": None,
        "resolution_note": None, "horizon": "long", "params": {"falsifier": "no major deal"},
    },
]

PLACEMENTS = [
    {"tech": "solid-state-batteries", "label": "Solid-state batteries", "domain": "energy",
     "committed_stage": "growth", "maturity": "emerging", "maturity_anchored": True},
    {"tech": "unrelated-tech", "label": "Unrelated", "domain": "ai",
     "committed_stage": "mature"},
]


ANCHORS = [{"as_of": "2026-07-08", "digest": "d" * 64, "row_count": 5}]


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(bl.data, "predictions", lambda: [dict(p) for p in PREDS])
    monkeypatch.setattr(bl, "_tech_placements", lambda: [dict(p) for p in PLACEMENTS])
    monkeypatch.setattr(bl, "digest_history", lambda: [dict(a) for a in ANCHORS])
    app = FastAPI()
    app.include_router(bl.router)
    return TestClient(app)


# ── payload shape ──────────────────────────────────────────────────────────────

def test_payload_shape(client):
    out = client.get("/api/ledger").json()
    assert set(out) == {"generated_at", "ledger_digest", "digest_recipe",
                        "digest_history", "digest_note", "stats",
                        "records_by_basis", "categories", "calibration_bins",
                        "forecasts", "technologies", "policy"}
    # the anchored chain rides along with a note explaining how to use it
    assert out["digest_history"] == ANCHORS
    assert "append-only" in out["digest_note"]
    # every forecast is present — open AND resolved, quarantined included
    assert len(out["forecasts"]) == len(PREDS)
    # rows are fingerprint-sorted (the digest order IS the delivery order)
    fps = [r["fingerprint"] for r in out["forecasts"]]
    assert fps == sorted(fps)
    # public row shape: timestamps, locked terms, evidence, quarantine flag
    row = {r["fingerprint"]: r for r in out["forecasts"]}
    deal = row["bbb1"]
    assert deal["made_on"] == "2026-05-01" and deal["resolved_on"] == "2026-05-20"
    assert deal["threshold"] == 3
    assert deal["threshold_basis"].startswith("calibrated-p60")
    assert deal["evidence"] == "4 ≥ 3 material deals"
    assert deal["quarantined"] is False and deal["outcome"] == "hit"
    price = row["aaa2"]
    assert price["quarantined"] is True          # flagged, never hidden
    tech = row["ccc3"]
    assert tech["status"] == "open" and tech["from_stage"] == "growth"
    assert tech["to_stage"] == "dominant-design"
    # policy block carries the honesty constants
    assert out["policy"]["quarantined_kinds"] == ["price_move"]
    assert out["policy"]["min_resolve_days"] == 7


def test_stats_carry_naive_baseline_and_quarantine(client):
    out = client.get("/api/ledger").json()
    s = out["stats"]
    # pooled headline excludes the quarantined price call: 2 resolved, 1 scored
    assert s["resolved"] == 2 and s["quarantined_resolved"] == 1
    assert s["hits"] == 2 and s["misses"] == 0
    # the naive-baseline fields ride along (the honesty is the product)
    for key in ("base_rate", "baseline_accuracy", "baseline_brier",
                "brier_skill", "accuracy_edge_pp"):
        assert key in s
    # all-hit record → no discrimination tested yet: skill is null, not 0
    assert s["base_rate"] == 1.0 and s["brier_skill"] is None
    # per-category rows keep the price call scored in its own row
    cats = {c["category"]: c for c in out["categories"]}
    assert cats["Price (low-signal)"]["resolved"] == 1
    assert "base_rate" in cats["Technology"]


def test_calibration_bins_match_headline_population(client):
    out = client.get("/api/ledger").json()
    # 2 scored resolved (0.6 hit, 0.58 hit) — the 0.5 quarantined miss held out,
    # so no 40–60% bin dragged in by the price call at confidence 0.5... the two
    # hits land in the 40–60% band? 0.6 → band 60–80 (bin 3), 0.58 → 40–60.
    n_total = sum(b["n"] for b in out["calibration_bins"])
    assert n_total == 2                           # quarantined call not binned


def test_tech_sections_group_transition_calls(client):
    out = client.get("/api/ledger").json()
    assert len(out["technologies"]) == 1          # only techs WITH transition forecasts
    t = out["technologies"][0]
    assert t["tech"] == "solid-state-batteries"
    assert t["label"] == "Solid-state batteries"
    assert t["current_stage"] == "growth"         # anchored display stage from placements
    assert t["anchored"] is True and t["domain"] == "energy"
    assert [r["fingerprint"] for r in t["open"]] == ["ccc3"]
    assert [r["fingerprint"] for r in t["resolved"]] == ["ddd4"]


def test_tech_sections_survive_missing_placements(monkeypatch):
    monkeypatch.setattr(bl.data, "predictions", lambda: [dict(p) for p in PREDS])
    monkeypatch.setattr(bl, "_tech_placements", lambda: [])
    monkeypatch.setattr(bl, "digest_history", lambda: [])
    out = bl.build_ledger()
    t = out["technologies"][0]
    assert t["current_stage"] is None             # honest null, not a guess
    assert t["label"] == "Solid-state batteries"  # falls back to the locked params


# ── the digest — a cheap verifiable "this exact history" checksum ─────────────

def test_digest_deterministic_same_rows():
    rows_a = bl.ledger_rows([dict(p) for p in PREDS])
    rows_b = bl.ledger_rows([dict(p) for p in reversed(PREDS)])  # input order irrelevant
    assert bl.ledger_digest(rows_a) == bl.ledger_digest(rows_b)


def test_digest_changes_when_a_row_changes():
    base = bl.ledger_digest(bl.ledger_rows([dict(p) for p in PREDS]))
    edited = [dict(p) for p in PREDS]
    edited[0]["outcome"] = "miss"                 # one flipped outcome
    assert bl.ledger_digest(bl.ledger_rows(edited)) != base
    trimmed = [dict(p) for p in PREDS[1:]]        # one deleted row
    assert bl.ledger_digest(bl.ledger_rows(trimmed)) != base


def test_digest_recomputable_from_delivered_json(client):
    """The public verification path: sha256 over the payload's own `forecasts`
    array (canonical JSON) must equal `ledger_digest`."""
    out = client.get("/api/ledger").json()
    canon = json.dumps(out["forecasts"], sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False)
    assert hashlib.sha256(canon.encode("utf-8")).hexdigest() == out["ledger_digest"]


# ── anchor_digest — append-only daily anchoring, idempotent per day ───────────

class _FakeDigestQuery:
    def __init__(self, sb):
        self.sb = sb
        self._as_of = None
        self._inserted = False

    def select(self, *_a, **_k):
        return self

    def eq(self, _col, value):
        self._as_of = value
        return self

    def limit(self, _n):
        return self

    def execute(self):
        class R:
            data: list = []
        r = R()
        if not self._inserted:
            r.data = [dict(row) for row in self.sb.rows if row["as_of"] == self._as_of]
        return r

    def insert(self, rec):
        self.sb.rows.append(dict(rec))
        self.sb.inserts += 1
        self._inserted = True
        return self


class _FakeDigestSB:
    """Fake Supabase client for the ledger_digests table only."""

    def __init__(self):
        self.rows: list[dict] = []
        self.inserts = 0

    def table(self, name):
        assert name == "ledger_digests"
        return _FakeDigestQuery(self)


def test_anchor_digest_inserts_once_and_is_idempotent():
    sb = _FakeDigestSB()
    preds = [dict(p) for p in PREDS]
    first = bl.anchor_digest(sb, preds=preds, as_of="2026-07-08")
    expected = bl.ledger_digest(bl.ledger_rows(preds))
    assert first == {"digest": expected, "as_of": "2026-07-08", "row_count": len(PREDS)}
    assert sb.inserts == 1

    # second call the same day: no new insert, the stored anchor comes back —
    # even if the ledger changed in between (the anchor is the day's record)
    changed = preds[1:]
    second = bl.anchor_digest(sb, preds=changed, as_of="2026-07-08")
    assert sb.inserts == 1
    assert second["digest"] == expected

    # a new day appends a new anchor
    third = bl.anchor_digest(sb, preds=changed, as_of="2026-07-09")
    assert sb.inserts == 2
    assert third["digest"] == bl.ledger_digest(bl.ledger_rows(changed))
    assert [r["as_of"] for r in sb.rows] == ["2026-07-08", "2026-07-09"]


def test_download_returns_attachment(client):
    r = client.get("/api/ledger?download=1")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="lodestar-ledger.json"'
    body = json.loads(r.content.decode("utf-8"))
    # the downloaded artifact verifies with the same recipe
    canon = json.dumps(body["forecasts"], sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False)
    assert hashlib.sha256(canon.encode("utf-8")).hexdigest() == body["ledger_digest"]
