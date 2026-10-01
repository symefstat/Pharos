"""Tests for the technology unit-of-analysis layer (pure functions)."""

import analytics.tech_layer as tl
import analytics.mot_analyst as ma


def test_match_technologies_by_keyword_in_title_and_companies():
    assert "glp-1" in tl.match_technologies({"title": "Novo's Wegovy sales surge"})
    assert "advanced-logic" in tl.match_technologies({"summary": "TSMC ramps its 2nm node"})
    assert "ai-accelerators" in tl.match_technologies({"companies": ["Nvidia"], "title": "new GPU"})
    assert tl.match_technologies({"title": "a quiet day in markets"}) == []


def test_match_multiple_technologies():
    keys = tl.match_technologies({"title": "HBM memory demand from AI data centers"})
    assert "hbm-memory" in keys and "ai-datacenters" in keys


def test_placements_rolls_up_modal_stage_and_counts_entrants():
    rows = [
        {"title": "TSMC 2nm ramp", "companies": ["TSMC"], "maturity_stage": "growth",
         "adoption_stage": "early-adopters", "strategic_move": "standards-battle"},
        {"title": "Samsung 2nm yields", "companies": ["Samsung"], "maturity_stage": "growth",
         "adoption_stage": "early-adopters", "strategic_move": "standards-battle"},
        {"title": "Intel 2nm delay", "companies": ["Intel"], "maturity_stage": "emerging",
         "adoption_stage": "innovators", "strategic_move": "entry-timing"},
        {"title": "unrelated", "companies": ["Acme"], "maturity_stage": "growth"},  # no tech match
    ]
    plc = tl.placements(rows)
    adv = next(p for p in plc if p["tech"] == "advanced-logic")
    assert adv["maturity"] == "growth"          # 2 growth vs 1 emerging → modal growth
    assert adv["articles"] == 3                 # 3 classified matched
    assert adv["entrants"] == 3                 # TSMC, Samsung, Intel
    assert adv["domain"] == "Chips"


def test_placements_skips_unclassified_only_tech():
    rows = [{"title": "perovskite research note", "maturity_stage": None}]
    assert [p for p in tl.placements(rows) if p["tech"] == "perovskite-solar"] == []


def test_domain_labels_align_with_feed_labels():
    # Registry domains mirror feeds.py labels wherever a 1:1 feed exists;
    # Frontier / Supply chain are cross-feed technology groupings, not feeds.
    from feeds import FEEDS
    from technologies import DOMAIN_LABELS, TECHNOLOGIES, domain_label

    feed_labels = {f.label for f in FEEDS}
    groupings = {"Frontier", "Supply chain"}
    for t in TECHNOLOGIES:
        if t.domain not in groupings:
            assert t.domain in feed_labels, f"{t.key}: {t.domain!r} is not a feed label"
        assert t.domain not in DOMAIN_LABELS, f"{t.key} still uses a legacy domain"
    # Legacy stored strings map to the current labels; current strings pass through.
    assert domain_label("Mobility") == "EV"
    assert domain_label("AI & energy") == "AI & Energy"
    assert domain_label("Climate") == "Climate & Energy"
    assert domain_label("Biotech") == "Biotech & Health"
    assert domain_label("Frontier") == "Frontier"
    assert domain_label("Chips") == "Chips"
    assert domain_label(None) is None


def test_detect_transitions_maps_legacy_stored_domain_at_read_time():
    # Pre-alignment history rows hold old domain strings; the reader maps them
    # so old and new snapshots render identically — the DB is never rewritten.
    history = [
        {"technology": "solid-state-batteries", "label": "Solid-state batteries",
         "domain": "Mobility", "as_of": "2026-07-01", "maturity_stage": "emerging"},
        {"technology": "solid-state-batteries", "label": "Solid-state batteries",
         "domain": "Mobility", "as_of": "2026-07-02", "maturity_stage": "growth"},
    ]
    trans = tl.detect_transitions(history)
    assert trans and trans[0]["domain"] == "EV"


