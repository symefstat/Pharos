"""
Thesis watch — "thesis maintenance" automated, for the investor's PRIVATE book.

The admin registers an investment thesis with the evidence that would FALSIFY
it and (optionally) the evidence that would CONFIRM it. This module reuses the
falsifier-watch detection engine (analytics.falsifier_watch.match_evidence —
imported, not duplicated) to scan recent news against BOTH texts of every
active thesis, labeling each candidate event "falsifies" or "confirms".
Candidates are persisted to `thesis_events` (UNIQUE(thesis_id, article_url) →
idempotent re-runs) and new ones are pushed by falsifier_run.py.

Theses deliberately live in their OWN `theses` table, never in `predictions`:
they must not contaminate the public ledger, the track record, or the
calibration stats. Detection never changes a thesis — a match is a review
prompt for the admin (the Theses card in Track record).

`watch_rows`, `match_thesis_evidence`, `new_thesis_events` and
`format_thesis_alerts` are pure (unit-tested); ThesisWatch does the Supabase
I/O and the thesis CRUD behind /api/theses.
"""

from __future__ import annotations

import logging

from supabase import Client

from db import get_supabase
from analytics.aggregator import PulseAggregator
from analytics.falsifier_watch import KW_THRESHOLD, match_evidence

logger = logging.getLogger(__name__)

THESES_TABLE = "theses"
EVENTS_TABLE = "thesis_events"

# Event labels — what the matched text means for the thesis.
LABEL_FALSIFIES = "falsifies"
LABEL_CONFIRMS = "confirms"


def watch_rows(theses: list[dict]) -> list[dict]:
    """The (thesis, direction) pairs worth scanning — the watch set. Pure.

    Input: thesis rows (any archived states); output: one dict per non-empty
    falsifier/confirmer text of each ACTIVE thesis, carrying the label the
    engine will stamp on a match."""
    out: list[dict] = []
    for t in theses or []:
        if t.get("archived"):
            continue
        made_on = str(t.get("created_at") or "")[:10]
        for text, label in ((t.get("falsifier"), LABEL_FALSIFIES),
                            (t.get("confirmer"), LABEL_CONFIRMS)):
            text = str(text or "").strip()
            if text:
                out.append({"thesis_id": t.get("id"), "text": text,
                            "label": label, "made_on": made_on})
    return out


def match_thesis_evidence(theses: list[dict], articles: list[dict], *,
                          threshold: float = KW_THRESHOLD) -> list[dict]:
    """Match articles against every active thesis's falsifier AND confirmer,
    labeling each event. Pure — delegates the scoring to the falsifier-watch
    engine (falsifier_watch.match_evidence), so the two loops can never drift.

    Returns [{thesis_id, matched, label, article_title, article_url,
    published_at, score}], best score first."""
    out: list[dict] = []
    for row in watch_rows(theses):
        matches = match_evidence(
            [{"pred_id": row["thesis_id"], "falsifier": row["text"],
              "made_on": row["made_on"]}],
            articles, threshold=threshold)
        for m in matches:
            out.append({"thesis_id": m["pred_id"], "matched": m["falsifier"],
                        "label": row["label"],
                        "article_title": m["article_title"],
                        "article_url": m["article_url"],
                        "published_at": m["published_at"],
                        "score": m["score"]})
    out.sort(key=lambda e: e["score"], reverse=True)
    return out


def new_thesis_events(candidates: list[dict], existing_pairs: set) -> list[dict]:
    """The candidates not yet in `thesis_events` — the only ones worth an
    alert. `existing_pairs` = {(thesis_id, article_url), …} already persisted.
    Also dedupes within the batch (an article can match both the falsifier and
    the confirmer — best score, which sorts first, wins). Pure; the DB's
    UNIQUE(thesis_id, article_url) enforces the same rule at write time."""
    seen = set(existing_pairs or set())
    out = []
    for e in candidates or []:
        key = (e.get("thesis_id"), e.get("article_url"))
        if None in key or key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def format_thesis_alerts(events: list[dict], as_of: str | None = None) -> str:
    """Webhook body for new thesis evidence — distinct 🧭 prefix so it can't be
    confused with the public falsifier-watch alerts. Pure."""
    if not events:
        return ""
    head = (f"🧭 Thesis watch ({len(events)})" + (f" — {as_of}" if as_of else "")
            + " · candidate evidence only — review in Track record (private thesis book)")
    lines = [head, ""]
    for e in events:
        lines.append(f"🧭 Thesis evidence ({e.get('label')}): '{e.get('matched')}' "
                     f"matched — {e.get('article_title')} ({e.get('article_url')})")
    return "\n".join(lines)


