"""Radar (horizon scanning) — the pure pipeline: unmatched mining, Scout pack
and parse, the corroboration evidence gate, registry dedupe, and the no-agent
fallback. The gate is the load-bearing piece: an agent proposal must NEVER
surface without independent corpus support."""

from dataclasses import dataclass, field

import pytest

from analytics.radar import (
    MIN_MENTIONS,
    MIN_SOURCES,
    MIN_SPREAD_DAYS,
    build_scout_pack,
    corroborate,
    dedupe_against_registry,
    fallback_candidates,
    parse_scout,
    sample_stories,
    slugify,
    strip_thinking,
    unmatched,
)


@dataclass
class Tech:
    key: str
    label: str
    keywords: list = field(default_factory=list)
    domain: str = "Frontier"


TECHS = [
    Tech("quantum-computing", "Quantum computing", ["quantum comput", "qubit"]),
    Tech("green-hydrogen", "Green hydrogen", ["green hydrogen", "electrolyzer"]),
]


def story(title, source="Reuters", feed="Chips", date="2026-07-01", summary="", tags=None):
    return {"title": title, "summary": summary, "tags": tags or [],
            "companies": [], "source_name": source, "_feed_label": feed,
            "published_at": f"{date}T00:00:00Z"}


# ── unmatched ────────────────────────────────────────────────────────────────
def test_unmatched_excludes_registry_matches():
    rows = [story("Qubit counts double"), story("Solid-state cooling ships")]
    out = unmatched(rows, TECHS)
    assert [r["title"] for r in out] == ["Solid-state cooling ships"]


# ── sample_stories ───────────────────────────────────────────────────────────
def test_sample_dedupes_titles_and_prefers_material():
    rows = [
        story("Dup", date="2026-07-01"),
        story("Dup", date="2026-07-02"),
        story("Old but material", date="2026-06-01") | {"business_impact": "material"},
        story("Newest routine", date="2026-07-03"),
    ]
    out = sample_stories(rows, n=2)
    titles = [r["title"] for r in out]
    assert titles[0] == "Old but material"  # material band first
    assert len(titles) == 2 and len(set(titles)) == 2


# ── build_scout_pack ─────────────────────────────────────────────────────────
def test_pack_numbers_stories_and_lists_tracked():
    pack = build_scout_pack([story("A"), story("B")], ["Quantum computing"], ["Chips"])
    assert "[S1]" in pack and "[S2]" in pack
    assert "Quantum computing" in pack and "Chips" in pack


# ── parse_scout ──────────────────────────────────────────────────────────────
GOOD = '[{"name": "Solid-state cooling", "keywords": ["solid-state cooling"], ' \
       '"domain_hint": "Chips", "why": "x [S1][S2]", "stories": [1, 2]}]'


def test_parse_accepts_think_trace_and_fences():
    raw = f"<think>reasoning...</think>```json\n{GOOD}\n```"
    out = parse_scout(raw, n_stories=5)
    assert len(out) == 1 and out[0]["name"] == "Solid-state cooling"


def test_parse_drops_phantom_citations():
    bad = GOOD.replace("[1, 2]", "[1, 99]")
    assert parse_scout(bad, n_stories=5) == []


def test_parse_drops_under_cited():
    bad = GOOD.replace("[1, 2]", "[1]")
    assert parse_scout(bad, n_stories=5) == []


def test_parse_garbage_returns_empty():
    assert parse_scout("no json here", 5) == []
    assert parse_scout('{"not": "a list"}', 5) == []


# ── corroborate (the evidence gate) ──────────────────────────────────────────
def _corpus(n_stories=6, n_sources=4, spread_ok=True):
    dates = ["2026-06-01", "2026-06-05", "2026-06-12", "2026-06-20",
             "2026-06-25", "2026-07-01"]
    if not spread_ok:
        dates = ["2026-07-01"] * 6
    return [
        story(f"Solid-state cooling advance {i}", source=f"Src{i % n_sources}",
              feed=f"Feed{i % 2}", date=dates[i % len(dates)])
        for i in range(n_stories)
    ]


