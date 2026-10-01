"""Tests for the gold-label schema/loader/validator (eval/gold.py) — pure."""

import json
from pathlib import Path

import pytest

from eval.gold import (
    GOLD_FIELDS, GoldLabel, label_from_dict, load_gold, normalize_label, validate,
)


def test_normalize_label():
    assert normalize_label("Early_Majority") == "early-majority"
    assert normalize_label("  GROWTH ") == "growth"
    assert normalize_label("") is None
    assert normalize_label(None) is None


def test_label_from_dict_normalises():
    lab = label_from_dict({"url": " https://x.com/a ".strip(),
                           "maturity_stage": "Dominant_Design",
                           "scope": "Single_Company", "feed": "ev"})
    assert lab.maturity_stage == "dominant-design"
    assert lab.scope == "single-company"
    assert lab.feed == "ev"


def test_labelled_fields_skips_nulls():
    lab = label_from_dict({"url": "u", "business_impact": "material", "scope": "deal"})
    assert lab.labelled_fields == {"business_impact": "material", "scope": "deal"}
    assert "maturity_stage" not in lab.labelled_fields


def test_validate_clean():
    labs = [
        label_from_dict({"url": "a", "maturity_stage": "growth"}),
        label_from_dict({"url": "b", "scope": "regulatory"}),
    ]
    assert validate(labs) == []


def test_validate_flags_bad_value():
    labs = [label_from_dict({"url": "a", "maturity_stage": "banana"})]
    problems = validate(labs)
    assert len(problems) == 1 and "maturity_stage" in problems[0]


def test_validate_flags_duplicate_url():
    labs = [label_from_dict({"url": "a", "scope": "deal"}),
            label_from_dict({"url": "a", "scope": "sector"})]
    assert any("duplicate url" in p for p in validate(labs))


def test_validate_flags_missing_url_and_empty_row():
    labs = [label_from_dict({"maturity_stage": "growth"}),   # no url
            label_from_dict({"url": "b"})]                    # nothing labelled
    problems = validate(labs)
    assert any("missing url" in p for p in problems)
    assert any("no labelled fields" in p for p in problems)


def test_load_gold_skips_blank_lines(tmp_path):
    f = tmp_path / "g.jsonl"
    f.write_text(
        json.dumps({"url": "a", "scope": "deal"}) + "\n\n"
        + json.dumps({"url": "b", "maturity_stage": "growth"}) + "\n",
        encoding="utf-8",
    )
    labs = load_gold(f)
    assert [l.url for l in labs] == ["a", "b"]


def test_load_gold_raises_on_bad_json_with_lineno(tmp_path):
    f = tmp_path / "g.jsonl"
    f.write_text(json.dumps({"url": "a", "scope": "deal"}) + "\n{not json}\n", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        load_gold(f)
    assert ":2:" in str(e.value)  # the offending line number


def test_example_gold_is_valid():
    # The shipped example must always pass validation (it documents the format).
    path = Path(__file__).parent.parent / "eval" / "gold_labels.example.jsonl"
    labs = load_gold(path)
    assert len(labs) >= 3
    assert validate(labs) == []


def test_gold_fields_constant():
    assert GOLD_FIELDS == ("maturity_stage", "adoption_stage", "business_impact", "scope")
