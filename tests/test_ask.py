"""Tests for Ask Lodestar's pure retrieval/pack logic (no network)."""

from analytics.ask import (
    _merge_stories,
    _neutralize_phantom_citations,
    _question_tokens,
    _relevant_stories,
    AskLodestar,
)


def test_question_tokens_drops_stopwords_short():
    toks = _question_tokens("What is the state of solid-state batteries?")
    assert "solid" in toks and "state" in toks and "batteries" in toks
    assert "the" not in toks and "is" not in toks and "of" not in toks


def test_relevant_stories_ranks_by_overlap_then_material():
    rows = [
        {"title": "Solid-state battery breakthrough at Toyota", "summary": "energy density",
         "companies": ["Toyota"], "tags": ["battery"], "business_impact": "material",
         "published_at": "2026-06-10"},
        {"title": "LFP battery prices fall", "summary": "cheaper packs", "companies": ["CATL"],
         "tags": ["battery"], "business_impact": "contextual", "published_at": "2026-06-09"},
        {"title": "Unrelated chip export rule", "summary": "policy", "companies": ["Nvidia"],
         "tags": ["export"], "business_impact": "material", "published_at": "2026-06-11"},
    ]
    out = _relevant_stories(rows, "solid-state battery energy density", top=5)
    assert out[0]["title"].startswith("Solid-state battery")   # most token overlap + material
    assert all("export rule" not in s["title"] for s in out)    # the chip story has no overlap


def test_relevant_stories_empty_question():
    assert _relevant_stories([{"title": "x"}], "the of a", top=5) == []


# ── Hybrid merge (vector + keyword) ───────────────────────────────────────────

def test_merge_stories_vector_ranks_first_then_keyword_fills():
    vec = [{"url": "https://a.com/1", "title": "V1"}, {"url": "https://a.com/2", "title": "V2"}]
    kw = [{"url": "https://a.com/3", "title": "K1"}]
    out = _merge_stories(vec, kw, limit=5)
    assert [s["title"] for s in out] == ["V1", "V2", "K1"]   # vector first, keyword fills


def test_merge_stories_dedups_by_normalized_url():
    # Same story from both branches (http/https + trailing slash + www) → once.
    vec = [{"url": "https://www.a.com/x", "title": "V"}]
    kw = [{"url": "http://a.com/x/", "title": "K"}]
    out = _merge_stories(vec, kw, limit=5)
    assert len(out) == 1 and out[0]["title"] == "V"          # vector copy wins


def test_merge_stories_respects_limit():
    vec = [{"url": f"https://a.com/{i}", "title": f"V{i}"} for i in range(10)]
    assert len(_merge_stories(vec, [], limit=3)) == 3


def test_merge_stories_empty_branches_fall_back():
    kw = [{"url": "https://a.com/1", "title": "K1"}]
    assert _merge_stories([], kw, limit=5) == kw             # vector empty → keyword stands in
    assert _merge_stories(kw, [], limit=5) == kw             # keyword empty → vector stands in
    assert _merge_stories([], [], limit=5) == []


def test_build_pack_includes_question_stories_theory():
    pack = AskLodestar._build_pack(
        "What about TSMC?",
        [{"role": "user", "content": "Tell me about chips"}, {"role": "assistant", "content": "..."}],
        [{"_feed_label": "Chips", "title": "TSMC 2nm", "summary": "ramp", "companies": ["TSMC"],
          "business_impact": "material", "published_at": "2026-06-10"}],
        [{"source_file": "TSE.pdf", "chunk_text": "dominant design theory", "similarity": 0.7}],
    )
    assert "QUESTION: What about TSMC?" in pack
    assert "[S1] (Chips) TSMC 2nm" in pack and "[T1] TSE.pdf" in pack
    assert "CONVERSATION SO FAR" in pack


def test_build_pack_includes_financial_context_when_given():
    pack = AskLodestar._build_pack(
        "Is TSMC investing in R&D?",
        [],
        [{"_feed_label": "Chips", "title": "TSMC 2nm", "summary": "ramp", "companies": ["TSMC"],
          "business_impact": "material", "published_at": "2026-06-10"}],
        [],
        {"financials": [{"entity": "TSMC", "rd_intensity": 0.065}], "prices": {}},
    )
    assert "=== COMPANY FINANCIALS" in pack and "TSMC: 6.5%" in pack
    # absent context → no financials block (the TASK line still references it)
    plain = AskLodestar._build_pack("q", [], [], [], None)
    assert "=== COMPANY FINANCIALS" not in plain


# ── Phantom-citation guard ────────────────────────────────────────────────────

def test_phantom_citations_out_of_range_are_neutralized():
    out = _neutralize_phantom_citations("Per [S7], the market moved. Theory says so [T4].",
                                        n_stories=3, n_theory=2)
    body, _, notice = out.partition("\n\n_Note:")
    assert "[S7]" not in out and "[T4]" not in out
    assert body.count("[unverified]") == 2
    assert "marked [unverified]" in notice  # one-line notice appended


