"""
MOT Lens — annotate stored articles with Management-of-Technology framework
fields (lifecycle maturity, diffusion/adoption stage, strategic move), grounded
in the MOT curriculum. Classified in batches by a dedicated Toqan agent and
written back to each feed's table. Same enrichment pattern as the old
backfill_classification: read unclassified rows → classify → update.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from supabase import Client

from db import get_supabase
from feeds import FEEDS, Feed
from home_news.writer import _is_missing_column_error
from toqan.client import ToqanAgent
from toqan.json_utils import parse_json_array

logger = logging.getLogger(__name__)

ENV_KEY = "TOQAN_MOT_LENS"
BATCH = 8

# Id of the MOT Lens prompt currently deployed in Toqan. Persisted on every row this
# code classifies (unless the agent echoes its own `prompt_version`, which wins), so
# labels are attributable to a prompt and A/B-able (backend/eval_run.py scores by version).
# Bump this in lockstep when you re-paste a changed MOT_Lens_Agent.md.
LENS_PROMPT_VERSION = "mot-lens-v3"

_MATURITY = ("research", "emerging", "growth", "dominant-design", "mature", "declining", "n/a")
_ADOPTION = ("innovators", "early-adopters", "early-majority", "late-majority", "laggards", "n/a")
_MOVE = ("standards-battle", "entry-timing", "collaboration", "appropriability", "platform", "disruption", "none")


def _pick(value, allowed: tuple, default: str) -> str:
    v = str(value or "").strip().lower().replace("_", "-")
    return v if v in allowed else default


@dataclass
class LensRunStats:
    """Per-run accounting for the lens stage — how many rows we asked the agent to
    classify vs how many it actually returned. A gap means the agent dropped rows
    (today they get an `n/a` fallback and a `lens_classified_at` stamp anyway — a
    known data-integrity issue Phase 3.1 will fix using the same `returned` flag).
    Persisted to `feed_runs` via analytics/run_ledger.py. Pure.
    """
    requested: int = 0   # rows sent to the agent across all batches
    returned: int = 0     # rows the agent actually returned (its index was present)
    written: int = 0      # returned rows we successfully persisted (returned-written = write failures)
    batches: int = 0      # number of agent calls

    def to_metrics(self) -> dict:
        missing = self.requested - self.returned
        return {
            "requested": self.requested,
            "returned": self.returned,
            "written": self.written,
            "missing": missing,
            "batches": self.batches,
        }


def reconcile_batch(rows: list[dict], by_index: dict[int, dict]) -> list[tuple]:
    """Pure. Resolve one batch: for each requested row, return
    `(url, fields, returned)` where `fields` is the normalised lens dict and
    `returned` is True iff the agent actually returned that index.

    `returned` is what the run-ledger counts and what Phase 3.1 will gate the
    write on. Today's behaviour is unchanged: callers still persist every row
    (an omitted row gets the `n/a`/`none` fallbacks below)."""
    out: list[tuple] = []
    for i, r in enumerate(rows):
        o = by_index.get(i)
        returned = o is not None
        src = o or {}
        fields = {
            "maturity_stage": _pick(src.get("maturity_stage"), _MATURITY, "n/a"),
            "adoption_stage": _pick(src.get("adoption_stage"), _ADOPTION, "n/a"),
            "strategic_move": _pick(src.get("strategic_move"), _MOVE, "none"),
            "lens_rationale": (str(src.get("rationale") or "").strip() or None),
            # The prompt version the agent declares for itself, if any. None here →
            # the caller stamps the deployed LENS_PROMPT_VERSION instead.
            "lens_prompt_version": (str(src.get("prompt_version") or "").strip() or None),
        }
        out.append((r.get("url"), fields, returned))
    return out


class LensClassifier:
    def __init__(self, client: Client | None = None):
        self.client = client or get_supabase()

    def _unclassified(self, table: str, limit: int = BATCH) -> list[dict]:
        try:
            return (
                self.client.table(table)
                .select("url,title,summary,companies,tags")
                .is_("maturity_stage", "null")
                .limit(limit)
                .execute()
                .data
                or []
            )
        except Exception as e:
            logger.warning("Lens: could not read %s: %s", table, e)
            return []

    def _classify_batch(self, rows: list[dict]) -> dict[int, dict]:
        api_key = os.getenv(ENV_KEY)
        if not api_key:
            raise RuntimeError(f"{ENV_KEY} is not set in .env — the MOT Lens agent cannot be called.")

        lines = []
        for i, r in enumerate(rows):
            lines.append(
                f"{i}. {r.get('title')} | companies={r.get('companies')} | tags={r.get('tags')}\n"
                f"   {r.get('summary') or ''}"
            )
        message = (
            "Classify each item below with the three MOT lenses. Return a JSON array, "
            "one object per item (include its `index`).\n\n" + "\n".join(lines)
        )

        agent = ToqanAgent(api_key=api_key, agent_name="MOT Lens Agent")
        try:
            arr = parse_json_array(agent.ask(message))
        except ValueError:
            arr = []  # tolerate a malformed batch — leave its rows unclassified

        by_index: dict[int, dict] = {}
        for obj in arr:
            if isinstance(obj, dict) and "index" in obj:
                try:
                    by_index[int(obj["index"])] = obj
                except (ValueError, TypeError):
                    continue
        # Positional fallback if the agent omitted `index` but returned one per row.
        if not by_index and len(arr) == len(rows):
            by_index = {i: obj for i, obj in enumerate(arr) if isinstance(obj, dict)}
        return by_index

    def classify_feed(self, feed: Feed, max_items: int = 200) -> int:
        """Classify a feed's unclassified rows; returns the count written.
        Thin wrapper over `classify_feed_with_stats` (drops the stats)."""
        return self.classify_feed_with_stats(feed, max_items=max_items)[0]

    def classify_feed_with_stats(
        self, feed: Feed, max_items: int = 200
    ) -> tuple[int, LensRunStats]:
        """Classify a feed's unclassified rows, returning `(written, LensRunStats)`.

        Only rows the agent actually returned are written (with a `lens_classified_at`
        stamp + prompt version). A row the agent omits/garbles is left NULL — NOT
        written as a fake `n/a` — so a transient agent failure doesn't permanently
        poison the row; a future run retries it. The loop is bounded by an `attempted`
        set so persistently-omitted rows can't spin it forever."""
        done = 0
        stats = LensRunStats()
        include_version = True  # flips off (for the rest of this feed) if the column is unapplied
        attempted: set = set()  # urls tried this run — bounds the loop when the agent omits rows
        while done < max_items:
            fetched = self._unclassified(feed.table)
            if not fetched:
                break
            # Skip rows we already tried this run. An omitted row stays NULL (below) and
            # would otherwise be re-fetched forever; once a fetch brings back nothing new,
            # we stop — the omitted rows wait for a future run rather than looping here.
            batch = [r for r in fetched if r.get("url") not in attempted]
            if not batch:
                logger.info("Lens: only agent-omitted rows remain for %s — stopping "
                            "(they'll retry next run).", feed.key)
                break
            attempted.update(r.get("url") for r in batch)
            by_index = self._classify_batch(batch)
            stats.batches += 1
            stats.requested += len(batch)
            now = datetime.now(timezone.utc).isoformat()
            for url, fields, returned in reconcile_batch(batch, by_index):
                if not returned:
                    # Agent didn't return this row — leave it NULL for a future run to
                    # retry, instead of poisoning it with a fake 'n/a' + classified stamp.
                    continue
                stats.returned += 1
                row = {**fields, "lens_classified_at": now}
                # Stamp the prompt version: the agent's echoed value wins, else the
                # deployed constant. Dropped if the column isn't applied yet.
                row["lens_prompt_version"] = row.get("lens_prompt_version") or LENS_PROMPT_VERSION
                if not include_version:
                    row.pop("lens_prompt_version", None)
                try:
                    self.client.table(feed.table).update(row).eq("url", url).execute()
                    done += 1
                except Exception as e:
                    if include_version and _is_missing_column_error(e, "lens_prompt_version"):
                        # Column not applied — drop it and retry, and skip it for the rest.
                        logger.warning(
                            "%s has no lens_prompt_version column yet — classifying without it. "
                            "Apply database/schema/lens_prompt_version_column.sql.", feed.table)
                        include_version = False
                        row.pop("lens_prompt_version", None)
                        try:
                            self.client.table(feed.table).update(row).eq("url", url).execute()
                            done += 1
                        except Exception as e2:
                            logger.warning("Lens: update failed for %s: %s", url, e2)
                    else:
                        logger.warning("Lens: update failed for %s: %s", url, e)
            if len(fetched) < BATCH:
                break
        stats.written = done  # successful persists; returned-written exposes write failures
        logger.info(
            "Lens: classified %d items for %s (requested %d, agent returned %d over %d batches)",
            done, feed.key, stats.requested, stats.returned, stats.batches,
        )
        return done, stats

    def classify_in_memory(self, rows: list[dict]) -> dict[str, dict]:
        """Classify the given rows with the deployed agent and return {url: fields}
        WITHOUT writing to the DB. `fields` is the normalised lens dict
        (maturity_stage / adoption_stage / strategic_move / lens_rationale /
        lens_prompt_version). Batches like classify_feed_with_stats. Used by the A/B
        harness (lens_ab.py) to score a prompt version against gold non-destructively
        — so an experiment never mutates production rows."""
        out: dict[str, dict] = {}
        for i in range(0, len(rows), BATCH):
            batch = rows[i:i + BATCH]
            by_index = self._classify_batch(batch)
            for url, fields, _returned in reconcile_batch(batch, by_index):
                if url:
                    out[url] = fields
        return out

    def run(self, max_items_per_feed: int = 200) -> dict:
        """Classify every feed; returns {feed_key: written_count}."""
        return {k: v[0] for k, v in self.run_with_stats(max_items_per_feed).items()}

    def run_with_stats(
        self, max_items_per_feed: int = 200
    ) -> dict[str, tuple[int, LensRunStats, str | None]]:
        """Classify every feed; returns {feed_key: (written_count, LensRunStats, error)}
        where `error` is None on success or the error string if that feed raised.
        Per-feed failures are caught (logged) so one bad feed can't abort the run —
        but the error is surfaced, not swallowed, so the ledger can record it as a
        failed run rather than mislabelling it a clean no-op."""
        out: dict[str, tuple[int, LensRunStats, str | None]] = {}
        for feed in FEEDS:
            try:
                written, stats = self.classify_feed_with_stats(feed, max_items=max_items_per_feed)
                out[feed.key] = (written, stats, None)
            except Exception as e:
                logger.warning("Lens failed for %s: %s", feed.key, e)
                out[feed.key] = (0, LensRunStats(), str(e))
        return out
