"""Tests for the financial reducers + ticker registry (pure — no network)."""

import analytics.financials as fa
from tickers import ticker_for, TICKERS, TICKER_BY_ENTITY


def test_widened_ticker_resolution():
    # New names + suffix/alias variants resolve to the right symbol.
    assert ticker_for("Micron Technology Inc.").symbol == "MU"
    assert ticker_for("Cisco Systems").symbol == "CSCO"
    assert ticker_for("Johnson & Johnson").symbol == "JNJ"
    assert ticker_for("Stellantis N.V").symbol == "STLA"          # suffix 'N.V' stripped
    # Existing ticker, newly reachable via a descriptive-variant alias.
    assert ticker_for("Palantir Technologies").symbol == "PLTR"
    # Private / untracked still resolve to None (no fabricated figures).
    assert ticker_for("Stripe") is None


def test_market_cap_share_by_sector_and_change():
    fins = [
        {"entity": "Nvidia", "market_cap": 100.0, "currency": "USD"},   # Chips
        {"entity": "Tesla", "market_cap": 100.0, "currency": "USD"},    # Auto & EV
    ]
    prices = {
        "NVDA": [{"date": "2026-05-01", "close": 50.0}, {"date": "2026-06-01", "close": 100.0}],
        "TSLA": [{"date": "2026-05-01", "close": 80.0}, {"date": "2026-06-01", "close": 80.0}],
    }
    out = {r["sector"]: r for r in fa.market_cap_share(fins, prices, ticker_for, lookback_days=30)}
    assert out["Chips"]["share"] == 50.0 and out["Auto & EV"]["share"] == 50.0
    # Nvidia doubled (then 50 → now 100) while Tesla was flat → Chips gained share.
    assert out["Chips"]["delta"] == 16.7 and out["Auto & EV"]["delta"] == -16.7
    assert fa.market_cap_share([], {}, ticker_for) == []
    assert fa.market_cap_donut(list(out.values())) is not None
    assert fa.market_cap_donut([]) is None


def test_ticker_coverage_splits_tracked_and_gaps():
    from tickers import ticker_coverage
    rows = [
        {"companies": ["Nvidia", "Stripe"]},
        {"companies": ["Nvidia Corp", "Databricks"]},   # 'Nvidia Corp' → tracked (suffix stripped)
        {"companies": ["Stripe"]},
    ]
    cov = ticker_coverage(rows)
    assert cov["tracked_mentions"] == 2                  # Nvidia ×2
    assert cov["untracked_mentions"] == 3                # Stripe ×2 + Databricks ×1
    assert cov["coverage"] == round(2 / 5, 3)
    top = dict(cov["top_untracked"])
    assert top["Stripe"] == 2 and top["Databricks"] == 1
    assert cov["untracked_entities"] == 2


def test_rd_intensity_and_signal():
    assert fa.rd_intensity(1000, 150) == 0.15
    assert fa.rd_intensity(0, 10) is None        # non-positive revenue
    assert fa.rd_intensity(None, 10) is None
    assert fa.investment_signal(0.20) == "R&D-heavy"
    assert fa.investment_signal(0.08) == "moderate"
    assert fa.investment_signal(0.01) == "harvesting"
    assert fa.investment_signal(None) == "unknown"


def _series():
    return [
        {"date": "2026-06-01", "close": 100.0},
        {"date": "2026-06-02", "close": 101.0},   # the event day (baseline is 06-01, strictly before)
        {"date": "2026-06-03", "close": 103.0},
        {"date": "2026-06-04", "close": 106.0},
        {"date": "2026-06-05", "close": 110.0},    # +3 trading days
    ]


def test_event_reaction_baseline_is_strictly_before_event():
    rx = fa.event_reaction("2026-06-02", _series(), window=3)
    assert rx is not None
    # baseline is the last close STRICTLY BEFORE the event (06-01, 100.0) — so the
    # announcement-day move (06-01→06-02) is captured, not leaked into the baseline.
    assert rx["base_date"] == "2026-06-01" and rx["post_date"] == "2026-06-04"
    assert rx["pct"] == round((106.0 - 100.0) / 100.0 * 100, 1)
    assert rx["trading_days"] == 3
    # no pre-event baseline in the series → None; empty series → None
    assert fa.event_reaction("2026-01-01", _series(), window=3) is None
    assert fa.event_reaction("2026-06-02", [], window=3) is None


