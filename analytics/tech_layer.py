"""
Technology-level roll-up: map classified articles to tracked technologies, place
each *technology* on its lifecycle, and track stage transitions over time.

This is the fix for the unit-of-analysis problem (Ortt's three levels, A4): the
MOT lens classifies articles, but the frameworks describe technologies/markets.
Here we aggregate article classifications up to the technologies in
`technologies.py`, place each technology at the centroid-committed stage of its
classification spread (the stage every surface displays, via `display_stage`),
and snapshot it daily so the *decisive* event — a stage transition
(emerging→growth, early-adopters→early-majority) — becomes detectable (A1/A2/B2).

Pure functions (match_technologies, placements, detect_transitions) are unit-
tested; the builder/reader hit Supabase.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timezone

from supabase import Client

from db import get_supabase
from technologies import TECHNOLOGIES, TECH_BY_KEY, Technology, domain_label, registry
from analytics.aggregator import PulseAggregator
from analytics.entities import normalize as normalize_entity
from home_news.writer import _is_missing_column_error

logger = logging.getLogger(__name__)

HISTORY_TABLE = "technology_stage_history"

# Placement-confidence columns (SQL Tables/technology_stage_history_confidence.sql).
# Optional: if the migration isn't applied, snapshot() strips these and retries so
# a feed run never breaks on a pending migration.
_CONFIDENCE_COLS = ("maturity_modal_share", "maturity_mixed",
                    "adoption_modal_share", "adoption_mixed")

_MATURITY_ORDER = ["research", "emerging", "growth", "dominant-design", "mature", "declining"]
_ADOPTION_ORDER = ["innovators", "early-adopters", "early-majority", "late-majority", "laggards"]
_MOVE_ORDER = ["standards-battle", "entry-timing", "collaboration", "appropriability", "platform", "disruption"]
_ORDER_BY_DIM = {"maturity": _MATURITY_ORDER, "adoption": _ADOPTION_ORDER}

# Debounce: how many of the most-recent snapshots a just-changed stage may already
# occupy and still count as *current* news. A move surfaces while its new stage sits
# within this many classified snapshots of the top, then drops off once it has long
# settled — so the feed shows recent moves (and their confirmation), not ancient ones.
_TRANSITION_FRESH_SNAPSHOTS = 4


def match_technologies(row: dict, techs: list[Technology] | None = None) -> list[str]:
    """Tech keys whose keywords appear in the article's text / tags / companies.

    Pure. Matches against the static registry by default; the IO boundary
    (TechAnalyst, the API routers) passes the merged registry
    (`technologies.registry(client)`) so self-serve tracked technologies match
    too."""
    if techs is None:
        techs = TECHNOLOGIES
    hay = " ".join([
        str(row.get("title") or ""),
        str(row.get("summary") or ""),
        " ".join(str(t) for t in (row.get("tags") or [])),
        " ".join(str(c) for c in (row.get("companies") or [])),
    ]).lower()
    return [t.key for t in techs if any(kw in hay for kw in t.keywords)]


def _modal(items: list[dict], field: str, allowed: list[str]) -> str | None:
    c = Counter(
        v for r in items
        if (v := str(r.get(field) or "").strip().lower().replace("_", "-")) in allowed
    )
    return c.most_common(1)[0][0] if c else None


def _dimension_stats(items: list[dict], field: str, order: list[str]) -> dict:
    """Lifecycle placement for ONE dimension (maturity or adoption), honest about its
    own confidence (pure).

    Over the *real* stages only ('n/a' excluded, since a policy/energy story has no
    curve position), returns: the spread (`dist`), the on-curve article count
    (`articles`), the spread's **centroid** rank (`centroid`) and the nearest stage to
    it (`committed`) — so a contested tech sits at the *centre* of its spread instead
    of being slammed to whichever single stage won a thin plurality. `mixed` flags
    techs where no stage holds a majority, so the chart can fade them."""
    stages = [v for r in items
              if (v := str(r.get(field) or "").strip().lower().replace("_", "-")) in order]
    if not stages:
        return {"dist": {}, "articles": 0, "centroid": None,
                "committed": None, "modal_share": None, "mixed": False}
    dist = Counter(stages)
    n = len(stages)
    centroid = sum(order.index(s) * c for s, c in dist.items()) / n
    idx = max(0, min(len(order) - 1, round(centroid)))
    committed = order[idx]
    modal_category, modal_count = dist.most_common(1)[0]
    modal_share = modal_count / n
    # Contested ("faded") when no category holds a clear majority (≤50%, incl. a 50/50),
    # OR when the centroid places the dot at a category that ISN'T the most-classified
    # one — a skewed/bimodal spread whose mean lands in a sparsely-supported middle
    # stage (e.g. a plurality says 'early-majority' but the dot is dragged to
    # 'early-adopters'). Either way the position can't be trusted at face value.
    mixed = modal_share <= 0.5 or modal_category != committed
    return {"dist": dict(dist), "articles": n, "centroid": round(centroid, 3),
            "committed": committed, "modal_share": round(modal_share, 3), "mixed": mixed}


def _stage_stats(items: list[dict]) -> dict:
    """Maturity-dimension placement for the technology S-curve (back-compat keys)."""
    s = _dimension_stats(items, "maturity_stage", _MATURITY_ORDER)
    return {"stage_dist": s["dist"], "stage_articles": s["articles"],
            "stage_centroid": s["centroid"], "committed_stage": s["committed"],
            "modal_share": s["modal_share"], "mixed": s["mixed"]}


def _adoption_stats(items: list[dict]) -> dict:
    """Adoption-dimension placement for the innovation-adoption (diffusion) curve."""
    s = _dimension_stats(items, "adoption_stage", _ADOPTION_ORDER)
    return {"adoption_dist": s["dist"], "adoption_articles": s["articles"],
            "adoption_centroid": s["centroid"], "adoption_committed": s["committed"],
            "adoption_modal_share": s["modal_share"], "adoption_mixed": s["mixed"]}


def placements(rows: list[dict], techs: list[Technology] | None = None) -> list[dict]:
    """Roll classified articles up to technologies (pure).

    Returns one record per technology that has ≥1 classified matched article:
    modal maturity/adoption, dominant move, article + distinct-entrant counts.
    `techs` defaults to the static registry; pass the merged registry
    (`technologies.registry(client)`) at the IO boundary to include self-serve
    tracked technologies.
    """
    if techs is None:
        techs = TECHNOLOGIES
    by_key = {t.key: t for t in techs}
    matched: dict[str, list[dict]] = {}
    for r in rows:
        for key in match_technologies(r, techs):
            matched.setdefault(key, []).append(r)

    out = []
    for key, items in matched.items():
        classified = [r for r in items if str(r.get("maturity_stage") or "").strip()]
        if not classified:
            continue
        entrants = {
            normalize_entity(str(c)) for r in items for c in (r.get("companies") or [])
            if normalize_entity(str(c))
        }
        tech = by_key[key]
        out.append({
            "tech": key,
            "label": tech.label,
            "domain": tech.domain,
            "articles": len(classified),
            "entrants": len(entrants),
            "maturity": _modal(classified, "maturity_stage", _MATURITY_ORDER),
            "adoption": _modal(classified, "adoption_stage", _ADOPTION_ORDER),
            "move": _modal(classified, "strategic_move", _MOVE_ORDER),
            **_stage_stats(classified),
            **_adoption_stats(classified),
        })
    out.sort(key=lambda p: -p["articles"])
    return out


# Coverage floor (eval/reports/40_world_truth.md §4.1): a 30-day news centroid
# over a handful of articles is noise — below this many stage-classified
# articles a placement is flagged `thin_signal` and rendered hollow, not
# hidden (analysts still want to see it, just visibly less confident).
THIN_SIGNAL_MIN_ARTICLES = 10

# Evidence floor (domain-strategy plan): below this many stage-classified
# articles a technology is not *placed* on the curves at all — it is flagged
# `watching` ("watching — insufficient evidence") and kept visible in the
# placement table without a stage position. This is rolling-window evidence
# (the same coverage count the placements use), so a watching tech re-enters
# the curves automatically — re-check as volume accrues rather than lowering
# the floor. Marquee names with structurally light coverage (solid-state
# batteries, LFP) sitting below the floor is intended, not a bug.
EVIDENCE_FLOOR = 15


def apply_anchors(recs: list[dict], anchors: dict | None = None) -> list[dict]:
    """Overlay the curated anchor stages on news-derived placements (pure).

    World-truth fix (eval/reports/40_world_truth.md §4): the rolling news
    window is a good change detector but a systematically EARLY level
    estimator (the measured bias is perfectly unidirectional — news only ever
    under-places). Each anchor is therefore a FLOOR, deliberately simple:
    the displayed stage per axis becomes the LATER of (anchor stage,
    news-derived stage). News can still advance a tech beyond its anchor;
    it can never drag it below. Per placement this adds:

      • `thin_signal`     — stage-classified article count < THIN_SIGNAL_MIN_ARTICLES;
      • `watching`        — stage-classified article count < EVIDENCE_FLOOR:
        insufficient evidence to place the tech on the curves at all (the API
        drops it from `on_curve`/`on_adoption_curve`; the table keeps the row
        with a "watching" badge instead of a stage);
      • `news_maturity` / `news_adoption` — the pre-floor news-derived stage
        (nothing is hidden; the change-detector read stays in the payload);
      • `maturity_anchored` / `adoption_anchored` / `anchored` — True where
        the floor actually raised the displayed stage;
      • `anchor_as_of`    — the anchor assessment date;
      • `lifecycle_fit` / `lifecycle_note` — False + reason for tracked names
        that are not actually technologies (taxonomy misfit, §4.4): excluded
        from the curves and footnoted instead of plotted as a misleading dot.

    Flooring rewrites `committed_stage` / `adoption_committed` (what
    `display_stage()` returns) and floors the matching centroid so the chart
    dot moves with the stage. Transition safety: `snapshot()` persists the
    floored display stage, so the first post-anchor snapshot can read as a
    stage change — `detect_transitions` absorbs it exactly like the
    modal→committed migration (run==1 → unconfirmed → suspect, downranked and
    never watchlist-alerted); pinned in tests/test_tech_anchors.py.
    """
    if anchors is None:
        from analytics.tech_anchors import ANCHORS as anchors
    out = []
    for p in recs:
        p = dict(p)
        n = p.get("stage_articles")
        if n is None:
            n = p.get("articles") or 0
        p["thin_signal"] = n < THIN_SIGNAL_MIN_ARTICLES
        p["watching"] = n < EVIDENCE_FLOOR
        a = anchors.get(p.get("tech")) or {}
        if a:
            p["anchor_as_of"] = a.get("as_of")
        if a.get("lifecycle_fit") is False:
            p["lifecycle_fit"] = False
            p["lifecycle_note"] = a.get("evidence")
        for dim, anchor_key, committed_key, centroid_key, order in (
            ("maturity", "maturity_anchor", "committed_stage", "stage_centroid", _MATURITY_ORDER),
            ("adoption", "adoption_anchor", "adoption_committed", "adoption_centroid", _ADOPTION_ORDER),
        ):
            anchor = a.get(anchor_key)
            if anchor not in order:
                continue
            news = display_stage(p, dim)
            p[f"news_{dim}"] = news
            a_idx = order.index(anchor)
            n_idx = order.index(news) if news in order else -1
            if a_idx > n_idx:                       # floor: anchor is later than news
                p[committed_key] = anchor
                cen = p.get(centroid_key)
                if cen is None or cen < a_idx:      # move the chart dot with the stage
                    p[centroid_key] = float(a_idx)
                p[f"{dim}_anchored"] = True
            else:                                    # news at/beyond anchor — news wins
                p[f"{dim}_anchored"] = False
        p["anchored"] = bool(p.get("maturity_anchored") or p.get("adoption_anchored"))
        out.append(p)
    return out


def display_stage(p: dict, dim: str = "maturity") -> str | None:
    """The stage to *show* for a placement on `dim` ('maturity' or 'adoption').

    Returns the centroid-based committed stage — where the S-curve / diffusion dot
    actually sits — falling back to the bare modal, then None. Use this anywhere a
    placement's stage is displayed or reasoned over (placement table, Compare, the
    Strategist context) so none of them disagree with the chart: on a bimodal spread
    the plurality (modal) and the centroid (committed) can name different stages, and
    the charts place by the centroid."""
    if dim == "adoption":
        return p.get("adoption_committed") or p.get("adoption")
    return p.get("committed_stage") or p.get("maturity")


def _latest_change(snaps: list[dict], field: str) -> tuple[str, str, int] | None:
    """Most recent stage change in `field`, anchored on the current placement (pure).

    `snaps` is newest-first. The current stage is the latest snapshot's value; walking
    back, we find the first earlier snapshot whose stage differs (blank snapshots are
    skipped, not treated as a change). Returns `(from_stage, to_stage, run_length)` —
    `run_length` is how many of the most-recent *classified* snapshots already hold the
    new stage (1 = it appeared only in the latest snapshot; ≥2 = it has persisted).
    Returns None when the latest snapshot is unclassified or the stage never changed.
    """
    to_stage = snaps[0].get(field)
    if not to_stage:
        return None
    run = 0
    for s in snaps:
        v = s.get(field)
        if not v:
            continue                 # gap in coverage — don't reset the run
        if v == to_stage:
            run += 1
        else:
            return v, to_stage, run  # first earlier, different stage = the source
    return None                       # never changed across the available history


def detect_transitions(history_rows: list[dict]) -> list[dict]:
    """Per-technology stage transitions from the snapshot history (pure).

    A transition (maturity or adoption stage change) is the decisive event the
    lifecycle/diffusion theory cares about — but only when it is *trustworthy*. These
    axes are near-monotonic (adoption is cumulative — you don't un-cross the chasm), so
    each transition is graded on three axes and the untrustworthy ones are downranked,
    never dropped:
      • `backward` — the new stage ranks *earlier* on its axis (emerging→research,
        early-majority→innovators). Almost always re-estimation noise, not a real
        regression; sorted to the very bottom.
      • `confirmed` — the new stage has held for ≥2 of the most-recent snapshots
        (debounce). A single-snapshot flip is shown as pending, not headlined.
      • `contested` — the destination snapshot had no clear majority stage (`*_mixed`).
    `suspect` is the convenience OR of the three. Rows predating the confidence columns
    read as not-contested/unknown (NULL → False/None). Long-settled moves (new stage
    older than `_TRANSITION_FRESH_SNAPSHOTS` snapshots) drop off as no longer current.
    """
    by_tech: dict[str, list[dict]] = {}
    for r in history_rows:
        by_tech.setdefault(r.get("technology"), []).append(r)
    out = []
    for tech, snaps in by_tech.items():
        snaps = sorted(snaps, key=lambda s: str(s.get("as_of") or ""), reverse=True)
        if len(snaps) < 2:
            continue
        cur = snaps[0]
        for field, label in (("maturity_stage", "maturity"), ("adoption_stage", "adoption")):
            change = _latest_change(snaps, field)
            if not change:
                continue
            a, b, run = change
            if run > _TRANSITION_FRESH_SNAPSHOTS:
                continue              # long-settled — no longer a current event
            order = _ORDER_BY_DIM[label]
            try:
                backward = order.index(b) < order.index(a)
            except ValueError:
                backward = False      # unknown/legacy stage label — can't judge direction
            confirmed = run >= 2
            contested = bool(cur.get(f"{label}_mixed"))
            out.append({
                "technology": tech,
                "label": cur.get("label") or tech,
                # Stored rows may hold pre-alignment domain strings ("Mobility");
                # map to the current feed-aligned label at read time — the DB is
                # never rewritten.
                "domain": domain_label(cur.get("domain")),
                "dimension": label,
                "from": a,
                "to": b,
                "as_of": cur.get("as_of"),
                # Confidence of the *destination* placement (the stage moved INTO).
                "contested": contested,
                "modal_share": cur.get(f"{label}_modal_share"),
                "backward": backward,
                "confirmed": confirmed,
                # Consecutive snapshots the destination stage has held. run == 2 is
                # the exact moment a move confirms — the delivery layer alerts on
                # that value so a transition notifies once, not on every snapshot.
                "run": run,
                "suspect": backward or not confirmed or contested,
            })
    # Recency first, then float the trustworthy moves up: a backward (near-impossible)
    # move sinks hardest, then contested, then unconfirmed; maturity outranks adoption
    # at equal trust. Nothing is dropped — only ordered.
    out.sort(key=lambda t: str(t.get("as_of") or ""), reverse=True)
    out.sort(key=lambda t: (t["backward"], t["contested"], not t["confirmed"],
                            t["dimension"] != "maturity"))
    return out


class TechAnalyst:
    def __init__(self, client: Client | None = None):
        self.client = client or get_supabase()
        self.pulse = PulseAggregator(self.client)

    def registry(self) -> list[Technology]:
        """The merged technology registry (static + self-serve DB rows) —
        degrades to static-only when the table is missing."""
        return registry(self.client)

    def current_placements(self, days: int = 30) -> list[dict]:
        """Technology placements from the recent classified articles (live),
        with the curated anchor floor applied (`apply_anchors`) so history
        snapshots, the Strategist context and the API all display world-truth
        stages, never below the anchors. Uses the merged registry, so
        self-serve tracked technologies place (and snapshot) too."""
        rows = [r for r in self.pulse.all_recent(days=days) if r.get("maturity_stage")]
        return apply_anchors(placements(rows, self.registry()))

    def snapshot(self, days: int = 30) -> int:
        """Persist today's per-technology placement to the history table (upsert).

        Persists the **displayed** stage (`display_stage()` — centroid-committed,
        falling back to bare modal), not the bare modal, so the history table,
        the transitions built from it, and every display surface agree by
        construction: on a bimodal spread the modal and committed stages can
        name different stages, and the surfaces all show the committed one.

        Migration note (modal → committed semantics): rows snapshotted before
        this change hold the bare modal. For a tech whose last stored modal
        differs from its committed stage, the first committed-semantics snapshot
        can read as a one-time stage change. That is exactly the bimodal case,
        so the old row was persisted with `*_mixed=True` and today's snapshot is
        (for a similar corpus) also mixed → the move is graded `contested`, and
        at run==1 it is unconfirmed — either way `suspect`, so it is downranked
        and never watchlist-alerted, the same treatment contested moves already
        get. No history rewrite is needed."""
        as_of = datetime.now(timezone.utc).date().isoformat()
        now = datetime.now(timezone.utc).isoformat()
        recs = self.current_placements(days=days)
        rows = [{
            "technology": p["tech"],
            "as_of": as_of,
            "label": p["label"],
            "domain": p["domain"],
            # The stage every surface shows (committed, modal fallback) — keeps
            # transition from/to labels consistent with the placement table.
            "maturity_stage": display_stage(p),
            "adoption_stage": display_stage(p, "adoption"),
            "strategic_move": p["move"],
            "article_count": p["articles"],
            "entrant_count": p["entrants"],
            # Placement confidence — carried so a contested flip isn't headlined.
            "maturity_modal_share": p.get("modal_share"),
            "maturity_mixed": p.get("mixed"),
            "adoption_modal_share": p.get("adoption_modal_share"),
            "adoption_mixed": p.get("adoption_mixed"),
            "updated_at": now,
        } for p in recs]
        if not rows:
            return 0
        try:
            self.client.table(HISTORY_TABLE).upsert(rows, on_conflict="technology,as_of").execute()
        except Exception as e:
            # If the confidence columns aren't applied yet, snapshot without them so
            # the run still succeeds (the placement stages persist; confidence is NULL).
            if not any(_is_missing_column_error(e, c) for c in _CONFIDENCE_COLS):
                logger.warning("Tech history snapshot failed: %s", e)
                return 0
            logger.warning(
                "technology_stage_history has no confidence columns yet — snapshotting "
                "without them. Apply SQL Tables/technology_stage_history_confidence.sql."
            )
            rows = [{k: v for k, v in r.items() if k not in _CONFIDENCE_COLS} for r in rows]
            try:
                self.client.table(HISTORY_TABLE).upsert(rows, on_conflict="technology,as_of").execute()
            except Exception as e2:
                logger.warning("Tech history snapshot failed: %s", e2)
                return 0
        logger.info("Tech history: snapshotted %d technologies for %s", len(rows), as_of)
        return len(rows)

    def transitions(self) -> list[dict]:
        try:
            rows = (
                self.client.table(HISTORY_TABLE)
                .select("*")
                .order("as_of", desc=True)
                .limit(2000)
                .execute()
                .data
                or []
            )
        except Exception as e:
            logger.warning("Tech history read failed: %s", e)
            return []
        return detect_transitions(rows)
