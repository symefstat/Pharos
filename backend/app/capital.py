"""
/api/capital — the 💰 Capital & Economics read, assembled from the SAME pure
analytics the Streamlit tab uses (analytics.financials, analytics.mot_analyst,
tickers). The difference: where Streamlit called the `*_chart()` builders to get
Altair objects, here we return the underlying *data* (points / rollups / timelines)
as JSON and let the React frontend draw the charts. The numeric read is identical;
only the rendering layer moves.

Section numbers below map 1:1 to the §-comments in Home.py `render_capital()`.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import data

router = APIRouter(prefix="/api/capital", tags=["capital"])


def build_capital() -> dict:
    """Assemble the full Capital payload. Pure w.r.t. its inputs; all Supabase IO
    happens in the cached `data.*` accessors."""
    import analytics.financials as fa
    from analytics import mot_analyst as ma
    from tickers import TICKERS, ticker_coverage, ticker_for

    rows = data.rows(days=30)
    fins = data.financials()
    prices = data.prices()
    have_fin = bool(fins)

    posture = ma.capital_posture(rows)
    board = ma.capital_board(rows)

    # FX provenance for the exhibit source captions — written by financials_run
    # once database/migrations/2026-07-03_fx_asof.sql is applied; None (undated caption)
    # until then, since select("*") simply won't carry the columns.
    fx_latest = max((f for f in fins if f.get("fx_as_of")),
                    key=lambda f: str(f["fx_as_of"]), default=None)

    payload: dict = {
        "have_fin": have_fin,
        "have_prices": bool(prices),
        "row_count": len(rows),
        "fx_as_of": str(fx_latest["fx_as_of"]) if fx_latest else None,
        "fx_source": (fx_latest.get("fx_source") or None) if fx_latest else None,
        # ── §1 executive read ────────────────────────────────────────────────
        "posture": posture,
        "kpis": (
            fa.capital_kpis(rows, fins, prices, ticker_for)
            if have_fin
            else None
        ),
        "synthesis": (
            fa.capital_synthesis(rows, fins, prices, ticker_for)
            if have_fin
            else ma.interpret_capital(board)
        ),
        # ── §5 deal flow & posture (always available — news-derived) ──────────
        "board": board,
        "board_read": ma.interpret_capital(board),
        "deal_flow": fa.deal_flow_timeline(rows, weeks=8),
        "concentration": ma.capital_concentration(rows),
        # ── §7 structural shifts ──────────────────────────────────────────────
        "market_structure": ma.market_structure(rows),
        "market_structure_read": ma.interpret_market_structure(ma.market_structure(rows)),
        # ── §9 universe coverage ──────────────────────────────────────────────
        "coverage": ticker_coverage(rows),
        "tracked_tickers": len(TICKERS),
    }

    if have_fin:
        pts = fa.landscape_points(fins, ticker_for)
        payload["landscape"] = pts                                   # §2 + §4 (intensity)
        payload["sector_rollup"] = fa.sector_rollup(fins, rows, ticker_for)  # §3
        payload["market_cap_share"] = fa.market_cap_share(fins, prices, ticker_for)
        # §8 — a scorecard per company so the client deep-dive needs no round-trip.
        names = sorted({f["entity"] for f in fins if f.get("entity")})
        payload["companies"] = [
            fa.company_scorecard(n, fins, prices, rows, ticker_for) for n in names
        ]
    else:
        payload["landscape"] = []
        payload["sector_rollup"] = []
        payload["market_cap_share"] = []
        payload["companies"] = []

    # ── §6 consensus vs. reality (needs price history) ───────────────────────
    if prices:
        reactions = fa.deal_reactions(rows, prices, ticker_for, window=3)
        div = fa.consensus_divergence(reactions)
        payload["reactions"] = reactions
        payload["divergence"] = div
        payload["divergence_read"] = fa.interpret_divergence(div, threshold=2.0)
    else:
        payload["reactions"] = []
        payload["divergence"] = None
        payload["divergence_read"] = None

    return payload


@router.get("")
def capital() -> dict:
    return build_capital()
