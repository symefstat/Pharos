"""
arXiv source for Radar — the research-stage evidence stream.

News lags research by years; abstracts in the categories below are where a
technology first becomes nameable. Fetched via the free arXiv Atom API (no
auth; ~1 request per category with polite pacing per their ToS), parsed into
rows shaped like stories so the Radar pipeline treats them uniformly — the
`_radar_kind: "paper"` marker is what separates the research gate from the
news gate downstream. Fail-open everywhere: an arXiv outage costs Radar its
research signal for one scan, never the scan itself.

parse_feed is pure (unit-tested on a fixture); fetch_recent does the HTTP.
"""

from __future__ import annotations

import logging
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

API_URL = "http://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"

# Categories chosen to shadow Lodestar's domains: emerging compute (cs.ET),
# hardware (cs.AR), AI (cs.AI), robotics (cs.RO), quantum (quant-ph),
# materials/energy (cond-mat.mtrl-sci), applied physics (physics.app-ph).
CATEGORIES = ["cs.ET", "cs.AR", "cs.AI", "cs.RO",
              "quant-ph", "cond-mat.mtrl-sci", "physics.app-ph"]

_PACE_S = float(os.getenv("ARXIV_PACE_S", "").strip() or 3.0)
_TIMEOUT_S = 20


def parse_feed(xml_text: str) -> list[dict]:
    """Atom feed → story-shaped paper rows (pure). Bad XML → []."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out: list[dict] = []
    for e in root.findall(f"{_ATOM}entry"):
        title = " ".join((e.findtext(f"{_ATOM}title") or "").split())
        summary = " ".join((e.findtext(f"{_ATOM}summary") or "").split())
        url = e.findtext(f"{_ATOM}id") or None
        published = e.findtext(f"{_ATOM}published") or None
        cat_el = e.find(f"{_ARXIV}primary_category")
        cat = cat_el.get("term") if cat_el is not None else None
        if not title:
            continue
        out.append({
            "title": title,
            "summary": summary[:600],
            "url": url,
            "published_at": published,
            "source_name": f"arXiv ({cat})" if cat else "arXiv",
            "_feed_label": "arXiv",
            "tags": [],
            "companies": [],
            "_radar_kind": "paper",
        })
    return out


def fetch_recent(days: int = 30, per_category: int = 80,
                 categories: list[str] | None = None) -> list[dict]:
    """Recent abstracts across the categories, deduped by arXiv id and
    filtered to the window. Each category degrades independently."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    seen: set[str] = set()
    papers: list[dict] = []
    for i, cat in enumerate(categories or CATEGORIES):
        if i:
            time.sleep(_PACE_S)  # arXiv ToS: no bursts
        q = urllib.parse.urlencode({
            "search_query": f"cat:{cat}",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": per_category,
        })
        try:
            with urllib.request.urlopen(f"{API_URL}?{q}", timeout=_TIMEOUT_S) as r:
                rows = parse_feed(r.read().decode("utf-8", errors="replace"))
        except Exception as e:
            logger.warning("arXiv fetch failed for %s: %s", cat, e)
            continue
        for p in rows:
            pid = p.get("url") or p["title"]
            if pid in seen or str(p.get("published_at") or "")[:10] < cutoff:
                continue
            seen.add(pid)
            papers.append(p)
    return papers
