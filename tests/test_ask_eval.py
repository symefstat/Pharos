"""Tests for the offline L9 Ask eval harness (eval/judges/ask_eval.py). Pure, no network."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.judges.ask_eval import (
    DEMO_FIXTURE,
    citation_validity,
    faithfulness,
    parse_citations,
    refusal_check,
    retrieval_precision_at_k,
    score_row,
)

DOCS = [
    {"label": "S1", "title": "Solid-state battery breakthrough", "text": "Toyota energy density 900 Wh/l"},
    {"label": "T1", "source_file": "Schilling.pdf", "text": "The s-curve model of technology performance"},
    {"label": "T2", "source_file": "Ortt.pdf", "text": "adaptation phase niche strategies"},
]


def test_parse_citations_orders_and_dedupes():
    assert parse_citations("See [S1] and [T2], again [S1], also [T1].") == ["S1", "T2", "T1"]


def test_citation_validity_flags_out_of_range():
    res = citation_validity(["S1", "T2", "S3", "T9"], DOCS)
    assert res["phantom_citations"] == ["S3", "T9"]
    assert res["n_retrieved_s"] == 1 and res["n_retrieved_t"] == 2


def test_citation_validity_clean():
    assert citation_validity(["S1", "T1", "T2"], DOCS)["phantom_citations"] == []


def test_precision_at_k_keyword_proxy():
    assert retrieval_precision_at_k(DOCS, ["s-curve", "battery", "niche"], k=3) == 1.0
    assert retrieval_precision_at_k(DOCS, ["quantum"], k=3) == 0.0
    assert retrieval_precision_at_k(DOCS, [], k=3) is None  # unanswerable → no precision


def test_faithfulness_flags_number_not_in_docs():
    bad = faithfulness("Toyota shipped 5 million units last year.", DOCS)
    assert len(bad["ungrounded_claims"]) == 1
    ok = faithfulness("Toyota reached 900 Wh/l energy density [S1].", DOCS)
    assert ok["ungrounded_claims"] == []


def test_faithfulness_ignores_refusal_sentences():
    res = faithfulness("The pack does not contain enough evidence about CASP16 to answer.", DOCS)
    assert res["ungrounded_claims"] == []


def test_refusal_check():
    assert refusal_check("There is insufficient evidence in the pack.", "unanswerable")["refusal_correct"] is True
    assert refusal_check("Absolutely, the answer is 42.", "unanswerable")["refusal_correct"] is False
    assert refusal_check("The s-curve says performance plateaus.", "answerable")["refusal_correct"] is True


def test_demo_fixture_clean_and_dirty_rows():
    clean = score_row(dict(DEMO_FIXTURE[0]), k=5)
    assert clean["phantom_citations"] == [] and clean["ungrounded_claims"] == []
    dirty = score_row(dict(DEMO_FIXTURE[1]), k=5)
    assert dirty["phantom_citations"] == ["T4"]
    assert len(dirty["ungrounded_claims"]) >= 1  # the Gartner 47% claim


def test_questions_file_well_formed():
    path = Path(__file__).parent.parent / "eval" / "judges" / "ask_questions.jsonl"
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    assert len(rows) >= 25
    types = {r["type"] for r in rows}
    assert types == {"answerable", "unanswerable", "boundary"}
    for r in rows:
        assert r["q"] and "expected_sources_hint" in r and "notes" in r
        if r["type"] == "answerable":
            assert r["expected_sources_hint"], f"answerable q needs hints: {r['q']}"
    assert sum(1 for r in rows if r["type"] == "unanswerable") >= 4
