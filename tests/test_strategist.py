"""Tests for the Strategist's pure logic (no network — no agent/embed/DB calls).

generate() and the retribackend/eval/embedding paths are network-bound and not tested
here; the pack-building, query-construction, focus-filtering, and parsing are
pure and are what these cover.
"""

import pytest

from analytics.strategist import Strategist

# Construct with a sentinel client; the methods under test never call it.
S = Strategist(client=object())

STORIES = [
    {"_feed_label": "Chips", "title": "TSMC 2nm ramp", "tags": ["node", "fab"],
     "companies": ["TSMC", "Apple"], "business_impact": "material",
     "maturity_stage": "growth", "_also_in": ["Disruptive Tech"], "summary": "x" * 600},
    {"_feed_label": "AI & Energy", "title": "Data-center demand surge", "tags": ["data-center"],
     "companies": ["Nvidia"], "business_impact": "material", "summary": "short"},
]


def test_theory_query_daily_uses_tags_and_companies_and_framing():
    q = Strategist._theory_query("daily", STORIES)
    assert "node" in q and "TSMC" in q
    assert "S-curve" in q and "dominant design" in q  # the fixed framing


def test_theory_query_freetext_focus_leads_with_focus():
    q = Strategist._theory_query("standards battle in EV charging", STORIES)
    assert q.startswith("standards battle in EV charging")


def test_filter_by_focus_matches_company_and_text():
    assert [r["title"] for r in Strategist._filter_by_focus(STORIES, "tsmc")] == ["TSMC 2nm ramp"]
    assert [r["_feed_label"] for r in Strategist._filter_by_focus(STORIES, "data-center")] == ["AI & Energy"]


def test_filter_by_focus_normalizes_entity():
    rows = [{"title": "x", "companies": ["DeepMind"]}]
    assert Strategist._filter_by_focus(rows, "google")  # DeepMind normalizes to Alphabet (Google)


def test_build_pack_labels_lens_alsoin_and_theory():
    passages = [{"source_file": "Schilling_Ch4.pdf", "similarity": 0.81, "chunk_text": "y" * 900}]
    pack = S._build_pack("daily", STORIES, passages)
    assert "[S1]" in pack and "[S2]" in pack and "[T1]" in pack
    assert "maturity=growth" in pack
    assert "also in: Disruptive Tech" in pack
    assert "…" in pack  # long summary / chunk truncated


def test_build_pack_without_theory_notes_absence():
    pack = S._build_pack("daily", STORIES, [])
    assert "none retrieved" in pack


def test_parse_read_markdown():
    assert Strategist._parse_read("**Top line**\n### Decisive signals") == {
        "markdown": "**Top line**\n### Decisive signals"
    }


def test_parse_read_strips_think():
    assert Strategist._parse_read("<think>reason</think>\n**Read**")["markdown"] == "**Read**"


def test_parse_read_legacy_object():
    out = Strategist._parse_read('{"headline": "H", "top_line": "T"}')
    assert out.get("headline") == "H"


def test_parse_read_structured_brief():
    raw = (
        '{"bottom_line":"X locks in a dominant design.","confidence":"HIGH",'
        '"signals":[{"title":"T","lens":"Standards battle","implication":"why",'
        '"action":"DEFEND","action_rationale":"hold the node","impact":"high",'
        '"horizon":"near","value_capture":"incumbent wins","falsifier":"yields slip",'
        '"sources":["S1","S2"],"confidence":"med"}],'
        '"convergence":[{"theme":"th","implication":"im","feeds":["Chips","EV"]}],'
        '"scenarios":{"base":"b","bull":"u","bear":"d"},'
        '"watch":[{"item":"i","why":"w","horizon":"Near"}]}'
    )
    out = Strategist._parse_read(raw)
    assert out["format"] == "structured"
    assert out["bottom_line"].startswith("X locks")
    assert out["confidence"] == "high"            # coerced from "HIGH"
    sig = out["signals"][0]
    assert sig["lens"] == "Standards battle" and sig["sources"] == ["S1", "S2"]
    assert sig["confidence"] == "medium"          # "med" invalid -> default
    assert sig["action"] == "defend"              # coerced lower-case
    assert sig["impact"] == "high" and sig["horizon"] == "near"
    assert sig["value_capture"] == "incumbent wins" and sig["falsifier"] == "yields slip"
    assert out["convergence"][0]["feeds"] == ["Chips", "EV"]
    assert out["scenarios"] == {"base": "b", "bull": "u", "bear": "d"}
    assert out["watch"][0]["horizon"] == "near"


