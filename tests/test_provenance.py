"""Tests for the signal-provenance audit trail (pure — no network)."""

from analytics.provenance import signal_provenance, citation


def _row(**over):
    base = {
        "title": "BigCo buys X", "url": "https://www.reuters.com/a",
        "source_name": "Reuters", "published_at": "2026-06-10",
        "business_impact": "material", "scope": "deal", "sentiment": "positive",
        "companies": ["Nvidia", "TSMC"], "country": "US",
    }
    base.update(over)
    return base


def test_signal_provenance_high_confidence_when_all_from_source():
    row = _row(provenance={
        "business_impact": "agent", "scope": "agent", "sentiment": "agent",
        "companies": "agent", "country": "agent", "title": "agent", "url": "agent",
        "source_name": "agent", "published_at": "agent",
    })
    pv = signal_provenance(row)
    assert pv["has_provenance"] is True
    assert pv["provided_count"] == 5 and pv["field_count"] == 5
    assert pv["confidence"] == "high" and pv["score"] == 1.0
    # every judgment field reads as provided
    assert all(f["provided"] for f in pv["fields"])
    assert pv["source"]["domain"] == "reuters.com"      # www. stripped


def test_signal_provenance_low_confidence_with_defaults_and_missing():
    row = _row(sentiment=None, country=None, provenance={
        "business_impact": "default", "scope": "default",
        "sentiment": "missing", "companies": "agent", "country": "missing",
    })
    pv = signal_provenance(row)
    assert pv["provided_count"] == 1 and pv["confidence"] == "low"
    by = {f["field"]: f for f in pv["fields"]}
    assert by["business_impact"]["provided"] is False
    assert by["companies"]["provided"] is True
    assert by["country"]["value"] == "—"


def test_signal_provenance_degrades_without_map():
    # No 'provenance' key (row predates the column) → coverage mode, no fake confidence.
    pv = signal_provenance(_row())
    assert pv["has_provenance"] is False
    assert pv["confidence"] is None and pv["score"] is None
    by = {f["field"]: f for f in pv["fields"]}
    assert by["business_impact"]["provenance"] == "present"   # populated, source unknown
    assert by["country"]["provided"] is False                 # 'present' isn't 'provided'
    # an all-empty row: every coverage check reads 'absent'
    empty = signal_provenance({})
    assert {f["provenance"] for f in empty["fields"]} == {"absent"}


def test_lens_trail_and_citation():
    row = _row(maturity_stage="growth", adoption_stage="early-majority",
               strategic_move="platform", lens_rationale="HBM crossing the chasm")
    pv = signal_provenance(row)
    assert pv["lens"]["classified"] is True and pv["lens"]["maturity"] == "growth"
    assert pv["lens"]["rationale"] == "HBM crossing the chasm"

    c = citation(row)
    assert c == '"BigCo buys X." Reuters (2026-06-10). https://www.reuters.com/a'
    # missing source/date degrade to domain + n.d.
    assert "unknown source" not in citation(_row())          # has a source
    bare = citation({"title": "T", "url": "https://x.com/p"})
    assert "x.com" in bare and "n.d." in bare


def test_domain_handles_scheme_less_url():
    # A scheme-less URL puts the host in path, not netloc — the domain must still
    # resolve (so the source isn't mislabeled 'unknown source').
    c = citation({"title": "T", "url": "example.com/news/x"})
    assert "example.com" in c and "unknown source" not in c
    pv = signal_provenance({"title": "T", "url": "www.bbc.co.uk/n"})
    assert pv["source"]["domain"] == "bbc.co.uk"        # www. stripped