def test_event_reaction_captures_announcement_day_move_not_shrug():
    # News on 06-02: a +20% jump that day, then flat. The old on-or-before baseline used
    # the post-jump 06-02 close → reads as a "shrug" (0%). Strictly-before captures it.
    series = [{"date": "2026-06-01", "close": 100.0},
              {"date": "2026-06-02", "close": 120.0},   # announcement-day jump
              {"date": "2026-06-03", "close": 120.0},
              {"date": "2026-06-04", "close": 120.0}]
    rx = fa.event_reaction("2026-06-02", series, window=3)
    assert rx["base_date"] == "2026-06-01" and rx["pct"] == 20.0


def test_event_reaction_handles_event_on_nontrading_day():
    # 2026-06-06 is past the last close; base falls back to 06-05, no forward data → None
    assert fa.event_reaction("2026-06-06", _series(), window=3) is None


def test_classify_reaction_thresholds():
    assert fa.classify_reaction(5.0) == "up"
    assert fa.classify_reaction(-5.0) == "down"
    assert fa.classify_reaction(0.5) == "flat"
    assert fa.classify_reaction(None) == "unknown"


def test_deal_reactions_matches_material_deals_to_prices():
    rows = [
        {"title": "BigCo to acquire X", "scope": "deal", "business_impact": "material",
         "companies": ["Nvidia"], "published_at": "2026-06-02", "_feed_label": "Chips",
         "url": "http://x"},
        {"title": "minor funding", "scope": "deal", "business_impact": "minor",
         "companies": ["Nvidia"], "published_at": "2026-06-02"},     # not material → excluded
        {"title": "no ticker", "scope": "deal", "business_impact": "material",
         "companies": ["Some Private Co"], "published_at": "2026-06-02"},  # unmapped → skipped
    ]
    prices = {"NVDA": _series()}
    out = fa.deal_reactions(rows, prices, ticker_for, window=3)
    assert len(out) == 1
    assert out[0]["company"] == "Nvidia" and out[0]["symbol"] == "NVDA"
    assert out[0]["direction"] == "up" and out[0]["pct"] > 0
    # event_date (the deal day) is surfaced so forecast_run can filter reactions by when
    # the deal hit, not by the back-shifted baseline (06-01) — see Phase 3.2 review fix.
    assert out[0]["event_date"] == "2026-06-02" and out[0]["base_date"] == "2026-06-01"
    txt = fa.summarize_reactions(out)
    assert "1 of 1" in txt
    assert "No priced material deals" in fa.summarize_reactions([])


def test_deal_reactions_dedupes_cross_feed_copies_of_one_event():
    """The same deal lands in several feed tables by design (cross-feed
    corroboration) — the event study must count the EVENT once, not once per
    copy, or identical rows repeat ('Rocket Lab · Jun 29 (2)') and inflate the
    'N of M deals' counts."""
    copy = {"scope": "deal", "business_impact": "material", "companies": ["Nvidia"],
            "published_at": "2026-06-02", "url": "http://x"}
    rows = [
        {**copy, "title": "BigCo to acquire X", "_feed_label": "Chips"},
        {**copy, "title": "BigCo acquires X — report", "_feed_label": "Disruptive Tech"},
        {**copy, "title": "X bought by BigCo", "_feed_label": "AI & Energy"},
        # same company, DIFFERENT day → a genuine second event, kept
        {**copy, "title": "BigCo follow-on deal", "published_at": "2026-06-04",
         "_feed_label": "Chips"},
    ]
    out = fa.deal_reactions(rows, {"NVDA": _series()}, ticker_for, window=3)
    assert [(r["symbol"], r["event_date"]) for r in sorted(out, key=lambda r: r["event_date"])] \
        == [("NVDA", "2026-06-02"), ("NVDA", "2026-06-04")]
    # the first-seen article is the representative for the deduped event
    assert next(r for r in out if r["event_date"] == "2026-06-02")["feed"] == "Chips"


def _rx(company, pct, direction):
    return {"company": company, "symbol": company[:4].upper(), "title": f"{company} deal",
            "url": "http://x", "feed": "Chips", "pct": pct, "direction": direction}


