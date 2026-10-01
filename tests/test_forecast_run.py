"""First direct coverage for forecast_run.py — generate() and resolve() driven
with a fake Supabase client and a stubbed _load_context (no network, no writes
outside the fake). Pins, at the enforcement point:

  • calibrated deal-flow/reactivity thresholds locked into inserted rows
    (params.threshold / threshold_pct + params.threshold_basis + claim text);
  • the stage_advance_tech generation path (anchor-grounded transitions);
  • insert-side idempotency (fingerprint + open (kind, subject) dedupe);
  • the MIN_RESOLVE_DAYS gate — no resolution inside the first 7 days;
  • confirmed-advance HIT with a persisted evidence snapshot, suspect moves
    left open, and the overdue→miss backstop;
  • locked-when-made: resolution updates touch resolution fields ONLY.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import analytics.forecasts as fc
import forecast_run as fr


# ── fake Supabase ─────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self.rows = list(rows)

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self

    def in_(self, col, vals):
        vals = set(vals)
        self.rows = [r for r in self.rows if r.get(col) in vals]
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def range(self, *a, **k):
        return self

    def execute(self):
        return _Resp([dict(r) for r in self.rows])


class _Update:
    def __init__(self, store, name, patch):
        self.store, self.name, self.patch = store, name, dict(patch)
        self.filters = {}

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def execute(self):
        for r in self.store.tables.get(self.name, []):
            if all(r.get(c) == v for c, v in self.filters.items()):
                r.update(self.patch)
        self.store.updates.append((self.name, dict(self.filters), dict(self.patch)))
        return _Resp([])


class _Table:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def select(self, *a, **k):
        return _Query(self.store.tables.get(self.name, []))

    def insert(self, rows):
        rows = rows if isinstance(rows, list) else [rows]
        self.store.tables.setdefault(self.name, []).extend(dict(r) for r in rows)
        self.store.inserted.setdefault(self.name, []).extend(dict(r) for r in rows)

        class _Exec:
            def execute(self_inner):
                return _Resp(rows)
        return _Exec()

    def update(self, patch):
        return _Update(self.store, self.name, patch)


class FakeSB:
    def __init__(self, tables=None):
        self.tables = {k: [dict(r) for r in v] for k, v in (tables or {}).items()}
        self.inserted = {}
        self.updates = []

    def table(self, name):
        return _Table(self, name)


# ── fake context (what _load_context would return) ───────────────────────────
@dataclass(frozen=True)
class _Tk:
    entity: str
    symbol: str
    exchange: str
    sector: str


def _ticker_for(name):
    return {"NvidiaX": _Tk("NvidiaX", "NVX", "X", "Chips")}.get(str(name))


def _deal_rows():
    """A material capital deal in Chips every day 2026-05-24 → 2026-07-03 —
    41 days of trailing history → 11 full rolling 30d windows of 30 deals each."""
    rows, d = [], date(2026, 5, 24)
    while d <= date(2026, 7, 3):
        rows.append({"published_at": d.isoformat(), "title": "deal", "summary": "",
                     "business_impact": "material", "scope": "deal",
                     "companies": ["NvidiaX"], "tags": ["funding"]})
        d += timedelta(days=1)
    return rows


_PLACEMENTS = [{
    "tech": "solid-state-batteries", "label": "Solid-state batteries",
    "articles": 20, "stage_articles": 20,
    "stage_dist": {"emerging": 12, "growth": 8},
    "committed_stage": "emerging", "mixed": False,
    "adoption": "innovators",
}]


def _gen_ctx():
    # rows, placements, rollup, prices, symbol_entity, brief, ticker_for
    return (_deal_rows(), [dict(p) for p in _PLACEMENTS], [], {}, {}, {}, _ticker_for)


def _empty_ctx():
    return ([], [], [], {}, {}, {}, lambda name: None)


# ── generate() ────────────────────────────────────────────────────────────────
def test_generate_locks_calibrated_thresholds_into_new_rows(monkeypatch):
    monkeypatch.setattr(fr, "_load_context", lambda sb: _gen_ctx())
    sb = FakeSB({"predictions": []})
    n = fr.generate(sb, "2026-07-03")
    inserted = sb.inserted["predictions"]
    assert n == len(inserted) > 0
    by_kind = {}
    for r in inserted:
        by_kind.setdefault(r["kind"], []).append(r)

    # deal_flow: 30 deals per trailing 30d window → p60 = 30, clamped to the cap —
    # nothing like the old constant 2 that made the base rate ~100%
    df = by_kind["deal_flow"][0]
    assert df["params"]["threshold"] == fc.DEAL_FLOW_THRESHOLD_CAP
    assert df["params"]["threshold_basis"] == "calibrated-p60 (trailing 11 × 30d windows)"
    assert f"≥{fc.DEAL_FLOW_THRESHOLD_CAP} more material deals" in df["claim"]

    # reactivity: no priced reactions in the fake context → per-window maxima are 0,
    # clamped up to the floor — but still calibrated + audited, never silently default
    rx = by_kind["reactivity"][0]
    assert rx["params"]["threshold_pct"] == fc.REACTIVITY_THRESHOLD_PCT
    assert rx["params"]["threshold_basis"].startswith("calibrated-p60")

    # the anchor-grounded transition forecast is generated alongside the adoption one
    sat = by_kind["stage_advance_tech"][0]
    assert sat["subject"] == "solid-state-batteries"
    assert sat["params"]["from_stage"] == "emerging" and sat["params"]["to_stage"] == "growth"
    assert sat["resolve_by"] == "2026-10-01" and sat["status"] == "open"
    assert "stage_advance" in by_kind                     # existing kind untouched


def test_generate_is_idempotent_and_dedupes_open_subjects(monkeypatch):
    monkeypatch.setattr(fr, "_load_context", lambda sb: _gen_ctx())
    sb = FakeSB({"predictions": []})
    n1 = fr.generate(sb, "2026-07-03")
    assert n1 > 0
    # same day, same data → every candidate's fingerprint already logged → 0 inserts
    assert fr.generate(sb, "2026-07-03") == 0
    assert len(sb.tables["predictions"]) == n1
    # next day: new fingerprints, but the open (kind, subject) rows block quant dupes
    assert fr.generate(sb, "2026-07-04") == 0


def test_generate_dedupes_against_preexisting_open_forecast(monkeypatch):
    monkeypatch.setattr(fr, "_load_context", lambda sb: _gen_ctx())
    seed = {"fingerprint": "prior-fp", "kind": "stage_advance_tech",
            "subject": "solid-state-batteries", "status": "open", "outcome": None}
    sb = FakeSB({"predictions": [seed]})
    fr.generate(sb, "2026-07-03")
    sats = [r for r in sb.tables["predictions"] if r["kind"] == "stage_advance_tech"]
    assert sats == [seed]           # no second open forecast for the same subject


# ── claims_similar / paraphrase dedupe ────────────────────────────────────────
def test_claims_similar_catches_reworded_strategist_call():
    # Real duplicate pair from the live ledger (2026-07-08): same call, reworded
    # claim and falsifier, different fingerprint.
    a = ("Mastercard forces network-token standard on card-on-file merchants — "
         "wrong if: Mastercard delays mandate past Q3 2026")
    b = ("Mastercard forces network tokenization standard with Q3 mandate — "
         "wrong if: Visa adopts incompatible tokenization architecture")
    assert fc.claims_similar(a, b)


def test_claims_similar_keeps_distinct_calls_about_same_subject():
    a = "Mastercard forces network tokenization standard with Q3 mandate"
    b = "Mastercard expands stablecoin settlement to EU acquirers by December"
    assert not fc.claims_similar(a, b)
    assert not fc.claims_similar("", a)  # degenerate input never matches


def test_resolve_deal_flow_ignores_events_after_resolve_by(monkeypatch):
    """H9: a stalled cron resolving late must not bank a HIT from deals that
    happened after the claim's own window. All qualifying deals here land after
    resolve_by, so the overdue forecast is a MISS, not a hit."""
    late_rows = [{"published_at": d.isoformat(), "title": "deal", "summary": "",
                  "business_impact": "material", "scope": "deal",
                  "companies": ["NvidiaX"], "tags": ["funding"]}
                 for d in (date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3))]
    monkeypatch.setattr(
        fr, "_load_context",
        lambda sb: (late_rows, [], [], {}, {}, {}, _ticker_for))
    pred = {"id": 9, "kind": "deal_flow", "subject": "Chips", "status": "open",
            "made_on": "2026-05-01", "resolve_by": "2026-06-01",
            "params": {"threshold": 2}, "confidence": 0.7, "outcome": None}
    sb = FakeSB({"predictions": [pred]})
    assert fr.resolve(sb, "2026-07-05") == 1  # resolved — but not as a hit
    row = sb.tables["predictions"][0]
    assert row["outcome"] == "miss"
    assert "unmet by resolve-by" in row["resolution_note"]


def test_select_new_drops_paraphrase_of_open_call():
    open_call = {"fingerprint": "fp-1", "kind": "manual", "subject": "Mastercard",
                 "status": "open", "outcome": None,
                 "claim": ("Mastercard forces network-token standard on "
                           "card-on-file merchants — wrong if: mandate delayed")}
    paraphrase = {"fingerprint": "fp-2", "kind": "manual", "subject": "Mastercard",
                  "source": "strategist", "confidence": 0.75,
                  "claim": ("Mastercard forces network tokenization standard with "
                            "Q3 mandate — wrong if: regulatory intervention")}
    fresh = {"fingerprint": "fp-3", "kind": "manual", "subject": "Mastercard",
             "source": "strategist", "confidence": 0.6,
             "claim": "Mastercard expands stablecoin settlement to EU acquirers"}
    out = fr.select_new([paraphrase, fresh], [open_call])
    assert [c["fingerprint"] for c in out] == ["fp-3"]


# ── resolve() ─────────────────────────────────────────────────────────────────
def _sat_row(pred_id=1, **kw):
    row = {"id": pred_id, "kind": "stage_advance_tech", "subject": "ssb",
           "status": "open", "made_on": "2026-06-01", "resolve_by": "2026-08-30",
           "params": {"to_index": 2}, "confidence": 0.59, "outcome": None}
    row.update(kw)
    return row


def _snap(as_of, stage, mixed=False, tech="ssb"):
    return {"technology": tech, "as_of": as_of, "maturity_stage": stage,
            "maturity_mixed": mixed, "adoption_stage": None}


def test_resolve_confirmed_advance_hits_with_evidence_and_locked_fields(monkeypatch):
    monkeypatch.setattr(fr, "_load_context", lambda sb: _empty_ctx())
    sb = FakeSB({
        "predictions": [_sat_row()],
        "technology_stage_history": [_snap("2026-06-20", "growth"),
                                     _snap("2026-06-21", "growth")],
    })
    assert fr.resolve(sb, "2026-07-03") == 1
    row = sb.tables["predictions"][0]
    assert row["status"] == "resolved" and row["outcome"] == "hit"
    assert row["resolved_on"] == "2026-07-03"
    assert "2 consecutive snapshots" in row["resolution_note"]
    ev = row["resolution_evidence"]
    assert ev["kind"] == "stage_advance_tech"
    assert [s["stage"] for s in ev["snapshots_seen"]] == ["growth", "growth"]
    # locked-when-made: the UPDATE touched resolution fields only
    _, _, patch = sb.updates[0]
    assert set(patch) == {"status", "outcome", "resolved_on",
                          "resolution_note", "resolution_evidence"}


def test_resolve_suspect_move_stays_open(monkeypatch):
    monkeypatch.setattr(fr, "_load_context", lambda sb: _empty_ctx())
    sb = FakeSB({
        "predictions": [_sat_row()],
        # contested flip + a single clean snapshot — neither may bank a HIT
        "technology_stage_history": [_snap("2026-06-20", "growth", mixed=True),
                                     _snap("2026-06-21", "growth", mixed=True)],
    })
    assert fr.resolve(sb, "2026-07-03") == 0
    assert sb.tables["predictions"][0]["status"] == "open"
    assert sb.updates == []


def test_resolve_min_resolve_days_gate_blocks_early_hit(monkeypatch):
    # confirmed advance in the data, but only 3 days elapsed → must stay open
    monkeypatch.setattr(fr, "_load_context", lambda sb: _empty_ctx())
    sb = FakeSB({
        "predictions": [_sat_row(made_on="2026-06-30", resolve_by="2026-09-28")],
        "technology_stage_history": [_snap("2026-07-01", "growth"),
                                     _snap("2026-07-02", "growth")],
    })
    assert fr.resolve(sb, "2026-07-03") == 0
    assert sb.tables["predictions"][0]["status"] == "open"


def test_resolve_overdue_unconfirmed_advance_is_a_miss(monkeypatch):
    monkeypatch.setattr(fr, "_load_context", lambda sb: _empty_ctx())
    sb = FakeSB({
        "predictions": [_sat_row(made_on="2026-05-01", resolve_by="2026-06-15")],
        "technology_stage_history": [_snap("2026-06-10", "growth")],   # unconfirmed
    })
    assert fr.resolve(sb, "2026-07-03") == 1
    row = sb.tables["predictions"][0]
    assert row["outcome"] == "miss"
    assert row["resolution_note"] == "criterion unmet by resolve-by date"


def test_resolve_leaves_manual_and_undue_forecasts_alone(monkeypatch):
    monkeypatch.setattr(fr, "_load_context", lambda sb: _empty_ctx())
    sb = FakeSB({"predictions": [
        {"id": 1, "kind": "manual", "subject": "signal", "status": "open",
         "made_on": "2026-05-01", "resolve_by": "2026-06-01", "params": {},
         "confidence": 0.75, "outcome": None},                  # overdue but human-graded
        _sat_row(pred_id=2),                                    # open, nothing confirming
    ]})
    assert fr.resolve(sb, "2026-07-03") == 0
    assert all(r["status"] == "open" for r in sb.tables["predictions"])
