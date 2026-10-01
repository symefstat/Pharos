"""Golden-fixture snapshot tests for the technology layer (L5 eval).

Fixed synthetic inputs → exact expected outputs, pinning behavior that the
existing suite (tests/test_tech_layer.py) leaves unexercised:

  A. centroid → placement math, including boundary values (endpoints, exact-half
     centroids / Python banker's rounding, normalization of raw stage strings);
  B. transition debouncing (a flapping input must never produce a *confirmed*
     transition; the freshness window boundary run==4 vs run==5; coverage gaps
     do not reset the run; an unclassified latest snapshot emits nothing);
  C. direction-awareness (regressions flagged `backward` and sunk below forward
     moves even when newer AND confirmed; unknown legacy labels can't be judged;
     adoption axis handled like maturity);
  D. cross-surface consistency: the stage a chart places a dot at equals
     tech_layer.display_stage() — the single display source of truth — including
     history snapshots: TechAnalyst.snapshot() persists the displayed (committed)
     stage, not the bare modal (was a strict xfail documenting the gap; now fixed
     and asserted), and the one-time modal→committed migration transition is
     pinned as suspect/downranked.

Pure functions only — no network, no Supabase.
"""

import analytics.mot_analyst as ma
import analytics.tech_layer as tl


# ══════════════════════════════════════════════════════════════════════════════
# A. centroid → placement, boundary values
# ══════════════════════════════════════════════════════════════════════════════

def test_centroid_endpoints_first_and_last_stage():
    first = tl._dimension_stats([{"maturity_stage": "research"}] * 3,
                                "maturity_stage", tl._MATURITY_ORDER)
    assert first == {"dist": {"research": 3}, "articles": 3, "centroid": 0.0,
                     "committed": "research", "modal_share": 1.0, "mixed": False}
    last = tl._dimension_stats([{"maturity_stage": "declining"}] * 3,
                               "maturity_stage", tl._MATURITY_ORDER)
    assert last["centroid"] == 5.0 and last["committed"] == "declining"
    assert last["mixed"] is False
    # adoption axis endpoint (max index 4)
    lag = tl._dimension_stats([{"adoption_stage": "laggards"}] * 2,
                              "adoption_stage", tl._ADOPTION_ORDER)
    assert lag["centroid"] == 4.0 and lag["committed"] == "laggards"


def test_centroid_exact_half_uses_bankers_rounding():
    # A 50/50 tie between adjacent stages lands the centroid exactly on the
    # boundary. Python's round() is banker's rounding (round-half-to-EVEN), so
    # the committed stage snaps to the even-indexed neighbour — asymmetric
    # across boundaries. Pinned here because it decides which band a tied dot
    # sits in; every such tie is also mixed=True (modal_share == 0.5), so the
    # chart fades it — the asymmetry is never presented as a confident call.
    def half(a, b):
        return tl._dimension_stats([{"maturity_stage": a}, {"maturity_stage": b}],
                                   "maturity_stage", tl._MATURITY_ORDER)

    for a, b, expected in [
        ("research", "emerging", "research"),          # 0.5 → 0 (even)
        ("emerging", "growth", "growth"),              # 1.5 → 2 (even)
        ("growth", "dominant-design", "growth"),       # 2.5 → 2 (even)
        ("dominant-design", "mature", "mature"),       # 3.5 → 4 (even)
    ]:
        s = half(a, b)
        assert s["committed"] == expected, (a, b, s)
        assert s["mixed"] is True                      # tie → always contested


def test_centroid_normalizes_underscores_and_case():
    # Raw classifier strings arrive as 'Early_Majority' etc.; the stats must
    # normalize before matching the vocabulary — silently dropping them would
    # skew the centroid.
    s = tl._dimension_stats(
        [{"adoption_stage": "Early_Majority"}, {"adoption_stage": " early-majority "},
         {"adoption_stage": "EARLY-MAJORITY"}],
        "adoption_stage", tl._ADOPTION_ORDER)
    assert s == {"dist": {"early-majority": 3}, "articles": 3, "centroid": 2.0,
                 "committed": "early-majority", "modal_share": 1.0, "mixed": False}


