#!/usr/bin/env python3
"""
Classify stored articles with the MOT Lens (maturity / adoption / strategic move)
via the Toqan MOT Lens agent. Backfills any unclassified rows across all feeds.
Safe to run from cron/CLI; re-running only classifies rows that are still NULL.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

from config import Config
from analytics.lens import LensClassifier
from analytics.run_ledger import RunLedger

logger = logging.getLogger("lens_run")


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
    logger.info("=" * 60)
    logger.info("MOT Lens classification starting")
    logger.info("=" * 60)
    classifier = LensClassifier()
    ledger = RunLedger(classifier.client)  # reuse the same Supabase client
    try:
        result = classifier.run_with_stats()
    except Exception as e:
        logger.error("MOT Lens classification failed: %s", e, exc_info=True)
        return 1
    for feed_key, (_written, stats, error) in result.items():
        ledger.record("lens", feed_key, stats.to_metrics(), ok=(error is None), error=error)
    logger.info("Classified per feed: %s", {k: v[0] for k, v in result.items()})
    logger.info("MOT Lens classification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
