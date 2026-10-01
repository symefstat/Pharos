"""Tests for the yfinance network layer (finance.client) — retry + graceful degradation.

yfinance is an unofficial, flaky source; the statement fetch in `fundamentals` is wrapped
in `net.retry` so a transient blip doesn't lose a company's fundamentals for the cycle, yet
a hard failure still degrades to None (never raises). We exercise the REAL retry with its
backoff sleep no-op'd, so the tests are instant.
"""

import logging
import sys
import types

import pandas as pd

import net
import finance.client as fc


def _install_fake_yfinance(monkeypatch, ticker_cls):
    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = ticker_cls
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    # Exercise the real retry, but no-op the backoff sleep so the test doesn't wait.
    orig_retry = net.retry
    monkeypatch.setattr(net, "retry", lambda fn, **kw: orig_retry(fn, sleep=lambda _s: None, **kw))


def test_fundamentals_retries_transient_failure(monkeypatch):
    state = {"fails": 1}  # fail once, then succeed

    class _FlakyTicker:
        def __init__(self, symbol):
            if state["fails"] > 0:
                state["fails"] -= 1
                raise RuntimeError("transient yfinance blip")
        income_stmt = balance_sheet = cashflow = None  # _first(None) → None; degrades cleanly
        fast_info = {"market_cap": 1_000_000_000.0, "currency": "USD"}
        info = {"financialCurrency": "USD"}

    _install_fake_yfinance(monkeypatch, _FlakyTicker)
    out = fc.fundamentals("NVDA")
    assert state["fails"] == 0                                   # the first attempt really failed
    assert out is not None                                        # ...but the retry recovered it
    assert out["market_cap"] == 1_000_000_000.0 and out["currency"] == "USD"


def test_fundamentals_degrades_to_none_when_all_attempts_fail(monkeypatch):
    class _AlwaysFails:
        def __init__(self, symbol):
            raise RuntimeError("yfinance down")

    _install_fake_yfinance(monkeypatch, _AlwaysFails)
    assert fc.fundamentals("NVDA") is None                        # never raises; degrades to None


# ── Fiscal-period alignment: every statement field anchors to revenue's column ──

def _ticker_cls(income=None, balance=None, flow=None):
    class _T:
        def __init__(self, symbol):
            pass
        income_stmt = income
        balance_sheet = balance
        cashflow = flow
        fast_info = {"market_cap": 1_000_000_000.0, "currency": "USD"}
        info = {"financialCurrency": "USD"}
    return _T


def test_fundamentals_never_mixes_fiscal_years(monkeypatch, caplog):
    # The 2× rd_intensity repro: FY2025 revenue is filed but Yahoo hasn't backfilled
    # the FY2025 R&D row yet. The old per-field _first paired FY2024 R&D (30) with
    # FY2025 revenue (200) → 15% instead of the true FY2024 30%. Now: R&D must be
    # None (unknown for the anchor period), flagged — never a cross-year value.
    income = pd.DataFrame({
        "2025-12-31": {"Total Revenue": 200.0, "Research And Development": float("nan")},
        "2024-12-31": {"Total Revenue": 100.0, "Research And Development": 30.0},
    })
    _install_fake_yfinance(monkeypatch, _ticker_cls(income=income))
    with caplog.at_level(logging.WARNING, logger="finance.client"):
        out = fc.fundamentals("MIXCO")
    assert out["revenue"] == 200.0                                # anchor = FY2025
    assert out["rd_expense"] is None                              # NOT 30.0 from FY2024
    assert "mixing fiscal years" in caplog.text                   # flagged, not silent
    # downstream: None stays *unknown* (never 0, never a mixed-year 15%)
    from analytics.financials import rd_intensity
    assert rd_intensity(out["revenue"], out["rd_expense"]) is None


def test_fundamentals_reads_all_fields_from_the_anchor_period(monkeypatch):
    income = pd.DataFrame({
        "2025-12-31": {"Total Revenue": 200.0, "Research And Development": 50.0},
        "2024-12-31": {"Total Revenue": 100.0, "Research And Development": 30.0},
    })
    flow = pd.DataFrame({
        "2025-12-31": {"Capital Expenditure": -20.0},
        "2024-12-31": {"Capital Expenditure": -10.0},
    })
    _install_fake_yfinance(monkeypatch, _ticker_cls(income=income, flow=flow))
    out = fc.fundamentals("SAMECO")
    assert out["revenue"] == 200.0 and out["rd_expense"] == 50.0  # same column
    assert out["capex"] == 20.0                                   # anchor date, abs()'d
    from analytics.financials import rd_intensity
    assert rd_intensity(out["revenue"], out["rd_expense"]) == 0.25  # same-period ratio


