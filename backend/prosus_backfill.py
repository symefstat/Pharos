#!/usr/bin/env python3
"""
Backfill prosus_tags on existing feed articles.

New articles are tagged at write time by home_news/writer.py; this script
tags the rows that were written before the Prosus lens existed. Reads the
alias index from prosus_companies, scans every feed table (title + summary +
agent-extracted companies), and updates rows whose computed tags differ from
what is stored.

Prereqs: database/schema/prosus_companies.sql applied, prosus_seed.py run, and
database/migrations/2026-07-03_prosus_tags.sql applied.

⚠️ Makes live Supabase writes. Use --dry-run first.

  ./venv/bin/python backend/prosus_backfill.py [--feed KEY] [--dry-run] [--page-size 500]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from db import get_supabase, is_missing_column_error
from feeds import FEEDS
from prosus.matcher import load_alias_index, match_prosus_tags

_COLS = "id,title,summary,companies,prosus_tags"


def backfill_table(client, table: str, index, page_size: int,
                   dry_run: bool) -> tuple[int, int]:
    """Tag one feed table. Returns (rows_scanned, rows_updated)."""
    scanned = updated = 0
    offset = 0
    while True:
        try:
            rows = (client.table(table).select(_COLS)
                    .order("id").range(offset, offset + page_size - 1)
                    .execute().data or [])
        except Exception as e:
            if is_missing_column_error(e, "prosus_tags"):
                print(f"  {table}: no prosus_tags column — apply "
                      f"database/migrations/2026-07-03_prosus_tags.sql first", file=sys.stderr)
                return scanned, updated
            raise
        if not rows:
            break
        for row in rows:
            scanned += 1
            tags = match_prosus_tags(index, row.get("title"),
                                     row.get("summary"), row.get("companies"))
            if tags == sorted(row.get("prosus_tags") or []):
                continue
            updated += 1
            if dry_run:
                print(f"  would tag {table}#{row['id']}: {tags}  "
                      f"({(row.get('title') or '')[:70]})")
            else:
                (client.table(table).update({"prosus_tags": tags})
                 .eq("id", row["id"]).execute())
        if len(rows) < page_size:
            break
        offset += page_size
    return scanned, updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--feed", help="only this feed key (see feeds.py)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without writing")
    parser.add_argument("--page-size", type=int, default=500)
    args = parser.parse_args()

    client = get_supabase()
    index = load_alias_index(client)
    if index is None:
        print("error: prosus_companies unavailable or empty — apply "
              "database/schema/prosus_companies.sql and run prosus_seed.py",
              file=sys.stderr)
        return 1

    total_scanned = total_updated = 0
    for feed in FEEDS:
        if args.feed and feed.key != args.feed:
            continue
        print(f"{feed.key} ({feed.table}) …")
        scanned, updated = backfill_table(client, feed.table, index,
                                          args.page_size, args.dry_run)
        print(f"  {scanned} scanned, {updated} "
              f"{'to update' if args.dry_run else 'updated'}")
        total_scanned += scanned
        total_updated += updated

    verb = "would update" if args.dry_run else "updated"
    print(f"\nDone: {total_scanned} rows scanned, {verb} {total_updated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
