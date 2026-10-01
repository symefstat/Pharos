"""The Analyst engine — posture parsing, validation, exhibits, pack (pure)."""

from analytics.analyst import (
    THIN_COVERAGE_BELOW,
    build_exhibits,
    format_pack,
    parse_posture,
    validate_report,
)

GOOD_BLOCK = """
POSTURE: watch
ADDRESSEE: corporate strategy teams evaluating grid-scale storage
CONFIDENCE: 65%
WRONG IF: no utility-scale sodium-ion deployment above 100MWh is announced by 2027-03-31
RESOLVE BY: 2027-03-31
"""

GOOD_REPORT = (
    "## Bottom line\nSodium-ion is real but pre-chasm [S1].\n\n"
    "## The evidence\nCATL began mass production [S2]; a classic standards battle on cost.\n\n"
    "## Market & capital\nTwo commitments vs five options — capital is buying information.\n\n"
    "## Risks — and what would prove this wrong\nLithium price collapse removes the wedge [S1].\n\n"
    "## Recommended posture\nStay close, don't commit.\n" + GOOD_BLOCK
)


# ── posture block ──────────────────────────────────────────────────────────────

def test_parse_posture_happy_path():
    p = parse_posture(GOOD_BLOCK)
    assert p == {
        "posture": "watch",
        "addressee": "corporate strategy teams evaluating grid-scale storage",
        "confidence": 0.65,
        "falsifier": "no utility-scale sodium-ion deployment above 100MWh is announced by 2027-03-31",
        "resolve_by": "2027-03-31",
    }


def test_parse_posture_rejects_missing_fields():
    assert parse_posture(GOOD_BLOCK.replace("WRONG IF:", "NOPE:")) is None
    assert parse_posture(GOOD_BLOCK.replace("2027-03-31", "sometime")) is None
    assert parse_posture(GOOD_BLOCK.replace("65%", "high")) is None
    assert parse_posture(GOOD_BLOCK.replace("watch", "hold")) is None
    assert parse_posture("") is None


# ── report validation ──────────────────────────────────────────────────────────

def test_validate_accepts_good_report():
    assert validate_report(GOOD_REPORT, n_stories=2) is None


def test_validate_rejects_theory_tags_and_phantoms():
    assert "forbidden" in validate_report(GOOD_REPORT + " per [T3].", 2)
    assert "phantom" in validate_report(GOOD_REPORT.replace("[S2]", "[S9]"), 2)


def test_validate_rejects_shape_failures():
    assert validate_report("tiny", 2) == "too short"
    no_block = GOOD_REPORT.replace("POSTURE: watch", "")
    assert "posture block" in validate_report(no_block, 2)
    bloated = GOOD_REPORT + " word" * 900
    assert "length ceiling" in validate_report(bloated, 2)


# ── exhibits ───────────────────────────────────────────────────────────────────

def test_exhibits_computed_from_data():
    stories = [
        {"published_at": "2026-05-10T08:00:00Z", "companies": ["CATL"]},
        {"published_at": "2026-05-20T08:00:00Z", "companies": ["CATL", "BYD Co Ltd"]},
        {"published_at": "2026-06-01T08:00:00Z", "companies": ["BYD"]},
    ]
    tracked = [{"tech": "grid-storage", "label": "Grid-scale storage",
                "maturity": "dominant-design", "adoption": "early-majority",
                "watching": False, "articles": 40}]
    capital = {"counts": {"commitment": 2, "option": 5}}
    funding = {"rounds": 4, "early": 3, "late": 1, "read": "early-phase"}
    ex = build_exhibits(stories, tracked, capital, funding)
    assert ex["mention_trend"] == [{"month": "2026-05", "count": 2},
                                   {"month": "2026-06", "count": 1}]
    assert ex["players"][0]["name"] == "CATL" and ex["players"][0]["mentions"] == 2
    # entity aliasing folds "BYD Co Ltd" into BYD
    assert {"name": "BYD", "mentions": 2} in ex["players"]
    assert ex["capital_split"] == {"commitment": 2, "option": 5}
    assert ex["stage_table"][0]["maturity"] == "dominant-design"
    assert ex["funding"]["rounds"] == 4


# ── pack ───────────────────────────────────────────────────────────────────────

def test_pack_flags_thin_coverage_and_unlabels_theory():
    stories = [{"published_at": "2026-06-01", "_feed_label": "EV",
                "title": "One story", "summary": "s"}] * (THIN_COVERAGE_BELOW - 1)
    pack = format_pack("sodium-ion", stories, [], [],
                       {"counts": {"commitment": 0, "option": 0}}, None,
                       [{"chunk_text": "dominant design theory says X"}], None, "2026-07-10")
    assert "COVERAGE: thin" in pack
    assert "apply by NAME in prose" in pack
    assert "[T1]" not in pack                       # theory is deliberately unlabeled
    assert "[S1]" in pack


def test_pack_empty_coverage_says_so():
    pack = format_pack("underwater basket weaving", [], [], [],
                       {"counts": {"commitment": 0, "option": 0}}, None, [], None, "2026-07-10")
    assert "(none — the feeds do not cover this topic)" in pack


def test_parse_posture_tolerates_markdown_decoration():
    decorated = """
**POSTURE:** watch
- **ADDRESSEE**: grid operators
> CONFIDENCE: 70%
**WRONG IF:** no deployment above 100MWh by 2027-03-31
**RESOLVE BY:** 2027-03-31
"""
    p = parse_posture(decorated)
    assert p is not None
    assert p["posture"] == "watch" and p["confidence"] == 0.70
    assert p["addressee"] == "grid operators"


def test_normalize_citations_expands_groups():
    from analytics.analyst import normalize_citations
    assert normalize_citations("Real [S2, S4] and [S1,S3, S5].") == "Real [S2][S4] and [S1][S3][S5]."
    assert normalize_citations("Single [S7] untouched.") == "Single [S7] untouched."
    # grouped phantoms become individually checkable
    assert "phantom" in validate_report(
        GOOD_REPORT.replace("[S1]", normalize_citations("[S1, S9]")), 2)


# ── follow-up interrogation ────────────────────────────────────────────────────

REPORT_ROW = {"id": 7, "topic": "sodium-ion", "as_of": "2026-07-10",
              "report": "## Bottom line\nWatch [S1].",
              "citations": [{"label": "S1", "title": "CATL launches", "feed": "EV",
                             "published_at": "2026-06-22"}]}


def test_format_followup_carries_rules_and_sources():
    from analytics.analyst import format_followup
    pack = format_followup(REPORT_ROW, "why watch and not invest?",
                           history=[{"role": "user", "content": "earlier q"},
                                    {"role": "assistant", "content": "earlier a"}])
    assert pack.startswith("FOLLOW-UP QUESTION on report #7")
    assert "THE PUBLISHED REPORT (immutable" in pack
    assert "[S1] (2026-06-22, EV) CATL launches" in pack
    assert "STANDS AS WRITTEN" in pack and "never revise the posture" in pack
    assert "USER: earlier q" in pack


def test_validate_followup():
    from analytics.analyst import validate_followup
    assert validate_followup("The thesis rests on CATL's launch [S1] — commercial, not pilot.", 1) is None
    assert "phantom" in validate_followup("Because [S9] says so and more words here.", 1)
    assert "forbidden" in validate_followup("Theory [T1] applies here and more words.", 1)
    assert validate_followup("hi", 1) == "too short"
