#!/usr/bin/env python3
"""
Ingest funding rounds into the funding_rounds table (idempotent upsert).

Today's source is a CSV (the provider-agnostic path); a Dealroom/PitchBook API
client can slot into `load_rounds` later without touching validation or the
upsert. Usage:

    python backend/funding_run.py path/to/rounds.csv
    python backend/funding_run.py --template          # print the expected header + an example row

CSV columns (header required):
    tech_key      registry key from technologies.py (e.g. ai-datacenters)
    company       company name
    round_type    seed | series-a | series-b | series-c | series-c-plus | growth
                  | ipo | m&a | grant | debt | other  (common aliases normalized)
    amount_usd    number, or empty for undisclosed
    announced_on  YYYY-MM-DD
    source_url    optional link to the announcement
    investors     optional, ';'-separated

Rows with an unknown tech_key or unparseable date are rejected and listed —
nothing invalid reaches the table. Apply 'database/schema/funding_rounds.sql' first.
"""

from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

from config import Config

logger = logging.getLogger("funding_run")

TEMPLATE = (
    "tech_key,company,round_type,amount_usd,announced_on,source_url,investors\n"
    "ai-datacenters,ExampleCo,series-b,120000000,2026-05-14,"
    "https://example.com/announcement,Investor One;Investor Two\n"
)

# Common provider spellings → the canonical vocabulary funding.py reasons over.
_ROUND_ALIASES = {
    "pre-seed": "seed", "preseed": "seed", "angel": "seed", "seed": "seed",
    "series a": "series-a", "series-a": "series-a", "a": "series-a",
    "series b": "series-b", "series-b": "series-b", "b": "series-b",
    "series c": "series-c-plus", "series-c": "series-c-plus",
    "series c+": "series-c-plus", "series-c-plus": "series-c-plus",
    "series d": "series-c-plus", "series-d": "series-c-plus",
    "series e": "series-c-plus", "series-e": "series-c-plus",
    "late stage": "series-c-plus", "late-stage": "series-c-plus",
    "growth": "growth", "growth equity": "growth", "private equity": "growth",
    "pe": "growth",
    "ipo": "ipo", "spac": "ipo",
    "m&a": "m&a", "acquisition": "m&a", "merger": "m&a", "buyout": "m&a",
    "grant": "grant", "debt": "debt", "loan": "debt", "convertible": "debt",
}


def normalize_round(raw: str) -> str:
    return _ROUND_ALIASES.get((raw or "").strip().lower(), "other")


def parse_csv(path: Path, valid_keys: set[str]) -> tuple[list[dict], list[str]]:
    """(valid_rows, rejects) — pure given the file contents; unit-tested."""
    rows: list[dict] = []
    rejects: list[str] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for i, rec in enumerate(csv.DictReader(f), start=2):  # 1 = header
            key = (rec.get("tech_key") or "").strip()
            company = (rec.get("company") or "").strip()
            announced = (rec.get("announced_on") or "").strip()
            if key not in valid_keys:
                rejects.append(f"line {i}: unknown tech_key '{key}'")
                continue
            if not company:
                rejects.append(f"line {i}: missing company")
                continue
            if len(announced) != 10 or announced[4] != "-" or announced[7] != "-":
                rejects.append(f"line {i}: announced_on must be YYYY-MM-DD, got '{announced}'")
                continue
            raw_amount = (rec.get("amount_usd") or "").strip()
            try:
                amount = float(raw_amount) if raw_amount else None
            except ValueError:
                rejects.append(f"line {i}: amount_usd is not a number: '{raw_amount}'")
                continue
            investors = [x.strip() for x in (rec.get("investors") or "").split(";") if x.strip()]
            rows.append({
                "tech_key": key,
                "company": company,
                "round_type": normalize_round(rec.get("round_type") or ""),
                "amount_usd": amount,
                "announced_on": announced,
                "investors": investors or None,
                "source": f"csv:{path.name}",
                "source_url": (rec.get("source_url") or "").strip() or None,
            })
    return rows, rejects


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    if len(sys.argv) == 2 and sys.argv[1] == "--template":
        print(TEMPLATE, end="")
        return 0
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    path = Path(sys.argv[1])
    if not path.exists():
        logger.error("No such file: %s", path)
        return 1

    load_dotenv()
    try:
        Config.validate()
    except ValueError as e:
        logger.error("%s — set them in .env before running.", e)
        return 1

    from db import get_supabase
    from technologies import registry

    client = get_supabase()
    valid_keys = {t.key for t in registry(client)}
    rows, rejects = parse_csv(path, valid_keys)
    for r in rejects:
        logger.warning("REJECTED %s", r)
    if not rows:
        logger.error("No valid rows in %s (%d rejected).", path, len(rejects))
        return 1

    from analytics.funding import FUNDING_TABLE

    try:
        client.table(FUNDING_TABLE).upsert(
            rows, on_conflict="tech_key,company,round_type,announced_on"
        ).execute()
    except Exception as e:
        logger.error("Upsert failed (%s) — is 'database/schema/funding_rounds.sql' applied?", e)
        return 1
    logger.info("Ingested %d round(s) from %s (%d rejected).", len(rows), path, len(rejects))
    return 0


if __name__ == "__main__":
    sys.exit(main())
