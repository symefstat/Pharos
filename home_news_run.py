#!/usr/bin/env python3
"""
Refresh the Home page news feed.

Calls the Toqan Home Page News Agent, parses the JSON response, upserts new
rows into Supabase, and prunes old ones. Safe to run from cron, GitHub
Actions, or the Streamlit UI refresh button.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

# Allow running as a standalone script from the repo root
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

from config import Config
from feeds import FEEDS, Feed
from analytics.run_ledger import RunLedger
from home_news.extractor import HomeNewsExtractor
from home_news.parser import HomeNewsParser
from home_news.writer import HomeNewsWriter

logger = logging.getLogger("home_news_run")


# Roughly how long the agent call usually takes (s) — used to creep the bar
# during the one step whose duration we can't know in advance.
_EXPECTED_AGENT_SECONDS = 90.0


def run_refresh(
    feed: Feed,
    status_callback: Optional[Callable[[str, float], None]] = None,
) -> dict:
    """
    Fetch fresh news for one feed (topic) from its agent and persist it.

    `status_callback(message, fraction)` is called from the calling thread at
    each stage (fraction in 0..1), and repeatedly while waiting on the agent
    (where the bar creeps with elapsed time), so a UI can show a progress bar.
    Safe to omit for cron/CLI use.

    Returns a dict suitable for logging / surfacing in the UI:
      success, feed, items_parsed, rows_upserted, rows_pruned, timestamp,
      parse_stats, [error]
    """
    if not feed.api_key:
        raise RuntimeError(
            f"{feed.env_key} is not set in .env — the {feed.label} news agent cannot be called."
        )

    def _emit(msg: str, frac: float) -> None:
        if status_callback:
            try:
                status_callback(msg, frac)
            except Exception:  # never let UI updates break the run
                pass

    extractor = HomeNewsExtractor(
        api_key=feed.api_key,
        api_url=Config.TOQAN_API_URL,
        agent_name=feed.agent_name,
    )
    parser = HomeNewsParser()
    writer = HomeNewsWriter(table=feed.table)

    _emit("Contacting the news agent…", 0.05)

    def _poll(elapsed: int) -> None:
        # Creep 10%→55% over the expected agent time; cap so it never reaches
        # the next stage's slot. Bar keeps moving even though the exact end is
        # unknown.
        frac = min(0.55, 0.10 + (elapsed / _EXPECTED_AGENT_SECONDS) * 0.45)
        _emit(f"Waiting for the news agent… {elapsed}s elapsed", frac)

    raw = extractor.fetch_raw(poll_callback=_poll)

    _emit("Parsing articles…", 0.65)
    try:
        items, parse_stats = parser.parse_with_stats(raw, max_age_days=feed.max_age_days)
    except Exception:
        logger.error(
            "Could not parse %s news. Raw agent answer (first 2000 chars):\n%s",
            feed.key, (raw or "")[:2000],
        )
        raise

    _emit(f"Downloading images & saving {len(items)} articles…", 0.80)
    upserted = writer.upsert(items)

    _emit("Pruning old articles…", 0.92)
    pruned = writer.prune_old(max_age_days=feed.max_age_days)

    # Fold writer-stage losses into the same metrics dict the ledger persists,
    # so cross-feed skips (count + capped identities) are auditable alongside
    # the parse-stage drops instead of living only in stdout logs.
    metrics = parse_stats.to_metrics()
    metrics["cross_feed_skipped"] = writer.cross_feed_skipped
    if writer.cross_feed_skipped_urls:
        metrics["cross_feed_skipped_urls"] = list(writer.cross_feed_skipped_urls)

    return {
        "success": True,
        "feed": feed.key,
        "items_parsed": len(items),
        "rows_upserted": upserted,
        "rows_pruned": pruned,
        "parse_stats": metrics,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    load_dotenv()
    try:
        Config.validate()
    except ValueError as e:
        logger.error("%s — set them in .env before running.", e)
        return 1

    # Optional CLI args select which feeds to run (by key); default = all feeds.
    requested = sys.argv[1:]
    feeds = [f for f in FEEDS if not requested or f.key in requested]
    if not feeds:
        logger.error(
            "No feed matches %s. Known feeds: %s",
            requested, [f.key for f in FEEDS],
        )
        return 1

    ledger = RunLedger()  # records per-feed parse metrics to feed_runs (degrades if unapplied)
    exit_code = 0
    for feed in feeds:
        logger.info("=" * 60)
        logger.info("News refresh starting: %s (%s)", feed.label, feed.key)
        logger.info("=" * 60)
        try:
            result = run_refresh(feed)
        except Exception as e:
            logger.error("%s refresh failed: %s", feed.label, e, exc_info=True)
            ledger.record("parse", feed.key, {}, ok=False, error=str(e))
            exit_code = 1
            continue
        ledger.record("parse", feed.key, result["parse_stats"], ok=True)
        logger.info(
            "[%s] Parsed: %d  Upserted: %d  Pruned: %d",
            feed.key, result["items_parsed"], result["rows_upserted"], result["rows_pruned"],
        )

    logger.info("News refresh complete")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