def test_detect_transitions_flags_stage_change_between_last_two_snapshots():
    history = [
        {"technology": "glp-1", "label": "GLP-1 drugs", "as_of": "2026-06-10",
         "maturity_stage": "growth", "adoption_stage": "early-adopters"},
        {"technology": "glp-1", "label": "GLP-1 drugs", "as_of": "2026-06-11",
         "maturity_stage": "growth", "adoption_stage": "early-majority"},   # crossed the chasm
        {"technology": "quantum-computing", "label": "Quantum", "as_of": "2026-06-11",
         "maturity_stage": "research"},                                     # only one snapshot
    ]
    trans = tl.detect_transitions(history)
    assert len(trans) == 1
    t = trans[0]
    assert t["technology"] == "glp-1" and t["dimension"] == "adoption"
    assert t["from"] == "early-adopters" and t["to"] == "early-majority"


def test_detect_transitions_ignores_unchanged():
    history = [
        {"technology": "x", "as_of": "2026-06-10", "maturity_stage": "growth"},
        {"technology": "x", "as_of": "2026-06-11", "maturity_stage": "growth"},
    ]
    assert tl.detect_transitions(history) == []


def test_stage_stats_centroid_committed_and_mixed():
    items = (
        [{"maturity_stage": "research"}] * 1
        + [{"maturity_stage": "emerging"}] * 13
        + [{"maturity_stage": "growth"}] * 8
        + [{"maturity_stage": "mature"}] * 6
        + [{"maturity_stage": "n/a"}] * 2           # excluded — no S-curve position
        + [{"maturity_stage": None}] * 3            # excluded
    )
    s = tl._stage_stats(items)
    assert s["stage_articles"] == 28                # n/a + None dropped (was 31)
    assert s["stage_dist"] == {"research": 1, "emerging": 13, "growth": 8, "mature": 6}
    # centroid = (1·0 + 13·1 + 8·2 + 6·4) / 28 = 53/28 ≈ 1.893  (mature index = 4)
    assert s["stage_centroid"] == round(53 / 28, 3)
    assert s["committed_stage"] == "growth"         # round(1.893) → 2 → growth, NOT modal 'emerging'
    assert s["mixed"] is True                       # modal share 13/28 = 46% < 50%
    empty = tl._stage_stats([{"maturity_stage": "n/a"}])
    assert empty["stage_centroid"] is None and empty["committed_stage"] is None
    assert empty["mixed"] is False and empty["stage_articles"] == 0


def test_stage_stats_clear_majority_not_mixed():
    s = tl._stage_stats([{"maturity_stage": "growth"}] * 7 + [{"maturity_stage": "emerging"}] * 2)
    assert s["committed_stage"] == "growth" and s["mixed"] is False     # 7/9 = 78%


def test_dimension_stats_fades_off_mode_and_ties():
    # Bimodal: the PLURALITY is early-majority (post-chasm), but the centroid (9/7≈1.29)
    # lands at early-adopters — a category only 1 of 7 articles chose. Must be faded,
    # even though early-majority holds 57% (> the old 50% bar).
    s = tl._dimension_stats(
        [{"adoption_stage": "early-majority"}] * 4 + [{"adoption_stage": "innovators"}] * 2
        + [{"adoption_stage": "early-adopters"}], "adoption_stage", tl._ADOPTION_ORDER)
    assert s["committed"] == "early-adopters" and s["modal_share"] == round(4 / 7, 3)
    assert s["mixed"] is True                          # placed off its own mode → contested

    # Exact 50/50 → contested (the old `< 0.5` let this through as 'clear').
    tie = tl._dimension_stats(
        [{"maturity_stage": "emerging"}, {"maturity_stage": "growth"}],
        "maturity_stage", tl._MATURITY_ORDER)
    assert tie["mixed"] is True

    # A clean majority that IS where the dot sits stays solid.
    clear = tl._dimension_stats(
        [{"adoption_stage": "early-adopters"}] * 5 + [{"adoption_stage": "innovators"}],
        "adoption_stage", tl._ADOPTION_ORDER)
    assert clear["committed"] == "early-adopters" and clear["mixed"] is False


def _find_rows(spec, key):
    """First list-of-dicts in the Vega-Lite spec whose dicts carry `key`."""
    hit = []
    def walk(o):
        if isinstance(o, list) and o and all(isinstance(x, dict) for x in o) and any(key in x for x in o):
            hit.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(spec)
    return hit[0] if hit else None


