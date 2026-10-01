"""World-truth fix tests (backend/eval/reports/40_world_truth.md §4).

Pins the three estimator fixes layered over the news-derived placements:

  1. Coverage floor — `thin_signal` at n<10 stage-classified articles
     (boundary: 9 thin, 10 not), so the GLP-1/LFP class of 3-to-5-article
     centroids never again renders as a confident dot.
  2. Curated anchor floor — display stage = the LATER of (anchor stage,
     news-derived stage) per axis: an anchor lifts an under-placed tech
     (anchored=True, news stage preserved), news beyond the anchor wins
     (change detection unimpeded), and the anchors registry itself is valid
     against the technology registry and the stage vocabularies.
  3. Taxonomy misfit — `lifecycle_fit: False` (critical minerals) marks the
     placement and takes it OFF both curves in the API payload.

Plus the domain-strategy evidence floor: `watching` at n < EVIDENCE_FLOOR (15)
stage-classified articles — off both curves entirely, but the placement table
keeps the row with a "watching — insufficient evidence" badge.

Transition safety: the anchor floor changes what `snapshot()` persists, so the
first post-anchor snapshot can read as a stage change — pinned here to be
absorbed by the same debounce path as the modal→committed migration
(run==1 → unconfirmed → suspect → downranked, never watchlist-alerted).

Pure functions + fake Supabase client only — no network, no Supabase.
"""

import analytics.tech_layer as tl
from analytics.tech_anchors import ANCHORS
from backend.app.mot import _tech_points
from technologies import TECH_BY_KEY


# ── helpers ───────────────────────────────────────────────────────────────────

def _glp1(n=5, stage="research", adoption="innovators"):
    """A GLP-1 placement built from n identically-classified articles."""
    rows = [{"title": "Ozempic study readout", "companies": ["Novo Nordisk"],
             "maturity_stage": stage, "adoption_stage": adoption}] * n
    return next(p for p in tl.placements(rows) if p["tech"] == "glp-1")


class _FakeTable:
    def __init__(self, parent):
        self.parent = parent

    def upsert(self, rows, on_conflict=None):
        self.parent.last_upsert = rows
        return self

    def execute(self):
        return type("Resp", (), {"data": self.parent.last_upsert})()


class _FakeClient:
    def __init__(self):
        self.last_upsert = None

    def table(self, name):
        return _FakeTable(self)


class _StubPulse:
    def __init__(self, rows):
        self._rows = rows

    def all_recent(self, days=30):
        return self._rows


# ── the anchors registry itself ───────────────────────────────────────────────

def test_anchor_registry_valid_against_technology_registry():
    for key, a in ANCHORS.items():
        assert key in TECH_BY_KEY, f"anchor for unknown tech key {key!r}"
        assert a.get("as_of") and a.get("evidence"), key
        assert a.get("confidence") in {"high", "medium", "low"}, key
        if a.get("lifecycle_fit") is False:
            continue                                   # misfit: no stage anchors
        assert a["maturity_anchor"] in tl._MATURITY_ORDER, key
        assert a["adoption_anchor"] in tl._ADOPTION_ORDER, key
    # 19 technologies carry stage anchors; critical minerals is the marked misfit.
    staged = [k for k, a in ANCHORS.items() if a.get("lifecycle_fit") is not False]
    assert len(staged) == 19
    assert ANCHORS["critical-minerals"]["lifecycle_fit"] is False
    assert "DLE" in ANCHORS["critical-minerals"]["evidence"]


# ── anchor floor semantics ────────────────────────────────────────────────────

def test_anchor_floor_lifts_underplaced_tech_and_preserves_news_stage():
    # The benchmark's worst miss: GLP-1 read research/innovators off 5 articles
    # while 1 in 8 US adults takes one. The anchor floors both axes; the
    # news-derived stage stays in the payload (nothing hidden).
    p = tl.apply_anchors([_glp1()])[0]
    assert tl.display_stage(p) == "dominant-design"
    assert tl.display_stage(p, "adoption") == "early-majority"
    assert p["maturity_anchored"] is True and p["adoption_anchored"] is True
    assert p["anchored"] is True
    assert p["news_maturity"] == "research" and p["news_adoption"] == "innovators"
    assert p["anchor_as_of"] == "2026-07-02"
    # the chart dot moves with the stage: centroid floored to the anchor rank
    assert p["stage_centroid"] == float(tl._MATURITY_ORDER.index("dominant-design"))
    assert p["adoption_centroid"] == float(tl._ADOPTION_ORDER.index("early-majority"))
    assert p["thin_signal"] is True                    # n=5 < 10


