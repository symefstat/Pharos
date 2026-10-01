"""
/api/theses — the investor's PRIVATE thesis book ("thesis maintenance").

Every endpoint is admin-gated — unlike the public falsifier watch, a thesis is
the investor's own position, not a published claim, so even reads are private.
Theses live in their own `theses` table (never `predictions`): they must not
contaminate the public ledger, the track record, or the calibration stats.
Writes follow the watchlist.py pattern: admin-gated, rate-limited, length-
validated. DELETE is a soft archive — evidence events are kept.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import data
from .auth import require_admin
from .ratelimit import rate_limit

router = APIRouter(prefix="/api/theses", tags=["theses"])

_RATE = rate_limit("theses", limit=30, window=60)

_MIGRATION_HINT = ("thesis tables are not set up — apply 'database/schema/theses.sql' "
                   "to activate thesis monitoring")


def _watch():
    from analytics.thesis_watch import ThesisWatch

    return ThesisWatch(data._supabase())


def _clean_text(text: str | None, field: str, required: bool = True) -> str | None:
    t = (text or "").strip()
    if not t and not required:
        return None
    if not 1 <= len(t) <= 300:
        raise HTTPException(status_code=400, detail=f"{field} must be 1-300 characters")
    return t


def _public_thesis(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "claim": row.get("claim"),
        "falsifier": row.get("falsifier"),
        "confirmer": row.get("confirmer"),
        "created_at": row.get("created_at"),
    }


def _raise_for(e: Exception) -> None:
    from analytics.thesis_watch import _is_missing_table_error

    if _is_missing_table_error(e):
        raise HTTPException(status_code=503, detail=_MIGRATION_HINT)
    raise HTTPException(status_code=502, detail=str(e))


@router.get("")
def list_theses(_admin: str = Depends(require_admin)) -> dict:
    """Admin read — the active (non-archived) theses, newest first."""
    return {"theses": [_public_thesis(t) for t in _watch().theses()]}


@router.get("/events")
def thesis_events(_admin: str = Depends(require_admin)) -> dict:
    """Recent candidate thesis evidence (falsifier_run.py), each joined with the
    claim of the thesis it bears on and labeled 'confirms' or 'falsifies'.
    Candidates only: nothing here changes a thesis — the admin reviews the
    evidence. Empty when the thesis tables aren't set up."""
    w = _watch()
    claims = {t.get("id"): t.get("claim") for t in w.theses(include_archived=True)}
    out = [
        {
            "id": e.get("id"),
            "thesis_id": e.get("thesis_id"),
            "claim": claims.get(e.get("thesis_id")),
            "matched": e.get("matched"),
            "label": e.get("label"),
            "article_title": e.get("article_title"),
            "article_url": e.get("article_url"),
            "published_at": e.get("published_at"),
            "score": e.get("score"),
            "detected_at": e.get("detected_at"),
        }
        for e in w.recent_events()
    ]
    return {"events": out, "count": len(out)}


class ThesisBody(BaseModel):
    claim: str
    falsifier: str
    confirmer: str | None = None


@router.post("", dependencies=[Depends(_RATE)])
def add_thesis(body: ThesisBody, _admin: str = Depends(require_admin)) -> dict:
    claim = _clean_text(body.claim, "claim")
    falsifier = _clean_text(body.falsifier, "falsifier")
    confirmer = _clean_text(body.confirmer, "confirmer", required=False)
    try:
        row = _watch().add(claim, falsifier, confirmer)
    except Exception as e:
        _raise_for(e)
    if not row:
        raise HTTPException(status_code=502, detail="thesis write returned no row")
    return {"ok": True, "thesis": _public_thesis(row)}


@router.delete("/{thesis_id}", dependencies=[Depends(_RATE)])
def archive_thesis(thesis_id: int, _admin: str = Depends(require_admin)) -> dict:
    """Soft delete: the thesis is archived (dropped from the book and the scan),
    its evidence events are kept."""
    try:
        found = _watch().archive(thesis_id)
    except Exception as e:
        _raise_for(e)
    if not found:
        raise HTTPException(status_code=404, detail=f"thesis {thesis_id} not found")
    return {"ok": True, "archived": thesis_id}