CAND = {"name": "Solid-state cooling", "keywords": ["solid-state cooling"]}


def test_gate_passes_with_enough_evidence():
    ev = corroborate(CAND, _corpus())
    assert ev and ev["mentions"] >= MIN_MENTIONS and ev["sources"] >= MIN_SOURCES
    assert ev["first_seen"] == "2026-06-01" and ev["last_seen"] == "2026-07-01"
    assert len(ev["stories"]) <= 6


def test_gate_fails_on_too_few_stories():
    assert corroborate(CAND, _corpus(n_stories=MIN_MENTIONS - 1)) is None


def test_gate_fails_on_single_source_burst():
    assert corroborate(CAND, _corpus(n_sources=1)) is None


def test_gate_fails_on_one_day_splash():
    assert corroborate(CAND, _corpus(spread_ok=False)) is None


def test_gate_fails_with_no_keywords():
    assert corroborate({"name": "x", "keywords": []}, _corpus()) is None


# ── dedupe_against_registry ──────────────────────────────────────────────────
def test_dedupe_drops_slug_and_keyword_overlap():
    cands = [
        {"name": "Quantum Computing", "keywords": ["quantum stack"]},   # slug dupe
        {"name": "Electrolyzers 2.0", "keywords": ["electrolyzer"]},    # keyword dupe
        {"name": "Solid-state cooling", "keywords": ["solid-state cooling"]},
    ]
    out = dedupe_against_registry(cands, TECHS)
    assert [c["name"] for c in out] == ["Solid-state cooling"]


# ── fallback ─────────────────────────────────────────────────────────────────
def test_fallback_excludes_event_tags():
    corpus = [story("A", tags=["m&a", "stablecoin"]), story("B", tags=["funding", "stablecoin"])]
    out = fallback_candidates(corpus)
    names = [c["name"] for c in out]
    assert "Stablecoin" in names and "M&A" not in names and "Funding" not in names


# ── helpers ──────────────────────────────────────────────────────────────────
def test_slugify_and_strip():
    assert slugify("Solid-state cooling!") == "solid-state-cooling"
    assert strip_thinking("<think>x</think> answer") == "answer"


# ── Radar v2: research stream ────────────────────────────────────────────────
ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2607.01234v1</id>
    <title>Thermoelectric  solid-state cooling
      for dense compute</title>
    <summary>We demonstrate a solid-state cooling module...</summary>
    <published>2026-07-01T00:00:00Z</published>
    <arxiv:primary_category term="physics.app-ph"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2607.05678v1</id>
    <title>A second paper</title>
    <summary>Abstract text.</summary>
    <published>2026-06-20T00:00:00Z</published>
    <arxiv:primary_category term="cs.ET"/>
  </entry>
