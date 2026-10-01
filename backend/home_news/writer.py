"""
Supabase writer for home_news_articles.
Upserts rows on URL conflict and prunes rows older than the configured cutoff.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import requests
from supabase import Client

from config import Config
from db import get_supabase, is_missing_column_error
from feeds import FEEDS
from prosus.matcher import load_alias_index, match_prosus_tags
from .parser import DROPPED_ITEMS_CAP, HomeNewsItem

logger = logging.getLogger(__name__)

_PROVENANCE_COL = "provenance"
_PROSUS_COL = "prosus_tags"

# Optional columns the upsert degrades on when their migration hasn't been
# applied yet (strip + retry), with the file to apply to stop the stripping.
_OPTIONAL_COL_HINTS = {
    _PROVENANCE_COL: "database/schema/feed_provenance_column.sql",
    _PROSUS_COL: "database/migrations/2026-07-03_prosus_tags.sql",
}


# Shared pending-column predicate — moved to db.py so financials_run.py can use
# the same degrade pattern for its optional columns; re-exported under the old
# name for existing imports/tests.
_is_missing_column_error = is_missing_column_error


# Two regexes because <meta> attribute order is not fixed.
_OG_RE_FORWARD = re.compile(
    r'<meta[^>]+(?:property|name)\s*=\s*["\']'
    r'(?:og:image(?::secure_url)?|twitter:image(?::src)?)'
    r'["\'][^>]*content\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_RE_REVERSE = re.compile(
    r'<meta[^>]+content\s*=\s*["\']([^"\']+)["\'][^>]*'
    r'(?:property|name)\s*=\s*["\']'
    r'(?:og:image(?::secure_url)?|twitter:image(?::src)?)["\']',
    re.IGNORECASE,
)

_OG_USER_AGENT = (
    "Mozilla/5.0 (compatible; EVNewsBot/1.0; +https://example.com)"
)


_CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg":  ".jpg",
    "image/png":  ".png",
    "image/gif":  ".gif",
    "image/webp": ".webp",
    "image/avif": ".avif",
}


def _fetch_article_html(article_url: str, timeout: int = 8) -> Optional[str]:
    """Fetch up to ~500 KB of the article HTML. One GET per article, shared by
    the og:image lookup and the pre-write groundedness check. None on any failure."""
    try:
        headers = {"User-Agent": _OG_USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
        resp = requests.get(article_url, headers=headers, timeout=timeout,
                            allow_redirects=True, stream=True)
        chunks, size = [], 0
        for chunk in resp.iter_content(chunk_size=16384, decode_unicode=False):
            chunks.append(chunk)
            size += len(chunk)
            if size > 500_000:  # enough body for grounding without a full download
                break
        return b"".join(chunks).decode("utf-8", errors="ignore")
    except Exception as e:
        logger.debug("Article fetch failed for %s: %s", article_url, e)
        return None


def _find_og_image_url(html_body: str, article_url: str) -> Optional[str]:
    """Extract the og:image / twitter:image URL from the article HTML. Pure."""
    head = html_body.split("</head>", 1)[0] if "</head>" in html_body else html_body
    for regex in (_OG_RE_FORWARD, _OG_RE_REVERSE):
        m = regex.search(head)
        if m:
            img = m.group(1).strip()
            if img.startswith("//"):
                img = "https:" + img
            elif img.startswith("/"):
                img = urljoin(article_url, img)
            if img.lower().startswith("https://"):
                return img
    return None


# ── Pre-write groundedness check (L2 fix 5) ───────────────────────────────────
# No source text exists at parse time (the agent returns only its JSON), so the
# strongest available check runs here, against the article page the writer
# already fetches for og:image: entities in `companies` and numbers in `summary`
# must appear in the page. Violations are LOGGED + FLAGGED in provenance (not
# dropped) — consistent with the pipeline's tolerate-and-mark treatment of
# suspect optional data, and safe against paywalls/derived-number false positives.

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _html_to_text(html_body: str) -> str:
    """Crude HTML→text for the groundedness check: drop script/style blocks,
    strip tags, unescape entities, collapse whitespace. Pure."""
    text = _SCRIPT_STYLE_RE.sub(" ", html_body)
    text = _TAG_RE.sub(" ", text)
    return " ".join(unescape(text).split())


def _significant_numbers(text: str) -> set[str]:
    """Comma-normalised numeric tokens worth verifying against the source.
    Single digits are skipped — they match any page trivially. Pure."""
    out: set[str] = set()
    for tok in _NUM_RE.findall(text or ""):
        norm = tok.replace(",", "")
        if len(norm.replace(".", "")) >= 2:
            out.add(norm)
    return out


def groundedness_violations(item: HomeNewsItem, page_text: str) -> dict:
    """Companies and summary numbers NOT found in the source page text.
    Case-insensitive substring match for companies; comma-insensitive digit
    match for numbers (so "3,650" grounds "3650"). Returns {} when everything
    checks out. Pure — `page_text` should already be plain text."""
    lower = page_text.lower()
    digits = page_text.replace(",", "")
    out: dict = {}
    bad_companies = [c for c in (item.companies or []) if c.lower() not in lower]
    if bad_companies:
        out["companies"] = bad_companies
    bad_numbers = sorted(
        n for n in _significant_numbers(item.summary or "") if n not in digits
    )
    if bad_numbers:
        out["numbers"] = bad_numbers
    return out


def _apply_groundedness(item: HomeNewsItem, html_body: Optional[str]) -> None:
    """Record the pre-write groundedness verdict in the item's provenance:
    'verified' (all companies + summary numbers found in the source page),
    'suspect' (+ what was missing — logged, but the row is kept), or
    'unverified' when the page couldn't be fetched (paywall/403/timeout —
    not evidence of fabrication)."""
    if html_body is None:
        marker: dict = {"status": "unverified"}
    else:
        violations = groundedness_violations(item, _html_to_text(html_body))
        if violations:
            marker = {"status": "suspect", **violations}
            logger.warning("Groundedness: %s not found in source %s", violations, item.url)
        else:
            marker = {"status": "verified"}
    item.provenance = dict(item.provenance or {}, groundedness=marker)


def _download_image(img_url: str, article_url: str, timeout: int = 8) -> Optional[Tuple[bytes, str]]:
    """Download the image. Returns (bytes, extension) or None on any failure."""
    headers = {
        "User-Agent": _OG_USER_AGENT,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": article_url,  # placate hotlink-protected CDNs
    }
    try:
        r = requests.get(img_url, headers=headers, timeout=timeout,
                         stream=True, allow_redirects=True)
        if r.status_code >= 400:
            return None
        ct = r.headers.get("Content-Type", "").lower().split(";")[0].strip()
        ext = _CONTENT_TYPE_EXT.get(ct)
        if not ext:
            return None

        chunks, size = [], 0
        for chunk in r.iter_content(chunk_size=16384):
            chunks.append(chunk)
            size += len(chunk)
            if size > Config.HOME_NEWS_IMAGE_MAX_BYTES:
                logger.debug("Image too large, skipping: %s", img_url)
                return None
        if size < 1024:  # skip tracking pixels / placeholders
            return None
        return b"".join(chunks), ext
    except Exception as e:
        logger.debug("Image download failed for %s: %s", img_url, e)
        return None


def _public_url_exists(public_url: str, timeout: int = 4) -> bool:
    """HEAD-check a Supabase Storage public URL to see if the object is there."""
    try:
        r = requests.head(public_url, timeout=timeout, allow_redirects=True)
        return r.status_code == 200
    except Exception:
        return False


class _ImageProxy:
    """Downloads og:image from articles and re-hosts them in Supabase Storage."""

    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.bucket = Config.HOME_NEWS_IMAGE_BUCKET

    def proxy_one(self, item: HomeNewsItem) -> Optional[str]:
        """Full pipeline for a single article: page fetch → groundedness check →
        og lookup → download → upload. The one page fetch feeds both the
        groundedness check and the og:image lookup."""
        article_url = item.url
        html_body = _fetch_article_html(article_url)
        _apply_groundedness(item, html_body)
        if not html_body:
            return None

        img_url = _find_og_image_url(html_body, article_url)
        if not img_url:
            return None

        downloaded = _download_image(img_url, article_url)
        if not downloaded:
            return None
        image_bytes, ext = downloaded

        digest = hashlib.sha256(image_bytes).hexdigest()
        path = f"{digest}{ext}"

        ct_by_ext = {v: k for k, v in _CONTENT_TYPE_EXT.items() if k != "image/jpg"}
        content_type = ct_by_ext.get(ext, "application/octet-stream")

        public_url = self.supabase.storage.from_(self.bucket).get_public_url(path).split("?")[0]

        # Content-addressable: if the same bytes were uploaded before, reuse them.
        if _public_url_exists(public_url):
            return public_url

        # storage3's .upload() has a known UnboundLocalError bug on some response
        # paths; call the REST API directly to avoid it.
        upload_url = f"{Config.SUPABASE_URL.rstrip('/')}/storage/v1/object/{self.bucket}/{path}"
        try:
            r = requests.post(
                upload_url,
                headers={
                    "Authorization": f"Bearer {Config.SUPABASE_KEY}",
                    "apikey": Config.SUPABASE_KEY,
                    "Content-Type": content_type,
                    "x-upsert": "true",
                },
                data=image_bytes,
                timeout=15,
            )
        except Exception as e:
            if _public_url_exists(public_url):
                return public_url
            logger.warning("Storage upload failed for %s: %s", img_url, e)
            return None

        if r.status_code in (200, 201):
            return public_url
        # 409 conflict despite x-upsert means the object is already there; reuse it.
        if r.status_code == 409 and _public_url_exists(public_url):
            return public_url
        logger.warning(
            "Storage upload failed for %s: HTTP %s — %s",
            img_url, r.status_code, r.text[:200].replace("\n", " "),
        )
        return None

    def proxy_many(self, items: List[HomeNewsItem], max_workers: int = 8) -> None:
        if not items:
            return
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(self.proxy_one, item): item for item in items}
            for fut in concurrent.futures.as_completed(futures):
                item = futures[fut]
                try:
                    item.image_url = fut.result()
                except Exception as e:
                    logger.debug("Proxy failed for %s: %s", item.url, e)
                    item.image_url = None
        enriched = sum(1 for i in items if i.image_url)
        logger.info("Image proxy: %d/%d items got a hosted image", enriched, len(items))


class HomeNewsWriter:
    def __init__(self, table: str | None = None, supabase_client: Client | None = None):
        self.supabase: Client = supabase_client or get_supabase()
        # One writer per feed; `table` selects the feed's Supabase table.
        self.table = table or Config.HOME_NEWS_TABLE
        self.max_age_days = Config.HOME_NEWS_MAX_AGE_DAYS
        # Items dropped by the cross-feed guard on the last upsert (see
        # `_filter_cross_feed_dups`) — exposed so callers can ledger it:
        # the exact count, plus WHICH urls were skipped (capped so the
        # feed_runs metrics payload stays small).
        self.cross_feed_skipped = 0
        self.cross_feed_skipped_urls: List[str] = []
        # Prosus alias index, loaded lazily on first upsert (one read per
        # writer). None = reference table unavailable/empty; tagging is skipped
        # and the run proceeds (prosus/matcher.py logs the pointer once).
        self._prosus_index = None
        self._prosus_index_loaded = False

    def _filter_cross_feed_dups(self, items: List[HomeNewsItem]) -> List[HomeNewsItem]:
        """Cross-feed dedup guard, first-feed-wins (mirrors the read side's
        `dedup_by_feed`): drop items whose canonical URL is already stored by
        ANOTHER feed's table. One `select url in (batch)` per other feed table —
        cheap, and best-effort: a failed read never blocks the write (the own
        table's on_conflict still covers within-feed dups). Exact-match works
        because URLs are canonicalized at parse time; pre-existing rows stored
        with tracking params won't match (known gap, self-heals as feeds prune)."""
        self.cross_feed_skipped = 0
        self.cross_feed_skipped_urls = []
        urls = [item.url for item in items]
        dupes: set[str] = set()
        for feed in FEEDS:
            if feed.table == self.table:
                continue
            try:
                resp = (
                    self.supabase.table(feed.table)
                    .select("url")
                    .in_("url", urls)
                    .execute()
                )
                dupes.update(r.get("url") for r in (resp.data or []))
            except Exception as e:
                logger.warning("Cross-feed dedup read failed for %s: %s", feed.table, e)
        if not dupes:
            return items
        kept = [item for item in items if item.url not in dupes]
        skipped = [item.url for item in items if item.url in dupes]
        self.cross_feed_skipped = len(skipped)
        self.cross_feed_skipped_urls = skipped[:DROPPED_ITEMS_CAP]
        for url in skipped:
            logger.info("Skipping cross-feed duplicate (already stored by another feed): %s", url)
        return kept

    def upsert(self, items: List[HomeNewsItem]) -> int:
        if not items:
            # Reset the per-upsert skip accounting so a caller reading it after
            # an empty run doesn't see the previous batch's numbers.
            self.cross_feed_skipped = 0
            self.cross_feed_skipped_urls = []
            logger.info("Nothing to upsert")
            return 0

        items = self._filter_cross_feed_dups(items)
        if not items:
            logger.info("Nothing to upsert (all items were cross-feed duplicates)")
            return 0

        _ImageProxy(self.supabase).proxy_many(items)

        rows = [item.to_row() for item in items]
        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            row["fetched_at"] = now

        # Prosus portfolio lens: tag rows that name a portfolio company
        # (prosus/matcher.py). Set on EVERY row ([] when nothing matched):
        # PostgREST unifies columns across a batch and null-fills rows missing
        # a key — a mixed batch would violate prosus_tags NOT NULL.
        if not self._prosus_index_loaded:
            self._prosus_index = load_alias_index(self.supabase)
            self._prosus_index_loaded = True
        if self._prosus_index:
            for row in rows:
                row[_PROSUS_COL] = match_prosus_tags(
                    self._prosus_index, row.get("title"),
                    row.get("summary"), row.get("companies"))

        # on_conflict='url' uses the UNIQUE constraint defined in the schema.
        # `provenance` and `prosus_tags` are optional columns; if a migration
        # isn't applied yet, strip that column and retry so the feed run still
        # succeeds (see _OPTIONAL_COL_HINTS). Bounded: each pass strips a new
        # column or raises.
        stripped: set[str] = set()
        while True:
            try:
                resp = self.supabase.table(self.table).upsert(rows, on_conflict="url").execute()
                break
            except Exception as e:
                missing = next(
                    (c for c in _OPTIONAL_COL_HINTS
                     if c not in stripped and _is_missing_column_error(e, c)),
                    None,
                )
                if missing is None:
                    raise
                stripped.add(missing)
                logger.warning(
                    "Table %s has no `%s` column yet — upserting without it. "
                    "Apply %s to capture it.",
                    self.table, missing, _OPTIONAL_COL_HINTS[missing],
                )
                rows = [{k: v for k, v in row.items() if k != missing} for row in rows]
        count = len(resp.data) if resp.data else 0
        logger.info("Upserted %d rows into %s", count, self.table)
        return count

    def prune_old(self, max_age_days: int | None = None) -> int:
        days = max_age_days if max_age_days is not None else self.max_age_days
        now = datetime.now(timezone.utc)
        cutoff_date = (now - timedelta(days=days)).date().isoformat()
        deleted = 0

        # Dated rows: prune by published_at (a DATE column).
        resp = (
            self.supabase.table(self.table)
            .delete()
            .lt("published_at", cutoff_date)
            .execute()
        )
        deleted += len(resp.data) if resp.data else 0

        # Undated rows (published_at IS NULL) would otherwise never age out —
        # prune them by fetched_at (a TIMESTAMPTZ) so they don't accumulate.
        cutoff_ts = (now - timedelta(days=days)).isoformat()
        resp_undated = (
            self.supabase.table(self.table)
            .delete()
            .is_("published_at", "null")
            .lt("fetched_at", cutoff_ts)
            .execute()
        )
        deleted += len(resp_undated.data) if resp_undated.data else 0

        if deleted:
            logger.info("Pruned %d rows from %s older than %s", deleted, self.table, cutoff_date)
        return deleted

    def fetch_recent(self, limit: int = 200) -> list[dict]:
        """Read rows for this feed's table — newest first by published_at then fetched_at."""
        resp = (
            self.supabase.table(self.table)
            .select("*")
            .order("published_at", desc=True)
            .order("fetched_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
