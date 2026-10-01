"""
/api/forecasts — the 🔮 Forecasts read (the accountable track record), assembled
from analytics.forecasts. Mirrors Home.py render_forecasts() + render_calibration_banner().
The calibration scatter is returned as data (bins) and redrawn in React.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import data
from .auth import require_admin

router = APIRouter(prefix="/api/forecasts", tags=["forecasts"])


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def build_forecasts() -> dict:
    import analytics.forecasts as fc

    preds = data.predictions()
    today = _today_iso()

    tr = fc.track_record(preds)
    resolved = [p for p in preds if p.get("status") == "resolved"]
    open_preds = [p for p in preds if p.get("status") == "open"]

    # Forward view — the 3 highest-confidence open calls.
    hero = sorted(open_preds, key=lambda p: p.get("confidence") or 0, reverse=True)[:3]
    hero_out = [
        {
            "claim": h.get("claim"),
            "confidence": h.get("confidence"),
            "category": fc.category_of(h.get("kind") or ""),
            "resolve_by": h.get("resolve_by"),
            "horizon": h.get("horizon"),
        }
        for h in hero
    ]

    # Overdue manual calls that need grading (the only user-resolvable kind).
    overdue = [
        {
            "id": p.get("id"),
            "claim": p.get("claim"),
            "confidence": p.get("confidence"),
            "category": fc.category_of(p.get("kind") or ""),
            "resolve_by": p.get("resolve_by"),
        }
        for p in open_preds
        if p.get("kind") == "manual" and fc.is_overdue(p, today)
    ]

    # Resolved receipts — most-recent 60.
    resolved_sorted = sorted(
        resolved, key=lambda p: p.get("resolved_on") or "", reverse=True
    )[:60]
    resolved_out = [
        {
            "id": p.get("id"),
            "claim": p.get("claim"),
            "outcome": p.get("outcome"),
            "made_on": p.get("made_on"),
            "resolved_on": p.get("resolved_on"),
            "resolution_note": p.get("resolution_note"),
            "confidence": p.get("confidence"),
            "category": fc.category_of(p.get("kind") or ""),
        }
        for p in resolved_sorted
    ]

    # NOTE: no `headline`/`tagline`/`state` here — those duplicate the Briefing
    # calibration banner (`/api/briefing`); this page derives its scorecard from
    # `track_record`/`calibration_verdict` directly (see backend/eval/reports/10_app_parity.md §2.11).
    # `track_record` / `categories` carry the naive-baseline fields (base_rate,
    # baseline_accuracy, baseline_brier, brier_skill, accuracy_edge_pp) — merged in
    # by analytics.forecasts.track_record and passed through here verbatim.
    return {
        "summary": fc.forecast_summary(preds, tr),
        "track_record": tr,
        # External (world-graded, citable) vs internal (self-referential,
        # consistency-only) split — the external record headlines (2.2).
        "records_by_basis": fc.records_by_basis(preds),
        "categories": fc.track_record_by_category(preds),
        "calibration_bins": fc.calibration_bins(resolved),
        "calibration_verdict": fc.calibration_verdict(tr),
        "open_table": fc.open_forecast_table(open_preds),
        "hero": hero_out,
        "overdue": overdue,
        "resolved": resolved_out,
    }


@router.get("")
def forecasts() -> dict:
    return build_forecasts()


@router.get("/falsifier-events")
def falsifier_events() -> dict:
    """Recent candidate falsifier evidence (falsifier_run.py), each joined with
    the claim of the open forecast it may disprove. Public read — the whole
    point of the falsifier loop is showing our exposure in the open. Candidates
    only: nothing here has resolved a forecast (grading stays human via
    POST /resolve). Empty when the falsifier_events table isn't set up."""
    events = data.falsifier_events()
    claims = {p.get("id"): p.get("claim") for p in data.predictions()}
    out = [
        {
            "id": e.get("id"),
            "pred_id": e.get("pred_id"),
            "claim": claims.get(e.get("pred_id")),
            "falsifier": e.get("falsifier"),
            "article_title": e.get("article_title"),
            "article_url": e.get("article_url"),
            "published_at": e.get("published_at"),
            "score": e.get("score"),
            "detected_at": e.get("detected_at"),
        }
        for e in events
    ]
    return {"events": out, "count": len(out)}


class ResolveBody(BaseModel):
    pred_id: int
    outcome: str  # "hit" | "miss" | "partial"


@router.post("/resolve", dependencies=[Depends(require_admin)])
def resolve(body: ResolveBody) -> dict:
    """Manually grade an overdue Strategist call (Home.py `_resolve_manual`).

    Admin-only: a graded outcome is immutable, so an open write here would let
    anyone permanently corrupt the public track record.

    Guarded (locked-outcome discipline): only a still-open, judgment-kind
    ('manual') forecast may be graded via this endpoint. Auto kinds resolve
    objectively in the resolver job, and a resolved outcome is immutable —
    both are rejected with a 4xx (analytics.forecasts.manual_resolution_error)."""
    import analytics.forecasts as fc

    if body.outcome not in ("hit", "miss", "partial"):
        raise HTTPException(status_code=400, detail="outcome must be hit | miss | partial")
    try:
        from db import get_supabase

        sb = get_supabase()
        rows = (
            sb.table("predictions")
            .select("id, kind, status")
            .eq("id", body.pred_id)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if not rows:
        raise HTTPException(status_code=404, detail=f"forecast {body.pred_id} not found")
    err = fc.manual_resolution_error(rows[0], body.outcome)
    if err:
        raise HTTPException(status_code=409, detail=err)

    try:
        # `.eq("status", "open")` re-checks the guard at write time (read/write race).
        sb.table("predictions").update(
            {
                "status": "resolved",
                "outcome": body.outcome,
                "resolved_on": _today_iso(),
                "resolution_note": "manually graded",
            }
        ).eq("id", body.pred_id).eq("status", "open").execute()
        data.clear_cache()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
