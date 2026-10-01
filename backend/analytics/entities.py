"""
Lightweight company/entity name normalization for cross-feed aggregation.

The same player shows up across feeds under different surface forms
("Google" / "Alphabet" / "DeepMind"). Collapsing them to one canonical name is
what makes cross-feed entity tracking and the "top companies" stats accurate.

This is intentionally a simple, extensible alias map — not NER. Add entries as
you see drift in the data. Unknown names pass through with whitespace trimmed.
"""

from __future__ import annotations

import re

# Canonical display name -> alias surface forms (compared lower-cased). Descriptive
# multi-word variants ("Palantir Technologies") are listed explicitly; generic legal
# suffixes ("Inc", "Corp", "plc"…) are stripped automatically by `normalize`, so they
# don't need an alias each.
_ALIASES: dict[str, list[str]] = {
    "Alphabet (Google)": ["google", "alphabet", "google deepmind", "deepmind", "waymo"],
    "Microsoft": ["microsoft", "msft", "azure", "github"],
    "Amazon": ["amazon", "aws", "amazon web services"],
    "Meta": ["meta", "facebook", "meta platforms"],
    "Nvidia": ["nvidia", "nvda"],
    "OpenAI": ["openai"],
    "Anthropic": ["anthropic"],
    "Apple": ["apple"],
    "TSMC": ["tsmc", "taiwan semiconductor", "taiwan semiconductor manufacturing"],
    "Samsung": ["samsung", "samsung electronics"],
    "SK Hynix": ["sk hynix", "hynix"],
    "Intel": ["intel"],
    "AMD": ["amd", "advanced micro devices"],
    "ASML": ["asml"],
    "Qualcomm": ["qualcomm"],
    "Broadcom": ["broadcom"],
    "Arm": ["arm", "arm holdings"],
    "Tesla": ["tesla"],
    "BYD": ["byd"],
    "Volkswagen": ["volkswagen", "vw", "volkswagen group"],
    "Toyota": ["toyota", "toyota motor"],
    "CATL": ["catl", "contemporary amperex"],
    "Ford": ["ford", "ford motor"],
    "General Motors": ["general motors", "gm"],
    "Eli Lilly": ["eli lilly", "lilly"],
    "Novo Nordisk": ["novo nordisk", "novo"],
    "Pfizer": ["pfizer"],
    "Moderna": ["moderna"],
    "Roche": ["roche"],
    "NextEra Energy": ["nextera", "nextera energy"],
    "Ørsted": ["orsted", "ørsted"],
    "First Solar": ["first solar"],
    "Constellation Energy": ["constellation", "constellation energy"],
    # Software & Cyber / Fintech / Defense & Space — variant surface forms
    "Oracle": ["oracle"],
    "Salesforce": ["salesforce"],
    "ServiceNow": ["servicenow", "service now"],
    "Adobe": ["adobe"],
    "Palantir": ["palantir", "palantir technologies"],
    "CrowdStrike": ["crowdstrike", "crowdstrike holdings"],
    "Palo Alto Networks": ["palo alto networks", "palo alto"],
    "Snowflake": ["snowflake"],
    "Block": ["block", "square", "block inc"],
    "PayPal": ["paypal"],
    "Coinbase": ["coinbase", "coinbase global"],
    "Robinhood": ["robinhood", "robinhood markets"],
    "Nubank": ["nubank", "nu holdings"],
    "RTX": ["rtx", "raytheon", "raytheon technologies"],
    "Lockheed Martin": ["lockheed martin", "lockheed"],
    "Northrop Grumman": ["northrop grumman", "northrop"],
    "BAE Systems": ["bae systems", "bae"],
    "Rocket Lab": ["rocket lab", "rocket lab usa"],
    "Planet Labs": ["planet labs", "planet"],
    # ── widened universe (see tickers.py): descriptive variants for the new names ──
    "Texas Instruments": ["texas instruments", "ti"],
    "Applied Materials": ["applied materials"],
    "Marvell": ["marvell", "marvell technology"],
    "Micron": ["micron", "micron technology"],
    "IBM": ["ibm", "international business machines"],
    "Cisco": ["cisco", "cisco systems"],
    "Cloudflare": ["cloudflare"],
    "Datadog": ["datadog"],
    "Shopify": ["shopify"],
    "Fortinet": ["fortinet"],
    "Rivian": ["rivian", "rivian automotive"],
    "NIO": ["nio"],
    "Stellantis": ["stellantis"],
    "Merck": ["merck", "merck & co"],
    "Johnson & Johnson": ["johnson & johnson", "johnson and johnson", "j&j", "jnj"],
    "AstraZeneca": ["astrazeneca"],
    "AbbVie": ["abbvie"],
    "Enphase Energy": ["enphase", "enphase energy"],
    "GE Vernova": ["ge vernova", "vernova"],
    "American Express": ["american express", "amex"],
    "Affirm": ["affirm", "affirm holdings"],
    "L3Harris": ["l3harris", "l3 harris", "l3harris technologies"],
    "Airbus": ["airbus"],
    # ── capital-audit shortlist (see tickers.py): most-mentioned public untracked ──
    "Circle": ["circle", "circle internet group", "circle internet financial"],
    "Klarna": ["klarna", "klarna group", "klarna bank"],
    "RWE": ["rwe"],
    "BlackRock": ["blackrock"],
    "BMW": ["bmw", "bayerische motoren werke"],
    "XPeng": ["xpeng", "xpeng motors", "xiaopeng", "xiaopeng motors"],
    "Intellia Therapeutics": ["intellia", "intellia therapeutics"],
    "IQM": ["iqm", "iqm quantum computers", "iqm quantum"],
}

# Reverse lookup: alias (lower) -> canonical.
_LOOKUP: dict[str, str] = {
    alias: canonical for canonical, aliases in _ALIASES.items() for alias in aliases
}

# Trailing legal / corporate designators, stripped before matching so "Alphabet
# Inc.", "Block Inc", "Stellantis N.V." collapse to their canonical. Deliberately a
# tight set of unambiguous legal forms — NOT descriptive words ("Networks"/"Motor"/
# "Energy"), NOT "Group" (part of many brand names: SoftBank Group, Tata Group), and
# NOT country-specific forms that distinguish real companies ("KGaA" separates Merck
# KGaA from the US Merck & Co; "AB"/"OYJ"/etc. are part of Nordic brand names).
_SUFFIX_RE = re.compile(
    r"[\s,]+(?:inc|incorporated|corp|corporation|co|company|ltd|limited|"
    r"l\.?l\.?c|p\.?l\.?c|a\.?g|s\.?e|s\.?a|n\.?v|gmbh|holdings?)\.?$",
    re.IGNORECASE,
)


def normalize(name: str) -> str:
    """Canonical name for `name`: alias hit → canonical; else strip trailing legal
    designators ONE AT A TIME, re-checking the alias map after each strip (so an
    alias-bearing intermediate like "Nu Holdings" wins before a further "Ltd" is
    removed); else the trimmed, suffix-stripped original. Suffix-stripping widens how
    many feed surface-forms collapse to one entity (and resolve to a ticker)."""
    if not name:
        return ""
    s = name.strip()
    if s.lower() in _LOOKUP:
        return _LOOKUP[s.lower()]
    prev = None
    while s != prev:
        prev = s
        stripped = _SUFFIX_RE.sub("", s).strip().rstrip(".,&").strip()
        if stripped == s:
            break                         # no trailing legal form left
        s = stripped
        if s.lower() in _LOOKUP:          # alias-bearing intermediate wins
            return _LOOKUP[s.lower()]
    return s or name.strip()
