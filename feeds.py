"""
Feed registry — the single source of truth for the topics the shared
`home_news` pipeline can run.

Each feed is one news topic (EV, AI & Energy, …). The pipeline code
(extractor / parser / writer / runner / UI) is topic-agnostic; everything that
differs between topics lives here. Adding a new feed = one `Feed(...)` entry
below + a prompt file in `Agents_prompt/` + its Toqan agent API key in `.env`.
No pipeline code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Feed:
    key: str            # used for per-tab widget keys + CLI feed selection
    table: str          # Supabase table backing this feed (one table per feed)
    label: str          # tab label
    icon: str           # tab emoji
    noun: str           # used in the empty-state hint ("No <noun> in the feed yet")
    env_key: str        # name of the .env var holding this feed's Toqan agent API key
    agent_name: str     # display name passed to the extractor
    max_age_days: int   # parser staleness cutoff + prune window for this feed
    tag_order: List[str]  # stable display order for tag chips (mirrors the prompt)
    # A cross-cutting *lens* (spans all sectors by design, e.g. Disruptive Tech)
    # rather than a sector. Excluded as a pole in the MOT convergence radar, where
    # it would otherwise bridge every real sector and drown out genuine seams.
    cross_cutting: bool = False

    @property
    def api_key(self) -> Optional[str]:
        """Toqan agent API key, read from the environment at call time."""
        return os.getenv(self.env_key)


FEEDS: List[Feed] = [
    Feed(
        key="ev",
        table="home_news_articles",
        label="EV",
        icon="⚡",
        noun="EV news",
        env_key="TOQAN_HOME_PAGE_NEWS",
        agent_name="EV News Agent",
        max_age_days=14,
        tag_order=[
            "launch", "sales", "earnings", "deal", "funding",
            "battery", "charging", "policy", "subsidy", "tariff",
            "supply-chain", "technology", "safety", "recall", "autonomy", "report",
        ],
    ),
    Feed(
        key="ai-energy",
        table="ai_energy_news_articles",
        label="AI & Energy",
        icon="🤖",
        noun="AI energy/environment news",
        env_key="TOQAN_AI_ENERGY_NEWS",
        agent_name="AI Energy Impact Agent",
        # This domain runs on reports/policy more than 72h breaking news, so the
        # window is wider than EV's.
        max_age_days=30,
        tag_order=[
            "energy-demand", "data-center", "electricity-price", "grid",
            "carbon", "water", "land", "efficiency", "renewables", "nuclear",
            "policy", "regulation", "infrastructure", "report",
        ],
    ),
    Feed(
        key="disruption",
        table="disruptive_tech_articles",
        label="Disruptive Tech",
        icon="🚀",
        noun="disruptive-tech news",
        env_key="TOQAN_DISRUPTIVE_TECH",
        agent_name="Disruptive Tech Agent",
        cross_cutting=True,   # a property-lens across all sectors, not a sector pole

        # Breakthroughs / funding / deep-tech move on an announcement cadence
        # rather than daily breaking news, so the window matches AI & Energy.
        max_age_days=30,
        tag_order=[
            "breakthrough", "product-launch", "new-entrant", "funding", "m&a",
            "partnership", "regulation", "standards", "research", "adoption",
            "incumbent-risk", "milestone",
        ],
    ),
    Feed(
        key="chips",
        table="semiconductor_news_articles",
        label="Chips",
        icon="🖥️",
        noun="semiconductor news",
        env_key="TOQAN_CHIPS_NEWS",
        agent_name="Semiconductor News Agent",
        max_age_days=21,
        tag_order=[
            "fab", "foundry", "node", "ai-accelerator", "memory", "packaging",
            "export-controls", "supply-chain", "capex", "m&a", "earnings", "research",
        ],
    ),
    Feed(
        key="geopolitics",
        table="geopolitics_trade_articles",
        label="Geopolitics & Trade",
        icon="🌐",
        noun="geopolitics & trade news",
        env_key="TOQAN_GEOPOLITICS_NEWS",
        agent_name="Geopolitics & Trade Agent",
        max_age_days=21,
        tag_order=[
            "tariff", "export-controls", "sanctions", "trade-deal", "supply-chain",
            "critical-minerals", "industrial-policy", "conflict", "alliance",
            "regulation", "report",
        ],
    ),
    Feed(
        key="climate",
        table="climate_energy_articles",
        label="Climate & Energy",
        icon="🌱",
        noun="climate & clean-energy news",
        env_key="TOQAN_CLIMATE_NEWS",
        agent_name="Climate & Clean Energy Agent",
        max_age_days=30,
        tag_order=[
            "solar", "wind", "grid", "hydrogen", "nuclear", "storage",
            "carbon-market", "policy", "subsidy", "emissions", "deal", "report",
        ],
    ),
    Feed(
        key="biotech",
        table="biotech_health_articles",
        label="Biotech & Health",
        icon="🧬",
        noun="biotech & health news",
        env_key="TOQAN_BIOTECH_NEWS",
        agent_name="Biotech & Health Agent",
        max_age_days=30,
        tag_order=[
            "approval", "trial", "gene-editing", "ai-drug-discovery", "diagnostics",
            "m&a", "funding", "regulation", "pandemic", "breakthrough", "research", "report",
        ],
    ),
    # ── Top-of-stack coverage: the software/digital, fintech, and defense layers ──
    Feed(
        key="software",
        table="software_security_articles",
        label="Software & Cyber",
        icon="💻",
        noun="software & cybersecurity news",
        env_key="TOQAN_SOFTWARE_NEWS",
        agent_name="Software & Cyber Agent",
        max_age_days=21,
        tag_order=[
            "ai-app", "saas", "dev-tools", "cloud", "cybersecurity", "breach",
            "open-source", "product-launch", "funding", "m&a", "earnings",
            "regulation", "research",
        ],
    ),
    Feed(
        key="fintech",
        table="fintech_articles",
        label="Fintech",
        icon="💳",
        noun="fintech & digital-asset news",
        env_key="TOQAN_FINTECH_NEWS",
        agent_name="Fintech & Digital Assets Agent",
        max_age_days=21,
        tag_order=[
            "payments", "banking", "lending", "digital-assets", "stablecoin",
            "crypto", "regtech", "product-launch", "funding", "m&a", "earnings",
            "regulation", "report",
        ],
    ),
    # ── Portfolio lens: company-first coverage of the Prosus group ──
    Feed(
        key="prosus",
        table="prosus_portfolio_articles",
        label="Prosus",
        icon="🧭",
        noun="Prosus portfolio news",
        env_key="TOQAN_PROSUS_NEWS",
        agent_name="Prosus Portfolio Agent",
        cross_cutting=True,   # a portfolio lens across sectors, not a sector pole
        max_age_days=14,      # operational/company news moves on a daily cadence
        tag_order=[
            "earnings", "competitor-move", "regulation", "funding", "m&a",
            "ipo", "product-launch", "expansion", "partnership",
            "market-share", "incident", "corporate", "report",
        ],
    ),
    Feed(
        key="defense",
        table="defense_space_articles",
        label="Defense & Space",
        icon="🛰️",
        noun="defense & space news",
        env_key="TOQAN_DEFENSE_NEWS",
        agent_name="Defense & Space Agent",
        max_age_days=30,
        tag_order=[
            "defense-tech", "dual-use", "space", "satellite", "launch", "drone",
            "autonomy", "procurement", "contract", "funding", "m&a", "policy", "report",
        ],
    ),
]

FEEDS_BY_KEY = {f.key: f for f in FEEDS}


def get_feed(key: str) -> Feed:
    """Look up a feed by its key; raises KeyError if unknown."""
    return FEEDS_BY_KEY[key]
