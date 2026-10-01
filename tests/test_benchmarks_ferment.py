"""Tests for the measured performance curves + ferment/convergence detection."""

import analytics.mot_analyst as ma
from benchmarks import BENCHMARKS, ADOPTION_BENCHMARKS
from technologies import TECH_BY_KEY


def test_benchmarks_reference_real_technologies_and_are_well_formed():
    for label, table in (("performance", BENCHMARKS), ("adoption", ADOPTION_BENCHMARKS)):
        assert table, f"expected seeded {label} series"
        for key, spec in table.items():
            assert key in TECH_BY_KEY, f"{key} not a known technology"
            assert spec["unit"] and spec["metric"]
            assert isinstance(spec["lower_is_better"], bool)
            assert len(spec["series"]) >= 2
            dates = [d for d, _ in spec["series"]]
            assert dates == sorted(dates)  # ascending by date


def test_adoption_benchmark_chart_renders():
    spec = ADOPTION_BENCHMARKS["ev-charging"]
    chart = ma.benchmark_chart(spec)
    assert chart is not None and chart.to_dict().get("mark")


def test_benchmark_chart_spec_valid_and_thin_series_none():
    spec = BENCHMARKS["lfp-batteries"]
    chart = ma.benchmark_chart(spec)
    assert chart is not None and chart.to_dict().get("mark")
    assert ma.benchmark_chart({"series": [("2020-01-01", 1)]}) is None  # <2 points
    assert ma.benchmark_chart({}) is None


def test_ferment_regime_labels():
    placements = [
        {"label": "Quantum", "maturity": "emerging", "entrants": 6, "articles": 3},   # ferment
        {"label": "≤3nm", "maturity": "growth", "entrants": 5, "articles": 8},         # growth + many → ferment
        {"label": "Niche", "maturity": "growth", "entrants": 1, "articles": 2},        # growth + few → converging
        {"label": "LFP", "maturity": "dominant-design", "entrants": 4, "articles": 6}, # converged
    ]
    by_label = {r["label"]: r["regime"] for r in ma.ferment_regime(placements)}
    assert by_label == {
        "Quantum": "ferment", "≤3nm": "ferment",
        "Niche": "converging", "LFP": "converged",
    }


def test_ferment_chart_and_interpretation():
    regimed = ma.ferment_regime([
        {"label": "Quantum", "maturity": "emerging", "entrants": 6, "articles": 3},
        {"label": "LFP", "maturity": "dominant-design", "entrants": 4, "articles": 6},
    ])
    chart = ma.ferment_chart(regimed)
    assert chart is not None and chart.to_dict().get("mark")
    txt = ma.interpret_ferment(regimed)
    assert "Ferment" in txt and "Converged" in txt
    assert ma.ferment_chart([]) is None


def test_capital_moves_classifies_option_vs_commitment():
    rows = [
        {"title": "Acme raises Series B funding round", "scope": "deal", "tags": ["funding"]},
        {"title": "BigCo to acquire Startup in $2 billion deal", "scope": "deal", "tags": ["m&a"]},
        {"title": "Routine product launch", "scope": "single-company", "tags": ["launch"]},  # not capital
        {"title": "Firm announces partnership", "scope": "deal", "tags": ["deal"]},
    ]
    moves = ma.capital_moves(rows)
    kinds = {m["title"][:4]: m["kind"] for m in moves}
    assert len(moves) == 3                      # the launch is excluded
    assert kinds["Acme"] == "option"            # Series B / funding round / raises
    assert kinds["BigC"] == "commitment"        # acquire / billion
    assert kinds["Firm"] == "option"            # partnership

    board = ma.capital_board(rows)
    assert board["counts"] == {"commitment": 1, "option": 2, "unclear": 0}
    assert len(board["commitment"]) == 1 and len(board["option"]) == 2
    assert "option" in ma.interpret_capital(board).lower()

    empty = ma.capital_board([])
    assert empty["shown"] == 0
    assert "No clearly-typed" in ma.interpret_capital(empty)


