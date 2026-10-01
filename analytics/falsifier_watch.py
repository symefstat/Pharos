"""
Falsifier watch — the alert loop behind "we told you what would prove us wrong,
and we'll tell you when it happens."

Every Strategist signal is captured as an open `manual` forecast whose
resolution criterion is its falsifier (analytics.forecasts.gen_from_strategist).
This module scans recent news for CANDIDATE evidence that a falsifier may have
triggered: vector similarity over the news embeddings when available (primary
signal), token-overlap keyword matching over the raw feeds otherwise/alongside
(fallback — fresh articles may not be embedded yet). Candidates are persisted to
`falsifier_events` (UNIQUE(pred_id, article_url) → idempotent re-runs) and new
ones are pushed by falsifier_run.py.

Detection NEVER resolves a forecast. A match is a review prompt for a human
grader (POST /api/forecasts/resolve) — resolutions stay human/objective, so a
fuzzy text match can never corrupt the public track record.

`open_falsifiers`, `match_evidence`, `new_events` and `format_falsifier_alerts`
are pure (unit-tested); FalsifierWatch does the Supabase/embedding I/O.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from supabase import Client

from db import get_supabase
from analytics.aggregator import PulseAggregator, _normalize_url
from analytics.events import _STOP

logger = logging.getLogger(__name__)

EVENTS_TABLE = "falsifier_events"

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Keyword path: fraction of the falsifier's content tokens that must appear in
# the article (title+summary+companies+tags). 0.5 with a 2-hit floor is strict
# enough that a single shared entity name ("Tether…", "OpenAI…") can't trigger,
# while a genuine event report — which restates the falsifier's core terms —
# clears it comfortably (see tests/test_falsifier_watch.py).
KW_THRESHOLD = 0.5
_KW_MIN_HITS = 2

# Vector path: cosine floor for falsifier→article similarity. Ask's calibrated
# question→news floor is 0.45; evidence that pushes a webhook alert warrants
# more precision than a retrieval pack, so this sits a notch higher.
VEC_SIM_FLOOR = 0.50


def _falsifier_tokens(text: str) -> set:
    return {t for t in _TOKEN_RE.findall((text or "").lower())
            if len(t) >= 3 and t not in _STOP}


def open_falsifiers(preds: list[dict]) -> list[dict]:
    """The open judgment calls that carry a falsifier — the watch set. Pure.

    Input: prediction rows (any kinds/statuses); output: one dict per open
    `manual` forecast whose params carry a non-empty falsifier."""
    out = []
    for p in preds or []:
        if p.get("status") != "open" or p.get("kind") != "manual":
            continue
        fals = str((p.get("params") or {}).get("falsifier") or "").strip()
        if not fals:
            continue
        out.append({"pred_id": p.get("id"), "claim": p.get("claim"),
                    "falsifier": fals, "made_on": p.get("made_on")})
    return out


def match_evidence(falsifier_rows: list[dict], articles: list[dict], *,
                   threshold: float = KW_THRESHOLD) -> list[dict]:
    """Keyword-overlap matching of articles against falsifiers. Pure.

    For each falsifier, score every article by the fraction of the falsifier's
    content tokens (≥3 chars, stopwords out) found in the article's
    title+summary+companies+tags — same token machinery as ask._relevant_stories,
    but normalized by the falsifier length so the score is comparable across
    falsifiers. A match needs `threshold` of the tokens AND ≥2 token hits (one
    shared name is never evidence). Articles published before the forecast was
    made are skipped — evidence can't predate the call.

    Returns [{pred_id, falsifier, article_title, article_url, published_at,
    score}], best score first."""
    out: list[dict] = []
    for row in falsifier_rows or []:
        tokens = _falsifier_tokens(row.get("falsifier") or "")
        if not tokens:
            continue
        made_on = str(row.get("made_on") or "")
        for a in articles or []:
            pub = str(a.get("published_at") or "")
            if made_on and pub and pub[:10] < made_on[:10]:
                continue                       # evidence can't predate the call
            hay = " ".join([
                str(a.get("title") or ""), str(a.get("summary") or ""),
                " ".join(str(c) for c in (a.get("companies") or [])),
                " ".join(str(t) for t in (a.get("tags") or [])),
            ]).lower()
            hits = sum(1 for t in tokens if t in hay)
            score = hits / len(tokens)
            if hits >= _KW_MIN_HITS and score >= threshold:
                out.append({"pred_id": row.get("pred_id"),
                            "falsifier": row.get("falsifier"),
                            "article_title": a.get("title"),
                            "article_url": a.get("url"),
                            "published_at": a.get("published_at"),
                            "score": round(score, 3)})
    out.sort(key=lambda e: e["score"], reverse=True)
    return out


def new_events(candidates: list[dict], existing_pairs: set) -> list[dict]:
    """The candidates not yet in `falsifier_events` — the only ones worth an
    alert. `existing_pairs` = {(pred_id, article_url), …} already persisted.
    Also dedupes within the batch (vector + keyword can find the same article).
    Pure; the DB's UNIQUE(pred_id, article_url) enforces the same rule at
    write time."""
    seen = set(existing_pairs or set())
    out = []
    for e in candidates or []:
        key = (e.get("pred_id"), e.get("article_url"))
        if None in key or key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def format_falsifier_alerts(events: list[dict], as_of: str | None = None) -> str:
    """Webhook body for new falsifier evidence. Pure. Events that carry a
    judge verdict (see the judge glue in falsifier_run.py) are ordered by it —
    'triggers' first, then 'partial' — so the human reads signal before noise;
    unjudged events render exactly as before."""
    if not events:
        return ""
    head = (f"⚠ Falsifier watch ({len(events)})" + (f" — {as_of}" if as_of else "")
            + " · candidate evidence only — review and grade in Track record")
    lines = [head, ""]
    order = {"triggers": 0, "partial": 1, None: 2, "unrelated": 3}
    for e in sorted(events, key=lambda x: order.get(x.get("judge_verdict"), 2)):
        verdict = e.get("judge_verdict")
        if verdict == "triggers":
            lines.append(f"⚠ LIKELY TRIGGERED: '{e.get('falsifier')}' — "
                         f"{e.get('article_title')} ({e.get('article_url')})")
        elif verdict == "partial":
            lines.append(f"◐ Partial evidence: '{e.get('falsifier')}' — "
                         f"{e.get('article_title')} ({e.get('article_url')})")
        else:
            lines.append(f"⚠ Falsifier evidence: '{e.get('falsifier')}' may have triggered "
                         f"— {e.get('article_title')} ({e.get('article_url')})")
        if e.get("judge_why"):
            lines.append(f"   judge: {e['judge_why']}")
    return "\n".join(lines)


def parse_judge_verdicts(raw: str, n_events: int) -> dict[int, dict]:
    """Parse the Falsifier Judge agent's JSON array into {index: {verdict, why}}.
    Pure and forgiving: junk rows, out-of-range indices, and unknown verdicts
    are dropped — a malformed judgment must never break the alert run."""
    import json

    # Toqan agents may emit a <think>…</think> trace despite the contract —
    # strip it first so a bracket inside the trace can't hijack the JSON match.
    raw = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL | re.IGNORECASE)
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return {}
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return {}
    out: dict[int, dict] = {}
    for row in arr if isinstance(arr, list) else []:
        if not isinstance(row, dict):
            continue
        idx = row.get("index")
        verdict = row.get("verdict")
        if (isinstance(idx, int) and 0 <= idx < n_events
                and verdict in ("triggers", "partial", "unrelated")):
            out[idx] = {"verdict": verdict, "why": str(row.get("why") or "").strip()[:200]}
    return out


def apply_verdicts(events: list[dict], verdicts: dict[int, dict],
                   drop_unrelated: bool = True) -> list[dict]:
    """Annotate events with judge verdicts (pure; input not mutated). Events
    judged 'unrelated' are dropped from the ALERT list by default — they stay
    persisted in falsifier_events, so nothing is hidden, only de-prioritized.
    Unjudged events pass through unchanged (fail-open: no judge, no filtering)."""
    out = []
    for i, e in enumerate(events):
        v = verdicts.get(i)
        if v is None:
            out.append(dict(e))
            continue
        if drop_unrelated and v["verdict"] == "unrelated":
            continue
        out.append({**e, "judge_verdict": v["verdict"], "judge_why": v["why"]})
    return out


def _is_missing_table_error(err: Exception) -> bool:
    """True if a falsifier_events read/write failed because the table hasn't
    been created yet (SQL Tables/falsifier_events.sql not applied). Matches the
    specific missing-relation signatures — Postgres 42P01 ('relation … does not
    exist') or PostgREST PGRST205 ('Could not find the table … in the schema
    cache') — mirroring db.is_missing_column_error. Pure."""
    msg = str(err).lower()
    if EVENTS_TABLE not in msg:
        return False
    return any(tok in msg for tok in
               ("does not exist", "could not find", "schema cache", "pgrst205", "42p01"))


class FalsifierWatch:
    """Detect candidate falsifier evidence in recent news and persist it.

    Detection only — this class never touches predictions.status/outcome."""

    def __init__(self, client: Client | None = None, embedder=None):
        self.client = client or get_supabase()
        self.embedder = embedder      # injectable embed_texts(texts) for tests

    # ── detection ──────────────────────────────────────────────────────────────
    def detect(self, days: int = 1, threshold: float = KW_THRESHOLD) -> list[dict]:
        """Candidate events for every open falsifier against the last `days` of
        news. Vector similarity is the primary signal; the keyword score runs
        alongside as the fallback (fresh articles may not be embedded yet, and
        it's the only path when OPENAI_API_KEY is absent). Merged, deduped by
        (pred_id, normalized url), vector hits first."""
        rows = open_falsifiers(self._open_predictions())
        if not rows:
            return []
        vec = self._vector_matches(rows, days=days)
        articles = PulseAggregator(self.client).all_recent(days=days)
        kw = match_evidence(rows, articles, threshold=threshold)

        merged: list[dict] = []
        seen: set = set()
        for e in vec + kw:
            key = (e.get("pred_id"), _normalize_url(e.get("article_url") or ""))
            if key in seen:
                continue
            seen.add(key)
            merged.append(e)
        return merged

    def _open_predictions(self) -> list[dict]:
        try:
            return (self.client.table("predictions")
                    .select("id, claim, kind, status, params, made_on")
                    .eq("status", "open").eq("kind", "manual")
                    .limit(1000).execute().data or [])
        except Exception as e:
            logger.warning("Falsifier watch: predictions read failed: %s", e)
            return []

    def _vector_matches(self, falsifier_rows: list[dict], days: int) -> list[dict]:
        """Cosine search of each falsifier against the news embeddings; empty
        (with a log line) when embeddings are unavailable, so the caller falls
        back to keyword-only."""
        try:
            embed = self.embedder
            if embed is None:
                from vectordb.embedder import embed_texts
                embed = embed_texts
            from vectordb.news_store import NewsVectorStore

            vectors = embed([r["falsifier"] for r in falsifier_rows])
            store = NewsVectorStore(self.client)
            since = (date.today() - timedelta(days=days)).isoformat()
            out: list[dict] = []
            for row, vec in zip(falsifier_rows, vectors):
                made_on = str(row.get("made_on") or "")
                for h in store.search(vec, k=5, since=since):
                    sim = float(h.get("similarity") or 0)
                    pub = str(h.get("published_at") or "")
                    if sim < VEC_SIM_FLOOR:
                        continue
                    if made_on and pub and pub[:10] < made_on[:10]:
                        continue               # evidence can't predate the call
                    out.append({"pred_id": row.get("pred_id"),
                                "falsifier": row.get("falsifier"),
                                "article_title": h.get("title"),
                                "article_url": h.get("url"),
                                "published_at": h.get("published_at"),
                                "score": round(sim, 3)})
            out.sort(key=lambda e: e["score"], reverse=True)
            return out
        except Exception as e:
            logger.warning("Falsifier watch: vector matching unavailable (%s) — "
                           "keyword-only this run.", e)
            return []

    # ── persistence ────────────────────────────────────────────────────────────
    def persist(self, events: list[dict]) -> list[dict]:
        """Upsert candidate events (idempotent on (pred_id, article_url)) and
        return only the NEW ones — the ones worth an alert. Degrades gracefully
        when the table is missing: logs the SQL file to apply and returns []
        (nothing persisted → nothing alerted, so an unmigrated deploy can't
        spam the webhook with repeats every 6h)."""
        if not events:
            return []
        try:
            pred_ids = sorted({e["pred_id"] for e in events if e.get("pred_id") is not None})
            existing = (self.client.table(EVENTS_TABLE)
                        .select("pred_id, article_url")
                        .in_("pred_id", pred_ids).execute().data or [])
            existing_pairs = {(r.get("pred_id"), r.get("article_url")) for r in existing}
            fresh = new_events(events, existing_pairs)
            if fresh:
                self.client.table(EVENTS_TABLE).upsert(
                    [{"pred_id": e["pred_id"], "falsifier": e.get("falsifier"),
                      "article_url": e["article_url"],
                      "article_title": e.get("article_title"),
                      "published_at": e.get("published_at"),
                      "score": e.get("score")} for e in fresh],
                    on_conflict="pred_id,article_url").execute()
            return fresh
        except Exception as e:
            if _is_missing_table_error(e):
                logger.warning("Falsifier watch: the %s table is missing — apply "
                               "'SQL Tables/falsifier_events.sql' to activate the "
                               "falsifier alert loop. (%s)", EVENTS_TABLE, e)
            else:
                logger.warning("Falsifier watch: persist failed: %s", e)
            return []

    def recent_events(self, limit: int = 50) -> list[dict]:
        """Most recent candidate events (for the API). Empty when the table is
        missing (with the apply-the-SQL hint) — the UI simply shows no card."""
        try:
            return (self.client.table(EVENTS_TABLE).select("*")
                    .order("detected_at", desc=True).limit(limit).execute().data or [])
        except Exception as e:
            if _is_missing_table_error(e):
                logger.warning("Falsifier watch: the %s table is missing — apply "
                               "'SQL Tables/falsifier_events.sql'. (%s)", EVENTS_TABLE, e)
            else:
                logger.warning("Falsifier watch: events read failed: %s", e)
            return []