def test_valid_citations_survive_untouched():
    text = "See [S1] and [S3]; theory in [T1] and [T2]."
    out = _neutralize_phantom_citations(text, n_stories=3, n_theory=2)
    assert out == text


def test_mixed_valid_and_phantom_citations():
    out = _neutralize_phantom_citations("Grounded [S2] but invented [T9] and [S0].",
                                        n_stories=3, n_theory=2)
    assert "[S2]" in out                       # in-range kept
    assert "[T9]" not in out and "[S0]" not in out   # out-of-range (incl. index 0) gone
    assert out.partition("\n\n_Note:")[0].count("[unverified]") == 2


def test_guard_noop_on_empty_or_citation_free_answers():
    assert _neutralize_phantom_citations("", 3, 2) == ""
    assert _neutralize_phantom_citations("No citations here.", 0, 0) == "No citations here."


def test_guarded_output_passes_ask_eval_phantom_check():
    # The eval harness's phantom detector must find zero phantoms in guarded output.
    from eval.judges.ask_eval import citation_validity, parse_citations
    docs = [{"label": "S1"}, {"label": "S2"}, {"label": "T1"}]
    guarded = _neutralize_phantom_citations("Real [S1], fake [S9], real [T1], fake [T3].",
                                            n_stories=2, n_theory=1)
    res = citation_validity(parse_citations(guarded), docs)
    assert res["phantom_citations"] == []
    assert res["citations"] == ["S1", "T1"]


# ── Empty-retrieval prompt path ───────────────────────────────────────────────

def test_empty_theory_pack_forbids_doctrine_citations():
    pack = AskLodestar._build_pack("What does MOT theory say?", [], [], [], None)
    assert "reason from MOT doctrine" not in pack
    assert "do NOT cite theory" in pack
    # TASK line: with nothing retrieved, citations are forbidden outright.
    assert "Do not use [S#]/[T#] citations" in pack
    assert "Cite developments" not in pack and "theory as [T#];" not in pack


def test_task_line_only_invites_citations_for_retrieved_kinds():
    story = [{"_feed_label": "Chips", "title": "TSMC 2nm", "summary": "ramp",
              "companies": ["TSMC"], "business_impact": "material", "published_at": "2026-06-10"}]
    theory = [{"source_file": "TSE.pdf", "chunk_text": "dominant design", "similarity": 0.7}]
    stories_only = AskLodestar._build_pack("q", [], story, [], None)
    assert "Cite developments as [S#];" in stories_only
    assert "theory as [T#]" not in stories_only.split("=== TASK ===")[1]
    both = AskLodestar._build_pack("q", [], story, theory, None)
    assert "Cite developments as [S#] and theory as [T#];" in both


# ── Tracked-state grounding (the Gartner-answer bug) ─────────────────────────

def test_stage_question_detector():
    from analytics.ask import _stage_question
    assert _stage_question("Which technologies moved lifecycle stage recently, and why?")
    assert _stage_question("Where does green hydrogen sit on the S-curve?")
    assert _stage_question("Has grid-scale storage crossed the chasm?")
    assert not _stage_question("Who wins from hyperscalers buying nuclear power?")
    assert not _stage_question("Why did Kodak fail?")


def test_recency_question_detector():
    from analytics.ask import _recency_question
    assert _recency_question("Which technologies moved lifecycle stage recently?")
    assert _recency_question("What happened this week in chips?")
    assert _recency_question("Where is capital concentrating right now?")
    assert not _recency_question("What does it take to cross the chasm?")


def test_build_pack_tracked_block_is_authoritative():
    tracked = ("Current stages (as of 2026-07-08; …):\n"
               "- AI data centres (AI & Energy): maturity=growth, adoption=early-majority")
    pack = AskLodestar._build_pack(
        "Which technologies moved lifecycle stage recently?", [], [], [], None,
        tracked=tracked)
    assert "LODESTAR TRACKED LIFECYCLE STATE" in pack
    assert "AI data centres" in pack
    # the tracked block precedes retrieved developments
    assert pack.index("LODESTAR TRACKED") < pack.index("=== DEVELOPMENTS")
    task = pack.split("=== TASK ===")[1]
    assert "MUST come from the LODESTAR TRACKED LIFECYCLE STATE" in task
    assert "Gartner" in task           # the named counter-example is spelled out
    # recency question → the no-web-fallback rule fires too
    assert "don't cover it" in task


def test_build_pack_without_tracked_has_no_stage_mandate():
    pack = AskLodestar._build_pack("Why did Kodak fail?", [], [], [], None)
    assert "LODESTAR TRACKED LIFECYCLE STATE" not in pack
    assert "MUST come from" not in pack


def test_build_pack_recency_rule_without_tracked():
    pack = AskLodestar._build_pack("What happened this week in chips?", [], [], [], None)
    task = pack.split("=== TASK ===")[1]
    assert "do not fill the gap from web research" in task
    assert "or the tracked state" not in task   # no tracked block → not referenced


def test_build_pack_web_supplement_is_background_only():
    pack = AskLodestar._build_pack("q", [], [], [], None)
    task = pack.split("=== TASK ===")[1]
    assert "background or theory context only" in task
    assert "never base a claim about recent developments" in task
