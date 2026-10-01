"""Tests for the MOT knowledge-base chunk-quality filter and the theory
retrieval relevance floor (pure, no network — fake Supabase client)."""

from vectordb.store import MotKnowledgeBase, _THEORY_SIM_FLOOR, is_useful_chunk

GOOD = (
    "The s-curve model suggests that technological change is cyclical. The emergence of a new "
    "technological discontinuity can overturn the existing competitive structure of an industry, "
    "creating new winners and losers — what Schumpeter calls creative destruction. One technology "
    "evolution model proposed by Utterback and Abernathy stated technology passes through a fluid "
    "phase of considerable uncertainty before a dominant design emerges and competition shifts to "
    "process innovation and scale."
)
INDEX_PAGE = (
    "Strategic fit, 189 Strategic intent 138 resource and capability gap, 140, 142 Strategic "
    "investors, 155 Strategic launch timing, 315 Strategic positions, 190 Strauss, Neil, 291 "
    "Stuart, Toby E., 43 Suarez, Fernando F., 67 Switching costs, 129 Tabarrok, Alexander, 37 "
    "Tagamet, 106, 262 Takeuchi, Hirotaka, 282 Tarakci, Murat, 40 Taylor, S. A., 281"
)
FIGURE_DUMP = (
    "Intel Transistor Density by Year 1970 1980 1990 2000 2010 2020 18,000,000 16,000,000 "
    "14,000,000 12,000,000 10,000,000 8,000,000 6,000,000 4,000,000 2,000,000 0 20,000 40,000 "
    "60,000 80,000 100,000 120,000 140,000"
)
REFERENCES = (
    "References Adner, R. (2017). Ecosystem as structure. Journal of Management, 43(1), 39-58. "
    "https://doi.org/10.1177/x ASML. (2018). Strategy update. Kamalaldin, A. (2021). Configuring "
    "ecosystem strategies. Technovation, 105. https://doi.org/10.1016/y Winston, B. (1998) Media "
    "Technology and Society."
)


def test_keeps_substantive_theory():
    assert is_useful_chunk(GOOD)


def test_drops_index_page():
    assert not is_useful_chunk(INDEX_PAGE)


def test_drops_figure_number_dump():
    assert not is_useful_chunk(FIGURE_DUMP)


def test_drops_reference_list():
    assert not is_useful_chunk(REFERENCES)


def test_drops_too_short():
    assert not is_useful_chunk("S-curve.")


# ── search(): similarity floor ────────────────────────────────────────────────
# The RPC returns top-k by cosine distance regardless of how far away those
# chunks are; search() must drop hits below _THEORY_SIM_FLOOR and is allowed
# to return an empty pack (downstream prompts abstain from [T#] citations).

class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def execute(self):
        class _Resp:
            pass
        resp = _Resp()
        resp.data = self._rows
        return resp


class _FakeClient:
    """Just enough Supabase client for MotKnowledgeBase.search()."""

    def __init__(self, rows):
        self.rows = rows
        self.rpc_calls: list[tuple] = []

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return _FakeQuery(self.rows)

    def table(self, name):  # pragma: no cover — search() never calls it
        raise AssertionError("search() should not touch tables")


def _hit(sim: float, text: str = GOOD, i: int = 0) -> dict:
    return {"id": i, "source_file": "book.pdf", "chunk_index": i,
            "chunk_text": text, "similarity": sim}


def _kb(rows) -> MotKnowledgeBase:
    return MotKnowledgeBase(client=_FakeClient(rows))


def test_search_keeps_hits_at_or_above_floor():
    kb = _kb([_hit(0.62, i=1), _hit(_THEORY_SIM_FLOOR, i=2), _hit(0.41, i=3)])
    out = kb.search([0.0], k=8)
    assert [r["id"] for r in out] == [1, 2, 3]


def test_search_drops_below_floor_hits():
    kb = _kb([_hit(0.62, i=1), _hit(_THEORY_SIM_FLOOR - 0.01, i=2), _hit(0.10, i=3)])
    out = kb.search([0.0], k=8)
    assert [r["id"] for r in out] == [1]


def test_search_empty_when_nothing_relevant():
    """All hits below the floor → empty pack, NOT a pad of the raw rows."""
    kb = _kb([_hit(0.30, i=1), _hit(0.22, i=2), _hit(0.05, i=3)])
    assert kb.search([0.0], k=8) == []


def test_search_no_junk_fallback():
    """Above-floor but non-substantive chunks (index pages, figure dumps) are
    dropped too, and the old raw-rows fallback must not reintroduce them."""
    kb = _kb([_hit(0.70, text=INDEX_PAGE, i=1), _hit(0.65, text=FIGURE_DUMP, i=2)])
    assert kb.search([0.0], k=8) == []


def test_search_caps_at_k():
    kb = _kb([_hit(0.60, i=i) for i in range(10)])
    assert len(kb.search([0.0], k=3)) == 3


def test_search_overfetches_so_filter_can_still_fill_k():
    kb = _kb([_hit(0.60)])
    kb.search([0.0], k=8)
    client = kb.client
    assert client.rpc_calls[0][0] == "match_mot_chunks"
    assert client.rpc_calls[0][1]["match_count"] > 8


def test_search_missing_similarity_treated_as_irrelevant():
    row = _hit(0.9, i=1)
    del row["similarity"]
    assert _kb([row]).search([0.0], k=8) == []


def test_search_swallows_rpc_failure():
    class _Boom:
        def rpc(self, *a, **kw):
            raise RuntimeError("network down")

    assert MotKnowledgeBase(client=_Boom()).search([0.0], k=8) == []
