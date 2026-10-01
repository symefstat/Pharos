"""
Free financial data via yfinance (no API key). Prices + a fundamentals snapshot.

Network layer only — returns plain dicts / lists, no Streamlit, no DB. yfinance is
an unofficial source and can flake or change shape, so every call degrades to
None / [] on failure; callers must treat a missing number as *unknown*, never as
zero. Heavy imports (yfinance) are local to each function so importing this module
is cheap and the rest of the app loads even if yfinance is absent.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── Curated R&D overrides ───────────────────────────────────────────────────────
# For filers whose R&D line yfinance does not carry AT ALL (the row is absent from
# the income statement, not merely null) — e.g. Toyota, which the 2×2 and
# rd_intensity otherwise silently drop. Values are in the company's REPORTING
# currency (financials_run FX-converts at write time, like every statement field)
# and are applied with the same fiscal-anchor discipline as `_at`: only when the
# override's fiscal year matches the revenue anchor column's calendar year —
# otherwise rd_expense stays None rather than mixing fiscal years. Rows filled
# this way are marked via `rd_basis` (e.g. "curated-override (20-F FY2026)").
#
# TM: Toyota FY2026 (2025-04-01 → 2026-03-31) consolidated R&D expenditures were
# ¥1,522.8B — Toyota "FINANCIAL SUMMARY FY2026" (results announced 2026-05-08;
# figure carried in the 20-F):
# https://global.toyota/pages/global_toyota/ir/financial-results/2026_4q_summary_en.pdf
RD_OVERRIDES: dict[str, dict] = {
    "TM": {"rd_expense": 1_522_800_000_000.0, "fiscal_year": "FY2026",
           "source": "20-F", "as_of": "2026-05-08"},
}


def _first(df, *row_names) -> float | None:
    """First non-null value from the most-recent column of a yfinance statement
    DataFrame, for any of the candidate row labels (label spellings drift).
    Ignores fiscal periods — only safe for standalone fields; use `_at` for
    anything that enters a ratio (see the period-mixing note there)."""
    if df is None or getattr(df, "empty", True):
        return None
    for name in row_names:
        if name in df.index:
            series = df.loc[name].dropna()
            if not series.empty:
                try:
                    return float(series.iloc[0])
                except (TypeError, ValueError):
                    return None
    return None


def _anchor_column(df, *row_names):
    """The most recent fiscal column where any candidate anchor row (revenue) is
    non-null — every other statement field is then read from THIS column so that
    ratios like rd_intensity never mix fiscal years. None if no such column."""
    if df is None or getattr(df, "empty", True):
        return None
    for name in row_names:
        if name in df.index:
            series = df.loc[name].dropna()
            if not series.empty:
                return series.index[0]
    return None


def _at(df, column, *row_names, field: str = "field") -> float | None:
    """Value for the first matching row label at ONE fiscal `column` (the revenue
    anchor period). Unlike `_first`, this never silently reaches into another
    fiscal year: a field that is null in the anchor period but populated in an
    older one returns None with a warning (mixing periods put FY(N-1) R&D over
    FY(N) revenue — a 2× rd_intensity error). A row that is missing entirely
    (e.g. Yahoo carries no R&D line for Toyota) returns None quietly — callers
    treat None as *unknown*, never zero."""
    if df is None or getattr(df, "empty", True):
        return None
    if column is None:                       # no revenue anywhere — nothing to align to
        return _first(df, *row_names)
    if column not in df.columns:             # this statement lacks the anchor period
        val = _first(df, *row_names)
        if val is not None:
            logger.warning("%s: anchor period %s not in statement — falling back to the "
                           "latest available period (may differ from revenue's)", field, column)
        return val
    stale = None  # most recent non-null period outside the anchor, for the warning
    for name in row_names:
        if name in df.index:
            row = df.loc[name]
            try:
                val = float(row.get(column))
            except (TypeError, ValueError):
                val = None
            if val is not None and val == val:            # non-null in the anchor period
                return val
            nonnull = row.dropna()
            if stale is None and not nonnull.empty:
                stale = nonnull.index[0]
    if stale is not None:
        logger.warning("%s: null in anchor period %s (non-null exists in %s) — keeping None "
                       "rather than mixing fiscal years", field, column, stale)
    return None


def _has_row(df, *row_names) -> bool:
    """Whether the statement carries any of the candidate row labels at all
    (regardless of null-ness). Distinguishes 'Yahoo has no R&D line' (curated
    override territory) from 'the row exists but is null in the anchor period'
    (unknown — never overridden)."""
    if df is None or getattr(df, "empty", True):
        return False
    return any(name in df.index for name in row_names)


def _fiscal_year_of(value) -> int | None:
    """Calendar year of a fiscal column label (Timestamp or string) or of an
    override's 'FY2026'-style tag. None if no 4-digit year is recoverable."""
    year = getattr(value, "year", None)
    if year is not None:
        return int(year)
    m = re.search(r"\d{4}", str(value or ""))
    return int(m.group()) if m else None


