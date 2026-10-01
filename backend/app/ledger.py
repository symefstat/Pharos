"""
/api/ledger — the PUBLIC ledger: Lodestar's entire forecast history in one
self-contained, outside-reader-shaped payload.

This is the trust artifact (eval/reports/20_product_completeness.md §D — "the
one artifact incumbents structurally cannot copy"): every forecast ever logged
(open AND resolved, quarantined included but flagged), the headline and
per-category stats WITH their naive-baseline comparisons, the calibration
bins, and a per-technology view of the stage-transition calls.

The API surface is strictly read-only — no route in this module ever writes
to Supabase. The single writer here is `anchor_digest`, called by
forecast_run.py (never by a request handler): one append-only insert per day
into `ledger_digests`.

`ledger_digest` makes the history cheaply verifiable: it is the sha256 hex of
the canonical JSON of the forecast rows (keys sorted, rows sorted by
fingerprint) — exactly the `forecasts` array in the payload. Anyone who
downloads the JSON can recompute it (see `DIGEST_RECIPE`); a different digest
means a different history. `anchor_digest` additionally anchors each day's
digest into the append-only `ledger_digests` table (SQL Tables/
ledger_digests.sql), and the payload ships the recent chain as
`digest_history` — so a rewrite of past rows is detectable after the fact,
not just at download time.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Response

from . import data

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

# The verification recipe, shipped in the payload so an outside reader can
# recompute the digest without reading our source.
DIGEST_RECIPE = (
    "sha256 of the canonical JSON of the `forecasts` array exactly as delivered: "
    'json.dumps(forecasts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)'
    ".encode('utf-8')"
)

DIGESTS_TABLE = "ledger_digests"

DIGEST_NOTE = (
    "each day's digest is anchored append-only into the ledger_digests table "
    "after resolution (one row per day; anchors can never be edited or deleted) "
    "— recompute today's digest and compare it against the stored chain in "
    "digest_history: a rewrite of past rows shows up as a mismatch with an "
    "already-anchored digest"
)


def _row(p: dict) -> dict:
    """One public forecast row — the locked record, nothing internal.

    Locked params surface as flat fields: `threshold` (+ `threshold_basis`)
    for the calibrated event kinds, `from_stage`/`to_stage` for the stage
    calls. `evidence` is the resolver's resolution note (what graded it)."""
    import analytics.forecasts as fc

    params = p.get("params") or {}
    threshold = params.get("threshold", params.get("threshold_pct"))
    return {
        "fingerprint": p.get("fingerprint"),
        "kind": p.get("kind"),
        "category": fc.category_of(p.get("kind") or ""),
        "subject": p.get("subject"),
        "claim": p.get("claim"),
        "made_on": p.get("made_on"),
        "resolve_by": p.get("resolve_by"),
        "resolved_on": p.get("resolved_on"),
        "status": "resolved" if p.get("status") == "resolved" else "open",
        "outcome": p.get("outcome"),
        "confidence": p.get("confidence"),
        "horizon": p.get("horizon"),
        "threshold": threshold,
        "threshold_basis": params.get("threshold_basis"),
        "from_stage": params.get("from_stage"),
        "to_stage": params.get("to_stage"),
        "evidence": p.get("resolution_note"),
        "quarantined": fc.is_quarantined(p),
    }


def ledger_rows(preds: list[dict]) -> list[dict]:
    """Every forecast as a public row, sorted by fingerprint (then made_on) —
    the exact array the digest covers, in the exact order it is delivered."""
    rows = [_row(p) for p in preds]
    rows.sort(key=lambda r: (r.get("fingerprint") or "", r.get("made_on") or ""))
    return rows


def ledger_digest(rows: list[dict]) -> str:
    """sha256 hex of the canonical JSON of the rows (sorted keys; the rows are
    already fingerprint-sorted). Same rows → same digest; any edit → different."""
    canon = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def anchor_digest(sb, preds: list[dict] | None = None, as_of: str | None = None) -> dict:
    """Anchor the ledger digest for `as_of` (default: today, UTC) into the
    append-only `ledger_digests` table. Idempotent — if a digest is already
    anchored for that date it is returned untouched (the table's UNIQUE(as_of)
    backs this at the DB level too). Called by forecast_run.py after
    resolution so the anchor reflects the day's final state; never called by
    an API route. `preds` is injectable for tests; by default the ledger is
    re-read fresh (not the TTL cache) so the anchor can't be stale."""
    as_of = as_of or datetime.now(timezone.utc).date().isoformat()
    existing = (sb.table(DIGESTS_TABLE).select("digest,as_of,row_count")
                .eq("as_of", as_of).limit(1).execute().data or [])
    if existing:
        return existing[0]
    rows = ledger_rows(preds if preds is not None else data.load_predictions())
    rec = {"digest": ledger_digest(rows), "as_of": as_of, "row_count": len(rows)}
    sb.table(DIGESTS_TABLE).insert(rec).execute()
    return rec