def _is_missing_table_error(err: Exception) -> bool:
    """True if a theses/thesis_events read/write failed because the tables
    haven't been created yet ('database/schema/theses.sql' not applied). Matches the
    specific missing-relation signatures — Postgres 42P01 or PostgREST PGRST205
    — mirroring falsifier_watch._is_missing_table_error. Pure."""
    msg = str(err).lower()
    if THESES_TABLE not in msg and EVENTS_TABLE not in msg:
        return False
    return any(tok in msg for tok in
               ("does not exist", "could not find", "schema cache", "pgrst205", "42p01"))


class ThesisWatch:
    """CRUD for the private thesis book + detection of candidate evidence.

    Detection only — this class never archives or grades a thesis by itself."""

    def __init__(self, client: Client | None = None):
        self.client = client or get_supabase()

    # ── thesis book (CRUD behind /api/theses) ─────────────────────────────────
    def theses(self, include_archived: bool = False) -> list[dict]:
        """The registered theses, newest first. Empty (with the apply-the-SQL
        hint) when the table is missing — the UI simply shows no book."""
        try:
            q = self.client.table(THESES_TABLE).select("*")
            if not include_archived:
                q = q.eq("archived", False)
            return q.order("created_at", desc=True).limit(500).execute().data or []
        except Exception as e:
            self._warn("theses read", e)
            return []

    def add(self, claim: str, falsifier: str, confirmer: str | None = None) -> dict | None:
        """Register a thesis. Raises on failure (the router turns a missing
        table into an actionable 503) — a silent no-op would lie to the admin."""
        payload: dict = {"claim": claim, "falsifier": falsifier}
        if confirmer:
            payload["confirmer"] = confirmer
        rows = self.client.table(THESES_TABLE).insert(payload).execute().data or []
        return rows[0] if rows else None

    def archive(self, thesis_id: int) -> bool:
        """Soft-delete: flag archived=true (events are kept). Returns False when
        no such thesis exists. Raises on transport/migration failure."""
        rows = (self.client.table(THESES_TABLE).update({"archived": True})
                .eq("id", thesis_id).execute().data or [])
        return bool(rows)

    # ── detection ──────────────────────────────────────────────────────────────
    def detect(self, days: int = 1, threshold: float = KW_THRESHOLD) -> list[dict]:
        """Candidate events for every active thesis against the last `days` of
        news — keyword-overlap over the raw feeds (the falsifier-watch fallback
        path; theses are few and their texts short, so the keyword engine is
        the right precision/complexity trade)."""
        rows = self.theses()
        if not rows:
            return []
        articles = PulseAggregator(self.client).all_recent(days=days)
        return match_thesis_evidence(rows, articles, threshold=threshold)

    # ── persistence ────────────────────────────────────────────────────────────
    def persist(self, events: list[dict]) -> list[dict]:
        """Upsert candidate events (idempotent on (thesis_id, article_url)) and
        return only the NEW ones — the ones worth an alert. Degrades gracefully
        when the table is missing: logs the SQL file to apply and returns []
        (nothing persisted → nothing alerted, so an unmigrated deploy can't
        spam the webhook with repeats every run)."""
        if not events:
            return []
        try:
            ids = sorted({e["thesis_id"] for e in events if e.get("thesis_id") is not None})
            existing = (self.client.table(EVENTS_TABLE)
                        .select("thesis_id, article_url")
                        .in_("thesis_id", ids).execute().data or [])
            pairs = {(r.get("thesis_id"), r.get("article_url")) for r in existing}
            fresh = new_thesis_events(events, pairs)
            if fresh:
                self.client.table(EVENTS_TABLE).upsert(
                    [{"thesis_id": e["thesis_id"], "matched": e.get("matched"),
                      "label": e.get("label"), "article_url": e["article_url"],
                      "article_title": e.get("article_title"),
                      "published_at": e.get("published_at"),
                      "score": e.get("score")} for e in fresh],
                    on_conflict="thesis_id,article_url").execute()
            return fresh
        except Exception as e:
            self._warn("persist", e)
            return []

    def recent_events(self, limit: int = 50) -> list[dict]:
        """Most recent candidate events (for the API). Empty when the table is
        missing (with the apply-the-SQL hint) — the UI simply shows no events."""
        try:
            return (self.client.table(EVENTS_TABLE).select("*")
                    .order("detected_at", desc=True).limit(limit).execute().data or [])
        except Exception as e:
            self._warn("events read", e)
            return []

    @staticmethod
    def _warn(what: str, e: Exception) -> None:
        if _is_missing_table_error(e):
            logger.warning("Thesis watch: %s failed — the theses/thesis_events "
                           "tables are missing; apply 'database/schema/theses.sql' to "
                           "activate thesis monitoring. (%s)", what, e)
        else:
            logger.warning("Thesis watch: %s failed: %s", what, e)
