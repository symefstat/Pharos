"""Tests for analytics/standards.py — the standards-battle tracker (pure)."""

from analytics.standards import FACTORS, _factor_of, standards_timeline


def brief(as_of, signals):
    return {"as_of": as_of, "strategic_read": {"format": "structured", "signals": signals}}


def sig(title, leader="", basis=None, read=""):
    return {"title": title, "standards": {"leader": leader, "basis": basis or [], "read": read}}


# ── harvesting ─────────────────────────────────────────────────────────────────

def test_empty_and_malformed_inputs_yield_empty():
    assert standards_timeline([]) == []
    assert standards_timeline(None) == []
    # non-dict read, missing read, non-dict signals — all skipped, never raise
    assert standards_timeline([
        {"as_of": "2026-07-01", "strategic_read": "prose fallback"},
        {"as_of": "2026-07-02"},
        {"as_of": "2026-07-03", "strategic_read": {"signals": ["oops", 42]}},
    ]) == []


def test_signals_without_standards_are_ignored():
    briefs = [brief("2026-07-01", [
        {"title": "Plain signal, no standards object"},
        {"title": "Empty standards", "standards": {"leader": "", "basis": [], "read": ""}},
        {"title": "Garbled standards", "standards": "NACS"},
    ])]
    assert standards_timeline(briefs) == []


def test_single_observation_battle_is_listed_and_flagged():
    briefs = [brief("2026-07-01", [
        sig("HBM4 memory interface standard race", leader="SK Hynix",
            basis=["installed base"], read="SK Hynix ships first."),
    ])]
    out = standards_timeline(briefs)
    assert len(out) == 1
    b = out[0]
    assert b["single_observation"] is True
    assert b["current_leader"] == "SK Hynix"
    assert b["first_seen"] == b["last_seen"] == "2026-07-01"
    assert b["leader_changes"] == 0
    assert len(b["observations"]) == 1
    assert b["observations"][0]["title"] == "HBM4 memory interface standard race"


# ── battle grouping (normalized title tokens) ──────────────────────────────────

def test_same_battle_groups_across_days_despite_rewording():
    briefs = [
        brief("2026-07-01", [sig("NACS becomes the de-facto EV charging standard",
                                 leader="Tesla", basis=["installed base", "complementary goods"],
                                 read="Ford and GM adopt NACS.")]),
        brief("2026-07-02", [sig("EV charging standard war: NACS adoption widens",
                                 leader="Tesla", basis=["installed base"],
                                 read="Two more OEMs sign on.")]),
    ]
    out = standards_timeline(briefs)
    assert len(out) == 1
    b = out[0]
    assert b["single_observation"] is False
    assert len(b["observations"]) == 2
    # newest first — the display name is the most recent phrasing
    assert b["observations"][0]["as_of"] == "2026-07-02"
    assert b["battle"] == "EV charging standard war: NACS adoption widens"
    assert b["first_seen"] == "2026-07-01" and b["last_seen"] == "2026-07-02"
    # factor citations accumulate across observations
    assert b["factor_counts"]["installed base"] == 2
    assert b["factor_counts"]["complementary goods"] == 1
    assert b["factor_counts"]["openness"] == 0 and b["factor_counts"]["timing"] == 0


def test_distinct_battles_stay_separate_and_sort_by_recency():
    briefs = [
        brief("2026-07-01", [sig("NACS EV charging standard", leader="Tesla")]),
        brief("2026-07-03", [sig("HBM4 memory interface standard", leader="SK Hynix")]),
    ]
    out = standards_timeline(briefs)
    assert len(out) == 2
    assert out[0]["last_seen"] == "2026-07-03"      # most recently seen first
    assert out[0]["current_leader"] == "SK Hynix"
    assert out[1]["current_leader"] == "Tesla"


def test_leader_change_counted_and_current_leader_is_newest():
    briefs = [
        brief("2026-07-01", [sig("Agent interoperability protocol battle: MCP vs A2A",
                                 leader="Anthropic MCP", basis=["openness"])]),
        brief("2026-07-02", [sig("Agent interoperability protocol battle heats up",
                                 leader="Google A2A", basis=["complementary goods"])]),
        brief("2026-07-04", [sig("Agent interoperability protocol consolidates",
                                 leader="Anthropic MCP", basis=["openness", "timing"])]),
    ]
    out = standards_timeline(briefs)
    assert len(out) == 1
    b = out[0]
    assert b["leader_changes"] == 2                 # MCP → A2A → MCP
    assert b["current_leader"] == "Anthropic MCP"
    assert [o["as_of"] for o in b["observations"]] == ["2026-07-04", "2026-07-02", "2026-07-01"]
    assert b["factor_counts"]["openness"] == 2
    assert b["factor_counts"]["timing"] == 1


def test_duplicate_reads_across_focus_rows_are_deduped():
    # Two brief rows for the same day (e.g. 'daily' + an entity focus) carrying
    # the identical read must not double-count the observation.
    s = sig("NACS EV charging standard", leader="Tesla", basis=["installed base"])
    briefs = [brief("2026-07-01", [s]), brief("2026-07-01", [s])]
    out = standards_timeline(briefs)
    assert len(out) == 1
    assert len(out[0]["observations"]) == 1
    assert out[0]["factor_counts"]["installed base"] == 1


# ── factor normalization ───────────────────────────────────────────────────────

def test_factor_counts_always_carry_all_four_factors():
    out = standards_timeline([brief("2026-07-01", [sig("Some standard fight", leader="X")])])
    assert set(out[0]["factor_counts"]) == set(FACTORS)
    assert all(v == 0 for v in out[0]["factor_counts"].values())


def test_factor_of_is_tolerant_of_paraphrases():
    assert _factor_of("installed base") == "installed base"
    assert _factor_of("large installed user base") == "installed base"
    assert _factor_of("complementary goods") == "complementary goods"
    assert _factor_of("ecosystem of complements") == "complementary goods"
    assert _factor_of("openness") == "openness"
    assert _factor_of("open licensing") == "openness"
    assert _factor_of("timing") == "timing"
    assert _factor_of("first-mover advantage") == "timing"
    assert _factor_of("brand strength") is None
    assert _factor_of("") is None