def test_placements_golden_snapshot_bimodal():
    # 3 emerging + 2 mature articles for one tech: exact expected placement.
    # centroid = (3·1 + 2·4)/5 = 2.2 → committed 'growth' — a stage NO article
    # chose; modal ('emerging') ≠ committed → mixed (the fade guard).
    rows = (
        [{"title": "TSMC 2nm pilot", "companies": ["TSMC"],
          "maturity_stage": "emerging", "adoption_stage": "innovators"}] * 3
        + [{"title": "TSMC 2nm volume", "companies": ["Samsung"],
            "maturity_stage": "mature", "adoption_stage": "innovators"}] * 2
    )
    p = next(p for p in tl.placements(rows) if p["tech"] == "advanced-logic")
    assert p["maturity"] == "emerging"            # bare modal
    assert p["stage_centroid"] == 2.2
    assert p["committed_stage"] == "growth"       # centroid-committed
    assert p["mixed"] is True                     # committed off-mode → contested
    assert p["stage_dist"] == {"emerging": 3, "mature": 2}
    assert p["adoption_centroid"] == 0.0 and p["adoption_committed"] == "innovators"
    assert tl.display_stage(p) == "growth"        # display == committed, not modal


# ══════════════════════════════════════════════════════════════════════════════
# B. transition debouncing
# ══════════════════════════════════════════════════════════════════════════════

def _hist(tech, stages_newest_last, start_day=1, **extra):
    """Snapshots for `tech`, one per day, given oldest→newest stage list."""
    return [{"technology": tech, "label": tech,
             "as_of": f"2026-06-{start_day + i:02d}", "maturity_stage": s, **extra}
            for i, s in enumerate(stages_newest_last)]


def test_flapping_input_never_confirms():
    # growth/emerging alternating every snapshot: the output must stay a single
    # PENDING (unconfirmed, suspect) move anchored on the latest value — the
    # debounce means a flapping input cannot produce a confirmed transition.
    flap = _hist("f", ["growth", "emerging", "growth", "emerging", "growth"])
    trans = tl.detect_transitions(flap)
    assert len(trans) == 1
    t = trans[0]
    assert (t["from"], t["to"]) == ("emerging", "growth")
    assert t["confirmed"] is False and t["suspect"] is True
    assert t["as_of"] == "2026-06-05"             # anchored on the latest snapshot

    # invert the phase (latest snapshot is 'emerging'): still one pending move,
    # now read in the other direction and flagged backward — never confirmed.
    flap2 = tl.detect_transitions(_hist("f", ["emerging", "growth", "emerging",
                                              "growth", "emerging"]))
    assert len(flap2) == 1
    assert flap2[0]["confirmed"] is False and flap2[0]["backward"] is True


def test_freshness_window_boundary_run4_shown_run5_dropped():
    # _TRANSITION_FRESH_SNAPSHOTS = 4: a new stage holding exactly 4 of the most
    # recent snapshots is still current news; at 5 it is long-settled and drops.
    assert tl._TRANSITION_FRESH_SNAPSHOTS == 4
    shown = tl.detect_transitions(_hist("x", ["emerging"] + ["growth"] * 4))
    assert [(t["from"], t["to"], t["confirmed"]) for t in shown] == \
        [("emerging", "growth", True)]
    assert tl.detect_transitions(_hist("x", ["emerging"] + ["growth"] * 5)) == []


def test_coverage_gap_does_not_reset_run_or_count_as_change():
    # A blank (unclassified) snapshot inside the run is skipped: emerging →
    # growth, growth, <gap>, growth reads as one confirmed move, not two.
    gap = [
        {"technology": "g", "as_of": "2026-06-11", "maturity_stage": "emerging"},
        {"technology": "g", "as_of": "2026-06-12", "maturity_stage": "growth"},
        {"technology": "g", "as_of": "2026-06-13", "maturity_stage": None},
        {"technology": "g", "as_of": "2026-06-14", "maturity_stage": "growth"},
    ]
    trans = tl.detect_transitions(gap)
    assert [(t["from"], t["to"], t["confirmed"]) for t in trans] == \
        [("emerging", "growth", True)]


def test_unclassified_latest_snapshot_emits_nothing():
    hist = [
        {"technology": "u", "as_of": "2026-06-12", "maturity_stage": "emerging"},
        {"technology": "u", "as_of": "2026-06-13", "maturity_stage": "growth"},
        {"technology": "u", "as_of": "2026-06-14", "maturity_stage": None},
    ]
    assert tl.detect_transitions(hist) == []


def test_single_snapshot_tech_emits_nothing():
    assert tl.detect_transitions(_hist("solo", ["growth"])) == []


# ══════════════════════════════════════════════════════════════════════════════
# C. direction-awareness
# ══════════════════════════════════════════════════════════════════════════════