def test_tech_scurve_centroid_placement_fade_and_min_articles():
    base = dict(adoption="innovators", move="entry-timing", entrants=4)
    plc = [
        {**base, "tech": "ai-dc", "label": "AI data centres", "domain": "AI & energy",
         "maturity": "emerging", "articles": 46, "stage_articles": 28, "stage_centroid": 1.89,
         "committed_stage": "growth", "stage_dist": {"emerging": 13, "growth": 8, "mature": 6, "research": 1},
         "mixed": True},
        {**base, "tech": "tiny", "label": "Tiny", "domain": "Biotech", "maturity": "emerging",
         "articles": 2, "stage_articles": 2, "stage_centroid": 1.0, "committed_stage": "emerging",
         "stage_dist": {"emerging": 2}, "mixed": False},
    ]
    rows = _find_rows(ma.tech_scurve_chart(plc, min_articles=3).to_dict(), "alpha")
    by = {r["label"]: r for r in rows}
    assert "Tiny" not in by                         # < 3 on-curve articles → dropped
    dc = by["AI data centres"]
    assert dc["band"] == "growth"                   # placed by centroid, not modal 'emerging'
    assert dc["size_n"] == 28                        # on-curve coverage (not 46)
    assert dc["alpha"] == 0.4                         # contested → faded
    # everything below the floor → no chart
    assert ma.tech_scurve_chart([plc[1]], min_articles=3) is None


def test_dimension_stats_generalizes_to_adoption():
    items = ([{"adoption_stage": "innovators"}]
             + [{"adoption_stage": "early-adopters"}] * 6
             + [{"adoption_stage": "early-majority"}] * 3
             + [{"adoption_stage": "n/a"}] * 2)         # n/a excluded
    s = tl._dimension_stats(items, "adoption_stage", tl._ADOPTION_ORDER)
    assert s["articles"] == 10
    assert s["centroid"] == 1.2                          # (0·1 + 1·6 + 2·3)/10
    assert s["committed"] == "early-adopters" and s["mixed"] is False   # modal 6/10 = 60%
    # placements emits the adoption_* family
    a = tl._adoption_stats([{"adoption_stage": "early-majority"}] * 4)
    assert a["adoption_committed"] == "early-majority" and a["adoption_centroid"] == 2.0


def test_adoption_curve_chart_places_and_marks_chasm():
    base = dict(move="entry-timing", entrants=4)
    plc = [
        {**base, "label": "Pre", "domain": "Frontier", "adoption_centroid": 0.5,
         "adoption_articles": 8, "adoption_committed": "early-adopters",
         "adoption_dist": {"innovators": 4, "early-adopters": 4}, "adoption_mixed": True},
        {**base, "label": "Post", "domain": "Chips", "adoption_centroid": 2.8,
         "adoption_articles": 10, "adoption_committed": "late-majority",
         "adoption_dist": {"early-majority": 4, "late-majority": 6}, "adoption_mixed": True},
    ]
    chart = ma.adoption_curve_chart(plc, min_articles=3)
    rows = _find_rows(chart.to_dict(), "band")
    bands = {r["band"] for r in rows}
    assert "early-adopters" in bands and "late-majority" in bands       # placed by adoption centroid
    # a red chasm rule is present (its colour appears in the spec)
    import json
    assert "#cf6679" in json.dumps(chart.to_dict())
    # nothing meets the floor → no chart
    assert ma.adoption_curve_chart([{"adoption_centroid": 1.0, "adoption_articles": 1}]) is None


def test_interpret_tech_honors_min_articles():
    plc = [
        {"label": "Big", "committed_stage": "growth", "stage_articles": 10, "maturity": "growth"},
        {"label": "Tiny", "committed_stage": "emerging", "stage_articles": 2, "maturity": "emerging"},
    ]
    txt = ma.interpret_tech(plc, min_articles=3)
    assert "Big" in txt and "Tiny" not in txt        # sub-floor tech isn't narrated
    assert txt.startswith("1 tracked")               # counts only placed techs


# ── confidence propagation (Phase 1.2) ───────────────────────────────────────

def test_detect_transitions_carries_destination_confidence():
    history = [
        {"technology": "glp-1", "as_of": "2026-06-10", "maturity_stage": "emerging"},
        {"technology": "glp-1", "as_of": "2026-06-11", "maturity_stage": "growth",
         "maturity_modal_share": 0.8, "maturity_mixed": False},
    ]
    t = tl.detect_transitions(history)[0]
    assert t["contested"] is False and t["modal_share"] == 0.8


