"""
Technology/market registry — the unit of analysis MOT frameworks actually
operate on.

The S-curve of *solid-state batteries*, the diffusion of *GLP-1 drugs*, a
standards battle in *advanced packaging* — these live at the technology level,
not the news-article level. This registry defines the tracked technologies and
the keywords that map articles to them; `analytics/tech_layer.py` rolls each
feed's classified articles up to these units and places the *technology* on the
S-curve / diffusion curve (Ortt's pattern level, A4 — not the project/article
level).

Adding a technology = one `Technology(...)` entry. Keywords are lowercased
substrings matched against title + summary + tags + companies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Technology:
    key: str
    label: str
    domain: str                 # short grouping tag (used for chart colour)
    keywords: tuple[str, ...]    # lowercased substrings that map an article here


# Domain naming: where a technology grouping corresponds 1:1 to a Lodestar feed,
# the domain string IS the feed label from feeds.py ("EV", "AI & Energy",
# "Chips", "Climate & Energy", "Biotech & Health") so charts, filters and the
# convergence radar speak one vocabulary. "Frontier" and "Supply chain" are
# deliberate exceptions: they are *technology groupings* that cut across
# several feeds (quantum/humanoids surface in Disruptive Tech, Chips, …;
# critical minerals in Geopolitics & Trade, EV, Chips) — they are not feeds,
# so they don't take a feed label.
TECHNOLOGIES: List[Technology] = [
    # ── EV / batteries (feed: "EV") ──
    Technology("solid-state-batteries", "Solid-state batteries", "EV",
               ("solid-state", "solid state batter")),
    Technology("lfp-batteries", "LFP batteries", "EV",
               ("lfp", "lithium iron phosphate", "lithium-iron-phosphate")),
    Technology("ev-charging", "EV charging", "EV",
               ("charging", "charger network", "fast charging", "nacs", "supercharger")),
    Technology("autonomous-driving", "Autonomous driving", "EV",
               ("robotaxi", "self-driving", "autonomous driving", "driverless", "waymo", "full self-driving", "fsd")),
    # ── Chips / compute (feed: "Chips") ──
    Technology("advanced-logic", "Advanced logic (≤3nm)", "Chips",
               ("2nm", "3nm", "1.4nm", "advanced node", "euv", "gate-all-around", "gaa")),
    Technology("hbm-memory", "HBM memory", "Chips",
               ("hbm", "high bandwidth memory", "high-bandwidth memory")),
    Technology("ai-accelerators", "AI accelerators", "Chips",
               ("ai accelerator", "ai chip", "gpu", "tpu", "blackwell", "h100", "h200", "mi300")),
    Technology("advanced-packaging", "Advanced packaging", "Chips",
               ("cowos", "chiplet", "advanced packaging", "2.5d", "3d stacking")),
    # ── AI / energy (feed: "AI & Energy") ──
    Technology("ai-datacenters", "AI data centres", "AI & Energy",
               ("data center", "data centre", "datacenter", "hyperscale", "data-center")),
    Technology("generative-ai", "Generative AI / LLMs", "AI & Energy",
               ("llm", "large language model", "generative ai", "foundation model", "frontier model")),
    # ── Frontier / deep tech — cross-feed technology grouping, NOT a feed ──
    Technology("quantum-computing", "Quantum computing", "Frontier",
               ("quantum comput", "qubit", "quantum processor")),
    Technology("humanoid-robots", "Humanoid robots", "Frontier",
               ("humanoid", "humanoid robot")),
    # ── Climate / clean energy (feed: "Climate & Energy") ──
    Technology("perovskite-solar", "Perovskite solar", "Climate & Energy",
               ("perovskite",)),
    Technology("green-hydrogen", "Green hydrogen", "Climate & Energy",
               ("hydrogen", "electrolyser", "electrolyzer")),
    Technology("grid-storage", "Grid-scale storage", "Climate & Energy",
               ("grid storage", "battery storage", "energy storage", "grid-scale", "bess")),
    Technology("nuclear-smr", "Small modular reactors", "Climate & Energy",
               ("smr", "small modular reactor", "modular nuclear")),
    Technology("carbon-capture", "Carbon capture", "Climate & Energy",
               ("carbon capture", "ccs", "direct air capture", "dac ")),
    # ── Biotech (feed: "Biotech & Health") ──
    Technology("glp-1", "GLP-1 drugs", "Biotech & Health",
               ("glp-1", "glp1", "ozempic", "wegovy", "semaglutide", "tirzepatide", "zepbound")),
    Technology("gene-editing", "Gene editing / therapy", "Biotech & Health",
               ("crispr", "gene editing", "gene-editing", "gene therapy")),
    Technology("ai-drug-discovery", "AI drug discovery", "Biotech & Health",
               ("ai drug", "drug discovery", "alphafold", "ai-discovered")),
    # ── Cross-cutting supply — cross-feed technology grouping, NOT a feed ──
    Technology("critical-minerals", "Critical minerals", "Supply chain",
               ("rare earth", "critical mineral", "lithium supply", "cobalt", "gallium", "germanium")),
]

TECH_BY_KEY = {t.key: t for t in TECHNOLOGIES}

# Legacy → current domain labels. Rows snapshotted into
# technology_stage_history before the feed-label alignment still hold the old
# strings ("Mobility", "Climate", …); they are NEVER rewritten in the DB —
# readers map them at display time with `domain_label()` so old and new rows
# render (and colour) identically. Technology *keys* are the stable identity
# (they sit in the stage-history primary key) and did not change.
DOMAIN_LABELS = {
    "Mobility": "EV",
    "AI & energy": "AI & Energy",
    "Climate": "Climate & Energy",
    "Biotech": "Biotech & Health",
    "Disruptive": "Disruptive Tech",   # historical value; no current registry entry
}


def domain_label(domain: str | None) -> str | None:
    """Current display label for a (possibly legacy, stored) domain string."""
    return DOMAIN_LABELS.get(domain, domain) if domain else domain


def known_domains() -> list[str]:
    """The valid domain labels for a tracked technology, in registry order —
    the vocabulary the self-serve tracking form (and its validation) uses."""
    seen: list[str] = []
    for t in TECHNOLOGIES:
        if t.domain not in seen:
            seen.append(t.domain)
    return seen


# ── self-serve technology tracking (database/schema/tracked_technologies.sql) ──────
# "Adding a technology = one entry" — but an admin-UI entry, not a code edit:
# custom technologies live in the `tracked_technologies` table and are merged
# with the static registry by `registry()`. Stage history uses tech keys as its
# primary key, so new keys are safe — they simply accumulate history from
# scratch.
TRACKED_TABLE = "tracked_technologies"


def registry(client=None) -> List[Technology]:
    """The merged technology registry: static TECHNOLOGIES + the active
    (non-archived) rows of `tracked_technologies`.

    Degrades to the static registry when no client is given, the table is
    missing, or the read fails — a pending migration must never break the
    placements. DB keys that collide with a static key (or repeat) are skipped
    and logged: the static registry always wins, so curated anchors/benchmarks
    keyed to a static tech can never be hijacked by a DB row.
    """
    merged = list(TECHNOLOGIES)
    if client is None:
        return merged
    try:
        rows = (
            client.table(TRACKED_TABLE)
            .select("key,label,domain,keywords")
            .eq("archived", False)
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.warning(
            "tracked_technologies unavailable (%s) — static registry only. "
            "Apply 'database/schema/tracked_technologies.sql' to enable self-serve tracking.",
            e,
        )
        return merged
    seen = set(TECH_BY_KEY)
    for r in rows:
        key = str(r.get("key") or "").strip()
        if not key:
            continue
        if key in seen:
            logger.warning("tracked_technologies key %r collides with an existing "
                           "registry key — skipping the DB row.", key)
            continue
        keywords = tuple(
            str(k).strip().lower() for k in (r.get("keywords") or []) if str(k).strip()
        )
        if not keywords:
            logger.warning("tracked_technologies key %r has no usable keywords — skipping.", key)
            continue
        merged.append(Technology(key, str(r.get("label") or key),
                                 str(r.get("domain") or ""), keywords))
        seen.add(key)
    return merged
