"""
L6 live spot-check judge (READ-ONLY, network: yfinance only).

For each proposed ticker it:
  1. fetches fundamentals via the repo's own `finance.client.fundamentals` (the
     exact production path, including `_first` column selection),
  2. re-derives WHICH fiscal-statement column `_first` picked per field (to test
     the period-misalignment bug on real data),
  3. replicates the app's USD normalisation + rd_intensity exactly as
     `financials_run.py:54-68` does (to_usd via the static _FX_TO_USD map),
  4. dumps the raw statement columns / non-null map so mixing is visible.

Also verifies the event-study strictly-before baseline on one real ticker/date
(pass `--event SYMBOL:YYYY-MM-DD`; prices come from the production
`price_history_batch` path).

No Supabase, no writes, no Toqan. Output: JSON to stdout.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from finance.client import fundamentals, price_history_batch  # noqa: E402
from analytics.financials import (  # noqa: E402
    _FX_TO_USD,
    event_reaction,
    market_cap_usd as to_usd,
    rd_intensity,
)

TICKERS = ["MSFT", "TM", "005930.KS", "ASML", "NVDA"]

# Row-label candidates copied verbatim from finance/client.py:50-58 so the
# period re-derivation matches what production actually selected.
FIELD_ROWS = {
    "revenue": ("income", ("Total Revenue", "TotalRevenue", "Operating Revenue")),
    "rd_expense": ("income", ("Research And Development", "Research Development")),
    "capex": ("flow", ("Capital Expenditure", "Capital Expenditures")),
    "cash": ("balance", ("Cash And Cash Equivalents",
                         "Cash Cash Equivalents And Short Term Investments",
                         "Cash And Short Term Investments")),
}


def _pick(df, row_names):
    """Replicate finance.client._first but also return the column (period) used."""
    if df is None or getattr(df, "empty", True):
        return None, None, None
    for name in row_names:
        if name in df.index:
            series = df.loc[name].dropna()
            if not series.empty:
                try:
                    return float(series.iloc[0]), str(series.index[0])[:10], name
                except (TypeError, ValueError):
                    return None, None, name
    return None, None, None


def _nonnull_map(df, row_names):
    """For visibility: which statement columns have data for these row labels."""
    if df is None or getattr(df, "empty", True):
        return None
    for name in row_names:
        if name in df.index:
            row = df.loc[name]
            return {str(c)[:10]: (None if v != v or v is None else float(v))
                    for c, v in row.items()}
    return None


def check_ticker(sym: str) -> dict:
    import yfinance as yf

    fin = fundamentals(sym)  # the production code path
    t = yf.Ticker(sym)
    stmts = {"income": t.income_stmt, "balance": t.balance_sheet, "flow": t.cashflow}

    fields = {}
    for field, (stmt, rows) in FIELD_ROWS.items():
        val, period, label = _pick(stmts[stmt], rows)
        fields[field] = {"raw_value": val, "period": period, "row_label": label,
                         "nonnull_columns": _nonnull_map(stmts[stmt], rows)}

    # Period-mixing check: does R&D (or capex) come from a different fiscal
    # column than revenue?
    rev_p = fields["revenue"]["period"]
    mixing = {
        f: {"field_period": fields[f]["period"], "revenue_period": rev_p,
            "mixed": bool(fields[f]["period"] and rev_p and fields[f]["period"] != rev_p)}
        for f in ("rd_expense", "capex")
    }

    out = {"symbol": sym, "fundamentals_production": fin, "field_periods": fields,
           "period_mixing": mixing}

    # Replicate the app pipeline (financials_run.py:57-68) — USD at write time.
    if fin:
        fc = fin.get("financial_currency") or fin.get("currency")
        rev_usd = to_usd(fin.get("revenue"), fc)
        rd_usd = to_usd(fin.get("rd_expense"), fc)
        out["app_pipeline"] = {
            "listing_currency": fin.get("currency"),
            "financial_currency": fin.get("financial_currency"),
            "static_fx_used": {"listing": _FX_TO_USD.get((fin.get("currency") or "USD").upper()),
                               "reporting": _FX_TO_USD.get((fc or "USD").upper())},
            "market_cap_usd": to_usd(fin.get("market_cap"), fin.get("currency")),
            "revenue_usd": rev_usd,
            "rd_expense_usd": rd_usd,
            "rd_intensity": rd_intensity(rev_usd, rd_usd),
            "rd_intensity_raw": rd_intensity(fin.get("revenue"), fin.get("rd_expense")),
        }
    return out


def check_event(spec: str) -> dict:
    """spec = 'SYMBOL:YYYY-MM-DD'. Uses the production batch-price path and
    analytics.financials.event_reaction; verifies base_date < event_date and that
    no trading day in the series lies between base_date and event_date."""
    sym, ev = spec.split(":")
    prices = price_history_batch([sym], days=120).get(sym, [])
    r = event_reaction(ev, prices, window=3)
    verdict = None
    if r:
        dates = sorted(p["date"] for p in prices)
        strictly_before = r["base_date"] < ev
        gap = [d for d in dates if r["base_date"] < d < ev]  # must be empty: LAST close before
        verdict = {"strictly_before": strictly_before, "is_last_close_before_event": not gap,
                   "closes_skipped_between": gap}
    return {"symbol": sym, "event_date": ev, "n_prices": len(prices),
            "first_price_date": prices[0]["date"] if prices else None,
            "last_price_date": prices[-1]["date"] if prices else None,
            "reaction": r, "baseline_verdict": verdict}


def main() -> None:
    event_spec = None
    for a in sys.argv[1:]:
        if a.startswith("--event="):
            event_spec = a.split("=", 1)[1]

    report = {"tickers": {}, "fx_static_map": _FX_TO_USD}
    for sym in TICKERS:
        try:
            report["tickers"][sym] = check_ticker(sym)
        except Exception as e:  # keep going — per-ticker degradation like prod
            report["tickers"][sym] = {"symbol": sym, "error": repr(e)}
    if event_spec:
        try:
            report["event_study"] = check_event(event_spec)
        except Exception as e:
            report["event_study"] = {"error": repr(e)}
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
