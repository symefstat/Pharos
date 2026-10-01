

# ── decision owner & persona (serve-time enrichment) ─────────────────────────
def test_extract_addressee_lifts_the_owner_clause():
    from analytics.strategist import extract_addressee

    assert extract_addressee(
        "if you operate or invest in EU payment rails, back the compliant rail"
    ) == "operate or invest in EU payment rails"
    assert extract_addressee(
        "if you are a payments processor, pilot agent authorization now"
    ) == "payments processor"
    assert extract_addressee("battery-materials investors should rebalance, fast"
                             ) == "battery-materials investors"
    assert extract_addressee("") is None
    assert extract_addressee("do the obvious thing") is None


def test_persona_of_classifies_conservatively():
    from analytics.strategist import persona_of

    assert persona_of({"action_rationale": "if you hold battery exposure, rebalance the portfolio"}) == "investment"
    assert persona_of({"action_rationale": "if you operate data centres, secure transformer capacity"}) == "strategy"
    # mixed or unclassifiable → 'both': a filter must never hide these
    assert persona_of({"action_rationale": "if you operate or invest in rails, move"}) == "both"
    assert persona_of({"action_rationale": "watch this space"}) == "both"