def _rd_override(symbol: str, income, anchor) -> tuple[float | None, str | None]:
    """(rd_expense, rd_basis) from RD_OVERRIDES, or (None, None).

    Applied ONLY when (a) the income statement lacks the R&D row entirely, and
    (b) the override's fiscal year matches the anchor (revenue) column's year —
    the same discipline as `_at`: a curated FY2026 figure must never sit over
    FY2027 revenue, so on mismatch we keep None (and warn) instead."""
    ov = RD_OVERRIDES.get(symbol)
    if not ov:
        return None, None
    if _has_row(income, "Research And Development", "Research Development"):
        return None, None  # Yahoo has the row — a null there means unknown, not override
    anchor_year = _fiscal_year_of(anchor)
    if anchor_year is None or _fiscal_year_of(ov.get("fiscal_year")) != anchor_year:
        logger.warning("%s: curated R&D override is for %s but the statement anchor is "
                       "%s — keeping None rather than mixing fiscal years",
                       symbol, ov.get("fiscal_year"), anchor)
        return None, None
    basis = f"curated-override ({ov['source']} {ov['fiscal_year']})"
    logger.info("%s: R&D row absent at Yahoo — using %s: %s (as of %s)",
                symbol, basis, ov["rd_expense"], ov.get("as_of"))
    return float(ov["rd_expense"]), basis


def fundamentals(symbol: str) -> dict | None:
    """Latest-annual fundamentals for `symbol`: revenue, R&D, capex, cash, market
    cap, currency. Missing fields come back as None. None overall on hard failure."""
    try:
        import yfinance as yf

        from net import retry

        # yfinance's statement endpoints transiently fail / rate-limit; retry the fetch
        # with backoff before degrading to None (same treatment as the batch price path).
        def _statements():
            t = yf.Ticker(symbol)
            return t, t.income_stmt, t.balance_sheet, t.cashflow

        t, income, balance, flow = retry(_statements, label=f"yf.fundamentals({symbol})")

        # Anchor every statement field to ONE fiscal period — the most recent
        # column where revenue is non-null — so numerator and denominator of the
        # downstream ratios (rd_intensity, investment_intensity) always come from
        # the same fiscal year. (Previously each field independently took its
        # latest non-null column, mixing years while Yahoo backfills a filing.)
        anchor = _anchor_column(income, "Total Revenue", "TotalRevenue", "Operating Revenue")
        revenue = _at(income, anchor, "Total Revenue", "TotalRevenue", "Operating Revenue",
                      field=f"{symbol} revenue")
        rd = _at(income, anchor, "Research And Development", "Research Development",
                 field=f"{symbol} rd_expense")
        rd_basis = None
        if rd is None:
            # Curated fallback for filers whose R&D row Yahoo lacks entirely (TM);
            # fiscal-anchor discipline enforced inside — mismatched year stays None.
            rd, rd_basis = _rd_override(symbol, income, anchor)
        capex = _at(flow, anchor, "Capital Expenditure", "Capital Expenditures",
                    field=f"{symbol} capex")
        cash = _at(
            balance,
            anchor,
            "Cash And Cash Equivalents",
            "Cash Cash Equivalents And Short Term Investments",
            "Cash And Short Term Investments",
            field=f"{symbol} cash",
        )

        market_cap = currency = None
        try:
            fast = t.fast_info
            for key in ("market_cap", "marketCap"):
                val = None
                try:
                    val = fast[key]
                except (KeyError, TypeError):
                    val = getattr(fast, key, None)
                if val:
                    market_cap = float(val)
                    break
            try:
                currency = fast["currency"]
            except (KeyError, TypeError):
                currency = getattr(fast, "currency", None)
        except Exception:  # fast_info is itself best-effort
            pass

        if revenue is None and rd is None and market_cap is None:
            return None  # nothing usable came back

        # The *reporting* currency of the financial statements — differs from the
        # listing currency for ADRs (e.g. TM lists in USD but reports in JPY), so
        # market_cap / revenue mixes currencies unless we know both.
        financial_currency = None
        try:
            financial_currency = (t.info or {}).get("financialCurrency")
        except Exception:
            pass

        return {
            "symbol": symbol,
            "revenue": revenue,
            "rd_expense": rd,
            "rd_basis": rd_basis,   # None for plain yfinance values; see RD_OVERRIDES
            "capex": abs(capex) if capex is not None else None,  # cashflow is an outflow
            "cash": cash,
            "market_cap": market_cap,
            "currency": currency,                       # listing currency (for market cap)
            "financial_currency": financial_currency,   # reporting currency (for revenue/cash/…)
        }
    except Exception as e:
        logger.warning("fundamentals(%s) failed: %s", symbol, e)
        return None


