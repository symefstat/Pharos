"""Tests for the backtest engine — rollup, calls, milestone comparison (pure)."""

from analytics.backtest import (
    MIN_ITEMS_PER_QUARTER,
    build_report,
    compare,
    false_calls,
    q_span,
    quarter_of,
    quarterly_stages,
    report_to_markdown,
    stage_calls,
)


def _items(quarter_stage_counts: list[tuple[str, str, int]]) -> list[dict]:
    """[('2020Q1', 'emerging', 6), …] → dated classified items."""
    month_of = {"1": "02", "2": "05", "3": "08", "4": "11"}
    out = []
    for q, stage, n in quarter_stage_counts:
        date = f"{q[:4]}-{month_of[q[-1]]}-10"
        out += [{"date": date, "maturity_stage": stage}] * n
    return out


def test_quarter_helpers():
    assert quarter_of("2021-03-11") == "2021Q1"
    assert quarter_of("2021-12-31") == "2021Q4"
    assert q_span("2020Q4", "2021Q2") == 2
    assert q_span("2021Q2", "2020Q4") == -2


def test_quarterly_stages_modal_and_floor():
    items = _items([("2020Q1", "emerging", 4), ("2020Q1", "research", 2),
                    ("2020Q2", "emerging", 3)])          # Q2 under the floor
    qs = quarterly_stages(items)
    assert qs[0]["quarter"] == "2020Q1" and qs[0]["stage"] == "emerging"
    assert qs[0]["n"] == 6 and qs[0]["modal_share"] == 0.67
    assert qs[1]["stage"] is None                        # 3 < MIN_ITEMS_PER_QUARTER
    assert MIN_ITEMS_PER_QUARTER == 5


def test_quarterly_stages_ignores_na_and_junk():
    items = [{"date": "2020-02-10", "maturity_stage": "n/a"},
             {"date": "2020-02-10", "maturity_stage": None},
             {"date": "2020-02-10", "maturity_stage": "weird"},
             {"date": "", "maturity_stage": "growth"}]
    assert quarterly_stages(items) == []


def test_stage_calls_need_two_consecutive_quarters():
    items = _items([("2020Q1", "emerging", 6), ("2020Q2", "emerging", 6),
                    ("2020Q3", "growth", 6), ("2020Q4", "growth", 6),
                    ("2021Q1", "growth", 6)])
    calls = stage_calls(quarterly_stages(items))
    assert [(c["stage"], c["quarter"]) for c in calls] == \
        [("emerging", "2020Q2"), ("growth", "2020Q4")]   # confirmed on the 2nd reading


def test_stage_calls_single_quarter_spike_never_calls():
    items = _items([("2020Q1", "emerging", 6), ("2020Q2", "growth", 6),
                    ("2020Q3", "emerging", 6), ("2020Q4", "emerging", 6)])
    calls = stage_calls(quarterly_stages(items))
    assert [c["stage"] for c in calls] == ["emerging"]   # the growth spike was noise


def test_stage_calls_evidence_gap_breaks_streak():
    items = _items([("2020Q1", "growth", 6), ("2020Q2", "growth", 2),   # gap (<floor)
                    ("2020Q3", "growth", 6), ("2020Q4", "growth", 6)])
    calls = stage_calls(quarterly_stages(items))
    assert calls[0]["quarter"] == "2020Q4"               # streak restarted after the gap


def test_compare_hits_misses_and_lag():
    calls = [{"stage": "growth", "quarter": "2021Q2", "evidence_n": 9, "modal_share": 0.8}]
    milestones = [
        {"stage": "growth", "quarter": "2021Q1", "event": "e1", "source": "s1"},
        {"stage": "dominant-design", "quarter": "2021Q4", "event": "e2", "source": "s2"},
    ]
    out = compare(calls, milestones)
    assert out[0]["hit"] and out[0]["lag_quarters"] == 1          # one quarter late
    assert not out[1]["hit"] and out[1]["lag_quarters"] is None   # MISS
    assert false_calls(calls, milestones) == []


def test_false_calls_flagged():
    calls = [{"stage": "mature", "quarter": "2021Q2", "evidence_n": 7, "modal_share": 0.6}]
    assert false_calls(calls, [{"stage": "growth", "quarter": "2021Q1",
                                "event": "e", "source": "s"}]) == calls


def test_report_and_markdown_carry_misses():
    case = {"key": "t", "label": "Tech T", "query": "q", "window": ["2020Q1", "2021Q4"],
            "milestones": [
                {"stage": "growth", "quarter": "2020Q3", "event": "The event",
                 "source": "https://example.com/e"},
                {"stage": "mature", "quarter": "2021Q4", "event": "Never happened in data",
                 "source": "https://example.com/m"},
            ], "notes": "a note"}
    items = _items([("2020Q1", "emerging", 6), ("2020Q2", "growth", 6),
                    ("2020Q3", "growth", 6)])
    r = build_report(case, items)
    assert r["n_classified"] == 18
    assert [c["hit"] for c in r["comparison"]] == [True, False]
    md = report_to_markdown([r], generated="2026-07-09")
    assert "1/2 milestones called" in md
    assert "MISS — never called" in md
    assert "[source](https://example.com/e)" in md
    assert "a note" in md
    assert "Limitations" in md                            # honesty section present
