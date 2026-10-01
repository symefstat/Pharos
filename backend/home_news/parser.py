"""
Parse + validate the JSON array returned by the Home Page News Agent.

The agent is instructed to return ONLY a JSON array, but real-world LLM output
sometimes wraps the array in ```json fences or prose. We strip those defensively
before parsing, then validate each item against the expected schema.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional
from urllib.parse import urlparse, urlunparse

from toqan.json_utils import parse_json_array

logger = logging.getLogger(__name__)

# Query params that are tracking/attribution noise — stripped by
# `canonicalize_url` so the same story shared via different channels collapses
# to one row. Meaningful params (?v=, ?id=, ?p= …) are KEPT: some publishers
# key distinct articles on them, and stripping the whole query over-merges.
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "gbraid", "wbraid", "msclkid", "yclid",
    "mc_cid", "mc_eid", "igshid", "_hsenc", "_hsmi", "mkt_tok",
    "oly_enc_id", "oly_anon_id", "s_kwcid",
})


def _is_tracking_param(key: str) -> bool:
    k = key.lower()
    return k.startswith(_TRACKING_PARAM_PREFIXES) or k in _TRACKING_PARAMS


def canonicalize_url(url: str) -> str:
    """Canonical URL used for both dedup and storage (the upsert conflict key):
    lowercase scheme + host, drop the #fragment and known tracking params
    (utm_*, fbclid, …), and strip the trailing slash. Stays a full working URL —
    path/query case and meaningful query params are preserved. Pure; returns the
    input unchanged if urlparse can't handle it."""
    try:
        p = urlparse(url)
    except ValueError:
        return url
    query = "&".join(
        pair for pair in p.query.split("&")
        if pair and not _is_tracking_param(pair.split("=", 1)[0])
    )
    return urlunparse(
        (p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), p.params, query, "")
    )

# Identities of dropped/skipped items kept in run stats are capped so the
# feed_runs `metrics` JSONB payload stays small even on a pathological run.
DROPPED_ITEMS_CAP = 20

_BUSINESS_IMPACT_VALUES = ("material", "contextual", "none")
_SCOPE_VALUES = ("single-company", "sector", "regulatory", "comparison", "deal")
# Defaults applied when the agent omits the field, so new rows are always
# populated. 'contextual'/'single-company' are the conservative middle.
_DEFAULT_BUSINESS_IMPACT = "contextual"
_DEFAULT_SCOPE = "single-company"


@dataclass
class ParseStats:
    """Per-run drop accounting for the parse stage — what the agent returned vs
    what survived validation. Turns today's stdout-only losses into a queryable
    record (persisted to `feed_runs` via analytics/run_ledger.py). Pure.

      received           — items in the agent's JSON array
      parsed             — items that survived (== len(returned items))
      dropped_malformed  — failed schema validation (missing/bad required fields)
      dropped_dup        — a duplicate URL within the same batch
      dropped_stale      — older than the feed's max_age_days cutoff
      dropped_items      — WHICH items were dropped ({reason, url|title}), so
                           losses are auditable after the fact instead of living
                           only in stdout logs. Capped at DROPPED_ITEMS_CAP per
                           run; counters above stay exact past the cap.
    """
    received: int = 0
    parsed: int = 0
    dropped_malformed: int = 0
    dropped_dup: int = 0
    dropped_stale: int = 0
    dropped_items: List[dict] = field(default_factory=list)

    def note_drop(self, reason: str, url: Optional[str] = None,
                  title: Optional[str] = None) -> None:
        """Record a dropped item's identity (url and/or title + reason) for the
        run ledger. Identity only — the caller still bumps the matching counter.
        Silently stops appending past DROPPED_ITEMS_CAP so the payload stays small."""
        if len(self.dropped_items) >= DROPPED_ITEMS_CAP:
            return
        ident: dict = {"reason": reason}
        if url:
            ident["url"] = str(url)[:500]
        if title:
            ident["title"] = str(title)[:200]
        self.dropped_items.append(ident)

    def to_metrics(self) -> dict:
        """Flat dict for the run-ledger `metrics` JSONB column."""
        return {
            "received": self.received,
            "parsed": self.parsed,
            "dropped_malformed": self.dropped_malformed,
            "dropped_dup": self.dropped_dup,
            "dropped_stale": self.dropped_stale,
            "dropped_items": list(self.dropped_items),
        }