def test_detect_transitions_old_rows_read_as_not_contested():
    # Rows predating the confidence columns → contested False / modal_share None.
    history = [
        {"technology": "x", "as_of": "2026-06-10", "adoption_stage": "early-adopters"},
        {"technology": "x", "as_of": "2026-06-11", "adoption_stage": "early-majority"},
    ]
    t = tl.detect_transitions(history)[0]
    assert t["contested"] is False and t["modal_share"] is None


def test_detect_transitions_downranks_contested_below_confident():
    history = [
        # contested maturity flip, most recent
        {"technology": "a", "label": "A", "as_of": "2026-06-12", "maturity_stage": "emerging"},
        {"technology": "a", "label": "A", "as_of": "2026-06-13", "maturity_stage": "growth",
         "maturity_mixed": True, "maturity_modal_share": 0.4},
        # high-confidence maturity flip, older
        {"technology": "b", "label": "B", "as_of": "2026-06-10", "maturity_stage": "research"},
        {"technology": "b", "label": "B", "as_of": "2026-06-11", "maturity_stage": "emerging",
         "maturity_mixed": False, "maturity_modal_share": 0.9},
    ]
    trans = tl.detect_transitions(history)
    # high-confidence surfaces first despite its older date; contested is kept, not dropped
    assert [t["technology"] for t in trans] == ["b", "a"]
    assert trans[0]["contested"] is False and trans[1]["contested"] is True


# ── direction-aware gate + debounce (near-monotonic axes) ─────────────────────

def test_detect_transitions_flags_and_downranks_backward_moves():
    # Maturity/adoption are near-monotonic: a backward move (emerging→research) is
    # almost always re-estimation noise. It must be flagged and sunk below a forward
    # move even though it is the more recent event.
    history = [
        # forward, confirmed maturity move (research→emerging, held 2 snapshots)
        {"technology": "fwd", "label": "Fwd", "as_of": "2026-06-10", "maturity_stage": "research"},
        {"technology": "fwd", "label": "Fwd", "as_of": "2026-06-11", "maturity_stage": "emerging",
         "maturity_mixed": False, "maturity_modal_share": 0.9},
        {"technology": "fwd", "label": "Fwd", "as_of": "2026-06-12", "maturity_stage": "emerging",
         "maturity_mixed": False, "maturity_modal_share": 0.9},
        # backward maturity move (emerging→research), the most recent event
        {"technology": "back", "label": "Back", "as_of": "2026-06-12", "maturity_stage": "emerging"},
        {"technology": "back", "label": "Back", "as_of": "2026-06-13", "maturity_stage": "research",
         "maturity_mixed": False, "maturity_modal_share": 0.9},
    ]
    trans = tl.detect_transitions(history)
    back = next(t for t in trans if t["technology"] == "back")
    fwd = next(t for t in trans if t["technology"] == "fwd")
    assert back["backward"] is True and back["suspect"] is True
    assert fwd["backward"] is False and fwd["confirmed"] is True and fwd["suspect"] is False
    # the backward move sinks below the forward one despite its later date
    assert trans.index(fwd) < trans.index(back)


def test_detect_transitions_debounce_confirms_persisted_stage():
    # A flip seen in only the latest snapshot is PENDING (run 1, suspect); the same
    # flip once it has held for ≥2 snapshots is CONFIRMED (trustworthy).
    pending = [
        {"technology": "p", "as_of": "2026-06-11", "maturity_stage": "emerging"},
        {"technology": "p", "as_of": "2026-06-12", "maturity_stage": "growth", "maturity_mixed": False},
    ]
    t = tl.detect_transitions(pending)[0]
    assert (t["from"], t["to"]) == ("emerging", "growth")
    assert t["confirmed"] is False and t["suspect"] is True

    confirmed = [
        {"technology": "c", "as_of": "2026-06-10", "maturity_stage": "emerging"},
        {"technology": "c", "as_of": "2026-06-11", "maturity_stage": "growth", "maturity_mixed": False},
        {"technology": "c", "as_of": "2026-06-12", "maturity_stage": "growth", "maturity_mixed": False},
    ]
    t = tl.detect_transitions(confirmed)[0]
    assert t["confirmed"] is True and t["backward"] is False and t["suspect"] is False


