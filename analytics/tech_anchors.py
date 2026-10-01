"""
Curated anchor stages — the world-truth floor under the news-derived placements.

The world-truth benchmark (eval/reports/40_world_truth.md) measured the rolling
30-day news window as a *perfectly unidirectional* level estimator: across 39
scoreable stage-axes it never over-placed a technology and under-placed 23 —
news systematically reports novelty, so the centroid of even abundant coverage
sits earlier than the world (GLP-1 read research/innovators while 1 in 8 US
adults takes one). News is a good change detector and a bad level estimator.

Fix (§4.3): each tracked technology carries a curated anchor from the
benchmark's truth columns. `analytics.tech_layer.apply_anchors` uses each
anchor as a FLOOR, deliberately simple: display stage = the LATER of
(anchor stage, news-derived stage) per axis. Because the measured bias is
one-directional, a floor corrects it without letting hype push a technology
past evidence — news can still ADVANCE a tech beyond its anchor (the
change-detection job it is good at), never lower it below.

Keys are `technologies.py` registry keys. `lifecycle_fit: False` marks a
tracked name that is not actually a technology (a single lifecycle label is a
forced fit) — excluded from the S-curve/diffusion curves and footnoted instead.

Revisit quarterly (the swing factors per technology are documented in the
benchmark's agent outputs). `as_of` dates the assessment.
"""

from __future__ import annotations

ANCHORS: dict[str, dict] = {
    # ── Mobility / batteries ──
    "solid-state-batteries": {
        "maturity_anchor": "emerging", "adoption_anchor": "innovators",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "Crossed research→emerging within ~12 months — first buyable ASSB product Q1 2026; buyers are still innovators.",
    },
    "lfp-batteries": {
        "maturity_anchor": "dominant-design", "adoption_anchor": "early-majority",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "Majority share of global EV/storage cell chemistry; the settled cathode choice (adoption trending early→late majority).",
    },
    "ev-charging": {
        "maturity_anchor": "dominant-design", "adoption_anchor": "early-majority",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "NACS won the connector standards battle; charging build-out is routine pragmatist infrastructure procurement.",
    },
    "autonomous-driving": {
        "maturity_anchor": "growth", "adoption_anchor": "early-adopters",
        "as_of": "2026-07-02", "confidence": "medium",
        "evidence": "Waymo ~500k paid rides/wk = growth; adoption anchored conservatively — early-majority only within served metros (medium confidence), early-adopters globally.",
    },
    # ── Chips / compute ──
    "advanced-logic": {
        "maturity_anchor": "growth", "adoption_anchor": "early-majority",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "≤3nm in volume ramp at TSMC/Samsung, shipping into mainstream phones and PCs.",
    },
    "hbm-memory": {
        "maturity_anchor": "dominant-design", "adoption_anchor": "late-majority",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "JEDEC-standardised design; effectively every shipping AI accelerator attaches HBM — late-majority buying.",
    },
    "ai-accelerators": {
        "maturity_anchor": "growth", "adoption_anchor": "early-majority",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "Nvidia-led volume supercycle; mainstream enterprises consume accelerators routinely via cloud.",
    },
    "advanced-packaging": {
        "maturity_anchor": "growth", "adoption_anchor": "early-majority",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "CoWoS/chiplet capacity ramping hard; every major AI chip design depends on it.",
    },
    # ── AI / energy ──
    "ai-datacenters": {
        "maturity_anchor": "growth", "adoption_anchor": "early-majority",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "Hyperscale capex supercycle still steep (growth); pragmatist enterprises now buy AI capacity as a matter of course.",
    },
    "generative-ai": {
        "maturity_anchor": "dominant-design", "adoption_anchor": "early-majority",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "Transformer LLM is the settled design; regular use by a majority of knowledge workers — mainstream adoption.",
    },
    # ── Frontier / deep tech ──
    "quantum-computing": {
        "maturity_anchor": "emerging", "adoption_anchor": "early-adopters",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "No commercially useful advantage yet; buyers are national labs and R&D programmes.",
    },
    "humanoid-robots": {
        "maturity_anchor": "emerging", "adoption_anchor": "early-adopters",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "Pilot deployments only; the design space is still wide open.",
    },
    # ── Climate / clean energy ──
    "green-hydrogen": {
        "maturity_anchor": "emerging", "adoption_anchor": "early-adopters",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "FIDs and pilot plants; offtake remains thin — visionary early-adopter buyers.",
    },
    "grid-storage": {
        "maturity_anchor": "dominant-design", "adoption_anchor": "early-majority",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "LFP BESS is the settled design; utility procurement of grid batteries is routine pragmatist buying.",
    },
    "nuclear-smr": {
        "maturity_anchor": "emerging", "adoption_anchor": "early-adopters",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "First units under construction; utility early adopters, no fleet-scale buying yet.",
    },
    "carbon-capture": {
        "maturity_anchor": "emerging", "adoption_anchor": "early-adopters",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "Working plants at tiny scale versus ambition; policy-driven early-adopter buyers.",
    },
    # ── Biotech ──
    "glp-1": {
        "maturity_anchor": "dominant-design", "adoption_anchor": "early-majority",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "Semaglutide/tirzepatide are the settled design; ~1 in 8 US adults has used a GLP-1 — mainstream adoption.",
    },
    "gene-editing": {
        "maturity_anchor": "emerging", "adoption_anchor": "early-adopters",
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "First approvals (e.g. Casgevy) crossed research→emerging; uptake is specialist early adopters.",
    },
    "ai-drug-discovery": {
        "maturity_anchor": "growth", "adoption_anchor": "early-majority",
        "as_of": "2026-07-02", "confidence": "medium",
        "evidence": "Scoping caveat: as a methodology it is growth/early-majority (top-10 pharma all run multiyear AI-discovery programmes); scoped to approved AI-designed drugs (zero so far) it reads emerging.",
    },
    # ── Cross-cutting supply ──
    "critical-minerals": {
        "lifecycle_fit": False,
        "as_of": "2026-07-02", "confidence": "high",
        "evidence": "Supply-chain capacity story, not a technology — extraction/processing tech has been dominant-design for decades; the news is geographic re-diversification, and the real emerging tech nested inside is DLE.",
    },
}