def price_history(symbol: str, days: int = 120) -> list[dict]:
    """Recent daily closes [{date: 'YYYY-MM-DD', close: float}], oldest → newest.
    Empty list on failure."""
    try:
        import yfinance as yf

        period = "6mo" if days <= 130 else "1y"
        hist = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return []
        out = []
        for idx, row in hist.tail(days).iterrows():
            close = row.get("Close")
            if close is None:
                continue
            try:
                out.append({"date": idx.strftime("%Y-%m-%d"), "close": float(close)})
            except (TypeError, ValueError):
                continue
        return out
    except Exception as e:
        logger.warning("price_history(%s) failed: %s", symbol, e)
        return []


def price_history_batch(symbols, days: int = 120) -> dict:
    """Daily closes for many symbols in ONE request (avoids the per-ticker rate
    limiting that throttles sequential calls): {symbol: [{date, close}] ascending}.
    Symbols missing from Yahoo's response map to []. Best-effort — degrades per
    symbol and overall."""
    symbols = list(symbols)
    out: dict = {s: [] for s in symbols}
    if not symbols:
        return out
    try:
        import pandas as pd
        import yfinance as yf

        from net import retry

        period = "6mo" if days <= 130 else "1y"
        # yfinance rate-limits sequential/batch calls; retry the one batch download
        # with backoff before degrading to empty series.
        df = retry(
            lambda: yf.download(symbols, period=period, interval="1d", auto_adjust=True,
                                group_by="ticker", threads=False, progress=False),
            label=f"yf.download({len(symbols)} symbols)",
        )
        if df is None or df.empty:
            return out
        multi = isinstance(df.columns, pd.MultiIndex)
        for s in symbols:
            try:
                closes = (df[s]["Close"] if multi else df["Close"]).dropna()
            except (KeyError, TypeError):
                continue
            rows = []
            for idx, val in closes.tail(days).items():
                try:
                    rows.append({"date": idx.strftime("%Y-%m-%d"), "close": float(val)})
                except (TypeError, ValueError):
                    continue
            out[s] = rows
        return out
    except Exception as e:
        logger.warning("price_history_batch(%d symbols) failed: %s", len(symbols), e)
        return out


def fx_rates_usd(currencies) -> dict:
    """Live FX → USD rates for `currencies` in ONE batched yfinance request
    (currency pairs like 'KRWUSD=X'): {"rates": {ccy: rate}, "as_of": "YYYY-MM-DD",
    "source": "yfinance"}. USD is excluded (identity). Best-effort — degrades to
    empty rates on failure so callers fall back to the static map in
    analytics.financials (and log/footnote which source was used)."""
    ccys = sorted({str(c).upper() for c in currencies if c} - {"USD"})
    out: dict = {"rates": {}, "as_of": None, "source": "yfinance"}
    if not ccys:
        return out
    try:
        import pandas as pd
        import yfinance as yf

        from net import retry

        pairs = [f"{c}USD=X" for c in ccys]
        # Same retry treatment as the batch price path — one flaky download must
        # not silently push every non-USD company onto stale fallback rates.
        df = retry(
            lambda: yf.download(pairs, period="5d", interval="1d", auto_adjust=True,
                                group_by="ticker", threads=False, progress=False),
            label=f"yf.download({len(pairs)} fx pairs)",
        )
        if df is None or df.empty:
            return out
        multi = isinstance(df.columns, pd.MultiIndex)
        for ccy, pair in zip(ccys, pairs):
            try:
                closes = (df[pair]["Close"] if multi else df["Close"]).dropna()
            except (KeyError, TypeError):
                continue
            if closes.empty:
                continue
            try:
                out["rates"][ccy] = float(closes.iloc[-1])
                day = closes.index[-1].strftime("%Y-%m-%d")
                out["as_of"] = max(out["as_of"], day) if out["as_of"] else day
            except (TypeError, ValueError):
                continue
        return out
    except Exception as e:
        logger.warning("fx_rates_usd(%d currencies) failed: %s", len(ccys), e)
        return out