def test_consensus_divergence_splits_and_sorts():
    reactions = [
        _rx("Alpha", 5.0, "up"),     # confirmed
        _rx("Bravo", -3.0, "down"),  # confirmed
        _rx("Charlie", 0.2, "flat"), # shrugged — most ignored
        _rx("Delta", 1.8, "flat"),   # shrugged
    ]
    div = fa.consensus_divergence(reactions)
    assert div["n"] == 4 and div["n_confirmed"] == 2 and div["n_shrugged"] == 2
    assert div["divergence_rate"] == 0.5
    # shrugged: most-ignored (smallest |move|) first
    assert [r["company"] for r in div["shrugged"]] == ["Charlie", "Delta"]
    # confirmed: biggest |move| first
    assert [r["company"] for r in div["confirmed"]] == ["Alpha", "Bravo"]


def test_consensus_divergence_empty_and_all_confirmed():
    empty = fa.consensus_divergence([])
    assert empty["n"] == 0 and empty["divergence_rate"] is None
    assert "No priced material deals" in fa.interpret_divergence(empty)

    all_conf = fa.consensus_divergence([_rx("Alpha", 5.0, "up")])
    assert all_conf["n_shrugged"] == 0
    assert "all 1" in fa.interpret_divergence(all_conf)


def test_interpret_divergence_flags_contrarian_gap():
    div = fa.consensus_divergence([_rx("A", 5.0, "up"), _rx("B", 0.1, "flat")])
    txt = fa.interpret_divergence(div, threshold=2.0)
    assert "1 of 2" in txt and "50% divergence" in txt and "contrarian" in txt


def test_rd_intensity_chart_none_when_empty():
    assert fa.rd_intensity_chart([]) is None
    assert fa.rd_intensity_chart([{"entity": "X", "rd_intensity": None}]) is None
    chart = fa.rd_intensity_chart([{"entity": "Nvidia", "rd_intensity": 0.27}])
    assert chart is not None


def test_financial_context_block_for_agent_pack():
    stories = [
        {"title": "BigCo to acquire X", "scope": "deal", "business_impact": "material",
         "companies": ["Nvidia"], "published_at": "2026-06-02"},          # [S1]
        {"title": "Intel earnings", "scope": "single-company", "business_impact": "notable",
         "companies": ["Intel"]},                                          # [S2] — not a deal
    ]
    financials = [
        {"entity": "Nvidia", "rd_intensity": 0.086},
        {"entity": "Intel", "rd_intensity": 0.261},
    ]
    prices = {"NVDA": _series()}
    block = fa.financial_context(stories, financials, prices, ticker_for, window=3)
    assert "COMPANY FINANCIALS" in block
    assert "R&D INTENSITY" in block
    assert "Nvidia: 8.6%" in block and "Intel: 26.1%" in block       # both in-play companies
    assert "MARKET REACTION" in block
    assert "[S1]" in block                                            # reaction tied to the deal story
    # nothing to add → empty string
    assert fa.financial_context([], financials, prices, ticker_for) == ""


def test_market_cap_usd_converts_non_usd():
    assert fa.market_cap_usd(1000, "USD") == 1000
    assert fa.market_cap_usd(1000, None) == 1000          # missing → assumed USD (warned)
    assert fa.market_cap_usd(1_000_000, "KRW") == 647.0   # 1e6 * 0.000647 static fallback
    assert fa.market_cap_usd(None, "USD") is None
    assert fa.market_cap_usd(100, "ZZZ") is None           # unknown currency → dropped


def test_market_cap_usd_prefers_live_rates_and_flags_static_fallback(caplog):
    import logging
    live = {"KRW": 0.000651, "EUR": 1.1452}
    # Live write-time rates win over the static map (KRW static is 0.000647).
    assert fa.market_cap_usd(1_000_000, "KRW", rates=live) == 651.0
    assert fa.market_cap_usd(100, "eur", rates=live) == 100 * live["EUR"]   # case-insensitive
    # Currency absent from the live dict → static fallback, loudly, citing FX_AS_OF.
    with caplog.at_level(logging.WARNING, logger="analytics.financials"):
        val = fa.market_cap_usd(100, "CHF", rates=live)
    assert val == 100 * fa._FX_TO_USD["CHF"]
    assert "static fallback" in caplog.text and fa.FX_AS_OF in caplog.text


