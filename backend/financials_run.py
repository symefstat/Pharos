#!/usr/bin/env python3
"""
Enrich tracked companies with free financial data (yfinance) into Supabase.

Writes a fundamentals snapshot to `company_financials` and ~4 months of daily
closes to `stock_prices` for every company in `tickers.py`. These power the
💰 Capital tab's R&D-intensity (E1) and event-reaction reads. No API key /
subscription needed.

Degrades per-ticker — one symbol failing never aborts the run, and the tab works
with whatever made it in. Safe for cron; run after analytics_run.py. Apply
`database/schema/company_financials.sql` and `database/schema/stock_prices.sql` first.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

from config import Config
from db import get_supabase, is_missing_column_error
from tickers import TICKERS
from finance.client import fundamentals, fx_rates_usd, price_history_batch
from analytics.financials import FX_AS_OF, rd_intensity, market_cap_usd as to_usd

logger = logging.getLogger("financials_run")

_PRICE_DAYS = 120
_CHUNK = 500

# Optional company_financials columns (database/migrations/2026-07-03_fx_asof.sql). Until
# the user applies the migration, upserts degrade by stripping these and retrying
# — same treatment as the feed tables' provenance column (home_news/writer.py).
_FX_MIGRATION = "database/migrations/2026-07-03_fx_asof.sql"
_OPTIONAL_FIN_COLS = ("fx_source", "fx_as_of", "rd_basis")


def _fx_provenance(fx: dict, ccys: set) -> tuple[str | None, str | None]:
    """(fx_source, fx_as_of) to stamp on this run's company_financials rows, so
    the Capital tab can caption which rates produced the stored USD figures.
    Live fetch → ('yfinance', <last close date>); fetch failed but non-USD
    currencies are in play → ('static-fallback', FX_AS_OF) — the dated map in
    analytics.financials that market_cap_usd falls back to; all-USD universe →
    (None, None), no FX was involved. Pure."""
    if fx.get("rates"):
        return fx.get("source") or "yfinance", fx.get("as_of")
    if ccys - {"USD"}:
        return "static-fallback", FX_AS_OF
    return None, None


def _upsert(sb, table: str, rows: list[dict], on_conflict: str,
            optional_cols: tuple[str, ...] = ()) -> int:
    """Guarded upsert: rows written on success, 0 on failure (a failed chunk or
    the fundamentals write never aborts the run — partial success persists).

    If the write failed ONLY because one of `optional_cols` isn't in the table yet
    (the migration is pending), strip those columns and retry so the base row
    still lands — mirroring how home_news/writer.py degrades the provenance
    column. The warning names the migration file to apply."""
    from net import retry

    try:
        try:
            retry(lambda: sb.table(table).upsert(rows, on_conflict=on_conflict).execute(),
                  label=f"{table} upsert ({len(rows)} rows)")
        except Exception as e:
            if not any(is_missing_column_error(e, c) for c in optional_cols):
                raise
            logger.warning("%s is missing one of the optional columns %s — upserting "
                           "without them. Apply %s to persist FX provenance / R&D basis.",
                           table, optional_cols, _FX_MIGRATION)
            slim = [{k: v for k, v in r.items() if k not in optional_cols} for r in rows]
            retry(lambda: sb.table(table).upsert(slim, on_conflict=on_conflict).execute(),
                  label=f"{table} upsert ({len(slim)} rows, degraded)")
        return len(rows)
    except Exception as e:
        logger.warning("%s upsert failed for %d rows (skipped): %s", table, len(rows), e)
        return 0


def run(sb) -> dict:
    """Enrich every ticker in `tickers.py` → `company_financials` + `stock_prices`.
    Takes an injected Supabase client so the app can reuse its cached one. Degrades
    per-ticker (one symbol failing never aborts). Free yfinance — no API key. Returns
    counts for surfacing in the UI / logs."""
    as_of = datetime.now(timezone.utc).date().isoformat()
    fund_rows: list[dict] = []
    price_rows: list[dict] = []
    ok_fund = ok_price = 0

    # Prices in ONE batched request — sequential per-ticker calls get rate-limited.
    prices = price_history_batch([t.symbol for t in TICKERS], days=_PRICE_DAYS)

    # Fetch all fundamentals first so ONE batched FX request can cover every
    # listing/reporting currency actually seen this run (live rates at write time;
    # the static map in analytics.financials is only the flagged fallback).
    funds = {t.symbol: fundamentals(t.symbol) for t in TICKERS}
    ccys = {c for f in funds.values() if f
            for c in (f.get("currency"), f.get("financial_currency")) if c}
    fx = fx_rates_usd(ccys)
    if fx["rates"]:
        logger.info("FX source: %s as of %s — %s", fx["source"], fx["as_of"],
                    ", ".join(f"{c}={r:.6g}" for c, r in sorted(fx["rates"].items())))
    elif ccys - {"USD"}:
        logger.warning("Live FX fetch returned nothing — non-USD figures will use the "
                       "static fallback map (as of %s; may be stale).", FX_AS_OF)
    fx_source, fx_as_of = _fx_provenance(fx, ccys)

    for t in TICKERS:
        fin = funds[t.symbol]
        if fin:
            # Normalise everything to USD at write-time: market cap by the listing
            # currency, revenue/R&D/capex/cash by the reporting currency. The DB
            # then holds consistent USD, so the multiple (cap/revenue) is correct.
            fc_ccy = fin.get("financial_currency") or fin.get("currency")
            mc = to_usd(fin.get("market_cap"), fin.get("currency"), rates=fx["rates"])
            rev = to_usd(fin.get("revenue"), fc_ccy, rates=fx["rates"])
            rd = to_usd(fin.get("rd_expense"), fc_ccy, rates=fx["rates"])
            fund_rows.append({
                "entity": t.entity,
                "symbol": t.symbol,
                "currency": "USD",
                "market_cap": mc,
                "revenue": rev,
                "rd_expense": rd,
                "rd_intensity": rd_intensity(rev, rd),
                "capex": to_usd(fin.get("capex"), fc_ccy, rates=fx["rates"]),
                "cash": to_usd(fin.get("cash"), fc_ccy, rates=fx["rates"]),
                "as_of": as_of,
                # FX provenance + curated-R&D basis — optional columns, see
                # _OPTIONAL_FIN_COLS; stripped on upsert until the migration runs.
                "fx_source": fx_source,
                "fx_as_of": fx_as_of,
                "rd_basis": fin.get("rd_basis"),
            })
            ok_fund += 1

        hist = prices.get(t.symbol, [])
        for p in hist:
            price_rows.append({"symbol": t.symbol, "day": p["date"], "close": p["close"]})
        if hist:
            ok_price += 1

        logger.info("%-12s fundamentals=%s prices=%d",
                    t.symbol, "ok" if fin else "—", len(hist))

    written_fund = (_upsert(sb, "company_financials", fund_rows, "entity",
                            optional_cols=_OPTIONAL_FIN_COLS) if fund_rows else 0)
    written_prices = 0
    for i in range(0, len(price_rows), _CHUNK):
        written_prices += _upsert(sb, "stock_prices", price_rows[i:i + _CHUNK], "symbol,day")

    return {"fundamentals": ok_fund, "prices": ok_price,
            "tickers": len(TICKERS), "price_rows": len(price_rows),
            "fundamentals_written": written_fund, "price_rows_written": written_prices}


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_dotenv()
    try:
        Config.validate()
    except ValueError as e:
        logger.error("%s — set them in .env before running.", e)
        return 1

    res = run(get_supabase())
    logger.info(
        "Done: %d/%d fundamentals, %d/%d price series (%d price rows) written.",
        res["fundamentals"], res["tickers"], res["prices"], res["tickers"], res["price_rows"],
    )
    if res["fundamentals"] == 0 and res["prices"] == 0:
        logger.warning("Nothing fetched — yfinance may be unreachable or rate-limited.")
        return 1
    # Fetched data but every upsert failed → nothing persisted: surface it (red run)
    # rather than exit green, since the per-upsert guards swallow individual failures.
    if res["fundamentals_written"] == 0 and res["price_rows_written"] == 0:
        logger.error("Fetched data but every upsert failed — nothing persisted to Supabase.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
