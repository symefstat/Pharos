"""Tests for the funding signal — aggregation, corroboration read, CSV ingest."""

from datetime import date
from pathlib import Path

from analytics.funding import MIN_ROUNDS_FOR_READ, funding_read, funding_summary
from funding_run import normalize_round, parse_csv

TODAY = date(2026, 7, 9)


def _r(round_type: str, announced: str, amount: float | None = 50e6) -> dict:
    return {"tech_key": "ai-datacenters", "company": "Co", "round_type": round_type,
            "amount_usd": amount, "announced_on": announced}


# ── funding_summary ────────────────────────────────────────────────────────────

def test_summary_none_without_rows():
    assert funding_summary([], TODAY) is None


def test_summary_windows_and_aggregates():
    rows = [
        _r("series-b", "2026-06-01", 120e6),
        _r("m&a", "2026-02-10", 1e9),
        _r("seed", "2026-01-15", None),          # undisclosed — counts, adds $0
        _r("series-a", "2024-01-01", 10e6),      # outside the 365d window
    ]
    s = funding_summary(rows, TODAY)
    assert s["rounds"] == 3 and s["total_usd"] == 1.12e9
    assert s["early"] == 2 and s["late"] == 1
    assert [t["quarter"] for t in s["trajectory"]] == ["2026Q1", "2026Q2"]
    assert s["trajectory"][0]["rounds"] == 2          # m&a + seed both in Q1
    assert s["latest"][0]["announced_on"] == "2026-06-01"


# ── funding_read (corroboration) ───────────────────────────────────────────────

def test_read_none_with_no_rounds():
    assert funding_read([], "growth", TODAY) is None


def test_read_withholds_below_floor():
    rows = [_r("seed", "2026-06-01"), _r("series-a", "2026-05-01")]
    out = funding_read(rows, "emerging", TODAY)
    assert "too few" in out and str(MIN_ROUNDS_FOR_READ) in out


def test_read_corroborates_matching_phase():
    rows = [_r("seed", "2026-06-01"), _r("series-a", "2026-05-01"),
            _r("series-b", "2026-04-01")]
    out = funding_read(rows, "emerging", TODAY)
    assert "early-phase" in out and "independently corroborates" in out


def test_read_flags_capital_running_later_than_stage():
    rows = [_r("m&a", "2026-06-01"), _r("ipo", "2026-05-01"),
            _r("series-c-plus", "2026-04-01")]
    out = funding_read(rows, "emerging", TODAY)
    assert "late-phase" in out and "runs later" in out


def test_read_flags_capital_running_earlier_than_stage():
    rows = [_r("seed", "2026-06-01"), _r("series-a", "2026-05-01"),
            _r("grant", "2026-04-01")]
    out = funding_read(rows, "mature", TODAY)
    assert "runs earlier" in out


def test_read_debt_and_other_carry_no_phase():
    rows = [_r("debt", "2026-06-01"), _r("other", "2026-05-01"),
            _r("debt", "2026-04-01"), _r("other", "2026-03-01")]
    out = funding_read(rows, "growth", TODAY)
    assert "too few" in out                            # 0 phase-classified


# ── CSV ingest ─────────────────────────────────────────────────────────────────

def test_normalize_round_aliases():
    assert normalize_round("Series C") == "series-c-plus"
    assert normalize_round("Pre-Seed") == "seed"
    assert normalize_round("Acquisition") == "m&a"
    assert normalize_round("Growth Equity") == "growth"
    assert normalize_round("weird thing") == "other"


def test_parse_csv_validates_and_normalizes(tmp_path: Path):
    p = tmp_path / "rounds.csv"
    p.write_text(
        "tech_key,company,round_type,amount_usd,announced_on,source_url,investors\n"
        "ai-datacenters,GoodCo,Series B,120000000,2026-05-14,https://x.com/a,Inv One;Inv Two\n"
        "not-a-tech,BadCo,seed,1,2026-05-14,,\n"
        "ai-datacenters,,seed,1,2026-05-14,,\n"
        "ai-datacenters,NoDate,seed,1,May 2026,,\n"
        "ai-datacenters,BadAmt,seed,abc,2026-05-14,,\n"
        "ai-datacenters,Undisclosed,acquisition,,2026-06-01,,\n"
    )
    rows, rejects = parse_csv(p, valid_keys={"ai-datacenters"})
    assert len(rows) == 2 and len(rejects) == 4
    good = rows[0]
    assert good["round_type"] == "series-b" and good["amount_usd"] == 120e6
    assert good["investors"] == ["Inv One", "Inv Two"]
    assert good["source"] == "csv:rounds.csv"
    assert rows[1]["round_type"] == "m&a" and rows[1]["amount_usd"] is None
    assert any("unknown tech_key" in r for r in rejects)
    assert any("YYYY-MM-DD" in r for r in rejects)
