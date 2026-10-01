"""Tests for the pure significance/source weight helpers (analytics/weights.py)."""

from collections import Counter

import pytest

from analytics.weights import (
    DEFAULT_TIER, IMPACT_WEIGHTS, TIER_WEIGHTS, company_bucket_weight,
    impact_weight, source_tier, tier_weight, weighted_companies_in_row,
    weighted_company_counts,
)


def _row_counts(row) -> Counter:
    c: Counter = Counter()
    for name, w in weighted_companies_in_row(row):
        c[name] += w
    return c


# ── significance ───────────────────────────────────────────────────────────────

def test_impact_weight_defaults_to_contextual():
    assert impact_weight("material") == IMPACT_WEIGHTS["material"]
    assert impact_weight("none") == IMPACT_WEIGHTS["none"]
    assert impact_weight(None) == IMPACT_WEIGHTS["contextual"]
    assert impact_weight("bogus") == IMPACT_WEIGHTS["contextual"]


# ── source tiers ───────────────────────────────────────────────────────────────

def test_source_tier_known_outlets():
    assert source_tier("Reuters") == "t1"
    assert source_tier("Bloomberg") == "t1"
    assert source_tier("The Wall Street Journal") == "t1"
    assert source_tier("CoinDesk") == "t2"
    assert source_tier("www.coindesk.com") == "t2"   # domain form
    assert source_tier("The Verge") == "t2"          # leading 'the' stripped


def test_source_tier_defaults_for_unknown_and_missing():
    assert source_tier(None) == DEFAULT_TIER
    assert source_tier("") == DEFAULT_TIER
    assert source_tier("Some Random Newsletter") == DEFAULT_TIER


def test_tier_weight_lookup():
    assert tier_weight("t1") == TIER_WEIGHTS["t1"]
    assert tier_weight("unknown") == TIER_WEIGHTS["unknown"]
    assert tier_weight("bogus") == TIER_WEIGHTS[DEFAULT_TIER]


# ── combined fold ──────────────────────────────────────────────────────────────

def test_company_bucket_weight_multiplies_impact_and_tier():
    assert company_bucket_weight("material|t1") == IMPACT_WEIGHTS["material"] * TIER_WEIGHTS["t1"]
    assert company_bucket_weight("contextual|unknown") == IMPACT_WEIGHTS["contextual"] * TIER_WEIGHTS["unknown"]
    assert company_bucket_weight("none|t2") == IMPACT_WEIGHTS["none"] * TIER_WEIGHTS["t2"]


def test_weighted_companies_in_row_uses_breakdown():
    row = {"by_company_breakdown": {"Nvidia": {"material|t1": 2, "contextual|unknown": 1}}}
    expected = (2 * IMPACT_WEIGHTS["material"] * TIER_WEIGHTS["t1"]
                + 1 * IMPACT_WEIGHTS["contextual"] * TIER_WEIGHTS["unknown"])
    assert _row_counts(row)["Nvidia"] == pytest.approx(expected)


def test_weighted_companies_in_row_fallback_is_neutral():
    # No breakdown (old row) → raw by_company at weight 1.0 (unweighted-equivalent),
    # NOT penalised by the unknown-tier weight.
    row = {"by_company": {"Nvidia": 4}}
    assert _row_counts(row)["Nvidia"] == 4.0


def test_weighted_company_counts_sums_breakdown_and_fallback():
    rows = [
        {"by_company_breakdown": {"Nvidia": {"material|t1": 1}}},   # impact×tier
        {"by_company": {"Nvidia": 2}},                              # fallback neutral 2.0
    ]
    expected = IMPACT_WEIGHTS["material"] * TIER_WEIGHTS["t1"] + 2.0
    assert weighted_company_counts(rows)["Nvidia"] == pytest.approx(expected)
