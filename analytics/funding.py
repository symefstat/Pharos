"""
Funding signal — the first evidence stream INDEPENDENT of news headlines.

Stage placements derive from headline+summary classification (the Methodology
page's admitted limitation). Funding-round stage mix is an independent read on
the same question: seed/A/B money chasing a field says "early"; C+/growth
rounds, IPOs and M&A say the design has settled enough for late-stage capital.
This module aggregates the funding_rounds table per technology and produces a
plain-English corroboration line comparing the funding-implied phase with the
news-derived maturity stage.

DISPLAY ONLY, by design: the read renders on the dossier next to the stage; it
does not enter the stage-call algorithm until the mapping has earned trust.
Everything except `tech_funding` (the table read) is pure and unit-tested.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta

logger = logging.getLogger(__name__)

FUNDING_TABLE = "funding_rounds"

# Round-type → phase. Grants/seed through B = early (venture money buying
# options); C+ onward, growth/PE, IPO and M&A = late (capital committing to a
# settled design). 'debt' and 'other' stay out of the mix — they carry no
# reliable phase information.
EARLY_ROUNDS = {"grant", "seed", "series-a", "series-b"}
LATE_ROUNDS = {"series-c-plus", "growth", "ipo", "m&a"}

# Below this many phase-classified rounds in the window, no corroboration claim
# is made — the same evidence-floor discipline the stage placements follow.
MIN_ROUNDS_FOR_READ = 3

# News-derived maturity stage → the funding phase you'd expect alongside it.
_STAGE_PHASE = {
    "research": "early",
    "emerging": "early",
    "growth": "mixed",
    "dominant-design": "late",
    "mature": "late",
    "declining": "late",
}
_PHASE_RANK = {"early": 0, "mixed": 1, "late": 2}


def _phase_of(rows: list[dict]) -> tuple[str | None, int]:
    """Funding-implied phase from the early/late round mix. Returns
    (phase|None, n_classified). None when under the evidence floor."""
    early = sum(1 for r in rows if (r.get("round_type") or "") in EARLY_ROUNDS)
    late = sum(1 for r in rows if (r.get("round_type") or "") in LATE_ROUNDS)
    n = early + late
    if n < MIN_ROUNDS_FOR_READ:
        return None, n
    share_early = early / n
    if share_early >= 0.67:
        return "early", n
    if share_early <= 0.33:
        return "late", n
    return "mixed", n


def _quarter(d: str) -> str:
    y, m = int(d[:4]), int(d[5:7])
    return f"{y}Q{(m - 1) // 3 + 1}"


def funding_summary(rows: list[dict], today: date, window_days: int = 365) -> dict | None:
    """Aggregate one technology's funding rows into the dossier section (pure).

    Returns None when there are no rows at all (table empty for this tech —
    the dossier omits the panel rather than showing a wall of zeros)."""
    if not rows:
        return None
    cutoff = (today - timedelta(days=window_days)).isoformat()
    recent = [r for r in rows if str(r.get("announced_on") or "") >= cutoff]

    by_q: dict[str, dict] = defaultdict(lambda: {"total_usd": 0.0, "rounds": 0})
    for r in recent:
        q = _quarter(str(r.get("announced_on")))
        by_q[q]["rounds"] += 1
        by_q[q]["total_usd"] += float(r.get("amount_usd") or 0.0)
    trajectory = [{"quarter": q, **v} for q, v in sorted(by_q.items())]

    early = sum(1 for r in recent if (r.get("round_type") or "") in EARLY_ROUNDS)
    late = sum(1 for r in recent if (r.get("round_type") or "") in LATE_ROUNDS)
    latest = sorted(recent, key=lambda r: str(r.get("announced_on") or ""), reverse=True)[:5]
    return {
        "window_days": window_days,
        "rounds": len(recent),
        "total_usd": sum(float(r.get("amount_usd") or 0.0) for r in recent),
        "early": early,
        "late": late,
        "trajectory": trajectory,
        "latest": [{
            "company": r.get("company"),
            "round_type": r.get("round_type"),
            "amount_usd": r.get("amount_usd"),
            "announced_on": str(r.get("announced_on") or "")[:10] or None,
            "source_url": r.get("source_url"),
        } for r in latest],
    }


def funding_read(rows: list[dict], maturity_stage: str | None,
                 today: date, window_days: int = 365) -> str | None:
    """One-sentence corroboration line: does the last year's funding mix agree
    with the news-derived maturity stage? None when under the evidence floor or
    when there is no stage to compare against. Pure; never overclaims — the
    wording always names both reads and the n it rests on."""
    cutoff = (today - timedelta(days=window_days)).isoformat()
    recent = [r for r in rows if str(r.get("announced_on") or "") >= cutoff]
    phase, n = _phase_of(recent)
    if phase is None:
        if not recent:
            return None
        return (f"Only {n} phase-classified round{'s' if n != 1 else ''} in the last "
                f"12 months — too few for an independent read (floor {MIN_ROUNDS_FOR_READ}).")
    label = {"early": "early-phase (seed–B dominate)",
             "mixed": "transitional (early and late rounds split)",
             "late": "late-phase (C+, growth, M&A/IPO dominate)"}[phase]
    expected = _STAGE_PHASE.get(maturity_stage or "")
    if expected is None:
        return f"Capital reads {label} across {n} rounds — no news stage to compare against."
    if phase == expected:
        verdict = f"independently corroborates the news-derived '{maturity_stage}' stage"
    elif _PHASE_RANK[phase] > _PHASE_RANK[expected]:
        verdict = f"runs later than the news-derived '{maturity_stage}' stage — capital is committing ahead of the coverage"
    else:
        verdict = f"runs earlier than the news-derived '{maturity_stage}' stage — capital is still exploratory despite the coverage"
    return f"Capital reads {label} across {n} rounds — {verdict}."


def tech_funding(client, tech_key: str) -> list[dict] | None:
    """This technology's funding rows, newest first. None (not []) when the
    table is missing/unreadable, so callers can distinguish 'no data yet' from
    'feature not set up' and degrade silently either way."""
    try:
        return (client.table(FUNDING_TABLE).select("*")
                .eq("tech_key", tech_key)
                .order("announced_on", desc=True).limit(500)
                .execute().data or [])
    except Exception as e:
        logger.warning("Funding rows unavailable for %s (%s) — apply "
                       "'SQL Tables/funding_rounds.sql' to enable the funding signal.",
                       tech_key, e)
        return None
