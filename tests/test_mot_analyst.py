"""Tests for the MOT Analyst reducers, interpretations, and chart specs.

Chart builders are validated headlessly via Altair's `.to_dict()` (which raises
on an invalid spec) — no browser/Streamlit needed.
"""

import analytics.mot_analyst as ma

ROWS = [
    {"maturity_stage": "growth", "adoption_stage": "early-adopters", "strategic_move": "platform",
     "_feed_label": "Chips", "companies": ["TSMC", "Apple"], "tags": ["node"], "sentiment": "positive",
     "business_impact": "material", "scope": "single-company"},
    {"maturity_stage": "growth", "adoption_stage": "early-majority", "strategic_move": "standards-battle",
     "_feed_label": "AI & Energy", "companies": ["Nvidia", "TSMC"], "tags": ["data-center"], "sentiment": "negative",
     "business_impact": "material", "scope": "deal"},
    {"maturity_stage": "emerging", "adoption_stage": "innovators", "strategic_move": "disruption",
     "_feed_label": "Chips", "companies": ["Nvidia"], "tags": ["ai-accelerator"], "sentiment": "neutral",
     "business_impact": "contextual", "scope": "sector"},
    {"maturity_stage": "declining", "adoption_stage": "laggards", "strategic_move": "collaboration",
     "_feed_label": "EV", "companies": ["Ford"], "tags": ["recall"], "sentiment": "negative",
     "business_impact": "material", "scope": "regulatory"},
]
MOMENTUM = [
    {"feed": "Chips", "recent": 12, "prior": 4, "pct": 200.0},
    {"feed": "AI & Energy", "recent": 8, "prior": 9, "pct": -11.0},
    {"feed": "EV", "recent": 3, "prior": 10, "pct": -70.0},
]


def test_scurve_points_only_classified_stages():
    pts = ma.scurve_points(ROWS)
    assert {p["stage"] for p in pts} == {"growth", "emerging", "declining"}
    growth = next(p for p in pts if p["stage"] == "growth")
    assert growth["count"] == 2 and 0 < growth["y"] < 1


def test_scurve_interpretation_flags_discontinuity_and_declining():
    txt = ma.interpret_scurve(ma.scurve_points(ROWS))
    assert "growth" in txt.lower()
    assert "discontinuity" in txt.lower()  # emerging share >= 20%
    assert "declining" in txt.lower()


def test_diffusion_detects_chasm_crossing():
    dp = ma.diffusion_points(ROWS)
    assert any(p["crossed"] for p in dp)  # early-majority present
    assert "crossed the chasm" in ma.interpret_diffusion(dp).lower()


def test_diffusion_pre_chasm_message():
    pre = [{"adoption_stage": "innovators"}, {"adoption_stage": "early-adopters"}]
    assert "pre-chasm" in ma.interpret_diffusion(ma.diffusion_points(pre)).lower()


def test_diffusion_strong_crossing_is_decisive():
    strong = [{"adoption_stage": s} for s in ["early-majority"] * 3 + ["innovators"] * 2]
    txt = ma.interpret_diffusion(ma.diffusion_points(strong)).lower()
    assert "crossed the chasm" in txt and "single most decisive" in txt


def test_diffusion_thin_crossing_is_hedged_not_decisive():
    thin = [{"adoption_stage": "early-majority"}, {"adoption_stage": "innovators"}]  # 1 of 2
    txt = ma.interpret_diffusion(ma.diffusion_points(thin)).lower()
    assert "crossed the chasm" in txt          # still named
    assert "indicative" in txt and "single most decisive" not in txt   # but not asserted


def test_interpret_move_too_few_and_thin_top():
    assert "too few" in ma.interpret_move([{"maturity": "growth", "move": "platform", "count": 1}]).lower()
    # total≥3 but all singletons: top cell hedged AND no winner-take-most claim (fragmented)
    cells = [{"maturity": "growth", "move": "platform", "count": 1},
             {"maturity": "emerging", "move": "standards-battle", "count": 1},
             {"maturity": "growth", "move": "disruption", "count": 1}]
    txt = ma.interpret_move(cells).lower()
    assert "indicative" in txt
    assert "winner-take-most" not in txt       # not asserted off a scatter of singletons
    assert "decisive moves" in txt             # but the decisive count is still reported


def test_interpret_move_winner_take_most_only_when_concentrated():
    cells = [{"maturity": "growth", "move": "platform", "count": 4},
             {"maturity": "emerging", "move": "entry-timing", "count": 1}]
    txt = ma.interpret_move(cells).lower()
    assert "winner-take-most" in txt           # concentrated decisive play (top n=4)
    assert "indicative" not in txt


