"""Tests for the convergence-radar reducer (pure — no network)."""

from analytics.entity_tracker import co_mentions, domain_convergence, interpret_convergence
from analytics.entities import normalize as _n
from analytics.weights import IMPACT_WEIGHTS as IW, TIER_WEIGHTS as TW


def _row(feed, companies):
    return {"_feed_label": feed, "companies": companies}


# Article weight for a row with no business_impact/source: contextual × unknown-tier.
_NEUTRAL_W = IW["contextual"] * TW["unknown"]


def test_domain_convergence_names_seams_and_bridges():
    # Nvidia spans Chips + Defense (a bridge); TSMC spans the same pair; AMD only
    # appears in Chips (not a bridge). Acme appears in Chips + Geopolitics.
    rows = [
        _row("Chips", ["Nvidia", "AMD"]),
        _row("Chips", ["Nvidia", "TSMC"]),
        _row("Defense & Space", ["Nvidia"]),
        _row("Defense & Space", ["TSMC"]),
        _row("Geopolitics & Trade", ["Nvidia"]),
        _row("Chips", ["AMD"]),                       # AMD: single-domain → no bridge
    ]
    seams = domain_convergence(rows)
    by_pair = {s["domains"]: s for s in seams}

    # Chips ✕ Defense & Space: Nvidia (Chips×2 + Defense×1 = 3 raw) and TSMC (1 + 1 = 2 raw).
    # These rows carry no impact/source, so each mention weighs _NEUTRAL_W; the displayed
    # 'mentions' is the rounded weighted sum.
    cd = by_pair[("Chips", "Defense & Space")]
    assert cd["n_bridges"] == 2                                                  # entity count, unweighted
    assert [b["entity"] for b in cd["bridges"]] == [_n("Nvidia"), _n("TSMC")]   # by weighted mentions desc
    assert cd["bridges"][0]["mentions"] == round(3 * _NEUTRAL_W)

    # Chips ✕ Geopolitics & Trade: only Nvidia bridges.
    cg = by_pair[("Chips", "Geopolitics & Trade")]
    assert cg["n_bridges"] == 1 and cg["bridges"][0]["entity"] == _n("Nvidia")

    # AMD never bridges (single domain) → appears in no seam.
    amd = _n("AMD")
    assert all(amd not in [b["entity"] for b in s["bridges"]] for s in seams)

    # Strongest pair first: Chips ✕ Defense (2 bridges) ranks above the 1-bridge pairs.
    assert seams[0]["domains"] == ("Chips", "Defense & Space")


def test_domain_convergence_min_feeds_and_empty():
    # Single-domain only → nobody bridges → empty.
    rows = [_row("Chips", ["Nvidia"]), _row("Chips", ["AMD"])]
    assert domain_convergence(rows) == []
    # Rows without a feed label are skipped.
    assert domain_convergence([{"companies": ["Nvidia"]}]) == []
    assert domain_convergence([]) == []


def test_domain_convergence_excludes_cross_cutting_feeds():
    rows = [
        _row("Chips", ["Nvidia"]),
        _row("AI & Energy", ["Nvidia"]),
        _row("Disruptive Tech", ["Nvidia"]),       # a cross-cutting lens, not a sector
    ]
    # Without exclusion the lens poses as a pole and bridges the real sectors.
    assert any("Disruptive Tech" in s["domains"] for s in domain_convergence(rows))
    # Excluding it leaves only the genuine sector × sector seam.
    seams = domain_convergence(rows, exclude_feeds={"Disruptive Tech"})
    pairs = {s["domains"] for s in seams}
    assert all("Disruptive Tech" not in p for p in pairs)
    assert ("AI & Energy", "Chips") in pairs       # sorted-order sector pair survives


def test_only_lens_feeds_are_flagged_cross_cutting():
    # Disruptive Tech (a property lens) and Prosus (a portfolio lens) span all
    # sectors by design; as radar poles they would bridge every real seam.
    from feeds import FEEDS
    assert {f.label for f in FEEDS if f.cross_cutting} == {"Disruptive Tech", "Prosus"}


def test_co_mentions_weighted_by_significance_and_source():
    # 'Big' is co-mentioned once in a material Reuters story; 'Small' twice in
    # 'none'-impact unknown-source stories. Weighting ranks Big first despite fewer raw.
    stories = [
        {"companies": ["Hub", "Big"], "business_impact": "material", "source_name": "Reuters"},
        {"companies": ["Hub", "Small"], "business_impact": "none", "source_name": "Some Blog"},
        {"companies": ["Hub", "Small"], "business_impact": "none", "source_name": "Some Blog"},
    ]
    names = [name for name, _ in co_mentions(stories, _n("Hub"))]
    assert names[0] == _n("Big")


def test_interpret_convergence():
    assert "staying within" in interpret_convergence([])
    rows = [
        _row("Chips", ["Nvidia"]),
        _row("Defense & Space", ["Nvidia"]),
    ]
    txt = interpret_convergence(domain_convergence(rows))
    assert "Chips ✕ Defense & Space" in txt and _n("Nvidia") in txt


def test_picker_and_dossier_agree_when_rollup_empty(monkeypatch):
    # Before the rollup is built, the picker falls back to live feeds. The dossier's
    # weighted prominence must use the SAME live-weighted measure (not read 0.0 against
    # a non-zero picker count). Regression guard for the picker/dossier divergence.
    from analytics.entity_tracker import EntityTracker
    from analytics.weights import article_weight

    et = EntityTracker(client=object())
    live = [
        {"companies": ["Nvidia"], "business_impact": "material", "source_name": "Reuters"},
        {"companies": ["Nvidia", "AMD"], "business_impact": "none", "source_name": "some blog"},
    ]
    monkeypatch.setattr(et, "_rollup_rows", lambda days: [])
    monkeypatch.setattr(et.pulse, "all_recent", lambda days=30: live)

    nvidia = _n("Nvidia")
    picker = dict(et.universe())
    prof = et.profile(nvidia)
    expected = article_weight(live[0]) + article_weight(live[1])   # Nvidia is in both rows

    assert prof["weighted"] == expected            # dossier = live weighted prominence
    assert prof["weighted"] > 0                     # NOT 0.0 — the bug this fixes
    assert picker[nvidia] == round(prof["weighted"])  # picker shows the same measure
