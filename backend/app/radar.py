"""
/api/radar — horizon-scanning candidates (technologies Lodestar doesn't track yet).

Read is public (the page is part of the product story); status changes are
admin-gated. Promotion itself goes through the existing self-serve flow
(POST /api/mot/technologies) so a promoted candidate gets the same validation
and evidence floor as any tracked technology — this router only records the
verdict on the candidate row. Scanning runs inside Refresh-all or via the
'radar' action (backend/app/actions.py), never on page load.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from . import data
from .auth import require_admin
from .ratelimit import rate_limit

router = APIRouter(prefix="/api/radar", tags=["radar"])

_RADAR_RATE = rate_limit("radar", limit=30, window=60)
_STATUSES = {"new", "dismissed", "promoted"}


@router.get("")
def radar() -> dict:
    import os

    from technologies import known_domains

    from analytics.radar import (
        ENV_KEY,
        MIN_MENTIONS,
        MIN_PAPERS,
        MIN_SOURCES,
        MIN_SPREAD_DAYS,
        list_candidates,
    )

    from analytics.radar import last_scan

    sb = data._supabase()
    return {
        "candidates": list_candidates(sb),
        "scout_configured": bool(os.getenv(ENV_KEY)),
        "domains": known_domains(),
        "gate": {"mentions": MIN_MENTIONS, "sources": MIN_SOURCES,
                 "spread_days": MIN_SPREAD_DAYS, "papers": MIN_PAPERS},
        "last_scan": last_scan(sb),
    }


@router.post("/scan", dependencies=[Depends(_RADAR_RATE)])
def scan(body: dict | None = None, _admin: str = Depends(require_admin)) -> dict:
    """Start a Radar scan job — broad, or directed when a brief is given.
    Reuses the actions job registry so the page polls it like any action."""
    from .actions import _launch, _run_radar

    brief = str((body or {}).get("brief") or "").strip() or None
    if brief and len(brief) > 200:
        raise HTTPException(status_code=400, detail="brief must be at most 200 characters")
    return _launch("radar", _run_radar, brief)


@router.post("/{key}/status", dependencies=[Depends(_RADAR_RATE)])
def set_status(key: str, body: dict, username: str = Depends(require_admin)) -> dict:
    from analytics.radar import CANDIDATES_TABLE

    status = str((body or {}).get("status") or "").strip().lower()
    if status not in _STATUSES:
        raise HTTPException(status_code=400,
                            detail=f"status must be one of: {sorted(_STATUSES)}")
    sb = data._supabase()
    try:
        hit = (sb.table(CANDIDATES_TABLE)
               .update({"status": status}).eq("key", key).execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    if not hit:
        raise HTTPException(status_code=404, detail=f"radar candidate '{key}' not found")

    # Promotion puts Radar itself on the record: lock a graded detection call
    # ("still above the evidence floor in 90 days"). Idempotent via the pred id
    # stored on the candidate; fail-open — a ledger hiccup must not undo the
    # promotion the admin just made.
    pred_id = None
    if status == "promoted":
        pred_id = _lock_detection_call(sb, hit[0], username)
    # Dismissal with memory: snapshot the signal the verdict was made on, so a
    # re-scan can resurface the candidate if it clearly outgrows it.
    if status == "dismissed":
        try:
            from datetime import date

            ev = hit[0].get("evidence") or {}
            sb.table(CANDIDATES_TABLE).update({"evidence": {
                **ev,
                "dismissed_at": date.today().isoformat(),
                "dismissed_signal": (ev.get("mentions") or 0) + (ev.get("papers") or 0),
            }}).eq("key", key).execute()
        except Exception:
            pass  # the dismissal itself already succeeded
    return {"ok": True, "key": key, "status": status,
            **({"pred_id": pred_id} if pred_id else {})}


def _lock_detection_call(sb, cand: dict, username: str) -> int | None:
    from datetime import date

    import analytics.forecasts as fc
    from analytics.radar import CANDIDATES_TABLE, detection_call_fields

    ev = cand.get("evidence") or {}
    if ev.get("ledger_pred_id"):
        return ev["ledger_pred_id"]
    try:
        fields = detection_call_fields(cand["label"], cand["key"], ev,
                                       date.today().isoformat())
        fields["basis"] += f", promoted by {username}"
        res = sb.table("predictions").insert(fc._mk(**fields)).execute()
        pred_id = (res.data or [{}])[0].get("id")
        if pred_id:
            sb.table(CANDIDATES_TABLE).update(
                {"evidence": {**ev, "ledger_pred_id": pred_id}}
            ).eq("key", cand["key"]).execute()
            data.clear_cache()  # the new call must show on the Track record now
        return pred_id
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(
            "Radar detection call not locked for %s: %s", cand.get("key"), e)
        return None