def digest_history(limit: int = 30) -> list[dict]:
    """The most recent daily digest anchors, newest first — the verification
    chain shipped in the public payload. Best-effort: [] when the table isn't
    set up yet (SQL Tables/ledger_digests.sql) or Supabase is unreachable."""
    try:
        sb = data._supabase()
        return (sb.table(DIGESTS_TABLE).select("as_of,digest,row_count")
                .order("as_of", desc=True).limit(limit).execute().data or [])
    except Exception:
        return []


def _tech_placements() -> list[dict]:
    """Current anchored technology placements (same read the MOT tab does) —
    best-effort context for the per-technology sections; [] when unavailable."""
    try:
        from analytics.tech_layer import apply_anchors, placements

        return apply_anchors(placements(data.rows(30)))
    except Exception:
        return []


def tech_sections(rows: list[dict], placements: list[dict]) -> list[dict]:
    """Per-technology grouping of the anchored maturity-transition forecasts
    (kind == stage_advance_tech): each tech with its current anchored display
    stage, its open call(s), and any resolved history. Pure."""
    by_tech: dict = {}
    for r in rows:
        if r.get("kind") != "stage_advance_tech":
            continue
        by_tech.setdefault(r.get("subject"), []).append(r)
    place = {p.get("tech"): p for p in (placements or [])}
    out = []
    for tech, group in by_tech.items():
        pl = place.get(tech) or {}
        # Newest forecast first inside each tech block.
        group.sort(key=lambda r: r.get("made_on") or "", reverse=True)
        label = pl.get("label") or next(
            (g.get("claim") or "").split(" advances maturity")[0] for g in group
        ) or tech
        out.append({
            "tech": tech,
            "label": label,
            "domain": pl.get("domain"),
            # The anchored display stage every surface shows — null when the
            # tech has no coverage in the current window.
            "current_stage": pl.get("committed_stage") or pl.get("maturity"),
            "anchored": bool(pl.get("maturity_anchored") or pl.get("anchored")),
            "open": [g for g in group if g.get("status") == "open"],
            "resolved": [g for g in group if g.get("status") == "resolved"],
        })
    # Techs with live open calls first, then by label.
    out.sort(key=lambda t: (-len(t["open"]), str(t["label"]).lower()))
    return out


def build_ledger() -> dict:
    import analytics.forecasts as fc

    preds = data.predictions()
    rows = ledger_rows(preds)

    # Headline stats — quarantined kinds excluded from the pooled numbers
    # (track_record), scored per category instead; the naive-baseline fields
    # (base_rate / baseline_accuracy / baseline_brier / brier_skill /
    # accuracy_edge_pp) ride along on both. The honesty is the product.
    stats = fc.calibration_headline(preds)
    categories = fc.track_record_by_category(preds)

    # Calibration bins over the SAME population as the headline (quarantined
    # price calls held out) so the hero curve and the hero stats agree.
    scored = [p for p in preds if p.get("status") == "resolved" and not fc.is_quarantined(p)]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ledger_digest": ledger_digest(rows),
        "digest_recipe": DIGEST_RECIPE,
        # The anchored chain (last ~30 daily digests, newest first) plus how to
        # use it — history rewrites are detectable, not just edits-in-flight.
        "digest_history": digest_history(),
        "digest_note": DIGEST_NOTE,
        "stats": stats,
        # What each record is graded against: "external" = public world events
        # (independently verifiable — the citable record); "internal" = the
        # system's own future labels (a consistency measure, not
        # world-prediction). Nothing hidden — the split only changes headlining.
        "records_by_basis": fc.records_by_basis(preds),
        "categories": categories,
        "calibration_bins": fc.calibration_bins(scored),
        "forecasts": rows,
        "technologies": tech_sections(rows, _tech_placements()),
        "policy": {
            "quarantined_kinds": list(fc.QUARANTINED_KINDS),
            "min_resolve_days": fc.MIN_RESOLVE_DAYS,
            "headline_accuracy_floor": fc.HEADLINE_ACCURACY_FLOOR,
            "internal_kinds_note": (
                "stage/posture/deal-flow calls are graded against Pharos's own "
                "future labels — they measure consistency, not world-prediction, "
                "and are excluded from the external headline"
            ),
        },
    }


@router.get("", response_model=None)
def ledger(download: bool = False) -> Response | dict:
    """The public ledger. `?download=1` returns the same JSON as an attachment
    so the artifact is exportable and diffable."""
    payload = build_ledger()
    if download:
        body = json.dumps(payload, indent=2, ensure_ascii=False)
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="lodestar-ledger.json"'},
        )
    return payload
