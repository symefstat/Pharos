"""
/api/analyst — commissioned Analyst reports ("analysis that will be graded").

POST commissions a report (admin-only: each run is real agent spend) as an
async job through the shared actions registry — the SPA polls the same
/api/actions/status/{jid} it already uses for Refresh all. GETs are public
reads, like the rest of the product: the report library and single reports.
The ledger hook ("log this call") ships with the frontend stage.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import data
from .actions import _finish, _launch, _log
from .auth import require_admin
from .ratelimit import rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analyst", tags=["analyst"])

_LIST_FIELDS = "id,topic,posture,coverage,as_of,created_by,created_at,ledger_pred_id"


class CommissionBody(BaseModel):
    topic: str


def _run_analyst(jid: str, topic: str, username: str) -> None:
    """Background runner: gather → agent → validate → store, with live steps."""
    try:
        from analytics.analyst import run_analysis

        _log(jid, f"Commissioned: “{topic}”")
        _log(jid, "Sweeping feeds, stages, forecasts, capital & funding…")
        stored = run_analysis(data._supabase(), topic, username)
        _log(jid, f"✓ Report stored (id={stored.get('id')}, coverage={stored.get('coverage')})")
        _finish(jid)
    except Exception as e:
        logger.exception("Analyst run failed")
        _log(jid, f"✗ {e}", ok=False)
        _finish(jid, str(e))


@router.post("", dependencies=[Depends(rate_limit("analyst", limit=4, window=3600))])
def commission(body: CommissionBody, username: str = Depends(require_admin)) -> dict:
    topic = (body.topic or "").strip()
    if not 3 <= len(topic) <= 200:
        raise HTTPException(status_code=400, detail="topic must be 3–200 characters")
    return _launch("analyst", _run_analyst, topic, username)


@router.get("")
def list_reports(limit: int = 25) -> dict:
    from analytics.analyst import REPORTS_TABLE

    try:
        rows = (data._supabase().table(REPORTS_TABLE).select(_LIST_FIELDS)
                .order("created_at", desc=True).limit(min(max(limit, 1), 100))
                .execute().data or [])
    except Exception as e:
        logger.warning("Analyst list unavailable (%s) — apply "
                       "'database/schema/analyst_reports.sql'.", e)
        rows = []
    return {"reports": rows}


class FollowupBody(BaseModel):
    question: str
    history: list[dict] = []


# Public like Ask (interrogating a public report builds trust), with the same
# per-IP budget discipline — each turn is one real Analyst-agent call.
@router.post("/{report_id}/ask",
             dependencies=[Depends(rate_limit("analyst_ask", limit=10, window=60))])
def followup(report_id: int, body: FollowupBody) -> dict:
    question = (body.question or "").strip()
    if not 3 <= len(question) <= 500:
        raise HTTPException(status_code=400, detail="question must be 3–500 characters")
    try:
        from analytics.analyst import answer_followup

        return answer_followup(data._supabase(), report_id, question,
                               history=body.history[-6:])
    except LookupError:
        raise HTTPException(status_code=404, detail=f"no report {report_id}")
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{report_id}/log-call",
             dependencies=[Depends(rate_limit("analyst_log", limit=10, window=3600))])
def log_call(report_id: int, username: str = Depends(require_admin)) -> dict:
    """Lock the report's central call into the forecast ledger — the analysis
    goes on the record and gets graded like every other manual (world-graded)
    call. Idempotent: a report logs at most one prediction."""
    from datetime import date

    import analytics.forecasts as fc
    from analytics.analyst import REPORTS_TABLE

    sb = data._supabase()
    rows = (sb.table(REPORTS_TABLE).select("*").eq("id", report_id)
            .limit(1).execute().data or [])
    if not rows:
        raise HTTPException(status_code=404, detail=f"no report {report_id}")
    report = rows[0]
    if report.get("ledger_pred_id"):
        return {"pred_id": report["ledger_pred_id"], "already_logged": True}

    p = report.get("posture") or {}
    required = ("posture", "addressee", "confidence", "falsifier", "resolve_by")
    if not all(p.get(k) for k in required):
        raise HTTPException(status_code=422, detail="report has no complete posture block")

    today = date.today()
    resolve_days = max((date.fromisoformat(p["resolve_by"]) - today).days, 7)
    row = fc._mk(
        kind="manual",
        subject=f"analyst:{report_id}",
        claim=(f"Analyst call — {report['topic']}: '{p['posture']}' posture holds for "
               f"{p['addressee']} — wrong if: {p['falsifier']}"),
        horizon="short" if resolve_days <= 120 else "long",
        confidence=float(p["confidence"]),
        basis=f"analyst report {report_id} ({report.get('as_of')}), logged by {username}",
        params={"falsifier": p["falsifier"], "analyst_report_id": report_id},
        as_of=today.isoformat(),
        fp_basis=f"analyst|{report_id}|{p['falsifier']}",
        source="analyst",
        resolve_days=resolve_days,
    )
    res = sb.table("predictions").insert(row).execute()
    pred_id = (res.data or [{}])[0].get("id")
    sb.table(REPORTS_TABLE).update({"ledger_pred_id": pred_id}).eq("id", report_id).execute()
    # The predictions read is TTL-cached — clear so the new call shows on the
    # Track record immediately, not after the cache expires.
    data.clear_cache()
    logger.info("Analyst report %s logged to ledger as prediction %s by %s",
                report_id, pred_id, username)
    return {"pred_id": pred_id, "already_logged": False}


@router.get("/{report_id}")
def get_report(report_id: int) -> dict:
    from analytics.analyst import REPORTS_TABLE

    try:
        rows = (data._supabase().table(REPORTS_TABLE).select("*")
                .eq("id", report_id).limit(1).execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"analyst reports unavailable: {e}")
    if not rows:
        raise HTTPException(status_code=404, detail=f"no report {report_id}")
    return rows[0]
