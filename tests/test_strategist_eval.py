"""Tests for the L8 Strategist judge harness (eval/judges/strategist_eval.py).

Fully offline: fixture briefs only — no Supabase, no Toqan. Pins that the
deterministic checks pass the clean synthetic brief and catch every seeded
defect in the defective one, and that the live paths stay gated.
"""

import json
from pathlib import Path

import pytest

from eval.judges.strategist_eval import (
    PANEL_SIZE,
    aggregate_panel,
    build_judge_prompts,
    extract_numeric_claims,
    run_deterministic,
    run_live_panel,
)

FIXTURES = Path(__file__).resolve().parents[1] / "eval" / "judges" / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def clean_sc():
    return run_deterministic(_load("brief_clean.json"))


@pytest.fixture(scope="module")
def defective_sc():
    return run_deterministic(_load("brief_defective.json"))


# ── numeric-claim extraction + normalization ─────────────────────────────────

def test_extract_currency_scale_and_percent():
    claims = extract_numeric_claims("a €3.2 billion fund, 90% booked, $500 million staged")
    by_raw = {c["raw"]: c for c in claims}
    assert by_raw["€3.2 billion"]["value"] == pytest.approx(3.2e9)
    assert by_raw["90%"]["cls"] == "pct"
    assert by_raw["$500 million"]["value"] == pytest.approx(500e6)


def test_extract_attached_scale_and_unit_token():
    claims = extract_numeric_claims("raised 3.2bn against the 2nm node")
    assert claims[0]["value"] == pytest.approx(3.2e9)   # "3.2bn" == "3.2 billion"
    assert claims[1]["cls"] == "unit" and claims[1]["unit_token"] == "2nm"


def test_years_and_small_counts_are_advisory_and_refs_skipped():
    claims = extract_numeric_claims("by Q2 2027, 3 players remain [S1]")
    assert all(c["advisory"] for c in claims)           # 2027 + 3; Q2/S1 not extracted
    assert {c["raw"] for c in claims} == {"2027", "3 players"} or len(claims) == 2


# ── clean fixture: all deterministic L8 targets met ──────────────────────────

def test_clean_brief_passes_all_targets(clean_sc):
    assert clean_sc["all_pass"] is True
    assert clean_sc["grounding"]["pct"] == 100.0
    assert clean_sc["grounding"]["hallucinated"] == []
    assert clean_sc["sref"]["pct"] == 100.0 and clean_sc["sref"]["phantom"] == []
    assert clean_sc["falsifier"]["mean_mech"] == 4.0
    assert clean_sc["overclaim"]["violations"] == []


def test_clean_brief_normalized_grounding(clean_sc):
    # '€3.2 billion' grounded against a source saying '3.2bn'; '90%' vs '90 percent'
    assert clean_sc["grounding"]["hard_claims"] >= 5
    assert clean_sc["grounding"]["grounded"] == clean_sc["grounding"]["hard_claims"]


# ── defective fixture: every seeded defect caught ────────────────────────────

def test_defect_hallucinated_number(defective_sc):
    h = defective_sc["grounding"]["hallucinated"]
    assert len(h) == 1 and h[0]["signal"] == 1 and "4.5" in h[0]["claim"]
    assert defective_sc["passes"]["zero_hallucinated_numbers"] is False


def test_defect_misattributed_number(defective_sc):
    m = defective_sc["grounding"]["misattributed"]
    assert len(m) == 1 and m[0]["signal"] == 3 and "80" in m[0]["claim"]


def test_defect_phantom_source_ref(defective_sc):
    p = defective_sc["sref"]["phantom"]
    assert [x["ref"] for x in p] == ["S9"] and p[0]["signal"] == 2
    assert defective_sc["passes"]["sref_100pct_valid"] is False


def test_defect_undated_unmeasurable_falsifier(defective_sc):
    rows = {r["signal"]: r for r in defective_sc["falsifier"]["per_signal"]}
    assert rows[3]["mech_score"] == 0
    assert rows[3]["has_date"] is False and rows[3]["has_threshold"] is False
    assert rows[1]["mech_score"] == 4 and rows[2]["mech_score"] == 4


def test_defect_overclaim_flagged_on_weak_evidence(defective_sc):
    v = defective_sc["overclaim"]["violations"]
    assert len(v) == 1 and v[0]["signal"] == 2
    assert "confirms" in v[0]["terms"] and "wins" in v[0]["terms"]
    assert defective_sc["overclaim"]["rate"] > 10.0


def test_defective_brief_fails_overall(defective_sc):
    assert defective_sc["all_pass"] is False


# ── LLM panel: prompts build offline; live paths stay gated ──────────────────

def test_judge_prompts_build_offline_and_count_calls():
    prompts = build_judge_prompts(_load("brief_clean.json"))
    assert len(prompts) == 3 * PANEL_SIZE                    # signals x judges
    roles = [p["role"] for p in prompts if p["signal"] == 1]
    assert roles.count("refuter") == 1                       # one adversarial judge
    refuter = next(p for p in prompts if p["role"] == "refuter")
    assert "REFUTE" in refuter["prompt"]
    assert "MOT Theory Fidelity" in prompts[0]["prompt"]     # rubrics embedded
    assert "Falsifier Quality" in prompts[0]["prompt"]


def test_panel_majority_rules_aggregation():
    votes = {1: [
        {"theory_fidelity": 3, "falsifier_total": 10, "misapplication": False},
        {"theory_fidelity": 2, "falsifier_total": 9, "misapplication": True},
        {"theory_fidelity": 1, "falsifier_total": 4, "misapplication": True},
    ]}
    agg = aggregate_panel(votes)
    assert agg["per_signal"][0]["theory_fidelity"] == 2      # median
    assert agg["per_signal"][0]["falsifier_total"] == 9
    assert agg["misapplications"] == [1]                     # 2 of 3 flagged


def test_judge_panel_is_gated(monkeypatch):
    # --from-supabase became a real SELECT-only path in the approved live run
    # (2026-07-02); the cost gate that must still hold is the Toqan judge panel.
    monkeypatch.delenv("TOQAN_JUDGE", raising=False)
    with pytest.raises(RuntimeError, match="NEEDS APPROVAL"):
        run_live_panel(_load("brief_clean.json"))