def test_backward_move_confirmed_is_still_suspect_and_sinks():
    # A regression that has HELD for 2 snapshots is confirmed by the debounce —
    # but direction-awareness must still flag it backward and keep it suspect,
    # sorting it below an unconfirmed forward move despite being newer.
    history = (
        _hist("back", ["growth", "emerging", "emerging"], start_day=12)   # newer
        + _hist("fwd", ["research", "emerging"], start_day=1)             # older, pending
    )
    trans = tl.detect_transitions(history)
    back = next(t for t in trans if t["technology"] == "back")
    fwd = next(t for t in trans if t["technology"] == "fwd")
    assert back["backward"] is True and back["confirmed"] is True
    assert back["suspect"] is True                 # backward ⇒ suspect regardless
    assert fwd["backward"] is False and fwd["confirmed"] is False
    assert trans.index(fwd) < trans.index(back)    # backward sinks hardest


def test_backward_flag_on_adoption_axis():
    history = [
        {"technology": "a", "as_of": "2026-06-12", "adoption_stage": "early-majority"},
        {"technology": "a", "as_of": "2026-06-13", "adoption_stage": "early-adopters"},
    ]
    t = tl.detect_transitions(history)[0]
    assert t["dimension"] == "adoption"
    assert (t["from"], t["to"]) == ("early-majority", "early-adopters")
    assert t["backward"] is True and t["suspect"] is True


def test_unknown_legacy_stage_label_not_judged_backward():
    # A stage outside the vocabulary ('ferment', pre-refactor data) can't be
    # ranked — direction defaults to forward (backward=False), never a crash.
    history = [
        {"technology": "l", "as_of": "2026-06-12", "maturity_stage": "ferment"},
        {"technology": "l", "as_of": "2026-06-13", "maturity_stage": "growth"},
    ]
    t = tl.detect_transitions(history)[0]
    assert t["backward"] is False


def test_trust_sort_order_backward_then_contested_then_pending():
    # Full ordering across the trust grades, all with the same recency shape:
    # clean-confirmed > pending(unconfirmed) > contested > backward.
    history = (
        _hist("clean", ["emerging", "growth", "growth"], maturity_mixed=False)
        + _hist("pend", ["emerging", "growth"], maturity_mixed=False)
        + _hist("cont", ["emerging", "growth", "growth"], maturity_mixed=True)
        + _hist("back", ["growth", "emerging", "emerging"], maturity_mixed=False)
    )
    order = [t["technology"] for t in tl.detect_transitions(history)]
    assert order == ["clean", "pend", "cont", "back"]


# ══════════════════════════════════════════════════════════════════════════════
# D. cross-surface consistency
# ══════════════════════════════════════════════════════════════════════════════

def _chart_rows(spec, key):
    """First list-of-dicts in a Vega-Lite spec whose dicts carry `key`."""
    hit = []
    def walk(o):
        if isinstance(o, list) and o and all(isinstance(x, dict) for x in o) \
                and any(key in x for x in o):
            hit.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(spec)
    return hit[0] if hit else None


_BIMODAL = {
    "tech": "adv", "label": "Adv", "domain": "Chips",
    "maturity": "emerging", "adoption": "innovators", "move": "entry-timing",
    "articles": 5, "entrants": 3,
    "stage_centroid": 2.2, "stage_articles": 5, "committed_stage": "growth",
    "stage_dist": {"emerging": 3, "mature": 2}, "mixed": True, "modal_share": 0.6,
    "adoption_centroid": 1.2, "adoption_articles": 5,
    "adoption_committed": "early-adopters",
    "adoption_dist": {"innovators": 4, "early-adopters": 1},
    "adoption_mixed": True, "adoption_modal_share": 0.8,
}


def test_chart_band_equals_display_stage_on_both_curves():
    # The band the S-curve/diffusion chart places the dot in must equal
    # display_stage() — the function every surface (placement table, Compare,
    # Strategist context, /api/mot, /api/explore) uses. On a bimodal spread the
    # bare modal would name a different stage; the surfaces must all follow the
    # chart, i.e. the centroid.
    p = dict(_BIMODAL)
    srow = {r["label"]: r for r in
            _chart_rows(ma.tech_scurve_chart([p], min_articles=3).to_dict(), "band")}["Adv"]
    assert srow["band"] == tl.display_stage(p) == "growth"
    assert srow["band"] != p["maturity"]           # ≠ bare modal: the drift case

    arow = {r["label"]: r for r in
            _chart_rows(ma.adoption_curve_chart([p], min_articles=3).to_dict(), "band")}["Adv"]
    assert arow["band"] == tl.display_stage(p, "adoption") == "early-adopters"

    # scurve_position (Compare's ranking) must match the chart's x-source too.
    assert ma.scurve_position(p) == p["stage_centroid"]


