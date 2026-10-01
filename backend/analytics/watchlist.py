"""
Watchlist + alerts — track technologies / entities / feeds and get pushed an
alert when something decisive happens (a new material story on a tracked item, or
a tracked technology changing lifecycle stage).

`match_alerts` / `format_alerts` are pure (unit-tested); the Watchlist class does
the Supabase reads/writes and assembles the inputs for them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from supabase import Client

from db import get_supabase
from analytics.aggregator import PulseAggregator
from analytics.entities import normalize as normalize_entity
from analytics.tech_layer import TechAnalyst, match_technologies
from feeds import FEEDS
from technologies import TECH_BY_KEY

logger = logging.getLogger(__name__)

WATCHLIST_TABLE = "watchlist"


def resolve_term(term: str) -> tuple[str, str]:
    """Pure: map a free-text term from the UI onto the watchlist's (kind, value)
    schema. A tracked technology's key or label → ("technology", key); a feed's
    key or label → ("feed", label); anything else is tracked as an entity,
    verbatim (entity matching normalizes at alert time)."""
    t = term.strip()
    low = t.lower()
    for key, tech in TECH_BY_KEY.items():
        if low in (key, tech.label.lower()):
            return "technology", key
    for f in FEEDS:
        if low in (f.key, f.label.lower()):
            return "feed", f.label
    return "entity", t


def find_watch_matches(items: list[dict], term: str) -> list[tuple[str, str]]:
    """Pure: the (kind, value) rows a user-supplied term refers to, matched
    case-insensitively against the stored value — and, for technologies, the
    display label too (the UI may show either)."""
    low = term.strip().lower()
    out: list[tuple[str, str]] = []
    for r in items:
        kind, value = r.get("kind"), str(r.get("value") or "")
        label = TECH_BY_KEY[value].label if (kind == "technology" and value in TECH_BY_KEY) else None
        if low == value.lower() or (label and low == label.lower()):
            out.append((kind, value))
    return out


def match_alerts(items: list[tuple[str, str]], recent_rows: list[dict],
                 transitions: list[dict], techs: list | None = None) -> list[dict]:
    """Pure alert matcher.

    items: (kind, value) watchlist entries — kind in {technology, entity, feed};
           technology value = tech key, entity value = canonical name, feed = label.
    recent_rows: recent *material* stories (title/url/_feed_label/companies).
    transitions: technology stage transitions (from tech_layer). Only *trustworthy*
        moves alert — a `suspect` transition (backward / unconfirmed / contested) is a
        watch-item, not a push-worthy event, so it's skipped here.

    Returns deduped alert dicts: {type, subject, title?, url?, feed?, detail?}.
    """
    watched_ent = {normalize_entity(v) for k, v in items if k == "entity"}
    watched_feed = {v for k, v in items if k == "feed"}
    watched_tech = {v for k, v in items if k == "technology"}

    seen: set = set()
    out: list[dict] = []

    def _add(alert: dict, key: tuple) -> None:
        if key not in seen:
            seen.add(key)
            out.append(alert)

    for r in recent_rows:
        title, url = r.get("title"), r.get("url")
        feed = r.get("_feed_label") or r.get("feed_label")
        ents = {normalize_entity(str(c)) for c in (r.get("companies") or [])}
        for e in (watched_ent & ents):
            _add({"type": "entity", "subject": e, "title": title, "url": url, "feed": feed},
                 ("entity", e, url))
        if feed in watched_feed:
            _add({"type": "feed", "subject": feed, "title": title, "url": url, "feed": feed},
                 ("feed", feed, url))
        for t in (set(match_technologies(r, techs)) & watched_tech):
            label = TECH_BY_KEY[t].label if t in TECH_BY_KEY else t
            _add({"type": "technology", "subject": label, "title": title, "url": url, "feed": feed},
                 ("technology", t, url))

    for tr in transitions:
        if tr.get("technology") in watched_tech and not tr.get("suspect"):
            _add({"type": "transition", "subject": tr.get("label") or tr.get("technology"),
                  "detail": f"{tr.get('dimension')} {tr.get('from')} → {tr.get('to')}"},
                 ("transition", tr.get("technology"), tr.get("as_of")))
    return out


def format_alerts(alerts: list[dict], as_of: str | None = None) -> str:
    """Render alerts as a plain-text notification body (Slack/Discord webhook-ready)."""
    if not alerts:
        return ""
    head = f"🔔 Lodestar alerts ({len(alerts)})" + (f" — {as_of}" if as_of else "")
    lines = [head, ""]
    icon = {"entity": "🏢", "feed": "📡", "technology": "🧬", "transition": "🔀"}
    for a in alerts:
        ic = icon.get(a["type"], "•")
        if a["type"] == "transition":
            lines.append(f"{ic} {a['subject']} — stage transition: {a.get('detail', '')}")
        else:
            feed = f" [{a['feed']}]" if a.get("feed") else ""
            lines.append(f"{ic} {a['subject']}{feed}: {a.get('title', '')}")
            if a.get("url"):
                lines.append(f"   {a['url']}")
    return "\n".join(lines)


class Watchlist:
    def __init__(self, client: Client | None = None):
        self.client = client or get_supabase()

    def items(self) -> list[dict]:
        try:
            return (self.client.table(WATCHLIST_TABLE).select("*")
                    .order("kind").order("value").execute().data or [])
        except Exception as e:
            logger.warning("Watchlist read failed: %s", e)
            return []

    def add(self, kind: str, value: str) -> None:
        try:
            self.client.table(WATCHLIST_TABLE).upsert(
                {"kind": kind, "value": value}, on_conflict="kind,value").execute()
        except Exception as e:
            logger.warning("Watchlist add failed: %s", e)

    def remove(self, kind: str, value: str) -> None:
        try:
            self.client.table(WATCHLIST_TABLE).delete().eq("kind", kind).eq("value", value).execute()
        except Exception as e:
            logger.warning("Watchlist remove failed: %s", e)

    def alerts(self, hours: int = 8) -> list[dict]:
        """Alerts for tracked items from material stories fetched in the last
        `hours` plus any technology stage transitions."""
        items = [(r["kind"], r["value"]) for r in self.items()]
        if not items:
            return []
        pulse = PulseAggregator(self.client)
        recent = pulse.targeted_recent(days=2, business_impact="material", limit_per_feed=80)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        recent = [r for r in recent if str(r.get("fetched_at") or "") >= cutoff]
        try:
            transitions = TechAnalyst(self.client).transitions()
        except Exception:
            transitions = []
        # Merged registry so a watched self-serve technology alerts too;
        # None (static) on any registry failure — never blocks the alerts.
        try:
            from technologies import registry

            techs = registry(self.client)
        except Exception:
            techs = None
        return match_alerts(items, recent, transitions, techs)

    def entity_moves(self, hours: int = 8) -> list[dict]:
        """Competitor move alerts (Phase 3 🏢): stories published in the last
        `hours` where the lens tagged a watched entity with a strategic move —
        any impact level, unlike `alerts` which only scans material stories.
        Matching/shaping is pure (analytics.entity_moves)."""
        from analytics.entity_moves import entity_moves

        entities = [r["value"] for r in self.items() if r.get("kind") == "entity"]
        if not entities:
            return []
        rows = PulseAggregator(self.client).all_recent(days=max(2, hours // 24 + 1))
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        return entity_moves(rows, entities, since)