def test_news_beyond_anchor_wins():
    # Solid-state is anchored emerging/innovators; a corpus reading
    # growth/early-adopters is LATER on both axes — the change detector wins,
    # the anchor never caps it, and nothing is flagged anchored.
    rows = [{"title": "Solid-state battery packs ship in volume",
             "maturity_stage": "growth", "adoption_stage": "early-adopters"}] * 12
    p = next(p for p in tl.placements(rows) if p["tech"] == "solid-state-batteries")
    p = tl.apply_anchors([p])[0]
    assert tl.display_stage(p) == "growth"
    assert tl.display_stage(p, "adoption") == "early-adopters"
    assert p["maturity_anchored"] is False and p["adoption_anchored"] is False
    assert p["anchored"] is False
    assert p["news_maturity"] == "growth"              # still recorded
    assert p["stage_centroid"] == 2.0                  # untouched by the anchor
    assert p["thin_signal"] is False                   # n=12


def test_anchor_equal_to_news_is_not_flagged_anchored():
    # Quantum: anchor emerging/early-adopters == news read → floor is a no-op.
    rows = [{"title": "Qubit count milestone", "maturity_stage": "emerging",
             "adoption_stage": "early-adopters"}] * 11
    p = next(p for p in tl.placements(rows) if p["tech"] == "quantum-computing")
    p = tl.apply_anchors([p])[0]
    assert tl.display_stage(p) == "emerging"
    assert p["maturity_anchored"] is False and p["anchored"] is False


def test_unanchored_tech_passes_through_with_thin_flag_only():
    # Perovskite solar has no anchor: placement untouched except the coverage flag.
    rows = [{"title": "Perovskite tandem record", "maturity_stage": "emerging",
             "adoption_stage": "innovators"}] * 4
    p = next(p for p in tl.placements(rows) if p["tech"] == "perovskite-solar")
    q = tl.apply_anchors([p])[0]
    assert q["thin_signal"] is True and "anchored" in q
    assert q["anchored"] is False and "news_maturity" not in q
    assert tl.display_stage(q) == tl.display_stage(p) == "emerging"


# ── coverage floor boundary ───────────────────────────────────────────────────

def test_thin_signal_boundary_at_10_stage_articles():
    assert tl.THIN_SIGNAL_MIN_ARTICLES == 10
    assert tl.apply_anchors([_glp1(n=9)])[0]["thin_signal"] is True
    assert tl.apply_anchors([_glp1(n=10)])[0]["thin_signal"] is False


# ── evidence floor ("watching — insufficient evidence") ──────────────────────

def test_watching_boundary_at_evidence_floor():
    # Rolling-window evidence floor: 14 stage-classified articles → watching,
    # 15 → placed. (14 is deliberately ≥ the thin floor of 10: a tech can be
    # confident-looking but still under-evidenced for a curve position.)
    assert tl.EVIDENCE_FLOOR == 15
    assert tl.apply_anchors([_glp1(n=14)])[0]["watching"] is True
    assert tl.apply_anchors([_glp1(n=15)])[0]["watching"] is False


def test_watching_tech_off_both_curves_but_keeps_table_row():
    # Below the floor the tech is NOT placed (off both curves) but stays a
    # placement-table row — marquee names with light coverage (solid-state,
    # LFP) remain visible as "watching", never silently dropped.
    p = tl.apply_anchors([_glp1(n=14)])[0]
    t = _tech_points([p], tl._MATURITY_ORDER, tl._ADOPTION_ORDER, {})[0]
    assert t["watching"] is True
    assert t["on_curve"] is False and t["on_adoption_curve"] is False
    assert t["lifecycle_fit"] is True          # a row (with badge), not a footnote
    assert t["coverage"] == 14                 # the badge's n=X