def test_market_cap_usd_warns_on_unknown_and_missing_currency(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="analytics.financials"):
        assert fa.market_cap_usd(100, "INR") is None       # unknown → dropped, no longer silent
        assert fa.market_cap_usd(100, None) == 100         # missing → assumed USD, warned
    assert "unknown currency" in caplog.text and "INR" in caplog.text
    assert "missing currency" in caplog.text


def test_valuation_multiple_and_investment_intensity():
    assert fa.valuation_multiple(1000, 200) == 5.0
    assert fa.valuation_multiple(1000, 0) is None
    assert fa.valuation_multiple(None, 200) is None
    assert fa.investment_intensity(150, 50, 1000) == 0.2          # (150+50)/1000
    assert fa.investment_intensity(None, 50, 1000) == 0.05        # capex-only still counts
    assert fa.investment_intensity(0, 0, 1000) is None            # no spend
    assert fa.investment_intensity(150, 50, 0) is None            # no revenue


def test_landscape_points_filters_and_enriches():
    fins = [
        {"entity": "Nvidia", "market_cap": 5e12, "revenue": 2e11, "rd_expense": 1.8e10,
         "rd_intensity": 0.09, "capex": 6e9},
        {"entity": "NoRevCo", "market_cap": 1e9, "revenue": None, "capex": 1e8},   # dropped
    ]
    pts = fa.landscape_points(fins, ticker_for)
    assert len(pts) == 1
    p = pts[0]
    assert p["entity"] == "Nvidia" and p["sector"] == "Chips"
    assert p["multiple"] == 25.0                                   # 5e12 / 2e11
    assert p["intensity"] == round((1.8e10 + 6e9) / 2e11 * 100, 1)


def test_deal_flow_timeline_buckets_by_week():
    rows = [
        {"title": "A raises Series B funding round", "scope": "deal", "tags": ["funding"],
         "published_at": "2026-06-01"},                            # option
        {"title": "B to acquire C for $2 billion", "scope": "deal", "tags": ["m&a"],
         "published_at": "2026-06-02"},                            # commitment, same week
        {"title": "D partnership pilot", "scope": "deal", "tags": ["deal"],
         "published_at": "2026-05-18"},                            # option, earlier week
    ]
    tl = fa.deal_flow_timeline(rows, weeks=4)
    # long-form, two kinds per week, counts present
    by = {(t["week"], t["kind"]): t["count"] for t in tl}
    wk_jun1 = "2026-06-01"   # Monday of the 06-01/06-02 week
    assert by[(wk_jun1, "option")] == 1 and by[(wk_jun1, "commitment")] == 1
    assert fa.deal_flow_timeline([], weeks=4) == []


def test_capital_kpis_and_synthesis_and_scorecard():
    rows = [
        {"title": "BigCo to acquire X for $3 billion", "scope": "deal", "tags": ["m&a"],
         "business_impact": "material", "companies": ["Nvidia"], "published_at": "2026-06-02",
         "maturity_stage": "growth"},
    ]
    fins = [{"entity": "Nvidia", "market_cap": 5e12, "revenue": 2e11, "rd_expense": 1.8e10,
             "rd_intensity": 0.09, "capex": 6e9}]
    prices = {"NVDA": _series()}
    k = fa.capital_kpis(rows, fins, prices, ticker_for)
    assert k["deals"] == 1 and k["commitment"] == 1
    assert k["top_rd"]["entity"] == "Nvidia"
    assert k["total_market_cap"] == 5e12
    synth = fa.capital_synthesis(rows, fins, prices, ticker_for)
    assert "Nvidia" in synth and "%" in synth
    card = fa.company_scorecard("Nvidia", fins, prices, rows, ticker_for)
    assert card["symbol"] == "NVDA" and card["multiple"] == 25.0
    assert card["reaction"] is not None and card["reaction"]["direction"] == "up"