</feed>"""


def paper(title, date="2026-06-15", cat="cs.ET"):
    return {"title": title, "summary": "", "url": f"http://arxiv.org/{title}",
            "published_at": f"{date}T00:00:00Z", "source_name": f"arXiv ({cat})",
            "_feed_label": "arXiv", "tags": [], "companies": [], "_radar_kind": "paper"}


def test_arxiv_parse_feed():
    from analytics.arxiv_feed import parse_feed

    rows = parse_feed(ATOM)
    assert len(rows) == 2
    assert rows[0]["title"] == "Thermoelectric solid-state cooling for dense compute"
    assert rows[0]["source_name"] == "arXiv (physics.app-ph)"
    assert rows[0]["_radar_kind"] == "paper"
    assert parse_feed("not xml") == []


def test_pack_numbers_papers_after_stories():
    pack = build_scout_pack([story("A"), story("B")], ["Quantum computing"],
                            ["Chips"], papers=[paper("P1")])
    assert "RESEARCH ABSTRACTS" in pack
    assert "[S3]" in pack and "[S4]" not in pack  # papers continue the numbering


def test_research_gate_surfaces_paper_only_candidate():
    papers = [paper("solid-state cooling advance 1", date="2026-06-01"),
              paper("solid-state cooling advance 2", date="2026-06-15"),
              paper("solid-state cooling advance 3", date="2026-07-01")]
    ev = corroborate(CAND, corpus=[], papers=papers)
    assert ev and ev["papers"] == 3 and ev["research_stage"] is True
    assert ev["mentions"] == 0 and len(ev["paper_items"]) == 3
    assert ev["first_seen"] == "2026-06-01" and ev["last_seen"] == "2026-07-01"


def test_research_gate_needs_spread_and_count():
    burst = [paper(f"solid-state cooling {i}", date="2026-07-01") for i in range(4)]
    assert corroborate(CAND, corpus=[], papers=burst) is None  # one-day splash
    two = [paper("solid-state cooling a", date="2026-06-01"),
           paper("solid-state cooling b", date="2026-07-01")]
    assert corroborate(CAND, corpus=[], papers=two) is None  # under MIN_PAPERS


def test_news_gate_pass_is_not_research_stage():
    papers = [paper("solid-state cooling advance 1", date="2026-06-01"),
              paper("solid-state cooling advance 2", date="2026-06-15"),
              paper("solid-state cooling advance 3", date="2026-07-01")]
    ev = corroborate(CAND, _corpus(), papers=papers)
    assert ev and ev["research_stage"] is False and ev["papers"] == 3


def test_trim_why_cuts_at_word_boundary():
    from analytics.radar import trim_why

    long = "word " * 80  # 400 chars
    out = trim_why(long)
    assert len(out) <= 301 and out.endswith("…") and not out.endswith("wor…")
    assert trim_why("short") == "short"


# ── Radar v3: directed scans ─────────────────────────────────────────────────
def test_pack_brief_section_leads_and_demands_responsiveness():
    pack = build_scout_pack([story("A")], ["Quantum computing"], ["Chips"],
                            brief="anything emerging in energy storage?")
    assert pack.startswith("=== FOCUS BRIEF")
    assert "anything emerging in energy storage?" in pack
    assert "return []" in pack  # the no-padding rule is inlined


def test_pack_without_brief_has_no_brief_section():
    pack = build_scout_pack([story("A")], ["Quantum computing"], ["Chips"])
    assert "FOCUS BRIEF" not in pack


# ── store_candidate: update-vs-insert (the upsert NOT NULL trap) ─────────────
class _FakeTable:
    def __init__(self, existing):
        self._existing = existing
        self.calls = []
        self._op = None

    def select(self, *_):
        self._op = ("select",)
        return self

    def update(self, row):
        self._op = ("update", row)
        return self

    def insert(self, row):
        self._op = ("insert", row)
        return self

    def upsert(self, row, **kw):
        self._op = ("upsert", row)
        return self

    def eq(self, *_):
        return self

    def execute(self):
        self.calls.append(self._op)
        class R:  # noqa: N801
            data = self._existing if self._op[0] == "select" else []
        return R()


class _FakeClient:
    def __init__(self, existing):
        self.tbl = _FakeTable(existing)

    def table(self, _name):
        return self.tbl


def test_store_candidate_updates_existing_without_touching_status():
    from analytics.radar import store_candidate

    fc = _FakeClient(existing=[{"key": "x", "status": "dismissed"}])
    store_candidate(fc, "x", {"name": "X", "keywords": ["x"], "domain_hint": "other",
                              "why": "w"}, {"mentions": 9}, "2026-07-10")
    ops = [c[0] for c in fc.tbl.calls]
    assert ops == ["select", "update"]
    updated = fc.tbl.calls[1][1]
    assert "status" not in updated and "first_detected" not in updated


def test_store_candidate_inserts_new_with_status_and_date():
    from analytics.radar import store_candidate

    fc = _FakeClient(existing=[])
    store_candidate(fc, "y", {"name": "Y", "keywords": ["y"], "domain_hint": "other",
                              "why": "w"}, {"mentions": 9}, "2026-07-10")
    ops = [c[0] for c in fc.tbl.calls]
    assert ops == ["select", "insert"]
    inserted = fc.tbl.calls[1][1]
    assert inserted["status"] == "new" and inserted["first_detected"] == "2026-07-10"


# ── Radar v4: emergence map inputs ───────────────────────────────────────────
def test_weekly_counts_buckets_from_newest():
    from analytics.radar import weekly_counts

    dates = ["2026-07-10", "2026-07-09", "2026-07-01", "2026-06-20", "2026-06-13"]
    out = weekly_counts(dates)
    assert out == [1, 1, 1, 2]  # oldest→newest, anchored at 2026-07-10
    assert weekly_counts([]) == [0, 0, 0, 0]


def test_corroborate_carries_weekly():
    ev = corroborate(CAND, _corpus())
    # 4 trailing weekly buckets cover 28 days — the 30-day-old mention falls out
    assert ev and ev["weekly"] == [1, 1, 1, 2]


def test_adjacency_counts_co_mentions():
    from analytics.radar import adjacency

    rows = [
        story("Qubit lab adopts solid-state cooling"),         # both
        story("Solid-state cooling for qubit racks"),          # both
        story("Solid-state cooling in HVAC"),                  # candidate only
        story("Green hydrogen plant opens"),                   # tracked only
    ]
    out = adjacency(["solid-state cooling"], rows, TECHS)
    assert out == [{"tech": "quantum-computing", "label": "Quantum computing", "n": 2}]


def test_adjacency_filters_below_min():
    from analytics.radar import adjacency

    rows = [story("Qubit lab adopts solid-state cooling")]
    assert adjacency(["solid-state cooling"], rows, TECHS) == []


def test_tracked_counts_measures_both_axes():
    from analytics.radar import tracked_counts

    rows = [story("Qubit counts double"), story("Green hydrogen deal"), story("Unrelated")]
    papers = [paper("Qubit error correction at scale")]
    out = {t["tech"]: t for t in tracked_counts(rows, papers, TECHS)}
    assert out["quantum-computing"]["stories"] == 1
    assert out["quantum-computing"]["papers"] == 1
    assert out["green-hydrogen"]["stories"] == 1 and out["green-hydrogen"]["papers"] == 0


# ── word-boundary matching + cross-scan identity ─────────────────────────────
def test_keyword_hits_respect_word_boundaries():
    from analytics.radar import _keyword_hits

    rows = [story("Stripe's Tempo chain validates"), story("Temporal fusion transformers"),
            story("Kitaev chains and bosonic symmetry")]
    hits = _keyword_hits(["tempo"], rows)
    assert [h["title"] for h in hits] == ["Stripe's Tempo chain validates"]


def test_keyword_hits_tolerate_plural():
    from analytics.radar import _keyword_hits

    rows = [story("Mega-constellations reach orbit")]
    assert len(_keyword_hits(["mega-constellation"], rows)) == 1


def test_match_existing_merges_renamed_candidates():
    from analytics.radar import match_existing

    stored = [{"key": "ngso-mega-constellation-networks",
               "label": "NGSO mega-constellation networks",
               "keywords": ["mega-constellation", "ngso"]}]
    renamed = {"name": "LEO satellite megaconstellations",
               "keywords": ["leo satellite", "mega-constellations"]}  # plural of a stored kw
    assert match_existing(renamed, stored) == "ngso-mega-constellation-networks"


def test_match_existing_leaves_distinct_candidates_alone():
    from analytics.radar import match_existing

    stored = [{"key": "stablecoin-payment-rails", "label": "Stablecoin payment rails",
               "keywords": ["stablecoin"]}]
    distinct = {"name": "Solid-state cooling", "keywords": ["solid-state cooling"]}
    assert match_existing(distinct, stored) is None


def test_match_existing_generic_token_never_merges():
    from analytics.radar import match_existing

    stored = [{"key": "ai-agent-payment-authorization",
               "label": "AI-agent payment authorization",
               "keywords": ["ai agent payment", "machine payment"]}]
    distinct = {"name": "Enterprise agentic AI", "keywords": ["agentic ai platform"]}
    assert match_existing(distinct, stored) is None


def test_match_existing_two_specific_tokens_merge():
    from analytics.radar import match_existing

    stored = [{"key": "solid-state-cooling", "label": "Solid-state cooling",
               "keywords": ["thermoelectric"]}]
    renamed = {"name": "Solid state cooling modules", "keywords": ["peltier"]}
    assert match_existing(renamed, stored) == "solid-state-cooling"


# ── Radar v5: graded detection calls ─────────────────────────────────────────
def test_detection_call_fields_shape_and_confidence():
    from analytics.radar import DETECTION_WINDOW_DAYS, detection_call_fields

    ev = {"mentions": 54, "sources": 41, "papers": 7, "first_seen": "2026-06-11",
          "research_stage": False}
    f = detection_call_fields("Agentic AI", "agentic-ai", ev, "2026-07-10")
    assert f["kind"] == "radar_detection" and f["subject"] == "agentic-ai"
    assert f["resolve_days"] == DETECTION_WINDOW_DAYS
    assert "still clears the placement evidence floor" in f["claim"]
    assert "wrong if" in f["claim"]
    assert f["confidence"] == 0.75  # 0.55 + all three boosts, capped
    weak = detection_call_fields("X", "x", {"mentions": 6, "sources": 4}, "2026-07-10")
    assert weak["confidence"] == 0.55


def _hist(tech, as_of, stage="emerging", n=20):
    return {"technology": tech, "as_of": as_of, "maturity_stage": stage,
            "article_count": n}


def _pred():
    return {"kind": "radar_detection", "subject": "agentic-ai",
            "made_on": "2026-07-10", "resolve_by": "2026-10-08"}


def test_radar_detection_pending_before_deadline():
    from analytics.forecasts import resolve_radar_detection

    hist = [_hist("agentic-ai", "2026-08-01")]
    assert resolve_radar_detection(_pred(), hist, "2026-09-01") is None


def test_radar_detection_hit_when_placed_at_deadline():
    from analytics.forecasts import resolve_radar_detection

    hist = [_hist("agentic-ai", "2026-08-01", n=30),
            _hist("agentic-ai", "2026-10-05", stage="growth", n=22)]
    res = resolve_radar_detection(_pred(), hist, "2026-10-08")
    assert res and res[0] == "hit" and "growth" in res[1]


def test_radar_detection_miss_below_floor_or_silent():
    from analytics.forecasts import resolve_radar_detection

    thin = [_hist("agentic-ai", "2026-10-05", n=4)]
    res = resolve_radar_detection(_pred(), thin, "2026-10-08")
    assert res and res[0] == "miss"
    res2 = resolve_radar_detection(_pred(), [], "2026-10-09")
    assert res2 and res2[0] == "miss" and "coverage died" in res2[1]


def test_radar_detection_ignores_snapshots_outside_window():
    from analytics.forecasts import resolve_radar_detection

    # only a pre-promotion snapshot exists — must not count as evidence
    hist = [_hist("agentic-ai", "2026-07-01", n=40)]
    res = resolve_radar_detection(_pred(), hist, "2026-10-09")
    assert res and res[0] == "miss"


def test_radar_detection_basis_is_internal():
    from analytics.forecasts import category_of, resolution_basis

    assert resolution_basis("radar_detection") == "internal"
    assert category_of("radar_detection") == "Radar detection"


# ── graduations: watching → first placed snapshot ────────────────────────────
def _snap(tech, as_of, n, stage="emerging", label=None):
    return {"technology": tech, "label": label or tech, "as_of": as_of,
            "maturity_stage": stage, "article_count": n}


def test_graduation_fires_on_first_at_floor_day_only():
    from analytics.radar import detect_graduations

    hist = [_snap("agentic-ai", "2026-07-09", 8),      # below floor
            _snap("agentic-ai", "2026-07-10", 17)]     # first ≥15 today
    out = detect_graduations(hist, "2026-07-10", floor=15)
    assert [g["technology"] for g in out] == ["agentic-ai"]
    assert out[0]["stage"] == "emerging" and out[0]["articles"] == 17
    # the day after, the same history must NOT re-alert
    assert detect_graduations(hist, "2026-07-11", floor=15) == []


def test_graduation_ignores_long_established_and_watching_techs():
    from analytics.radar import detect_graduations

    hist = [_snap("hbm-memory", "2026-05-01", 40),      # graduated long ago
            _snap("hbm-memory", "2026-07-10", 44),
            _snap("thin-tech", "2026-07-10", 3)]        # still watching
    assert detect_graduations(hist, "2026-07-10", floor=15) == []


def test_format_graduations_mentions_radar_provenance():
    from analytics.radar import format_graduations

    body = format_graduations([{"technology": "agentic-ai", "label": "Agentic AI",
                                "stage": "emerging", "articles": 17,
                                "as_of": "2026-07-10", "from_radar": True}],
                              "https://app")
    assert "Agentic AI earned its place" in body
    assert "Surfaced by Radar" in body and "https://app/tech/agentic-ai" in body


# ── dismissal with memory ────────────────────────────────────────────────────
def test_should_resurface_requires_double_and_absolute_growth():
    from analytics.radar import should_resurface

    assert should_resurface(8, 31) is True          # 2×+ and +23
    assert should_resurface(8, 15) is False         # not double
    assert should_resurface(1, 4) is False          # double but only +3 (noise)
    assert should_resurface(0, 6) is True           # new signal from nothing
    assert should_resurface(50, 60) is False        # big but not outgrown


# ── outage behavior: a configured-but-failing Scout must never tag-fallback ──
def test_scan_skips_instead_of_fallback_when_scout_fails(monkeypatch):
    import analytics.radar as radar_mod

    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("500 Server Error")

    import toqan.client as tc
    monkeypatch.setattr(tc, "ToqanAgent", _Boom)
    monkeypatch.setenv("RADAR_ARXIV", "0")
    fc = _FakeClient(existing=[])
    rows = [story("Solid-state cooling ships")]
    res = radar_mod.run_radar(fc, rows, TECHS, api_key="configured-key")
    assert res["surfaced"] == 0 and res["proposed"] == 0
    # nothing was stored — no insert/update calls reached the table
    assert all(c[0] not in ("insert", "update") for c in fc.tbl.calls)


def test_scan_still_falls_back_when_no_key_configured(monkeypatch):
    import analytics.radar as radar_mod

    monkeypatch.setenv("RADAR_ARXIV", "0")
    monkeypatch.delenv("TOQAN_SCOUT", raising=False)
    fc = _FakeClient(existing=[])
    rows = [story(f"S{i}", source=f"Src{i%4}", tags=["stablecoin"],
                  date=f"2026-06-{10+i:02d}") for i in range(8)]
    res = radar_mod.run_radar(fc, rows, TECHS, api_key=None)
    assert res["proposed"] >= 1  # tag themes proposed in unconfigured mode


def test_match_existing_picks_best_not_first():
    from analytics.radar import match_existing

    # regression: one shared keyword with an EARLIER row must not beat an
    # identical label + two shared keywords further down the list
    stored = [
        {"key": "ai-agent-payment-authorization",
         "label": "AI-agent payment authorization",
         "keywords": ["machine payment", "unified agent protocol"]},
        {"key": "on-chain-stablecoin-payment-rails",
         "label": "Stablecoin payment rails",
         "keywords": ["stablecoin", "pyusd", "on-chain settlement"]},
    ]
    proposal = {"name": "Stablecoin payment rails",
                "keywords": ["stablecoin", "machine payments", "pyusd"]}
    assert match_existing(proposal, stored) == "on-chain-stablecoin-payment-rails"