def test_display_stage_fallback_matches_inline_copies():
    # mot_analyst.scurve_position and interpret_tech used to carry inline copies
    # of the display fallback (committed_stage or maturity); they now delegate to
    # tech_layer.display_stage via mot_analyst._display_stage (lazy import). Keep
    # pinning that they agree with display_stage on every fallback shape.
    shapes = [
        {"committed_stage": "growth", "maturity": "emerging"},
        {"maturity": "emerging"},                          # legacy: modal only
        {"committed_stage": None, "maturity": "mature"},
        {},
    ]
    for p in shapes:
        expected = p.get("committed_stage") or p.get("maturity")
        assert tl.display_stage(p) == expected
        txt = ma.interpret_tech([{**p, "label": "T", "stage_articles": 9}])
        if expected in ("research", "emerging", "growth"):
            assert "T" in txt                     # named under its DISPLAYED stage
        elif expected:                            # placed (counted) but not narrated
            assert txt.startswith("1 tracked")
        else:                                     # no stage at all → nothing placed
            assert txt == ""


class _FakeTable:
    def __init__(self, parent):
        self.parent = parent
        self.rows = None

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


def test_snapshot_persists_displayed_stage_not_modal(monkeypatch):
    # CONSISTENCY FIX (was a strict xfail documenting the gap): snapshot() now
    # persists the stage display_stage() yields — the centroid-committed stage
    # every surface shows — not the bare modal. History, transitions, watchlist
    # alerts and Strategist context therefore speak the same stage names as the
    # placement table by construction, even on a bimodal spread where modal and
    # committed disagree.
    fake = _FakeClient()
    ta = tl.TechAnalyst(client=fake)
    p = dict(_BIMODAL)
    monkeypatch.setattr(ta, "current_placements", lambda days=30: [p])
    assert ta.snapshot() == 1
    row = fake.last_upsert[0]
    # The history table records what the surfaces display…
    assert row["maturity_stage"] == tl.display_stage(p) == "growth"
    assert row["adoption_stage"] == tl.display_stage(p, "adoption") == "early-adopters"
    # …NOT the bare modal (the historical drift case).
    assert row["maturity_stage"] != p["maturity"]                  # ≠ 'emerging'
    assert row["adoption_stage"] != p["adoption"]                  # ≠ 'innovators'
    # The confidence flags still ride along, so a bimodal snapshot stays fadeable.
    assert row["maturity_mixed"] is True and row["adoption_mixed"] is True


def test_snapshot_modal_fallback_when_no_committed_stage():
    # Legacy/partial placements without centroid stats fall back to the bare
    # modal — display_stage's own fallback — so nothing is dropped from history.
    p = {"tech": "t", "label": "T", "domain": "D", "maturity": "growth",
         "adoption": "innovators", "move": None, "articles": 3, "entrants": 1}
    fake = _FakeClient()
    ta = tl.TechAnalyst(client=fake)
    ta.current_placements = lambda days=30: [p]
    assert ta.snapshot() == 1
    row = fake.last_upsert[0]
    assert row["maturity_stage"] == "growth" and row["adoption_stage"] == "innovators"


def test_modal_to_committed_migration_transition_is_suspect():
    # One-time semantics change: history rows written before the fix hold the
    # bare MODAL stage; new snapshots hold the COMMITTED stage. For a tech whose
    # stored modal ≠ committed (exactly the bimodal case, so the old row carried
    # mixed=True and today's snapshot for a similar corpus does too), the first
    # committed-semantics snapshot reads as a stage change. Pin that this
    # one-time move is never headlined: run==1 → unconfirmed, destination
    # mixed → contested — suspect either way, downranked, never watchlist-alerted
    # (the same treatment contested moves already get).
    history = [
        # pre-fix row: bare modal 'emerging' persisted, mixed=True (modal≠committed)
        {"technology": "adv", "label": "Adv", "as_of": "2026-06-30",
         "maturity_stage": "emerging", "maturity_mixed": True, "maturity_modal_share": 0.6},
        # first post-fix row: committed 'growth' persisted, still a bimodal corpus
        {"technology": "adv", "label": "Adv", "as_of": "2026-07-01",
         "maturity_stage": "growth", "maturity_mixed": True, "maturity_modal_share": 0.6},
    ]
    trans = [t for t in tl.detect_transitions(history) if t["dimension"] == "maturity"]
    assert len(trans) == 1
    t = trans[0]
    assert (t["from"], t["to"]) == ("emerging", "growth")
    assert t["confirmed"] is False                 # run==1 — debounce holds it pending
    assert t["contested"] is True                  # destination snapshot is mixed
    assert t["suspect"] is True                    # → downranked, no watchlist alert
