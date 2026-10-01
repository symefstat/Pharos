"""
Portfolio-company matcher: tag feed articles with prosus_companies slugs.

The alias list comes from the `prosus_companies` table; matching itself is
pure so it can be unit-tested and reused by the write path
(home_news/writer.py) and the backfill (prosus_backfill.py).

Matching is deliberately conservative:
  - only companies with a non-empty `aliases` list are ever matched — ambiguous
    names (Rain, Honor, Ema, Oda, …) have aliases='{}' in the seed and are
    excluded here rather than patched with cleverness;
  - aliases match on word boundaries, case-insensitively, against the title,
    summary and the agent-extracted `companies` list. No fuzzy matching: a
    false tag on the Prosus page costs more trust than a missed one.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# One compiled pattern per company: (slug, pattern).
AliasIndex = List[Tuple[str, "re.Pattern[str]"]]


def build_alias_index(companies: Iterable[Dict]) -> AliasIndex:
    """Compile match patterns from prosus_companies rows (dicts with at least
    `slug`, `aliases`, `status`). Exited companies and empty alias lists are
    skipped. Pure."""
    index: AliasIndex = []
    for c in companies:
        aliases = [a for a in (c.get("aliases") or []) if a and a.strip()]
        if not aliases or c.get("status") == "exited":
            continue
        alternation = "|".join(re.escape(a.strip()) for a in
                               sorted(aliases, key=len, reverse=True))
        pattern = re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", re.IGNORECASE)
        index.append((c["slug"], pattern))
    return index


def match_prosus_tags(index: AliasIndex,
                      title: str | None,
                      summary: str | None,
                      companies: Sequence[str] | None = None) -> List[str]:
    """Slugs of portfolio companies mentioned in the article, sorted. Pure."""
    blob = " ".join(filter(None, [title, summary, " ".join(companies or [])]))
    if not blob:
        return []
    return sorted(slug for slug, pattern in index if pattern.search(blob))


def load_alias_index(client) -> Optional[AliasIndex]:
    """Read prosus_companies via the given Supabase client and build the index.
    None (not []) when the table is missing/unreadable or empty, so callers can
    distinguish "tagging unavailable" from "matched nothing" and skip tagging
    without failing the feed run."""
    try:
        rows = (client.table("prosus_companies")
                .select("slug,aliases,status")
                .execute().data or [])
    except Exception as e:
        logger.warning(
            "prosus_companies unavailable (%s) — feed rows will not get "
            "prosus_tags. Apply SQL Tables/prosus_companies.sql and run "
            "prosus_seed.py.", e,
        )
        return None
    if not rows:
        logger.warning(
            "prosus_companies is empty — feed rows will not get prosus_tags. "
            "Run prosus_seed.py.",
        )
        return None
    return build_alias_index(rows)