def test_at_the_floor_tech_is_placed_on_curve():
    p = tl.apply_anchors([_glp1(n=15)])[0]
    t = _tech_points([p], tl._MATURITY_ORDER, tl._ADOPTION_ORDER, {})[0]
    assert t["watching"] is False
    assert t["on_curve"] is True and t["on_adoption_curve"] is True


# ── taxonomy misfit ───────────────────────────────────────────────────────────

def test_misfit_marked_and_excluded_from_both_curves():
    rows = [{"title": "Rare earth export controls widen",
             "maturity_stage": "growth", "adoption_stage": "early-majority"}] * 6
    p = next(p for p in tl.placements(rows) if p["tech"] == "critical-minerals")
    p = tl.apply_anchors([p])[0]
    assert p["lifecycle_fit"] is False
    assert p["lifecycle_note"]                          # reason ships to the UI
    # API payload: off both curves (no misleading dot), but still present with
    # its note so the placement-table footnote can show it.
    t = _tech_points([p], tl._MATURITY_ORDER, tl._ADOPTION_ORDER, {})[0]
    assert t["on_curve"] is False and t["on_adoption_curve"] is False
    assert t["lifecycle_fit"] is False and t["lifecycle_note"] == p["lifecycle_note"]


def test_fit_tech_stays_on_curve_with_overlay_fields_in_payload():
    p = tl.apply_anchors([_glp1(n=15)])[0]              # 15 articles ≥ the evidence floor
    t = _tech_points([p], tl._MATURITY_ORDER, tl._ADOPTION_ORDER, {})[0]
    assert t["on_curve"] is True and t["watching"] is False
    assert t["thin_signal"] is False                    # n=15 ≥ 10
    assert t["anchored"] is True and t["maturity_anchored"] is True
    assert t["maturity"] == "dominant design"           # anchored stage displayed
    assert t["news_maturity"] == "research"             # news read preserved
    assert t["lifecycle_fit"] is True and t["lifecycle_note"] is None


# ── transition safety ─────────────────────────────────────────────────────────

def test_anchor_floor_first_snapshot_transition_is_absorbed():
    # History semantics change day: yesterday's snapshot holds the news-derived
    # stage, today's the anchor-floored one. The apparent research→dominant-design
    # "transition" is a curation event, not news — the debounce absorbs it the
    # same way as the modal→committed migration: run==1 → unconfirmed → suspect,
    # downranked and never watchlist-alerted.
    history = [
        {"technology": "glp-1", "label": "GLP-1 drugs", "as_of": "2026-07-01",
         "maturity_stage": "research", "maturity_mixed": False},
        {"technology": "glp-1", "label": "GLP-1 drugs", "as_of": "2026-07-02",
         "maturity_stage": "dominant-design", "maturity_mixed": False},
    ]
    trans = [t for t in tl.detect_transitions(history) if t["dimension"] == "maturity"]
    assert len(trans) == 1
    t = trans[0]
    assert (t["from"], t["to"]) == ("research", "dominant-design")
    assert t["confirmed"] is False                      # single snapshot — pending
    assert t["suspect"] is True                         # → downranked, no alert
    assert t["backward"] is False


def test_snapshot_persists_anchored_display_stage():
    # End-to-end through current_placements: the history row records the
    # anchor-floored displayed stage (what every surface shows), not the bare
    # news read — history and display agree by construction.
    rows = [{"title": "Wegovy trial coverage", "maturity_stage": "research",
             "adoption_stage": "innovators", "published_at": "2026-07-01"}] * 5
    fake = _FakeClient()
    ta = tl.TechAnalyst(client=fake)
    ta.pulse = _StubPulse(rows)
    recs = ta.current_placements()
    p = next(r for r in recs if r["tech"] == "glp-1")
    assert p["anchored"] is True and tl.display_stage(p) == "dominant-design"
    assert ta.snapshot() >= 1
    row = next(r for r in fake.last_upsert if r["technology"] == "glp-1")
    assert row["maturity_stage"] == "dominant-design"
    assert row["adoption_stage"] == "early-majority"