def test_detect_transitions_drops_long_settled_moves():
    # 'growth' has held for far more than the freshness window since the move →
    # no longer a *current* event, so it drops off the feed entirely.
    history = [{"technology": "old", "as_of": "2026-06-05", "maturity_stage": "emerging"}] + [
        {"technology": "old", "as_of": f"2026-06-{d:02d}", "maturity_stage": "growth"}
        for d in range(6, 12)   # six consecutive 'growth' snapshots — well past the window
    ]
    assert tl.detect_transitions(history) == []


class _FakeTable:
    def __init__(self, parent):
        self.parent = parent
        self.rows = None

    def upsert(self, rows, on_conflict=None):
        self.rows = rows
        return self

    def execute(self):
        self.parent.calls += 1
        if self.parent.fail_first and self.parent.calls == 1:
            raise Exception(
                "Could not find the 'maturity_modal_share' column of "
                "'technology_stage_history' in the schema cache"
            )
        self.parent.last_upsert = self.rows
        return type("Resp", (), {"data": self.rows})()


class _FakeClient:
    def __init__(self, fail_first=False):
        self.fail_first = fail_first
        self.calls = 0
        self.last_upsert = None

    def table(self, name):
        return _FakeTable(self)


_PLACEMENT = {
    "tech": "glp-1", "label": "GLP-1", "domain": "Biotech",
    "maturity": "growth", "adoption": "early-majority", "move": "platform",
    "articles": 7, "entrants": 3,
    "modal_share": 0.78, "mixed": False,
    "adoption_modal_share": 0.46, "adoption_mixed": True,
}


def test_snapshot_persists_confidence(monkeypatch):
    fake = _FakeClient()
    ta = tl.TechAnalyst(client=fake)
    monkeypatch.setattr(ta, "current_placements", lambda days=30: [dict(_PLACEMENT)])
    assert ta.snapshot() == 1
    row = fake.last_upsert[0]
    assert row["maturity_modal_share"] == 0.78 and row["maturity_mixed"] is False
    assert row["adoption_modal_share"] == 0.46 and row["adoption_mixed"] is True


def test_snapshot_degrades_without_confidence_columns(monkeypatch):
    fake = _FakeClient(fail_first=True)
    ta = tl.TechAnalyst(client=fake)
    monkeypatch.setattr(ta, "current_placements", lambda days=30: [dict(_PLACEMENT)])
    assert ta.snapshot() == 1          # still succeeds
    assert fake.calls == 2             # failed once, retried once
    row = fake.last_upsert[0]
    assert all(c not in row for c in tl._CONFIDENCE_COLS)  # confidence stripped
    assert row["maturity_stage"] == "growth"               # core fields still persisted


def test_tech_scurve_chart_spec_valid_and_empty_none():
    plc = [
        {"tech": "glp-1", "label": "GLP-1", "domain": "Biotech", "maturity": "growth",
         "adoption": "early-majority", "move": "platform", "articles": 5, "entrants": 3},
        {"tech": "advanced-logic", "label": "≤3nm", "domain": "Chips", "maturity": "growth",
         "adoption": "early-adopters", "move": "standards-battle", "articles": 4, "entrants": 3},
        {"tech": "quantum-computing", "label": "Quantum", "domain": "Frontier", "maturity": "emerging",
         "adoption": "innovators", "move": "entry-timing", "articles": 2, "entrants": 2},
    ]
    chart = ma.tech_scurve_chart(plc)
    assert chart is not None and (chart.to_dict().get("layer") or chart.to_dict().get("mark"))
    assert ma.tech_scurve_chart([]) is None
    assert "growth" in ma.interpret_tech(plc).lower()


def test_display_stage_prefers_committed_over_modal():
    # The displayed stage is the centroid-based committed stage (where the curve dot
    # sits), with the bare modal as a fallback for legacy/partial dicts.
    p = {"maturity": "emerging", "committed_stage": "growth",
         "adoption": "innovators", "adoption_committed": "early-adopters"}
    assert tl.display_stage(p) == "growth"                       # centroid, not modal
    assert tl.display_stage(p, "adoption") == "early-adopters"
    assert tl.display_stage({"maturity": "growth"}) == "growth"  # fallback to modal
    assert tl.display_stage({"adoption": "innovators"}, "adoption") == "innovators"
    assert tl.display_stage({}) is None and tl.display_stage({}, "adoption") is None