def test_fundamentals_missing_rd_row_stays_none_not_zero(monkeypatch):
    # Yahoo carries no R&D line at all and there is no curated override for the
    # symbol → rd_expense None (quietly). None must remain distinguishable from a
    # filed 0 upstream. (Toyota itself is now covered by RD_OVERRIDES — see below.)
    income = pd.DataFrame({"2026-03-31": {"Total Revenue": 5.0e13}})
    _install_fake_yfinance(monkeypatch, _ticker_cls(income=income))
    out = fc.fundamentals("NORD")
    assert "NORD" not in fc.RD_OVERRIDES                              # premise of this test
    assert out["revenue"] == 5.0e13 and out["rd_expense"] is None
    assert out["rd_basis"] is None
    from analytics.financials import investment_signal, rd_intensity
    assert rd_intensity(out["revenue"], out["rd_expense"]) is None   # unknown, not 0%
    assert investment_signal(None) == "unknown"                      # not "harvesting"


# ── Curated R&D overrides: only when Yahoo lacks the row, same fiscal anchor ──

def test_rd_override_fills_toyota_when_row_absent_and_fy_matches(monkeypatch):
    # Toyota: Yahoo's income statement has no R&D row at all; the curated 20-F
    # FY2026 figure applies because the revenue anchor column is FY2026 (2026-03-31).
    income = pd.DataFrame({"2026-03-31": {"Total Revenue": 5.0684952e13}})
    _install_fake_yfinance(monkeypatch, _ticker_cls(income=income))
    out = fc.fundamentals("TM")
    assert out["rd_expense"] == fc.RD_OVERRIDES["TM"]["rd_expense"]   # ¥1,522.8B
    assert out["rd_basis"] == "curated-override (20-F FY2026)"        # marked in the row
    from analytics.financials import rd_intensity
    ri = rd_intensity(out["revenue"], out["rd_expense"])
    assert ri is not None and 0.029 < ri < 0.031                      # ≈3.0%, FX-agnostic


def test_rd_override_respects_fiscal_anchor_discipline(monkeypatch, caplog):
    # Anchor moved on to FY2027 → the FY2026 override no longer matches the
    # revenue period: stay None (warned) rather than mixing fiscal years.
    income = pd.DataFrame({"2027-03-31": {"Total Revenue": 5.2e13}})
    _install_fake_yfinance(monkeypatch, _ticker_cls(income=income))
    with caplog.at_level(logging.WARNING, logger="finance.client"):
        out = fc.fundamentals("TM")
    assert out["rd_expense"] is None and out["rd_basis"] is None
    assert "mixing fiscal years" in caplog.text


def test_rd_override_not_used_when_yahoo_carries_the_row(monkeypatch):
    # The R&D row EXISTS but is null in the anchor period → that's *unknown*
    # (Yahoo mid-backfill), never override territory: the curated figure is only
    # for filers whose row Yahoo lacks entirely.
    income = pd.DataFrame({
        "2026-03-31": {"Total Revenue": 5.0e13, "Research And Development": float("nan")},
        "2025-03-31": {"Total Revenue": 4.5e13, "Research And Development": 1.2e12},
    })
    _install_fake_yfinance(monkeypatch, _ticker_cls(income=income))
    out = fc.fundamentals("TM")
    assert out["rd_expense"] is None and out["rd_basis"] is None


def test_capex_fallback_is_flagged_when_statement_lacks_anchor_period(monkeypatch, caplog):
    # Cashflow statement has no column for revenue's fiscal period → explicit,
    # warned fallback to its latest period (was: silent).
    income = pd.DataFrame({"2025-12-31": {"Total Revenue": 200.0}})
    flow = pd.DataFrame({"2024-12-31": {"Capital Expenditure": -10.0}})
    _install_fake_yfinance(monkeypatch, _ticker_cls(income=income, flow=flow))
    with caplog.at_level(logging.WARNING, logger="finance.client"):
        out = fc.fundamentals("LAGCO")
    assert out["capex"] == 10.0
    assert "anchor period" in caplog.text and "falling back" in caplog.text


# ── Live FX rates: one batched fetch, graceful degradation to the static map ──

def test_fx_rates_usd_parses_batch_with_source_and_as_of(monkeypatch):
    idx = pd.to_datetime(["2026-06-30", "2026-07-01"])
    cols = pd.MultiIndex.from_product([["EURUSD=X", "KRWUSD=X"], ["Close"]])
    df = pd.DataFrame([[1.1400, 0.000650], [1.1452, 0.000647]], index=idx, columns=cols)
    fake_yf = types.ModuleType("yfinance")
    fake_yf.download = lambda *a, **kw: df
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    out = fc.fx_rates_usd(["EUR", "KRW", "USD", None])            # USD/None excluded
    assert out["rates"] == {"EUR": 1.1452, "KRW": 0.000647}       # latest close per pair
    assert out["as_of"] == "2026-07-01" and out["source"] == "yfinance"


def test_fx_rates_usd_degrades_to_empty_rates_on_failure(monkeypatch):
    fake_yf = types.ModuleType("yfinance")

    def _boom(*a, **kw):
        raise RuntimeError("yfinance down")

    fake_yf.download = _boom
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    orig_retry = net.retry
    monkeypatch.setattr(net, "retry", lambda fn, **kw: orig_retry(fn, sleep=lambda _s: None, **kw))
    out = fc.fx_rates_usd(["EUR", "KRW"])
    assert out["rates"] == {}                                     # caller falls back to static map
    assert fc.fx_rates_usd([])["rates"] == {}                     # nothing to fetch → no call
