"""Tests for the new agents' pure glue — pack building, output validation,
judge parsing, verdict application. No network, no Toqan."""

from analytics.dossier_agent import build_pack, validate
from analytics.falsifier_watch import (
    apply_verdicts,
    format_falsifier_alerts,
    parse_judge_verdicts,
)
from analytics.digest import format_transition_alerts


# ── Dossier Analyst: pack + validation ─────────────────────────────────────────

DOSSIER = {
    "tech": "solid-state-batteries", "label": "Solid-state batteries", "domain": "EV",
    "as_of": "2026-07-09",
    "placement": {"maturity": "growth", "adoption": "early-adopters", "watching": False,
                  "thin_signal": False, "evidence": 22, "evidence_floor": 15,
                  "anchored": True, "anchor_as_of": "2026-07-01",
                  "lifecycle_fit": True, "lifecycle_note": None},
    "transitions": [{"dimension": "maturity", "from": "emerging", "to": "growth",
                     "as_of": "2026-06-20", "contested": False, "confirmed": True,
                     "backward": False}],
    "players": [{"name": "Toyota", "mentions": 9}],
    "capital": {"commitment": [], "option": [], "counts": {"commitment": 2, "option": 5}},
    "funding": {"rounds": 4, "early": 3, "late": 1, "read": "Capital reads early-phase…",
                "window_days": 365, "total_usd": 1e8, "trajectory": [], "latest": []},
    "open_forecasts": [{"claim": "Advances to dominant-design", "confidence": 0.6,
                        "resolve_by": "2026-09-30", "falsifier": "no advance by Q3",
                        "kind": "stage_advance_tech", "horizon": "short", "made_on": None,
                        "outcome": None, "resolved_on": None, "evidence": None}],
    "resolved_forecasts": [{"outcome": "hit"}, {"outcome": "miss"}],
    "stories": [{"title": "Toyota pilot line", "date": "2026-06-10", "source": "Reuters",
                 "url": "https://x.com/1"}],
}


def test_build_pack_carries_every_section():
    pack = build_pack(DOSSIER)
    assert "maturity=growth" in pack and "anchored to a curated assessment" in pack
    assert "emerging → growth" in pack and "confirmed" in pack
    assert "Toyota (9)" in pack
    assert "2 commitments vs 5 real options" in pack
    assert "4 rounds/12mo" in pack
    assert "wrong if: no advance by Q3" in pack
    assert "1 hit / 1 miss" in pack
    assert "[S1]" in pack and "Toyota pilot line" in pack


def test_build_pack_watching_makes_no_stage_claim():
    d = dict(DOSSIER, placement=dict(DOSSIER["placement"], watching=True))
    pack = build_pack(d)
    assert "WATCHING" in pack and "No stage claim" in pack
    assert "maturity=growth" not in pack


def test_validate_accepts_grounded_prose():
    ok = ("**Where it stands.** Growth on solid evidence [S1]. " * 3)
    assert validate(ok, n_stories=1) is None


def test_validate_rejects_bad_shapes():
    assert validate("", 1) == "too short"
    assert validate("short", 1) == "too short"
    assert validate('{"answer": "' + "x" * 100 + '"}', 1) == "not prose"
    long_prose = "A grounded paragraph about batteries and evidence. " * 4
    assert "phantom" in validate(long_prose + " Per [S7].", n_stories=2)


# ── Falsifier Judge: parsing + application ─────────────────────────────────────

def test_parse_judge_verdicts_strict_but_forgiving():
    raw = ('Here you go:\n[{"index": 0, "verdict": "triggers", "why": "Prices reversed.", '
           '"prompt_version": "falsifier-judge-v1"}, '
           '{"index": 1, "verdict": "nonsense", "why": "?"}, '
           '{"index": 9, "verdict": "partial", "why": "out of range"}, '
           '"junk"]')
    v = parse_judge_verdicts(raw, n_events=2)
    assert v == {0: {"verdict": "triggers", "why": "Prices reversed."}}
    assert parse_judge_verdicts("no json here", 2) == {}
    assert parse_judge_verdicts("[not valid json", 2) == {}


def test_apply_verdicts_drops_unrelated_keeps_unjudged():
    events = [{"falsifier": "A"}, {"falsifier": "B"}, {"falsifier": "C"}]
    verdicts = {0: {"verdict": "triggers", "why": "yes"},
                1: {"verdict": "unrelated", "why": "topical"}}
    out = apply_verdicts(events, verdicts)
    assert len(out) == 2
    assert out[0]["judge_verdict"] == "triggers"
    assert out[1] == {"falsifier": "C"}            # unjudged passes through untouched
    assert events[0] == {"falsifier": "A"}         # input not mutated


def test_alert_body_orders_by_verdict_and_carries_why():
    events = [
        {"falsifier": "B", "article_title": "b", "article_url": "u2",
         "judge_verdict": "partial", "judge_why": "one clause met"},
        {"falsifier": "A", "article_title": "a", "article_url": "u1",
         "judge_verdict": "triggers", "judge_why": "condition reported"},
        {"falsifier": "C", "article_title": "c", "article_url": "u3"},
    ]
    body = format_falsifier_alerts(events, as_of="now")
    assert body.index("LIKELY TRIGGERED") < body.index("Partial evidence")
    assert body.index("Partial evidence") < body.index("'C'")
    assert "judge: condition reported" in body
    assert "may have triggered" in body            # unjudged keeps the classic wording


# ── Transition Explainer: why line rides the alert ─────────────────────────────

def test_transition_alert_includes_why_when_present():
    trans = [{"technology": "glp-1", "label": "GLP-1 drugs", "dimension": "adoption",
              "from": "early-adopters", "to": "early-majority", "as_of": "2026-07-09",
              "contested": False, "why": "Driven by mainstream payer coverage [S1][S3]."}]
    body = format_transition_alerts(trans, "https://app.example.com")
    assert "Why: Driven by mainstream payer coverage" in body
    assert "/tech/glp-1" in body
    # absent why → no dangling label
    del trans[0]["why"]
    assert "Why:" not in format_transition_alerts(trans, "x")


def test_strip_thinking_removes_toqan_trace():
    from analytics.dossier_agent import strip_thinking
    raw = "<think>internal notes [S9] with brackets</think>\n**Where it stands.** Real prose [S1]."
    assert strip_thinking(raw) == "**Where it stands.** Real prose [S1]."
    assert strip_thinking("no trace") == "no trace"


def test_parse_judge_verdicts_ignores_brackets_inside_think():
    raw = ('<think>maybe [0, 1] hmm</think>'
           '[{"index": 0, "verdict": "partial", "why": "one clause"}]')
    v = parse_judge_verdicts(raw, n_events=1)
    assert v == {0: {"verdict": "partial", "why": "one clause"}}
