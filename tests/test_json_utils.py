"""Tests for the shared, drift-tolerant agent-output parsers."""

import pytest

from toqan.json_utils import parse_json_array, parse_json_object


class TestParseJsonArray:
    def test_bare_array(self):
        assert parse_json_array('[{"a": 1}, {"a": 2}]') == [{"a": 1}, {"a": 2}]

    def test_json_fence(self):
        assert parse_json_array('```json\n[{"a": 1}]\n```') == [{"a": 1}]

    def test_bare_fence(self):
        assert parse_json_array('```\n[1, 2, 3]\n```') == [1, 2, 3]

    def test_think_preamble_stripped(self):
        assert parse_json_array("<think>let me reason</think>\n[1, 2]") == [1, 2]

    def test_prose_around_array(self):
        assert parse_json_array("Here you go: [1, 2, 3]. Done.") == [1, 2, 3]

    def test_wrapper_key_object(self):
        # The case the old lens copy silently dropped to [].
        assert parse_json_array('{"items": [{"a": 1}, {"a": 2}]}') == [{"a": 1}, {"a": 2}]

    def test_other_known_wrapper_keys(self):
        for key in ("articles", "news", "data", "results", "feed"):
            assert parse_json_array(f'{{"{key}": [9]}}') == [9]

    def test_single_array_valued_key_fallback(self):
        assert parse_json_array('{"whatever": [7, 8]}') == [7, 8]

    def test_custom_keys(self):
        assert parse_json_array('{"rows": [1]}', keys=("rows",)) == [1]

    def test_empty_input_raises(self):
        with pytest.raises(ValueError):
            parse_json_array("")

    def test_no_json_raises(self):
        with pytest.raises(ValueError):
            parse_json_array("there is no array here at all")


class TestParseJsonObject:
    def test_plain_object(self):
        assert parse_json_object('{"headline": "x"}') == {"headline": "x"}

    def test_fenced_object(self):
        assert parse_json_object('```json\n{"k": 1}\n```') == {"k": 1}

    def test_think_stripped(self):
        assert parse_json_object("<think>hmm</think>{\"k\": 2}") == {"k": 2}

    def test_prose_around_object(self):
        assert parse_json_object('result: {"a": 1} ok') == {"a": 1}

    def test_none_when_absent(self):
        assert parse_json_object("just prose, no object") is None

    def test_none_on_empty(self):
        assert parse_json_object("") is None
