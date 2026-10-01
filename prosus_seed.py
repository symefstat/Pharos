#!/usr/bin/env python3
"""
Seed / update the prosus_companies reference table.

The portfolio list below was researched against prosus.com/portfolio,
prosus.com/prosus-ventures and press coverage as of 2026-07-03. Tier 'core'
is controlled / major-stake group companies (first-class on the Prosus page);
tier 'ventures' is notable minority positions. It is a curated subset, not the
full ~90-company ventures book — extend ROWS as needed and re-run.

Alias rules (they ARE the matching surface — see prosus/matcher.py):
  - aliases must be distinctive enough for case-insensitive word-boundary
    matching in news text. Companies whose names are everyday words (Oda,
    Flink, Ema, Shipper, …) get aliases=[] — kept for reference, never
    auto-matched.
  - deliberately excluded aliases: 'Grubhub' (sold by JET to Wonder, 2024),
    'AutoTrader' (collides with the unrelated UK Auto Trader plc),
    'Storia' (Italian common word).

⚠️ Makes live Supabase writes (upsert on slug). Use --dry-run to preview.

  ./venv/bin/python prosus_seed.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# slug, name, aliases, segment, tier, regions, ownership, notes
ROWS: list[dict] = [
    # ---- Tier 1: core group companies -------------------------------------
    dict(slug="ifood", name="iFood", aliases=["iFood"],
         segment="food-delivery", tier="core", regions=["latam"],
         ownership="100%", notes="Brazil food delivery; wholly owned."),
    dict(slug="just-eat-takeaway", name="Just Eat Takeaway.com",
         aliases=["Just Eat Takeaway", "Just Eat", "Takeaway.com", "Lieferando",
                  "Thuisbezorgd", "Pyszne.pl", "Menulog", "SkipTheDishes"],
         segment="food-delivery", tier="core", regions=["europe"],
         ownership="98% (delisted Nov 2025)",
         notes="€4.1bn acquisition completed Oct 2025; delisted 17 Nov 2025. "
               "Grubhub NOT an alias — sold to Wonder in 2024."),
    dict(slug="swiggy", name="Swiggy", aliases=["Swiggy"],
         segment="food-delivery", tier="core", regions=["india"],
         ownership="minority (listed)", notes="India food delivery + Instamart."),
    dict(slug="delivery-hero", name="Delivery Hero",
         aliases=["Delivery Hero", "Glovo", "foodpanda", "Talabat"],
         segment="food-delivery", tier="core",
         regions=["europe", "mena", "sea"],
         ownership="stake — being reduced",
         notes="EU condition of the JET clearance (Aug 2025) requires "
               "significant reduction of this holding."),
    dict(slug="payu", name="PayU",
         aliases=["PayU", "iyzico", "LazyPay", "Wibmo"],
         segment="payments-fintech", tier="core",
         regions=["india", "europe", "sea"],
         ownership="majority",
         notes="India/Turkey/SEA focused since the Global Payments "
               "Organisation sale to Rapyd (Mar 2025)."),
    dict(slug="remitly", name="Remitly", aliases=["Remitly"],
         segment="payments-fintech", tier="core", regions=["us"],
         ownership="~12%", notes="Cross-border remittances; listed."),
    dict(slug="olx", name="OLX",
         aliases=["OLX", "Otodom", "OTOMOTO", "Autovit", "Standvirtual",
                  "Imovirtual", "Property24"],
         segment="classifieds", tier="core",
         regions=["europe", "latam", "africa"],
         ownership="subsidiary",
         notes="Incl. OLX Brazil and CEE property/auto brands. 'AutoTrader' "
               "and 'Storia' deliberately not aliases (collisions)."),
    dict(slug="stack-overflow", name="Stack Overflow",
         aliases=["Stack Overflow"],
         segment="edtech", tier="core", regions=["global"],
         ownership="wholly owned", notes=None),
    dict(slug="skillsoft", name="Skillsoft",
         aliases=["Skillsoft", "Codecademy"],
         segment="edtech", tier="core", regions=["us", "global"],
         ownership="stake", notes="Codecademy is a Skillsoft brand."),
    dict(slug="goodhabitz", name="GoodHabitz", aliases=["GoodHabitz"],
         segment="edtech", tier="core", regions=["europe"],
         ownership="majority", notes=None),
    dict(slug="emag", name="eMAG", aliases=["eMAG"],
         segment="ecommerce-travel", tier="core", regions=["europe"],
         ownership="~80%", notes="Romania/CEE etail."),
    dict(slug="despegar", name="Despegar", aliases=["Despegar", "Decolar"],
         segment="ecommerce-travel", tier="core", regions=["latam"],
         ownership="100%",
         notes="US$1.7bn acquisition closed May 2025; Decolar is the Brazil brand."),
    dict(slug="rapido", name="Rapido", aliases=["Rapido"],
         segment="mobility", tier="core", regions=["india"],
         ownership="~26%",
         notes="Led US$240m round May 2026 at $3bn valuation; Prosus+WestBridge "
               "hold 56% combined."),
    dict(slug="tencent", name="Tencent",
         aliases=["Tencent", "WeChat", "Weixin"],
         segment="internet", tier="core", regions=["china"],
         ownership="~23%", notes="The NAV anchor; not a segment-tab company."),

    # ---- Tier 2: notable ventures — India / South Asia ---------------------
    dict(slug="meesho", name="Meesho", aliases=["Meesho"],
         segment="ecommerce-travel", tier="ventures", regions=["india"],
         ownership="minority", notes=None),
    dict(slug="pharmeasy", name="PharmEasy", aliases=["PharmEasy"],
         segment="ecommerce-travel", tier="ventures", regions=["india"],
         ownership="minority", notes=None),
    dict(slug="urban-company", name="Urban Company", aliases=["Urban Company"],
         segment="ecommerce-travel", tier="ventures", regions=["india"],
         ownership="minority", notes="Home services marketplace."),
    dict(slug="mensa-brands", name="Mensa Brands", aliases=["Mensa Brands"],
         segment="ecommerce-travel", tier="ventures", regions=["india"],
         ownership="minority", notes="'Mensa' alone is not an alias (collision)."),
    dict(slug="elasticrun", name="ElasticRun", aliases=["ElasticRun"],
         segment="ecommerce-travel", tier="ventures", regions=["india"],
         ownership="minority", notes=None),
    dict(slug="dehaat", name="DeHaat", aliases=["DeHaat"],
         segment="ecommerce-travel", tier="ventures", regions=["india"],
         ownership="minority", notes="Agritech."),
    dict(slug="vegrow", name="Vegrow", aliases=["Vegrow"],
         segment="ecommerce-travel", tier="ventures", regions=["india"],
         ownership="minority", notes="Agri marketplace."),
    dict(slug="shopup", name="ShopUp", aliases=["ShopUp"],
         segment="ecommerce-travel", tier="ventures", regions=["other"],
         ownership="minority", notes="Bangladesh B2B commerce."),
    dict(slug="bykea", name="Bykea", aliases=["Bykea"],
         segment="mobility", tier="ventures", regions=["other"],
         ownership="minority", notes="Pakistan ride-hailing/logistics."),

    # ---- Tier 2: notable ventures — LatAm ----------------------------------
    dict(slug="creditas", name="Creditas", aliases=["Creditas"],
         segment="payments-fintech", tier="ventures", regions=["latam"],
         ownership="minority", notes=None),
    dict(slug="klar", name="Klar", aliases=["Klar"],
         segment="payments-fintech", tier="ventures", regions=["latam"],
         ownership="minority", notes="Mexico neobank."),
    dict(slug="kovi", name="Kovi", aliases=["Kovi"],
         segment="payments-fintech", tier="ventures", regions=["latam"],
         ownership="minority", notes="Auto finance, Brazil."),
    dict(slug="azos", name="Azos", aliases=["Azos"],
         segment="payments-fintech", tier="ventures", regions=["latam"],
         ownership="minority", notes="Insurtech, Brazil."),
    dict(slug="luzia", name="Luzia", aliases=["Luzia"],
         segment="frontier-tech", tier="ventures", regions=["latam"],
         ownership="minority", notes="Consumer AI assistant."),
    dict(slug="99minutos", name="99minutos", aliases=["99minutos"],
         segment="ecommerce-travel", tier="ventures", regions=["latam"],
         ownership="minority", notes="Last-mile logistics."),

    # ---- Tier 2: notable ventures — SEA / MENA -----------------------------
    dict(slug="bibit", name="Bibit", aliases=["Bibit"],
         segment="payments-fintech", tier="ventures", regions=["sea"],
         ownership="minority", notes="Indonesia investing app."),
    dict(slug="tonik", name="Tonik", aliases=["Tonik"],
         segment="payments-fintech", tier="ventures", regions=["sea"],
         ownership="minority", notes="Philippines neobank."),
    dict(slug="endowus", name="Endowus", aliases=["Endowus"],
         segment="payments-fintech", tier="ventures", regions=["sea"],
         ownership="minority", notes="Singapore wealth platform."),
    dict(slug="thndr", name="Thndr", aliases=["Thndr"],
         segment="payments-fintech", tier="ventures", regions=["mena"],
         ownership="minority", notes="Egypt investing app."),
    dict(slug="foodics", name="Foodics", aliases=["Foodics"],
         segment="food-delivery", tier="ventures", regions=["mena"],
         ownership="minority", notes="Restaurant tech."),

    # ---- Tier 2: notable ventures — US / Europe ----------------------------
    dict(slug="bilt-rewards", name="Bilt Rewards",
         aliases=["Bilt Rewards", "Bilt"],
         segment="payments-fintech", tier="ventures", regions=["us"],
         ownership="minority", notes=None),
    dict(slug="taktile", name="Taktile", aliases=["Taktile"],
         segment="payments-fintech", tier="ventures", regions=["us", "europe"],
         ownership="minority", notes="Risk decisioning."),
    dict(slug="sharebite", name="Sharebite", aliases=["Sharebite"],
         segment="food-delivery", tier="ventures", regions=["us"],
         ownership="minority", notes=None),
    dict(slug="dott", name="Dott", aliases=["Dott"],
         segment="mobility", tier="ventures", regions=["europe"],
         ownership="minority", notes="Micromobility."),
    dict(slug="oda", name="Oda", aliases=[],
         segment="food-delivery", tier="ventures", regions=["europe"],
         ownership="minority",
         notes="Norway groceries. Name too ambiguous to auto-match."),
    dict(slug="flink", name="Flink", aliases=[],
         segment="food-delivery", tier="ventures", regions=["europe"],
         ownership="minority",
         notes="Germany groceries. Not auto-matched — collides with Apache Flink."),

    # ---- Tier 2: notable ventures — edtech minorities ----------------------
    dict(slug="brainly", name="Brainly", aliases=["Brainly"],
         segment="edtech", tier="ventures", regions=["europe", "us"],
         ownership="minority", notes=None),
    dict(slug="gostudent", name="GoStudent", aliases=["GoStudent"],
         segment="edtech", tier="ventures", regions=["europe"],
         ownership="minority", notes=None),
    dict(slug="eruditus", name="Eruditus", aliases=["Eruditus"],
         segment="edtech", tier="ventures", regions=["india"],
         ownership="minority", notes=None),
    dict(slug="platzi", name="Platzi", aliases=["Platzi"],
         segment="edtech", tier="ventures", regions=["latam"],
         ownership="minority", notes=None),
    dict(slug="sololearn", name="Sololearn", aliases=["Sololearn"],
         segment="edtech", tier="ventures", regions=["global"],
         ownership="minority", notes=None),
    dict(slug="edume", name="eduMe", aliases=["eduMe"],
         segment="edtech", tier="ventures", regions=["europe"],
         ownership="minority", notes=None),

    # ---- Tier 2: notable ventures — frontier tech --------------------------
    dict(slug="oxford-ionics", name="Oxford Ionics", aliases=["Oxford Ionics"],
         segment="frontier-tech", tier="ventures", regions=["europe"],
         ownership="minority",
         notes="Quantum computing. IonQ acquisition announced 2025 — verify "
               "current holding before featuring."),
    dict(slug="cuspai", name="CuspAI", aliases=["CuspAI"],
         segment="frontier-tech", tier="ventures", regions=["europe"],
         ownership="minority", notes="AI materials discovery."),
    dict(slug="corti", name="Corti", aliases=["Corti"],
         segment="frontier-tech", tier="ventures", regions=["europe"],
         ownership="minority", notes="Healthcare AI."),
    dict(slug="watchtowr", name="watchTowr", aliases=["watchTowr"],
         segment="frontier-tech", tier="ventures", regions=["global"],
         ownership="minority", notes="Cybersecurity."),
    dict(slug="tierra-biosciences", name="Tierra Biosciences",
         aliases=["Tierra Biosciences"],
         segment="frontier-tech", tier="ventures", regions=["us"],
         ownership="minority", notes="Synthetic biology / proteins."),
    dict(slug="qosmic", name="QOSMIC", aliases=["QOSMIC"],
         segment="frontier-tech", tier="ventures", regions=["global"],
         ownership="minority", notes="Space communications."),
    dict(slug="fundamental-research-labs", name="Fundamental Research Labs",
         aliases=["Fundamental Research Labs"],
         segment="frontier-tech", tier="ventures", regions=["us"],
         ownership="minority", notes="AI agents."),
    dict(slug="similarweb", name="Similarweb",
         aliases=["Similarweb", "SimilarWeb"],
         segment="frontier-tech", tier="ventures", regions=["global"],
         ownership="minority", notes="Digital intelligence; listed."),
    dict(slug="ema", name="Ema", aliases=[],
         segment="frontier-tech", tier="ventures", regions=["us"],
         ownership="minority",
         notes="AI workplace automation. Name too ambiguous to auto-match."),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the rows without writing to Supabase")
    args = parser.parse_args()

    slugs = [r["slug"] for r in ROWS]
    if len(slugs) != len(set(slugs)):
        dupes = sorted({s for s in slugs if slugs.count(s) > 1})
        print(f"error: duplicate slugs in ROWS: {dupes}", file=sys.stderr)
        return 1

    if args.dry_run:
        for r in ROWS:
            matchable = "auto-match" if r["aliases"] else "manual-only"
            print(f"{r['tier']:8s} {r['segment']:18s} {r['slug']:28s} {matchable}")
        print(f"\n{len(ROWS)} rows (dry run — nothing written)")
        return 0

    from db import get_supabase
    client = get_supabase()
    resp = client.table("prosus_companies").upsert(ROWS, on_conflict="slug").execute()
    print(f"Upserted {len(resp.data or [])} rows into prosus_companies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