def test_normalize_defaults_action_impact_and_sorts_by_rank():
    from analytics.strategist import _normalize_structured
    out = _normalize_structured({"signals": [
        {"title": "low-impact", "impact": "low", "confidence": "high"},
        {"title": "high-impact", "impact": "high", "confidence": "low"},
        {"title": "garbled", "impact": "???", "action": "nope"},  # -> medium / wait
    ]})
    # sorted by impact then confidence, descending
    assert [s["title"] for s in out["signals"]][0] == "high-impact"
    garbled = next(s for s in out["signals"] if s["title"] == "garbled")
    assert garbled["impact"] == "medium" and garbled["action"] == "wait"


def test_diff_briefs_new_dropped_changed():
    from analytics.strategist import diff_briefs
    prev = {"signals": [
        {"title": "Alpha", "action": "wait", "confidence": "low"},
        {"title": "Gamma", "action": "defend", "confidence": "high"},
    ]}
    curr = {"signals": [
        {"title": "Alpha", "action": "scale", "confidence": "high"},   # changed
        {"title": "Beta", "action": "enter", "confidence": "medium"},  # new
    ]}
    d = diff_briefs(prev, curr)
    assert d["new"] == ["Beta"]
    assert d["dropped"] == ["Gamma"]
    assert len(d["changed"]) == 1 and d["changed"][0]["title"] == "Alpha"
    assert d["changed"][0]["to_action"] == "scale" and d["changed"][0]["to_confidence"] == "high"


def test_diff_briefs_handles_missing_previous():
    from analytics.strategist import diff_briefs
    d = diff_briefs(None, {"signals": [{"title": "X"}]})
    assert d["new"] == ["X"] and d["dropped"] == [] and d["changed"] == []


def test_normalize_standards_scorecard():
    out = Strategist._parse_read(
        '{"bottom_line":"x","signals":[{"title":"t","lens":"Standards battle",'
        '"standards":{"leader":"TSMC","basis":["installed base","complementary goods"],'
        '"read":"complements favour incumbent"}}]}'
    )
    std = out["signals"][0]["standards"]
    assert std["leader"] == "TSMC"
    assert std["basis"] == ["installed base", "complementary goods"]
    # a signal without standards normalizes to None
    out2 = Strategist._parse_read('{"signals":[{"title":"t","lens":"Platform play"}]}')
    assert out2["signals"][0]["standards"] is None


def test_portfolio_summary_tally_and_order():
    from analytics.strategist import portfolio_summary
    read = {"signals": [
        {"title": "A", "action": "defend"},
        {"title": "B", "action": "enter"},
        {"title": "C", "action": "defend"},
        {"title": "D", "action": "bogus"},   # invalid -> excluded
    ]}
    board = portfolio_summary(read)
    actions = [b["action"] for b in board]
    assert actions == ["enter", "defend"]          # PORTFOLIO_ACTIONS order
    defend = next(b for b in board if b["action"] == "defend")
    assert defend["count"] == 2 and set(defend["titles"]) == {"A", "C"}


def test_build_pack_includes_technology_trajectories():
    s = Strategist(client=object())
    stories = [{"_feed_label": "Chips", "title": "x", "business_impact": "material"}]
    ctx = {
        "placements": [{"label": "GLP-1 drugs", "maturity": "growth", "adoption": "early-majority",
                        "move": "platform", "entrants": 5, "articles": 7}],
        "transitions": [{"label": "GLP-1 drugs", "dimension": "adoption",
                         "from": "early-adopters", "to": "early-majority", "as_of": "2026-06-11"}],
    }
    pack = s._build_pack("daily", stories, [], ctx)
    assert "TECHNOLOGY TRAJECTORIES" in pack
    assert "STAGE TRANSITIONS" in pack and "early-adopters → early-majority" in pack
    assert "GLP-1 drugs: maturity=growth" in pack
    # MANDATE echoed
    assert "CLIENT:" in pack


def test_build_pack_marks_contested_transition_and_placement():
    s = Strategist(client=object())
    stories = [{"_feed_label": "Chips", "title": "x", "business_impact": "material"}]
    ctx = {
        "placements": [{"label": "GLP-1", "maturity": "growth", "adoption": "early-majority",
                        "move": "platform", "entrants": 5, "articles": 7,
                        "mixed": False, "adoption_mixed": True}],
        "transitions": [{"label": "GLP-1", "dimension": "adoption", "from": "early-adopters",
                         "to": "early-majority", "as_of": "2026-06-11",
                         "contested": True, "modal_share": 0.4}],
    }
    pack = s._build_pack("daily", stories, [], ctx)
    assert "CONTESTED" in pack                 # the transition is flagged, not headlined
    assert "adoption contested" in pack        # the placement carries its contested flag


def test_build_pack_shows_modal_share_for_confident_transition():
    s = Strategist(client=object())
    ctx = {"placements": [], "transitions": [
        {"label": "X", "dimension": "maturity", "from": "emerging", "to": "growth",
         "as_of": "2026-06-11", "contested": False, "modal_share": 0.82}]}
    pack = s._build_pack("daily", [{"title": "x"}], [], ctx)
    # Check the transition LINE itself (the section header explains what CONTESTED means).
    line = next(l for l in pack.splitlines() if l.strip().startswith("- X:"))
    assert "modal share 82%" in line and "CONTESTED" not in line