@dataclass
class HomeNewsItem:
    title: str
    summary: str
    url: str
    source_name: Optional[str] = None
    published_at: Optional[date] = None
    country: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    companies: List[str] = field(default_factory=list)
    sentiment: Optional[str] = None  # platform-oriented: positive / negative / neutral
    # business_impact: would an informed investor plausibly re-price the stock?
    #   material / contextual / none. Defaults to 'contextual' when the agent omits
    #   it (a safe middle ground — neither hidden from the stock view nor flagged
    #   as a re-pricing event).
    business_impact: Optional[str] = None
    # scope: why multiple companies are named — single-company / sector /
    #   regulatory / comparison. Defaults to 'single-company' when omitted.
    scope: Optional[str] = None
    image_url: Optional[str] = None  # populated by the writer's OG scrape
    # Per-field extraction provenance for the audit trail — how each stored field
    # was obtained: 'agent' (canonical key), 'keydrift' (an alternate key the agent
    # used), 'default' (we filled a safe default), 'missing' (omitted → stored null).
    # Powers the "show your work / cite this" trail; persisted as a JSONB column.
    provenance: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        return {
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "source_name": self.source_name,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "country": self.country,
            "tags": self.tags,
            "companies": self.companies,
            "sentiment": self.sentiment,
            "business_impact": self.business_impact,
            "scope": self.scope,
            "image_url": self.image_url,
            "provenance": self.provenance or None,
        }


def _entry_identity(entry) -> dict:
    """Best-effort {url, title} for a RAW (possibly malformed) agent entry, using
    the same drift keys `_build_item` accepts. Non-dict entries fall back to their
    repr as the title so even garbage rows stay identifiable in the ledger. Pure."""
    if not isinstance(entry, dict):
        return {"title": repr(entry)[:200]}
    url = entry.get("url") or entry.get("link") or entry.get("source_url") or None
    title = entry.get("title") or entry.get("headline") or None
    return {"url": url, "title": title}


def _field_provenance(entry: dict, *, sentiment_valid: bool, impact_defaulted: bool,
                      scope_defaulted: bool) -> dict:
    """Per-field extraction provenance for the audit trail. For each signal-bearing
    field, how the stored value was obtained:
      'agent'    — the agent supplied the canonical key with a usable value
      'keydrift' — supplied under an alternate key (e.g. 'headline' for title)
      'default'  — agent omitted/invalid → we filled a safe default
      'missing'  — omitted with no default → stored null
    Pure; mirrors the resolution order in `_build_item`."""
    def pick(canonical: str, *alts: str) -> str:
        # Mirrors _build_item's `entry.get(canonical) or entry.get(alt) or …`
        # selection (raw truthiness — whichever key is non-empty wins).
        if entry.get(canonical) not in (None, "", [], {}):
            return "agent"
        for a in alts:
            if entry.get(a) not in (None, "", [], {}):
                return "keydrift"
        return "missing"

    return {
        "title": pick("title", "headline"),
        "summary": pick("summary", "description"),
        "url": pick("url", "link", "source_url"),
        "source_name": pick("source_name", "source"),
        "published_at": pick("published_at", "date"),
        "country": pick("country"),
        "tags": pick("tags", "categories", "category"),
        "companies": pick("companies"),
        "sentiment": "agent" if sentiment_valid else "missing",
        "business_impact": "default" if impact_defaulted else "agent",
        "scope": "default" if scope_defaulted else "agent",
    }