def test_scorecard_hedges_thin_modal():
    rows = [{"maturity_stage": "growth", "strategic_move": "platform",
             "companies": ["Acme"], "_feed_label": "Chips"},
            {"maturity_stage": "growth", "strategic_move": "platform",
             "companies": ["Acme"], "_feed_label": "EV"}]
    sc = ma.scorecard(rows, "Acme")           # only 2 mentions → thin
    assert "tentatively" in sc["questions"][0]["a"].lower()   # Q1 lifecycle hedged
    assert "thin" in sc["questions"][2]["a"].lower()          # Q3 move hedged


def test_move_matrix_and_decisive_interpretation():
    mm = ma.move_matrix(ROWS)
    assert {(c["maturity"], c["move"]) for c in mm} >= {
        ("growth", "platform"), ("growth", "standards-battle"), ("emerging", "disruption"),
    }
    assert "decisive" in ma.interpret_move(mm).lower()


def test_quadrant_points_one_per_feed_with_modal_maturity():
    qp = ma.quadrant_points(ROWS, MOMENTUM)
    by_feed = {p["feed"]: p for p in qp}
    assert set(by_feed) == {"Chips", "AI & Energy", "EV"}
    assert by_feed["Chips"]["maturity"] == "growth"   # 2 growth vs 1 emerging
    assert by_feed["EV"]["momentum"] == -70.0


def test_convergence_only_multi_feed_entities():
    cc = ma.convergence_cells(ROWS)
    assert {c["entity"] for c in cc} == {"TSMC", "Nvidia"}  # each spans 2 feeds
    assert "spans" in ma.interpret_convergence(cc).lower()


def test_convergence_empty_when_no_overlap():
    single = [{"_feed_label": "EV", "companies": ["Ford"]}]
    assert ma.convergence_cells(single) == []
    assert "no cross-domain" in ma.interpret_convergence([]).lower()


def test_scorecard_seven_questions():
    sc = ma.scorecard(ROWS, "TSMC")
    assert sc["entity"] == "TSMC"
    assert sc["mentions"] == 2
    assert len(sc["questions"]) == 7
    assert set(sc["feeds"]) == {"Chips", "AI & Energy"}
    assert all(q["q"] and q["a"] for q in sc["questions"])


def test_entity_universe_ranks_by_mentions():
    uni = ma.entity_universe(ROWS)
    assert "TSMC" in uni and "Nvidia" in uni and "Ford" in uni


class TestChartSpecsValidate:
    """Each builder must produce a valid Altair spec (.to_dict() raises if not)."""

    def test_all_charts_to_dict(self):
        builders = [
            ma.scurve_chart(ma.scurve_points(ROWS)),
            ma.diffusion_chart(ma.diffusion_points(ROWS)),
            ma.move_chart(ma.move_matrix(ROWS)),
            ma.quadrant_chart(ma.quadrant_points(ROWS, MOMENTUM)),
            ma.convergence_chart(ma.convergence_cells(ROWS)),
        ]
        for ch in builders:
            assert ch is not None
            spec = ch.to_dict()
            assert spec.get("layer") or spec.get("mark")

    def test_empty_inputs_return_none(self):
        assert ma.scurve_chart([]) is None
        assert ma.diffusion_chart([]) is None
        assert ma.move_chart([]) is None
        assert ma.quadrant_chart([]) is None
        assert ma.convergence_chart([]) is None


def test_market_structure_orders_by_real_impact_vocabulary():
    # The sort must use the live business_impact vocabulary (material > contextual >
    # none). A regression here keyed it to non-existent labels ('notable'/'minor'),
    # collapsing contextual and none to the same rank.
    rows = [
        {"scope": "regulatory", "business_impact": "none", "title": "n", "url": "u1"},
        {"scope": "regulatory", "business_impact": "material", "title": "m", "url": "u2"},
        {"scope": "regulatory", "business_impact": "contextual", "title": "c", "url": "u3"},
    ]
    ms = ma.market_structure(rows)
    assert [x["impact"] for x in ms["regulatory"]] == ["material", "contextual", "none"]
    assert ma._IMPACT_RANK == {"material": 0, "contextual": 1, "none": 2}


def test_scurve_position_uses_centroid_and_orders_by_it():
    # Bimodal A: modal 'emerging' but the centroid sits in 'growth' territory; B is a
    # clean 'emerging'. Ranking by centroid puts A ahead of B (the modal alone ties them).
    a = {"maturity": "emerging", "committed_stage": "growth", "stage_centroid": 1.9}
    b = {"maturity": "emerging", "committed_stage": "emerging", "stage_centroid": 1.0}
    assert ma.scurve_position(a) == 1.9 and ma.scurve_position(b) == 1.0
    assert ma.scurve_position(a) > ma.scurve_position(b)
    # No centroid → fall back to the committed/modal stage index.
    assert ma.scurve_position({"committed_stage": "growth"}) == float(ma.MATURITY_ORDER.index("growth"))
    assert ma.scurve_position({"maturity": "research"}) == 0.0
    assert ma.scurve_position({}) is None
