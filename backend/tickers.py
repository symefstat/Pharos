"""
Curated entity → stock-ticker registry for financial enrichment.

Keyed by the *canonical* entity names that ``analytics.entities.normalize()``
emits, so feed company mentions ("Google", "Taiwan Semiconductor") resolve to the
right ticker. Only companies listed here ever get financial numbers — everything
else degrades silently. Private companies (OpenAI, Anthropic) are intentionally
absent: no ticker, no fabricated figures.

Symbols use yfinance symbology (ADR or primary listing, whichever yfinance serves
most reliably). R&D intensity is a ratio, so mixed-currency filings stay
comparable. Extend this as the tracked universe grows — mirror new canonical
names from ``analytics.entities._ALIASES``.
"""

from __future__ import annotations

from dataclasses import dataclass

from analytics.entities import normalize


@dataclass(frozen=True)
class Ticker:
    entity: str    # canonical entity name (entities.normalize output)
    symbol: str    # yfinance ticker
    exchange: str  # human label, for provenance
    sector: str    # coarse sector, colours the Capital investment-landscape 2×2


TICKERS: list[Ticker] = [
    Ticker("Alphabet (Google)", "GOOGL", "NASDAQ", "Big Tech & AI"),
    Ticker("Microsoft", "MSFT", "NASDAQ", "Big Tech & AI"),
    Ticker("Amazon", "AMZN", "NASDAQ", "Big Tech & AI"),
    Ticker("Meta", "META", "NASDAQ", "Big Tech & AI"),
    Ticker("Apple", "AAPL", "NASDAQ", "Big Tech & AI"),
    Ticker("Nvidia", "NVDA", "NASDAQ", "Chips"),
    Ticker("TSMC", "TSM", "NYSE (ADR)", "Chips"),
    Ticker("Samsung", "005930.KS", "KRX", "Chips"),
    Ticker("SK Hynix", "000660.KS", "KRX", "Chips"),
    Ticker("Intel", "INTC", "NASDAQ", "Chips"),
    Ticker("AMD", "AMD", "NASDAQ", "Chips"),
    Ticker("ASML", "ASML", "NASDAQ (ADR)", "Chips"),
    Ticker("Qualcomm", "QCOM", "NASDAQ", "Chips"),
    Ticker("Broadcom", "AVGO", "NASDAQ", "Chips"),
    Ticker("Arm", "ARM", "NASDAQ", "Chips"),
    Ticker("Tesla", "TSLA", "NASDAQ", "Auto & EV"),
    Ticker("BYD", "BYDDY", "OTC (ADR)", "Auto & EV"),
    Ticker("Volkswagen", "VWAGY", "OTC (ADR)", "Auto & EV"),
    Ticker("Toyota", "TM", "NYSE (ADR)", "Auto & EV"),
    Ticker("CATL", "300750.SZ", "SZSE", "Auto & EV"),
    Ticker("Ford", "F", "NYSE", "Auto & EV"),
    Ticker("General Motors", "GM", "NYSE", "Auto & EV"),
    Ticker("Eli Lilly", "LLY", "NYSE", "Biotech & Health"),
    Ticker("Novo Nordisk", "NVO", "NYSE (ADR)", "Biotech & Health"),
    Ticker("Pfizer", "PFE", "NYSE", "Biotech & Health"),
    Ticker("Moderna", "MRNA", "NASDAQ", "Biotech & Health"),
    Ticker("Roche", "RHHBY", "OTC (ADR)", "Biotech & Health"),
    Ticker("NextEra Energy", "NEE", "NYSE", "Energy"),
    Ticker("Ørsted", "DNNGY", "OTC (ADR)", "Energy"),
    Ticker("First Solar", "FSLR", "NASDAQ", "Energy"),
    Ticker("Constellation Energy", "CEG", "NASDAQ", "Energy"),
    # ── Software & Cyber (top of the AI stack: enterprise SaaS, AI apps, security) ──
    Ticker("Oracle", "ORCL", "NYSE", "Software & Cyber"),
    Ticker("Salesforce", "CRM", "NYSE", "Software & Cyber"),
    Ticker("SAP", "SAP", "NYSE (ADR)", "Software & Cyber"),
    Ticker("ServiceNow", "NOW", "NYSE", "Software & Cyber"),
    Ticker("Adobe", "ADBE", "NASDAQ", "Software & Cyber"),
    Ticker("Palantir", "PLTR", "NASDAQ", "Software & Cyber"),
    Ticker("CrowdStrike", "CRWD", "NASDAQ", "Software & Cyber"),
    Ticker("Palo Alto Networks", "PANW", "NASDAQ", "Software & Cyber"),
    Ticker("Snowflake", "SNOW", "NYSE", "Software & Cyber"),
    # ── Fintech & digital assets ──
    Ticker("Visa", "V", "NYSE", "Fintech"),
    Ticker("Mastercard", "MA", "NYSE", "Fintech"),
    Ticker("PayPal", "PYPL", "NASDAQ", "Fintech"),
    Ticker("Block", "XYZ", "NYSE", "Fintech"),
    Ticker("Coinbase", "COIN", "NASDAQ", "Fintech"),
    Ticker("Robinhood", "HOOD", "NASDAQ", "Fintech"),
    Ticker("SoFi", "SOFI", "NASDAQ", "Fintech"),
    Ticker("Nubank", "NU", "NYSE", "Fintech"),
    # ── Defense & Space ──
    Ticker("Lockheed Martin", "LMT", "NYSE", "Defense & Space"),
    Ticker("RTX", "RTX", "NYSE", "Defense & Space"),
    Ticker("Northrop Grumman", "NOC", "NYSE", "Defense & Space"),
    Ticker("General Dynamics", "GD", "NYSE", "Defense & Space"),
    Ticker("Boeing", "BA", "NYSE", "Defense & Space"),
    Ticker("BAE Systems", "BAESY", "OTC (ADR)", "Defense & Space"),
    Ticker("Rocket Lab", "RKLB", "NASDAQ", "Defense & Space"),
    Ticker("Planet Labs", "PL", "NYSE", "Defense & Space"),
    Ticker("AeroVironment", "AVAV", "NASDAQ", "Defense & Space"),
    # ── Widened universe (data-driven, see ticker_coverage). High-confidence public
    #    names the feeds frequently mention; symbols in yfinance symbology. ──
    Ticker("Micron", "MU", "NASDAQ", "Chips"),
    Ticker("Texas Instruments", "TXN", "NASDAQ", "Chips"),
    Ticker("Applied Materials", "AMAT", "NASDAQ", "Chips"),
    Ticker("Marvell", "MRVL", "NASDAQ", "Chips"),
    Ticker("IBM", "IBM", "NYSE", "Big Tech & AI"),
    Ticker("Cisco", "CSCO", "NASDAQ", "Big Tech & AI"),
    Ticker("Cloudflare", "NET", "NYSE", "Software & Cyber"),
    Ticker("Datadog", "DDOG", "NASDAQ", "Software & Cyber"),
    Ticker("Shopify", "SHOP", "NYSE", "Software & Cyber"),
    Ticker("Fortinet", "FTNT", "NASDAQ", "Software & Cyber"),
    Ticker("Rivian", "RIVN", "NASDAQ", "Auto & EV"),
    Ticker("NIO", "NIO", "NYSE (ADR)", "Auto & EV"),
    Ticker("Stellantis", "STLA", "NYSE", "Auto & EV"),
    Ticker("Merck", "MRK", "NYSE", "Biotech & Health"),
    Ticker("Johnson & Johnson", "JNJ", "NYSE", "Biotech & Health"),
    Ticker("AstraZeneca", "AZN", "NASDAQ (ADR)", "Biotech & Health"),
    Ticker("AbbVie", "ABBV", "NYSE", "Biotech & Health"),
    Ticker("Enphase Energy", "ENPH", "NASDAQ", "Energy"),
    Ticker("GE Vernova", "GEV", "NYSE", "Energy"),
    Ticker("American Express", "AXP", "NYSE", "Fintech"),
    Ticker("Affirm", "AFRM", "NASDAQ", "Fintech"),
    Ticker("L3Harris", "LHX", "NYSE", "Defense & Space"),
    Ticker("Airbus", "EADSY", "OTC (ADR)", "Defense & Space"),
    # ── Capital-audit shortlist (backend/eval/reports/41_capital_audit.md §5): the 7 public
    #    companies among the top-15 most-mentioned untracked entities (~93 mentions;
    #    lifts feed coverage ~39.7% → ~44%). The private giants (SpaceX, Anthropic,
    #    OpenAI, …) stay out per the no-fabricated-figures rule above. `.DE` symbols
    #    are the XETRA primary listings (EUR reporters) in yfinance symbology. ──
    Ticker("Circle", "CRCL", "NYSE", "Fintech"),
    Ticker("Klarna", "KLAR", "NYSE", "Fintech"),
    Ticker("RWE", "RWE.DE", "XETRA", "Energy"),
    Ticker("BlackRock", "BLK", "NYSE", "Fintech"),
    Ticker("BMW", "BMW.DE", "XETRA", "Auto & EV"),
    Ticker("XPeng", "XPEV", "NYSE (ADR)", "Auto & EV"),
    Ticker("Intellia Therapeutics", "NTLA", "NASDAQ", "Biotech & Health"),
]