def test_normalize_structured_drops_garbage_and_defaults():
    from analytics.strategist import _normalize_structured
    out = _normalize_structured({"signals": ["garbage", {"title": "ok"}]})
    assert len(out["signals"]) == 1 and out["signals"][0]["title"] == "ok"
    assert out["signals"][0]["confidence"] == "medium"   # missing -> default
    assert out["confidence"] == "medium" and out["bottom_line"] == ""
    assert out["convergence"] == [] and out["watch"] == []


def test_parse_read_empty_raises():
    with pytest.raises(ValueError):
        Strategist._parse_read("   ")


def test_brief_to_markdown_structured():
    from analytics.strategist import brief_to_markdown
    read = {
        "format": "structured",
        "bottom_line": "2nm ramp locks in a dominant design.",
        "confidence": "high",
        "signals": [
            {"title": "TSMC packaging lock-in", "lens": "Standards battle",
             "implication": "Incumbent captures the value.", "sources": ["S1", "S4"],
             "confidence": "high"},
        ],
        "convergence": [{"theme": "TSMC", "implication": "spans chips + AI", "feeds": ["Chips", "AI & Energy"]}],
        "watch": [{"item": "2nm yield data", "why": "confirms the ramp", "horizon": "near"}],
    }
    md = brief_to_markdown(read, as_of="2026-06-11", focus="daily")
    assert "# Lodestar — Strategist Briefing" in md
    assert "As of 2026-06-11" in md and "Focus:" not in md   # daily focus omitted
    assert "**Bottom line:** 2nm ramp locks in a dominant design." in md
    assert "### TSMC packaging lock-in" in md
    assert "Standards battle" in md and "sources: S1, S4" in md
    assert "## Cross-domain convergence" in md and "TSMC" in md
    assert "## What to watch" in md and "2nm yield data" in md


def test_brief_to_markdown_markdown_fallback():
    from analytics.strategist import brief_to_markdown
    md = brief_to_markdown({"markdown": "**Just prose**"}, as_of="2026-06-11")
    assert "**Just prose**" in md and md.startswith("# Lodestar")


def test_slim_story_carries_label_lens_alsoin():
    slim = Strategist._slim_story(1, STORIES[0])
    assert slim["label"] == "S1"
    assert slim["feed_label"] == "Chips"
    assert slim["also_in"] == ["Disruptive Tech"]
    assert slim["maturity_stage"] == "growth"


def test_brief_to_pdf_returns_pdf_bytes():
    from analytics.strategist import brief_to_pdf
    read = {"format": "structured", "bottom_line": "x", "confidence": "high",
            "signals": [{"title": "t", "lens": "Standards battle", "implication": "y",
                         "action": "defend", "impact": "high", "horizon": "near",
                         "falsifier": "z", "sources": ["S1"], "confidence": "high",
                         "standards": {"leader": "TSMC", "basis": ["installed base"], "read": "ahead"}}],
            "scenarios": {"base": "b", "bull": "u", "bear": "d"},
            "convergence": [{"theme": "TSMC", "implication": "i", "feeds": ["Chips"]}],
            "watch": [{"item": "w", "why": "why", "horizon": "near"}]}
    out = brief_to_pdf(read, as_of="2026-06-12", focus="daily")
    assert isinstance(out, bytes) and out[:4] == b"%PDF"
    # markdown fallback shape also works
    assert brief_to_pdf({"markdown": "prose — with em dash → arrow"})[:4] == b"%PDF"


def test_build_pack_summarizes_backward_transitions_as_noise():
    # Forward moves are listed; backward 'regressions' are collapsed into a single count
    # so the agent isn't anchored by a list of near-impossible non-events.
    s = Strategist(client=object())
    ctx = {"placements": [], "transitions": [
        {"label": "AI DC", "dimension": "adoption", "from": "innovators", "to": "early-adopters",
         "as_of": "2026-06-14", "contested": False, "modal_share": 0.7},
        {"label": "GenAI", "dimension": "maturity", "from": "emerging", "to": "research",
         "as_of": "2026-06-14", "backward": True},
        {"label": "GLP-1", "dimension": "adoption", "from": "early-majority", "to": "innovators",
         "as_of": "2026-06-14", "backward": True},
    ]}
    pack = s._build_pack("daily", [{"title": "x"}], [], ctx)
    assert "AI DC: adoption innovators → early-adopters" in pack   # forward move listed
    assert "GenAI: maturity" not in pack                           # backward move NOT listed
    assert "GLP-1: adoption" not in pack                           # backward move NOT listed
    assert "2 backward 'regression' move(s)" in pack               # summarized as a count
