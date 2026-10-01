"""
/api/watchlist — manage the tracked terms behind the Briefing's "Tracking:" chips.

Read is public (the chips render for every visitor); add/remove are admin-gated
(single-admin app) and rate-limited. A submitted term is resolved onto the
watchlist's (kind, value) schema by analytics.watchlist.resolve_term: a tracked
technology's key/label → technology, a feed label → feed, else entity.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import data
from .auth import require_admin
from .ratelimit import rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

_RATE = rate_limit("watchlist", limit=30, window=60)

# Competitor moves (Phase 3 🏢) shown under a watched entity's chip: window and
# per-entity cap for the additive `moves` field on the public read.
MOVES_WINDOW_DAYS = 7
MOVES_PER_ENTITY = 10


def _watchlist():
    from analytics.watchlist import Watchlist

    return Watchlist(data._supabase())


def _clean_term(term: str) -> str:
    t = (term or "").strip()
    if not 1 <= len(t) <= 80:
        raise HTTPException(status_code=400, detail="term must be 1-80 characters")
    return t


def _public_item(row: dict) -> dict:
    from technologies import TECH_BY_KEY

    kind, value = row.get("kind"), str(row.get("value") or "")
    label = TECH_BY_KEY[value].label if (kind == "technology" and value in TECH_BY_KEY) else value
    return {
        "id": row.get("id"),
        "kind": kind,
        "term": value,
        "label": label,
        "added_on": row.get("created_at"),
    }


def _entity_moves_by_term(items: list[dict]) -> dict[str, list[dict]]:
    """Recent strategic moves (last MOVES_WINDOW_DAYS) keyed by watched-entity
    term — the additive `moves` field on the public payload. Computed with the
    pure analytics.entity_moves over the cached data layer; non-fatal (a data
    outage serves no moves, never a 500)."""
    from analytics.entities import normalize as normalize_entity
    from analytics.entity_moves import entity_moves

    terms = [str(it.get("term") or "") for it in items if it.get("kind") == "entity"]
    if not terms:
        return {}
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=MOVES_WINDOW_DAYS)).isoformat()
        moves = entity_moves(data.rows(30), terms, since)
    except Exception:
        logger.warning("watchlist moves computation failed — serving none", exc_info=True)
        return {}
    by_entity: dict[str, list[dict]] = {}
    for m in moves:
        by_entity.setdefault(m["entity"], []).append(m)
    # entity_moves returns newest-first, so the per-entity cap keeps the newest
    return {t: by_entity.get(normalize_entity(t), [])[:MOVES_PER_ENTITY] for t in terms}


@router.get("")
def list_watchlist() -> dict:
    """Public read — the tracked items (term + added_on), as the chips render,
    plus each watched entity's recent strategic moves (`moves`, additive)."""
    items = [_public_item(r) for r in _watchlist().items()]
    moves = _entity_moves_by_term(items)
    for it in items:
        it["moves"] = moves.get(it["term"], [])
    return {"items": items}


class WatchBody(BaseModel):
    term: str


@router.post("", dependencies=[Depends(_RATE)])
def add_watch(body: WatchBody, _admin: str = Depends(require_admin)) -> dict:
    from analytics.watchlist import resolve_term

    term = _clean_term(body.term)
    kind, value = resolve_term(term)
    _watchlist().add(kind, value)
    return {"ok": True, "item": {"kind": kind, "term": value}}


@router.delete("/{term}", dependencies=[Depends(_RATE)])
def remove_watch(term: str, _admin: str = Depends(require_admin)) -> dict:
    from analytics.watchlist import find_watch_matches

    term = _clean_term(term)
    wl = _watchlist()
    matches = find_watch_matches(wl.items(), term)
    if not matches:
        raise HTTPException(status_code=404, detail=f"'{term}' is not on the watchlist")
    for kind, value in matches:
        wl.remove(kind, value)
    return {"ok": True, "removed": len(matches)}