def test_capital_posture_flags_over_extension_and_timidity():
    # commitment-heavy into an EARLY field → over-extension (≥3 typed moves clears the floor)
    early = [
        {"title": "BigCo to acquire Startup in $2 billion deal", "scope": "deal",
         "tags": ["m&a"], "maturity_stage": "emerging"},
        {"title": "Mega buyout: merger / takeover completed", "scope": "deal",
         "tags": ["m&a"], "maturity_stage": "emerging"},
        {"title": "Rival commits to a multi-year gigafactory build-out", "scope": "deal",
         "tags": ["capex"], "maturity_stage": "emerging"},
    ]
    p = ma.capital_posture(early)
    assert p["stance"] == "commitment" and p["maturity"] == "emerging"
    assert p["flag"] == "over-extension"

    # option-heavy in a MATURE field → timid
    late = [
        {"title": "Acme raises a Series A funding round", "scope": "deal",
         "tags": ["funding"], "maturity_stage": "mature"},
        {"title": "Co announces a partnership pilot", "scope": "deal",
         "tags": ["deal"], "maturity_stage": "mature"},
        {"title": "Startup secures a seed minority stake", "scope": "deal",
         "tags": ["funding"], "maturity_stage": "mature"},
    ]
    q = ma.capital_posture(late)
    assert q["stance"] == "option" and q["flag"] == "timid"

    assert ma.capital_posture([])["flag"] == "none"


def test_capital_posture_low_confidence_below_floor():
    # Only 2 typed commitments — below the min-count floor → no over-extension verdict.
    rows = [
        {"title": "BigCo to acquire Startup in $2 billion deal", "scope": "deal",
         "tags": ["m&a"], "maturity_stage": "emerging"},
        {"title": "Mega buyout merger takeover", "scope": "deal",
         "tags": ["m&a"], "maturity_stage": "emerging"},
    ]
    p = ma.capital_posture(rows)
    assert p["flag"] == "low-confidence" and p["n"] == 2


def test_capital_moves_both_cues_is_unclear():
    # Trips BOTH a commitment cue (billion/acquire) and an option cue (Series B/raises) →
    # 'unclear', not silently 'commitment' (which used to poison the board).
    rows = [{"title": "Startup raises $2 billion Series B to acquire a rival",
             "scope": "deal", "tags": ["funding"]}]
    assert ma.capital_moves(rows)[0]["kind"] == "unclear"
    assert ma.capital_board(rows)["counts"]["unclear"] == 1
    assert ma.capital_board(rows)["shown"] == 0   # excluded from the board


def test_capital_concentration_by_feed_and_entity():
    rows = [
        {"title": "A raises round", "scope": "deal", "tags": ["funding"],
         "_feed_label": "Chips", "companies": ["Nvidia", "TSMC"]},
        {"title": "Nvidia acquires C", "scope": "deal", "tags": ["m&a"],
         "_feed_label": "Chips", "companies": ["Nvidia"]},
        {"title": "Not a deal", "scope": "single-company", "tags": ["launch"],
         "_feed_label": "Chips", "companies": ["Intel"]},
    ]
    from analytics.weights import article_weight
    nw = article_weight({})  # neutral weight for rows with no impact/source
    conc = ma.capital_concentration(rows)
    assert conc["total"] == 2                       # the launch is excluded (raw row count)
    # by_feed / by_entity counts are significance/source-weighted, then rounded.
    assert conc["by_feed"][0] == {"feed": "Chips", "count": round(2 * nw)}
    assert conc["by_entity"][0]["count"] == round(2 * nw)  # Nvidia in both deals
    assert ma.concentration_chart(conc["by_feed"], "feed") is not None
    assert ma.concentration_chart([], "feed") is None


def test_market_structure_splits_concentration_and_regulation():
    rows = [
        {"title": "BigCo to acquire Startup", "scope": "deal",
         "business_impact": "material", "_feed_label": "Chips"},
        {"title": "Acme raises Series B", "scope": "deal",          # deal, not concentrating
         "business_impact": "notable", "_feed_label": "Chips"},
        {"title": "EU opens antitrust probe", "scope": "regulatory",
         "business_impact": "material", "_feed_label": "Geopolitics"},
    ]
    ms = ma.market_structure(rows)
    assert ms["counts"]["concentrating"] == 1        # the acquisition only
    assert ms["counts"]["regulatory"] == 1
    assert ms["concentrating"][0]["title"].startswith("BigCo")
    txt = ma.interpret_market_structure(ms)
    assert "concentrating" in txt and "regulatory" in txt.lower()
    assert "No market-concentrating" in ma.interpret_market_structure(ma.market_structure([]))
