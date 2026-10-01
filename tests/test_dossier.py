"""Tests for the technology dossier — the exportable one-pager per tracked
technology (analytics/dossier.py) and its download route (/api/mot/dossier).
Pure builder/renderer tests on fixture data; the endpoint runs against a fake
data layer — no network, no Supabase."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from analytics.dossier import (
    MAX_STORIES,
    build_dossier,
    dossier_to_markdown,
    dossier_to_pdf,
)
from analytics.tech_layer import EVIDENCE_FLOOR


# ── fixtures — one of every interesting shape ──────────────────────────────────

PLACEMENTS = [
    {  # well-covered, anchored tech
        "tech": "solid-state-batteries", "label": "Solid-state batteries", "domain": "EV",
        "articles": 24, "stage_articles": 22, "entrants": 9,
        "maturity": "emerging", "committed_stage": "growth",
        "adoption": "innovators", "adoption_committed": "early-adopters",
        "thin_signal": False, "watching": False,
        "anchored": True, "maturity_anchored": True, "anchor_as_of": "2026-07-01",
    },
    {  # watching tech — under the evidence floor, no stage claim allowed
        "tech": "perovskite-solar", "label": "Perovskite solar", "domain": "Climate & Energy",
        "articles": 6, "stage_articles": 5, "entrants": 2,
        "maturity": "emerging", "committed_stage": "emerging",
        "adoption": "innovators", "adoption_committed": "innovators",
        "thin_signal": True, "watching": True,
    },
]

TRANSITIONS = [
    {"technology": "solid-state-batteries", "dimension": "maturity",
     "from": "emerging", "to": "growth", "as_of": "2026-06-20",
     "contested": False, "confirmed": True, "backward": False},
    {"technology": "solid-state-batteries", "dimension": "adoption",
     "from": "innovators", "to": "early-adopters", "as_of": "2026-07-02",
     "contested": True, "confirmed": False, "backward": False},
    {"technology": "glp-1", "dimension": "maturity",           # other tech — excluded
     "from": "growth", "to": "dominant-design", "as_of": "2026-07-01",
     "contested": False, "confirmed": True, "backward": False},
]

PREDICTIONS = [
    {  # open anchored stage call on the tech
        "id": 1, "kind": "stage_advance_tech", "subject": "solid-state-batteries",
        "claim": "Solid-state batteries advances maturity from ‘growth’ to "
                 "‘dominant-design’ (anchored display stage, confirmed) within ~1 quarter",
        "status": "open", "outcome": None, "confidence": 0.62, "horizon": "short",
        "made_on": "2026-06-15", "resolve_by": "2026-09-13",
        "params": {"from_stage": "growth", "to_stage": "dominant-design"},
    },
    {  # resolved stage call — the receipt
        "id": 2, "kind": "stage_advance_tech", "subject": "solid-state-batteries",
        "claim": "Solid-state batteries advances maturity from ‘emerging’ to ‘growth’ "
                 "(anchored display stage, confirmed) within ~1 quarter",
        "status": "resolved", "outcome": "hit", "confidence": 0.58, "horizon": "short",
        "made_on": "2026-02-01", "resolve_by": "2026-05-02", "resolved_on": "2026-04-10",
        "resolution_note": "maturity ‘growth’ held for 2 consecutive snapshots",
        "params": {"from_stage": "emerging", "to_stage": "growth"},
    },
    {  # open judgment call naming the tech in its claim — included, with falsifier
        "id": 3, "kind": "manual", "subject": "ev",
        "claim": "Solid-state batteries reach automotive qualification at two OEMs by 2027",
        "status": "open", "outcome": None, "confidence": 0.55, "horizon": "long",
        "made_on": "2026-05-01", "resolve_by": "2027-06-01",
        "params": {"falsifier": "no OEM announces a qualified solid-state pack by mid-2027"},
    },
    {  # unrelated manual call — excluded
        "id": 4, "kind": "manual", "subject": "capital",
        "claim": "Consolidation wave continues in fintech",
        "status": "open", "outcome": None, "confidence": 0.7, "horizon": "long",
        "made_on": "2026-06-01", "resolve_by": "2027-06-01",
        "params": {"falsifier": "no major deal"},
    },
    {  # stage call on ANOTHER tech — excluded
        "id": 5, "kind": "stage_advance_tech", "subject": "glp-1",
        "claim": "GLP-1 drugs advances maturity from ‘growth’ to ‘dominant-design’",
        "status": "open", "outcome": None, "confidence": 0.6, "horizon": "short",
        "made_on": "2026-06-15", "resolve_by": "2026-09-13", "params": {},
    },
]

STORIES = [
    {"title": f"Solid-state battery pilot line {i}",
     "summary": "solid-state cells", "tags": [], "companies": [],
     "published_at": f"2026-06-{i:02d}T08:00:00Z",
     "source_name": "Reuters" if i % 2 else None, "_feed_label": "EV",
     "url": f"https://example.com/ssb-{i}"}
    for i in range(1, 11)                       # 10 matches — must cap at 8
] + [
    {"title": "GLP-1 supply expands", "summary": "semaglutide capacity", "tags": [],
     "companies": [], "published_at": "2026-06-30T08:00:00Z",
     "source_name": "FT", "_feed_label": "Biotech & Health",
     "url": "https://example.com/glp"},
]

MEASURED = [
    {"tech_key": "solid-state-batteries", "label": "Demo pack energy density",
     "unit": "Wh/kg",
     "series": [{"year": 2024, "value": 350}, {"year": 2025, "value": 400}],
     "source": {"org": "ExampleOrg", "publication": "Battery Report 2026",
                "url": "https://example.org/report", "retrieved": "2026-07-08"},
     "direction_note": "Rising = performance progress."},
]

AS_OF = "2026-07-08"


def _build(key="solid-state-batteries", **over):
    kw = dict(placements=PLACEMENTS, transitions=TRANSITIONS,
              predictions=PREDICTIONS, stories=STORIES, measured=MEASURED,
              as_of=AS_OF)
    kw.update(over)
    return build_dossier(key, **kw)


# ── build_dossier ──────────────────────────────────────────────────────────────

def test_unknown_tech_returns_none():
    assert _build("not-a-tech") is None


def test_header_carries_placement_and_anchor_vintage():
    d = _build()
    assert d["tech"] == "solid-state-batteries"
    assert d["label"] == "Solid-state batteries" and d["domain"] == "EV"
    pl = d["placement"]
    # displayed stage = centroid-committed (display_stage), not the bare modal
    assert pl["maturity"] == "growth" and pl["adoption"] == "early-adopters"
    assert pl["watching"] is False and pl["thin_signal"] is False
    assert pl["evidence"] == 22 and pl["evidence_floor"] == EVIDENCE_FLOOR
    assert pl["anchored"] is True and pl["anchor_as_of"] == "2026-07-01"


def test_watching_tech_makes_no_stage_claim():
    d = _build("perovskite-solar")
    pl = d["placement"]
    assert pl["watching"] is True
    assert pl["maturity"] is None and pl["adoption"] is None   # no stage claim
    md = dossier_to_markdown(d)
    assert "Watching — insufficient evidence" in md
    assert "Maturity (S-curve)" not in md                      # really no stage line


def test_tech_without_any_placement_degrades_to_watching():
    d = _build(placements=[])
    pl = d["placement"]
    assert pl["watching"] is True and pl["evidence"] == 0
    assert pl["maturity"] is None


def test_transitions_filtered_to_tech_and_ordered_newest_first():
    d = _build()
    assert [t["as_of"] for t in d["transitions"]] == ["2026-07-02", "2026-06-20"]
    assert all("glp" not in str(t) for t in d["transitions"])
    contested = d["transitions"][0]
    assert contested["contested"] is True and contested["confirmed"] is False


def test_forecasts_scoped_and_falsifiers_included():
    d = _build()
    open_claims = [f["claim"] for f in d["open_forecasts"]]
    assert len(open_claims) == 2                               # stage call + manual mention
    assert not any("fintech" in c or "GLP-1" in c for c in open_claims)
    by_kind = {f["kind"]: f for f in d["open_forecasts"]}
    # manual call carries its own falsifier verbatim
    assert by_kind["manual"]["falsifier"] == (
        "no OEM announces a qualified solid-state pack by mid-2027")
    # stage call gets a synthesised falsifier with the locked terms + deadline
    fals = by_kind["stage_advance_tech"]["falsifier"]
    assert "'growth'" in fals and "'dominant-design'" in fals and "2026-09-13" in fals
    # resolved history — the receipts
    assert len(d["resolved_forecasts"]) == 1
    r = d["resolved_forecasts"][0]
    assert r["outcome"] == "hit" and r["resolved_on"] == "2026-04-10"
    assert "2 consecutive snapshots" in r["evidence"]


def test_stories_matched_capped_and_sourced():
    d = _build()
    assert len(d["stories"]) == MAX_STORIES                    # 10 matches → 8 kept
    assert d["stories"][0]["date"] == "2026-06-10"             # newest first
    assert all("GLP" not in (s["title"] or "") for s in d["stories"])
    srcs = {s["source"] for s in d["stories"]}
    assert "Reuters" in srcs and "EV" in srcs                  # source_name, feed fallback
    assert all(s["url"] for s in d["stories"])


def test_measured_curve_mapped_or_none():
    assert _build()["measured_curve"]["source"]["org"] == "ExampleOrg"
    assert _build("perovskite-solar")["measured_curve"] is None


# ── renderers ──────────────────────────────────────────────────────────────────

def test_markdown_contains_all_sections():
    md = dossier_to_markdown(_build())
    assert md.startswith("# Lodestar — Technology Dossier")
    assert "## Solid-state batteries (EV)" in md
    assert f"_Generated {AS_OF}" in md and "lodestar technology dossier" in md
    # placement + anchor vintage
    assert "**Maturity (S-curve):** growth" in md
    assert "curated stage assessment (2026-07-01)" in md
    # transitions with contested flag
    assert "maturity: emerging → growth" in md
    assert "innovators → early-adopters (contested · unconfirmed)" in md
    # falsifier lines
    assert "## Open forecasts — what would prove us wrong" in md
    assert "Wrong if: no OEM announces a qualified solid-state pack by mid-2027" in md
    # receipts
    assert "## Resolved forecasts — the receipts" in md and "**HIT** (2026-04-10)" in md
    # coverage citations
    assert "<https://example.com/ssb-10>" in md
    # measured curve + source citation
    assert "## Measured curve — Demo pack energy density (Wh/kg)" in md
    assert "Source: ExampleOrg — Battery Report 2026 (retrieved 2026-07-08)" in md
    # methodology footer
    assert "**Methodology.**" in md
    assert f"fewer than {EVIDENCE_FLOOR} stage-classified articles" in md
    assert "/methodology" in md


def test_markdown_degrades_without_optional_sections():
    d = _build(transitions=[], predictions=[], stories=[], measured=[])
    md = dossier_to_markdown(d)
    assert "## Stage-transition history" not in md
    assert "## Open forecasts" not in md and "## Recent coverage" not in md
    assert "**Methodology.**" in md                            # footer always present


def test_pdf_renders_bytes():
    out = dossier_to_pdf(_build())
    assert isinstance(out, (bytes, bytearray)) and bytes(out[:5]) == b"%PDF-"
    # the watching shape renders too (no stage lines, no crash)
    assert bytes(dossier_to_pdf(_build("perovskite-solar"))[:5]) == b"%PDF-"


# ── the download route ─────────────────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch):
    import backend.app.mot as bm

    rows = [dict(s, maturity_stage="emerging") for s in STORIES]
    monkeypatch.setattr(bm.data, "rows", lambda days=30: rows)
    monkeypatch.setattr(bm.data, "predictions", lambda: [dict(p) for p in PREDICTIONS])
    # no Supabase in tests: transitions read degrades to [] via the except path
    monkeypatch.setattr(bm.data, "_supabase",
                        lambda: (_ for _ in ()).throw(RuntimeError("no db in tests")))
    app = FastAPI()
    app.include_router(bm.router)
    return TestClient(app)


def test_route_unknown_tech_404(client):
    assert client.get("/api/mot/dossier?tech=warp-drive").status_code == 404


def test_route_bad_fmt_400(client):
    r = client.get("/api/mot/dossier?tech=solid-state-batteries&fmt=docx")
    assert r.status_code == 400


def test_route_serves_markdown_attachment(client):
    r = client.get("/api/mot/dossier?tech=solid-state-batteries&fmt=md")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == (
        f'attachment; filename="lodestar-dossier-solid-state-batteries-'
        f'{r.text.split("Generated ")[1][:10]}.md"')
    assert r.text.startswith("# Lodestar — Technology Dossier")
    assert "Solid-state batteries" in r.text


def test_route_serves_pdf_attachment(client):
    r = client.get("/api/mot/dossier?tech=solid-state-batteries&fmt=pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "lodestar-dossier-solid-state-batteries-" in r.headers["content-disposition"]
    assert r.content[:5] == b"%PDF-"


# ── capital section ────────────────────────────────────────────────────────────

CAPITAL_STORIES = STORIES + [
    {"title": "BigCo to acquire solid-state battery maker", "summary": "solid-state cells",
     "tags": ["m&a"], "companies": ["BigCo"], "published_at": "2026-07-01T08:00:00Z",
     "source_name": "Reuters", "_feed_label": "EV", "scope": "deal",
     "url": "https://example.com/deal-1"},
    {"title": "Startup raises Series B for solid-state pilot", "summary": "solid-state cells",
     "tags": ["funding"], "companies": ["Startup"], "published_at": "2026-07-03T08:00:00Z",
     "source_name": "FT", "_feed_label": "EV",
     "url": "https://example.com/deal-2"},
    {"title": "GLP-1 maker acquires plant", "summary": "semaglutide capacity",   # other tech
     "tags": ["m&a"], "companies": ["Pharma"], "published_at": "2026-07-02T08:00:00Z",
     "source_name": "FT", "_feed_label": "Biotech & Health", "scope": "deal",
     "url": "https://example.com/deal-3"},
]


def test_capital_moves_scoped_and_typed():
    d = _build(stories=CAPITAL_STORIES)
    cap = d["capital"]
    assert cap["counts"] == {"commitment": 1, "option": 1}
    assert cap["commitment"][0]["title"].startswith("BigCo to acquire")
    assert cap["option"][0]["title"].startswith("Startup raises Series B")
    # the other tech's deal never leaks in
    titles = [m["title"] for m in cap["commitment"] + cap["option"]]
    assert all("GLP-1" not in t for t in titles)


def test_capital_degrades_to_zero_counts():
    d = _build(stories=[])
    assert d["capital"] == {"commitment": [], "option": [],
                            "counts": {"commitment": 0, "option": 0}}


def test_route_tech_json_payload(client):
    r = client.get("/api/mot/tech/solid-state-batteries")
    assert r.status_code == 200
    d = r.json()
    assert d["tech"] == "solid-state-batteries"
    assert "placement" in d and "capital" in d and "open_forecasts" in d


def test_route_tech_json_unknown_404(client):
    assert client.get("/api/mot/tech/not-a-tech").status_code == 404


# ── funding section ────────────────────────────────────────────────────────────

FUNDING = [
    {"tech_key": "solid-state-batteries", "company": "CellCo", "round_type": "series-b",
     "amount_usd": 120e6, "announced_on": "2026-06-01", "source_url": "https://x.com/a"},
    {"tech_key": "solid-state-batteries", "company": "PackCo", "round_type": "seed",
     "amount_usd": None, "announced_on": "2026-05-01", "source_url": None},
    {"tech_key": "solid-state-batteries", "company": "OldCo", "round_type": "series-a",
     "amount_usd": 10e6, "announced_on": "2026-04-01", "source_url": None},
]


def test_funding_section_summary_and_read():
    d = _build(funding=FUNDING)
    fu = d["funding"]
    assert fu["rounds"] == 3 and fu["total_usd"] == 130e6
    assert fu["early"] == 3 and fu["late"] == 0
    # placed tech (growth) vs all-early capital → honest divergence read
    assert "runs earlier" in fu["read"]
    # markdown export carries the same section
    md = dossier_to_markdown(d)
    assert "## Funding signal — independent of news" in md and "CellCo" in md


def test_funding_section_absent_without_data():
    assert _build()["funding"] is None
    assert _build(funding=[])["funding"] is None
    assert "Funding signal" not in dossier_to_markdown(_build())


# ── analyst read + players ─────────────────────────────────────────────────────

def test_analyst_read_placed_tech_names_evidence():
    d = _build()
    read = " ".join(d["read"])
    assert "Where it stands" in read and "**growth**" in read
    assert "22 stage-classified articles" in read           # names its evidence
    assert "curated assessment" in read                     # anchor disclosed
    assert "The nearest test" in read and "2026-09-13" in read
    assert "Record on this technology" in read and "1✓ / 0✗" in read


def test_analyst_read_watching_tech_makes_no_stage_claim():
    d = _build("perovskite-solar")
    read = " ".join(d["read"])
    assert "watch list" in read and "no stage claim" in read
    assert "**growth**" not in read and "S-curve" not in read


def test_players_counted_and_capped():
    stories = [
        {"title": f"Solid-state {i}", "summary": "solid-state cells", "tags": [],
         "companies": ["Toyota", "QuantumScape"] if i % 2 else ["Toyota"],
         "published_at": f"2026-06-{i:02d}T08:00:00Z", "_feed_label": "EV",
         "url": f"https://example.com/p-{i}"}
        for i in range(1, 6)
    ]
    d = _build(stories=stories)
    assert d["players"][0] == {"name": "Toyota", "mentions": 5}
    assert d["players"][1]["name"] == "QuantumScape"
    read = " ".join(d["read"])
    assert "most-named: Toyota" in read.lower() or "Toyota" in read


def test_read_and_players_in_markdown_export():
    md = dossier_to_markdown(_build())
    assert "## Analyst read" in md and "Where it stands" in md
    assert "## Key players" not in md          # fixture stories carry no companies
    with_players = _build(stories=[
        {"title": "Solid-state pilot", "summary": "solid-state cells", "tags": [],
         "companies": ["Toyota"], "published_at": "2026-06-05T08:00:00Z",
         "_feed_label": "EV", "url": "https://example.com/x"}])
    assert "## Key players" in dossier_to_markdown(with_players)


def test_players_merge_entity_aliases():
    stories = [
        {"title": "Solid-state pilot A", "summary": "solid-state cells", "tags": [],
         "companies": ["IQM"], "published_at": "2026-06-01T08:00:00Z",
         "_feed_label": "EV", "url": "https://example.com/a"},
        {"title": "Solid-state pilot B", "summary": "solid-state cells", "tags": [],
         "companies": ["IQM Quantum Computers"], "published_at": "2026-06-02T08:00:00Z",
         "_feed_label": "EV", "url": "https://example.com/b"},
        {"title": "Solid-state pilot C", "summary": "solid-state cells", "tags": [],
         "companies": ["Toyota Motor Corp."], "published_at": "2026-06-03T08:00:00Z",
         "_feed_label": "EV", "url": "https://example.com/c"},
    ]
    d = _build(stories=stories)
    by_name = {p["name"]: p["mentions"] for p in d["players"]}
    assert by_name["IQM"] == 2                 # alias variants merged
    assert "IQM Quantum Computers" not in by_name
    assert by_name["Toyota"] == 1              # legal suffix stripped to canonical
