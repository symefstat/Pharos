"""
Competitor move alerts (Phase 3 🏢) — watch an entity, get alerted when the lens
tags it with a strategic move.

`entity_moves` is pure (unit-tested): it filters recent classified rows down to
those whose companies match a watched entity AND that carry a real
`strategic_move` classification (standards-battle / entry-timing / collaboration /
appropriability / platform / disruption — see analytics/lens.py `_MOVE`; the
lens writes "none" for stories without one, which must NOT alert).

Entity matching reuses analytics.entities.normalize, the same convention as
analytics/watchlist.py `match_alerts` — so "google", "DeepMind" and
"Alphabet (Google)" all resolve to one watched entity.

I/O-side assembly lives in analytics/watchlist.py (Watchlist.entity_moves for
the alert run) and backend/app/watchlist.py (the `moves` field on GET
/api/watchlist).
"""

from __future__ import annotations

from analytics.entities import normalize as normalize_entity

# Lens fallback values that mean "no strategic move detected" — an omitted or
# unclassified row gets "none"/"n/a" (see analytics/lens.py reconcile_batch).
_NON_MOVES = {"", "none", "n/a", "null"}


def entity_moves(rows: list[dict], watched_entities: list[str],
                 since_iso: str) -> list[dict]:
    """Pure: strategic moves by watched entities in recent classified rows.

    rows: classified stories (title/url/companies/strategic_move/published_at/
          business_impact, feed label under `_feed_label` or `feed_label`).
    watched_entities: entity names as stored on the watchlist (matched
          case-insensitively via analytics.entities.normalize).
    since_iso: ISO-8601 cutoff compared lexicographically against
          `published_at` (the repo's convention — ISO strings sort correctly);
          rows without a published_at are excluded ("recent" needs a date).

    Returns deduped ((entity, url)) dicts, newest first:
      {entity, move, title, url, feed, published_at, impact}
    where `entity` is the watched term's canonical (normalized) name.

    Matching compares lowercased normalized names: the alias map makes known
    players case-insensitive already, and lowercasing extends that to entities
    the alias map doesn't know (`normalize` passes those through verbatim).
    """
    # lowercased canonical -> canonical display form (from the watched side)
    watched: dict[str, str] = {}
    for e in watched_entities:
        canon = normalize_entity(str(e))
        if canon:
            watched[canon.lower()] = canon
    if not watched:
        return []

    seen: set = set()
    out: list[dict] = []
    for r in rows:
        move = str(r.get("strategic_move") or "").strip().lower()
        if move in _NON_MOVES:
            continue
        published = str(r.get("published_at") or "")
        if not published or published < since_iso:
            continue
        ents = {normalize_entity(str(c)).lower() for c in (r.get("companies") or [])}
        for low in sorted(watched.keys() & ents):
            entity = watched[low]
            key = (low, r.get("url"))
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "entity": entity,
                "move": move,
                "title": r.get("title"),
                "url": r.get("url"),
                "feed": r.get("_feed_label") or r.get("feed_label"),
                "published_at": r.get("published_at"),
                "impact": r.get("business_impact"),
            })
    out.sort(key=lambda m: str(m.get("published_at") or ""), reverse=True)
    return out


def format_move_alerts(moves: list[dict]) -> str:
    """Render move alerts as a plain-text webhook body:
    `🏢 Competitor move: <Entity> — <move> · <title> (<url>)` per line."""
    lines: list[str] = []
    for m in moves:
        line = f"🏢 Competitor move: {m.get('entity')} — {m.get('move')}"
        if m.get("title"):
            line += f" · {m['title']}"
        if m.get("url"):
            line += f" ({m['url']})"
        lines.append(line)
    return "\n".join(lines)