def test_capital_synthesis_no_causal_verb_and_low_confidence():
    # One typed deal → posture is low-confidence (no stance verdict asserted), and the
    # causal "rewarded/punished" framing is gone from the synthesis entirely.
    rows = [{"title": "BigCo to acquire X for $3 billion", "scope": "deal", "tags": ["m&a"],
             "companies": ["Nvidia"], "published_at": "2026-06-02", "maturity_stage": "growth"}]
    fins = [{"entity": "Nvidia", "market_cap": 5e12, "revenue": 2e11, "rd_expense": 1.8e10,
             "rd_intensity": 0.09, "capex": 6e9}]
    synth = fa.capital_synthesis(rows, fins, {"NVDA": _series()}, ticker_for)
    assert "rewarded" not in synth and "punished" not in synth     # no causal claim
    assert "too few to read a posture" in synth                     # 1 deal → not a stance verdict
    assert "committing capital" not in synth                        # the stance prose is withheld


def test_sector_rollup_aggregates_by_sector():
    fins = [
        {"entity": "Nvidia", "market_cap": 5e12, "revenue": 2e11, "rd_expense": 1.8e10,
         "rd_intensity": 0.09, "capex": 6e9, "currency": "USD"},          # Chips
        {"entity": "Intel", "market_cap": 6e11, "revenue": 5e10, "rd_expense": 1.3e10,
         "rd_intensity": 0.26, "capex": 2e10, "currency": "USD"},         # Chips
        {"entity": "Eli Lilly", "market_cap": 1e12, "revenue": 4e10, "rd_expense": 1e10,
         "rd_intensity": 0.25, "capex": 5e9, "currency": "USD"},          # Biotech
    ]
    rows = [
        {"title": "Nvidia to acquire X for $2 billion", "scope": "deal", "tags": ["m&a"],
         "companies": ["Nvidia"], "published_at": "2026-06-02"},          # Chips commitment
        {"title": "Lilly raises a Series B funding round", "scope": "deal", "tags": ["funding"],
         "companies": ["Eli Lilly"], "published_at": "2026-06-03"},       # Biotech option
    ]
    roll = fa.sector_rollup(fins, rows, ticker_for)
    by = {r["sector"]: r for r in roll}
    assert by["Chips"]["companies"] == 2
    assert by["Chips"]["market_cap"] == 5e12 + 6e11
    assert by["Chips"]["commitment"] == 1 and by["Chips"]["option"] == 0
    assert by["Biotech & Health"]["option"] == 1
    # sorted by market cap desc
    assert roll[0]["sector"] == "Chips"
    assert fa.sector_landscape_chart(roll) is not None
    assert fa.sector_landscape_chart([]) is None


def test_consultant_charts_render_or_none():
    pts = [{"entity": "Nvidia", "sector": "Chips", "intensity": 12.0, "rd_pct": 9.0,
            "capex_pct": 3.0, "multiple": 25.0, "market_cap": 5e12},
           {"entity": "Intel", "sector": "Chips", "intensity": 54.0, "rd_pct": 26.0,
            "capex_pct": 28.0, "multiple": 2.5, "market_cap": 6e11}]
    assert fa.landscape_chart(pts) is not None and fa.landscape_chart([]) is None
    assert fa.investment_intensity_chart(pts) is not None and fa.investment_intensity_chart([]) is None
    tl = [{"week": "2026-06-01", "kind": "option", "count": 2},
          {"week": "2026-06-01", "kind": "commitment", "count": 1}]
    assert fa.deal_flow_chart(tl) is not None and fa.deal_flow_chart([]) is None
    rx = [{"company": "Intel", "pct": 13.4, "direction": "up", "base_date": "2026-06-02"}]
    assert fa.reaction_chart(rx) is not None and fa.reaction_chart([]) is None


def test_ticker_registry_resolves_aliases_and_skips_private():
    assert ticker_for("Google").symbol == "GOOGL"            # alias → Alphabet (Google)
    assert ticker_for("nvidia").symbol == "NVDA"             # case-insensitive
    assert ticker_for("Taiwan Semiconductor").symbol == "TSM"
    assert ticker_for("OpenAI") is None                      # private, intentionally absent
    assert ticker_for("Totally Unknown Co") is None
    assert all(t.symbol and t.entity for t in TICKERS)
    assert len(TICKER_BY_ENTITY) == len(TICKERS)             # no duplicate canonical names
