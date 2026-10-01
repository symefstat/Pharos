#!/usr/bin/env python3
"""
Forecast ledger job — generate falsifiable predictions, then resolve due ones
objectively against our own data.

GENERATE: quant leading-indicator forecasts (stage advances, capital-posture
persistence, deal-flow continuation) + a capture of the latest Strategist signals
(manual-resolved). Idempotent — an open forecast for the same (kind, subject) is
never duplicated, and each Strategist signal is captured once.

RESOLVE: for each open forecast, check its criterion against the data. Auto kinds
resolve to hit as soon as satisfied, or to miss once past resolve_by. Strategist
(manual) forecasts are left for human grading in the 🔮 tab.

No agent calls — generation reads the *cached* Strategist brief, it doesn't run
the agent. Safe for cron; run after analytics_run.py + financials_run.py. Apply
`SQL Tables/predictions.sql` first.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

from config import Config
from db import get_supabase
from home_news.writer import _is_missing_column_error
import analytics.forecasts as fc

logger = logging.getLogger("forecast_run")


def _load_context(sb):
    """Everything the generators + resolvers read: placements, sector rollup,
    recent rows, price series, ticker map, and the latest cached Strategist brief."""
    from analytics.aggregator import PulseAggregator
    from analytics.tech_layer import TechAnalyst
    from analytics import financials as fa
    from tickers import ticker_for, TICKERS

    rows = PulseAggregator(sb).all_recent(days=45)
    placements = TechAnalyst(sb).current_placements(days=30)
    fins = sb.table("company_financials").select("*").execute().data or []
    rollup = fa.sector_rollup(fins, rows, ticker_for)

    prices: dict = {}
    start = 0
    while True:
        chunk = (sb.table("stock_prices").select("symbol,day,close")
                 .order("symbol").order("day").range(start, start + 999).execute().data or [])
        for r in chunk:
            prices.setdefault(r["symbol"], []).append({"date": r["day"], "close": r["close"]})
        if len(chunk) < 1000:
            break
        start += 1000
    symbol_entity = {t.symbol: t.entity for t in TICKERS}

    brief_rows = (sb.table("strategist_briefs").select("as_of,strategic_read")
                  .eq("focus", "daily").order("as_of", desc=True).limit(1).execute().data or [])
    brief = brief_rows[0] if brief_rows else {}
    return rows, placements, rollup, prices, symbol_entity, brief, ticker_for


def build_candidates(rows, placements, rollup, prices, symbol_entity, brief,
                     ticker_for, as_of) -> list[dict]:
    """Assemble every generator's candidates from the loaded context (pure — no
    client, unit-testable). The deal-flow / reactivity thresholds are recalibrated
    per sector from the trailing windows already present in `rows` (targeting a
    ~60% base rate so Brier skill is measurable) and LOCKED into each new
    forecast's params/claim, with a `threshold_basis` audit note — existing ledger
    rows are never touched."""
    from analytics import financials as fa

    deal_counts = fc.sector_deal_counts(rows, ticker_for)
    earliest = fc.earliest_published(rows)
    df_cal = fc.deal_flow_calibration(fc.sector_deal_dates(rows, ticker_for),
                                      as_of, earliest)
    rx_moves = fc.sector_reaction_moves(fa.deal_reactions(rows, prices, ticker_for),
                                        ticker_for)
    for sector in deal_counts:      # sectors with deals but no priced reaction still
        rx_moves.setdefault(sector, [])   # get a calibrated (floored) threshold
    rx_cal = fc.reactivity_calibration(rx_moves, as_of, earliest)

    return (
        fc.gen_stage_advance(placements, as_of)
        + fc.gen_stage_advance_tech(placements, as_of)
        + fc.gen_posture_persist(rollup, as_of)
        + fc.gen_deal_flow(deal_counts, as_of, calibration=df_cal)
        + fc.gen_reactivity(deal_counts, as_of, calibration=rx_cal)
        + fc.gen_price_move(prices, symbol_entity, as_of)
        + fc.gen_from_strategist(brief, as_of)
    )


def select_new(candidates, existing) -> list[dict]:
    """Recalibrate candidate confidence toward each kind's realized record, then
    drop anything already in the ledger: same fingerprint, or an open quant
    forecast for the same (kind, subject). Pure — the insert-side idempotency."""
    # Close the learning loop: recalibrate the new forecasts' confidence toward each
    # generator's realized track record before logging them (generation-time only —
    # locked forecasts are never edited).
    candidates = fc.apply_calibration(candidates, fc.realized_rates(existing))

    seen_fp = {p["fingerprint"] for p in existing}
    open_keys = {(p["kind"], p["subject"]) for p in existing if p["status"] == "open"}
    # Strategist judgment calls are exempt from the (kind, subject) block — several
    # distinct calls about one subject are legitimate — so paraphrased re-emissions
    # of the SAME call (reworded claim/falsifier, new fingerprint) need their own
    # guard: near-duplicate claim text against every open call.
    open_claims = [p["claim"] for p in existing
                   if p["status"] == "open" and p.get("claim")]

    to_insert = []
    for c in candidates:
        if c["fingerprint"] in seen_fp:
            continue
        if c["source"] != "strategist" and (c["kind"], c["subject"]) in open_keys:
            continue  # don't open a second forecast for the same quant claim
        if any(fc.claims_similar(c["claim"], prev) for prev in open_claims):
            continue  # paraphrase of an already-open call — would double-count
        to_insert.append(c)
        seen_fp.add(c["fingerprint"])
        open_keys.add((c["kind"], c["subject"]))
        open_claims.append(c["claim"])
    return to_insert


def generate(sb, as_of: str) -> int:
    rows, placements, rollup, prices, symbol_entity, brief, ticker_for = _load_context(sb)
    candidates = build_candidates(rows, placements, rollup, prices, symbol_entity,
                                  brief, ticker_for, as_of)

    existing = (sb.table("predictions")
                .select("fingerprint,kind,subject,status,outcome,claim").execute().data or [])
    to_insert = select_new(candidates, existing)

    if to_insert:
        sb.table("predictions").insert(to_insert).execute()
    logger.info("Generated %d new forecast(s) (%d candidates).", len(to_insert), len(candidates))
    return len(to_insert)


def resolve(sb, as_of: str) -> int:
    from analytics import financials as fa

    rows, _placements, rollup, prices, _se, _brief, ticker_for = _load_context(sb)
    open_preds = (sb.table("predictions").select("*").eq("status", "open").execute().data or [])
    if not open_preds:
        logger.info("No open forecasts to resolve.")
        return 0

    # context for resolvers
    tilt_now = {}
    for r in rollup:
        c, o = r.get("commitment", 0), r.get("option", 0)
        tilt_now[r["sector"]] = "commitment" if c > o else "option" if o > c else None

    # measured reactions for reactivity resolution (per sector, since each made_on)
    all_reactions = fa.deal_reactions(rows, prices, ticker_for)

    # Both counters are bounded to the claim's own window: strictly after made_on
    # AND no later than resolve_by (H9). Without the upper bound, a stalled cron
    # resolving late could bank a HIT on an overdue forecast from events that
    # happened after the window the claim text promised.
    def sector_move_pcts(sector, made_on, resolve_by):
        out = []
        for rx in all_reactions:
            tk = ticker_for(rx.get("company") or "")
            # Filter on the deal's EVENT date (published_at), strictly after made_on — a
            # deal predates/coincides with the forecast isn't it "coming true". Must NOT use
            # base_date: that's the pre-event baseline (day before the deal) since the 3.2
            # event-study fix, so it would wrongly drop a deal published the next day.
            ev = str(rx.get("event_date") or "")[:10]
            if tk and tk.sector == sector and made_on < ev <= resolve_by:
                out.append(rx.get("pct"))
        return out
    deal_since = {}  # (sector, made_on, resolve_by) → material deals inside the window
    from analytics.mot_analyst import _is_capital_row

    def deals_since(sector, made_on, resolve_by):
        key = (sector, made_on, resolve_by)
        if key not in deal_since:
            n = 0
            for r in rows:
                if str(r.get("business_impact") or "").lower() != "material" or not _is_capital_row(r):
                    continue
                pub = str(r.get("published_at") or "")[:10]
                if not (made_on < pub <= resolve_by):  # inside the claim's window only
                    continue
                secs = {tk.sector for comp in (r.get("companies") or []) if (tk := ticker_for(str(comp)))}
                if sector in secs:
                    n += 1
            deal_since[key] = n
        return deal_since[key]

    # stage history for the techs we have open stage forecasts on. Full rows ("*"):
    # stage_advance reads adoption_stage; stage_advance_tech reads maturity_stage +
    # maturity_mixed (the contested flag — a column the confidence migration adds,
    # so selecting "*" also degrades gracefully when it is pending).
    sa_subjects = {p["subject"] for p in open_preds
                   if p["kind"] in ("stage_advance", "stage_advance_tech", "radar_detection")}
    history = []
    if sa_subjects:
        history = (sb.table("technology_stage_history").select("*")
                   .in_("technology", list(sa_subjects)).execute().data or [])

    resolved = 0
    for p in open_preds:
        # A forecast must test the FUTURE: don't resolve an auto forecast — HIT *or*
        # MISS — in its first MIN_RESOLVE_DAYS. This kills both the day-0 "confirm the
        # present" hit and a same-day flip-miss from data drift between generate() and
        # resolve(). The overdue→miss backstop only fires past resolve_by (90d+), well
        # clear of this window. (Manual/Strategist calls are graded by hand in the UI.)
        if p["kind"] != "manual" and fc.elapsed_days(p, as_of) < fc.MIN_RESOLVE_DAYS:
            continue
        # Compute each resolver's input once, so the same value feeds both the verdict
        # and the persisted evidence snapshot (reproducibility — see resolution_evidence).
        res, ev_kwargs = None, {}
        if p["kind"] == "stage_advance":
            res = fc.resolve_stage_advance(p, history)
            ev_kwargs = {"history": history}
        elif p["kind"] == "stage_advance_tech":
            res = fc.resolve_stage_advance_tech(p, history)
            ev_kwargs = {"history": history}
        elif p["kind"] == "radar_detection":
            res = fc.resolve_radar_detection(p, history, as_of)
            ev_kwargs = {"history": history}
        elif p["kind"] == "posture_persist":
            tilt = tilt_now.get(p["subject"])
            res = fc.resolve_posture_persist(p, tilt, as_of)
            ev_kwargs = {"tilt": tilt}
        elif p["kind"] == "deal_flow":
            n = deals_since(p["subject"], p["made_on"], str(p.get("resolve_by") or "9999-12-31"))
            res = fc.resolve_deal_flow(p, n)
            ev_kwargs = {"deals": n}
        elif p["kind"] == "reactivity":
            moves = sector_move_pcts(p["subject"], p["made_on"],
                                     str(p.get("resolve_by") or "9999-12-31"))
            res = fc.resolve_reactivity(p, moves)
            ev_kwargs = {"moves": moves}
        elif p["kind"] == "price_move":
            series = prices.get(p["subject"])
            res = fc.resolve_price_move(p, series)
            ev_kwargs = {"series": series}
        if res is None and p["kind"] != "manual" and fc.is_overdue(p, as_of):
            res = ("miss", "criterion unmet by resolve-by date")
        if res is None:
            continue
        outcome, note = res
        update = {
            "status": "resolved", "outcome": outcome,
            "resolved_on": as_of, "resolution_note": note,
            "resolution_evidence": fc.resolution_evidence(p, **ev_kwargs),
        }
        try:
            sb.table("predictions").update(update).eq("id", p["id"]).execute()
        except Exception as e:
            if not _is_missing_column_error(e, "resolution_evidence"):
                raise
            logger.warning("predictions has no resolution_evidence column yet — resolving "
                           "without the snapshot. Apply SQL Tables/predictions_evidence_column.sql.")
            update.pop("resolution_evidence", None)
            sb.table("predictions").update(update).eq("id", p["id"]).execute()
        resolved += 1

    logger.info("Resolved %d forecast(s) of %d open.", resolved, len(open_preds))
    return resolved


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_dotenv()
    try:
        Config.validate()
    except ValueError as e:
        logger.error("%s — set them in .env before running.", e)
        return 1
    sb = get_supabase()
    as_of = datetime.now(timezone.utc).date().isoformat()
    try:
        generate(sb, as_of)
        resolve(sb, as_of)
    except Exception as e:
        logger.error("Forecast run failed: %s", e)
        return 1
    # Anchor today's ledger digest AFTER resolution so the append-only chain
    # (SQL Tables/ledger_digests.sql) records the day's final state. Non-fatal:
    # the run's forecasts are already locked either way.
    try:
        from backend.app.ledger import anchor_digest

        rec = anchor_digest(sb, as_of=as_of)
        logger.info("Ledger digest anchored for %s (%s rows): %s…",
                    as_of, rec.get("row_count"), str(rec.get("digest"))[:16])
    except Exception as e:
        logger.warning("Digest anchoring failed (non-fatal): %s — if the table is "
                       "missing, apply SQL Tables/ledger_digests.sql.", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