TICKER_BY_ENTITY: dict[str, Ticker] = {normalize(t.entity): t for t in TICKERS}
TICKER_BY_SYMBOL: dict[str, Ticker] = {t.symbol: t for t in TICKERS}


def ticker_for(entity_name: str) -> Ticker | None:
    """Resolve a (possibly aliased) company name to its Ticker, or None if untracked."""
    return TICKER_BY_ENTITY.get(normalize(entity_name))


def ticker_coverage(rows: list[dict], top_gaps: int = 12) -> dict:
    """How well the registry covers the companies the feeds actually mention.

    Counts company mentions (normalized, de-duped within each story) and splits them
    into *tracked* (resolves to a Ticker) vs *untracked*, then ranks the most-mentioned
    untracked companies — the data-driven shortlist for widening the universe past the
    hand-picked set, rather than guessing. Pure: uses this module's normalize +
    ticker_for, no network."""
    from collections import Counter

    tracked: Counter = Counter()
    untracked: Counter = Counter()
    for r in rows:
        seen: set = set()
        for comp in (r.get("companies") or []):
            nm = normalize(str(comp))
            if not nm or nm in seen:
                continue
            seen.add(nm)
            (tracked if ticker_for(nm) else untracked)[nm] += 1

    n_tracked, n_untracked = sum(tracked.values()), sum(untracked.values())
    total = n_tracked + n_untracked
    return {
        "mentions": total,
        "tracked_mentions": n_tracked,
        "untracked_mentions": n_untracked,
        "coverage": round(n_tracked / total, 3) if total else None,
        "tracked_entities": len(tracked),
        "untracked_entities": len(untracked),
        "top_untracked": untracked.most_common(top_gaps),
    }