class HomeNewsParser:
    """Parse the agent's raw answer into a list of HomeNewsItem."""

    def parse(self, raw: str, max_age_days: int = 7) -> List[HomeNewsItem]:
        """Parse the agent answer into validated items (drop-stats discarded).
        Thin wrapper over `parse_with_stats` — kept for the many callers/tests
        that only want the items."""
        return self.parse_with_stats(raw, max_age_days)[0]

    def parse_with_stats(
        self, raw: str, max_age_days: int = 7
    ) -> tuple[List[HomeNewsItem], ParseStats]:
        """Parse + validate, returning the items alongside a `ParseStats` count of
        what was dropped and why. The run-ledger uses the stats; `parse` ignores
        them. Same validation logic as before — only the accounting is new."""
        items_raw = parse_json_array(raw)
        cutoff = datetime.now().date() - timedelta(days=max_age_days)

        items: List[HomeNewsItem] = []
        seen_urls: set[str] = set()
        stats = ParseStats(received=len(items_raw))

        for entry in items_raw:
            try:
                item = self._build_item(entry)
            except ValueError as e:
                logger.warning("Dropping malformed item: %s — %s", e, entry)
                stats.dropped_malformed += 1
                stats.note_drop("malformed", **_entry_identity(entry))
                continue

            if item.url in seen_urls:
                logger.info("Dropping duplicate URL: %s", item.url)
                stats.dropped_dup += 1
                stats.note_drop("dup", url=item.url, title=item.title)
                continue
            if item.published_at and item.published_at < cutoff:
                logger.info("Dropping stale item (%s): %s", item.published_at, item.title)
                stats.dropped_stale += 1
                stats.note_drop("stale", url=item.url, title=item.title)
                continue

            seen_urls.add(item.url)
            items.append(item)

        stats.parsed = len(items)
        logger.info(
            "Parsed %d/%d items (dropped: %d malformed, %d dup, %d stale)",
            stats.parsed, stats.received,
            stats.dropped_malformed, stats.dropped_dup, stats.dropped_stale,
        )
        return items, stats

    def _build_item(self, entry: dict) -> HomeNewsItem:
        if not isinstance(entry, dict):
            raise ValueError("Item is not an object")

        # Tolerate common key drift from agents that don't follow the schema
        # exactly (e.g. 'headline' for 'title', 'link' for 'url'). `url` and
        # `summary` still can't be fabricated, so items lacking them are dropped.
        title = (entry.get("title") or entry.get("headline") or "").strip()
        summary = (entry.get("summary") or entry.get("description") or "").strip()
        url = (entry.get("url") or entry.get("link") or entry.get("source_url") or "").strip()

        missing = [n for n, v in (("title", title), ("summary", summary), ("url", url)) if not v]
        if missing:
            raise ValueError(f"Missing required field(s): {', '.join(missing)}")

        # Accept http or https (some outlets still serve http) — upgrade http to
        # https so stored links are secure; only reject non-web/relative URLs.
        parsed_url = urlparse(url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            raise ValueError(f"URL is not a canonical http(s) URL: {url}")
        if parsed_url.scheme == "http":
            url = "https://" + url[len("http://"):]
        # Canonicalize before dedup + storage so tracking-param / trailing-slash /
        # host-case variants of the same story collapse to one row (the live eval
        # found 53 slash-dup rows). Meaningful query params are kept.
        url = canonicalize_url(url)

        published_at: Optional[date] = None
        raw_date = entry.get("published_at") or entry.get("date")
        if raw_date:
            try:
                published_at = datetime.fromisoformat(str(raw_date)[:10]).date()
            except ValueError:
                raise ValueError(f"Bad published_at: {raw_date}")

        tags = entry.get("tags")
        if tags is None:
            tags = entry.get("categories") or entry.get("category") or []
        if not isinstance(tags, list):
            tags = [str(tags)]
        tags = [str(t).strip() for t in tags if str(t).strip()]

        # Dedupe companies case-insensitively while preserving the first-seen
        # casing — keeps "Uber"/"uber"/" Uber " from showing as three bars.
        raw_companies = entry.get("companies") or []
        if not isinstance(raw_companies, list):
            raw_companies = [str(raw_companies)]
        seen_lower: set[str] = set()
        companies: List[str] = []
        for c in raw_companies:
            name = str(c).strip()
            if not name:
                continue
            key = name.lower()
            if key in seen_lower:
                continue
            seen_lower.add(key)
            companies.append(name)

        sentiment = str(entry.get("sentiment") or "").strip().lower()
        if sentiment not in ("positive", "negative", "neutral"):
            sentiment = None  # tolerate missing/invalid — column is nullable

        # Materiality + scope: normalise, default when missing/invalid so new rows
        # are never blank (old DB rows stay NULL until re-fetched).
        impact = str(entry.get("business_impact") or "").strip().lower()
        impact_defaulted = impact not in _BUSINESS_IMPACT_VALUES
        business_impact = impact if not impact_defaulted else _DEFAULT_BUSINESS_IMPACT

        scope_raw = str(entry.get("scope") or "").strip().lower().replace("_", "-")
        scope_defaulted = scope_raw not in _SCOPE_VALUES
        scope = scope_raw if not scope_defaulted else _DEFAULT_SCOPE

        return HomeNewsItem(
            title=title,
            summary=summary,
            url=url,
            source_name=(entry.get("source_name") or entry.get("source") or None),
            published_at=published_at,
            country=(entry.get("country") or None),
            tags=tags,
            companies=companies,
            sentiment=sentiment,
            business_impact=business_impact,
            scope=scope,
            provenance=_field_provenance(
                entry, sentiment_valid=sentiment is not None,
                impact_defaulted=impact_defaulted, scope_defaulted=scope_defaulted),
        )
