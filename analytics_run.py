#!/usr/bin/env python3
"""
Rebuild the analytics layer: the never-pruned daily rollup and the cached
Executive Brief. Safe to run from cron, GitHub Actions, or the UI.

Run after the feeds have been refreshed (home_news_run.py) so the rollup and
brief reflect the latest articles.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow running as a standalone script from the repo root.
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

from config import Config
from analytics.rollup import RollupBuilder
from analytics.strategist import Strategist
from analytics.tech_layer import TechAnalyst

logger = logging.getLogger("analytics_run")


def run_analytics() -> dict:
    """Rebuild rollup + regenerate the Strategist read. Never raises."""
    result: dict = {}

    logger.info("Rebuilding daily metrics rollup…")
    try:
        result["rollup"] = RollupBuilder().run()
        logger.info("Rollup rebuilt: %s", result["rollup"])
    except Exception as e:
        logger.error("Rollup rebuild failed: %s", e, exc_info=True)
        result["rollup_error"] = str(e)

    logger.info("Snapshotting technology stage history…")
    try:
        result["tech_snapshot"] = TechAnalyst().snapshot()
        logger.info("Tech history: %s technologies snapshotted", result["tech_snapshot"])
    except Exception as e:
        logger.warning("Tech history snapshot skipped/failed: %s", e)
        result["tech_snapshot_error"] = str(e)

    logger.info("Generating the Strategist read…")
    try:
        read = Strategist().generate()
        result["strategist_as_of"] = read["as_of"]
        logger.info("Strategist read generated for %s", read["as_of"])
    except Exception as e:
        logger.warning("Strategist generation skipped/failed: %s", e)
        result["strategist_error"] = str(e)

    return result


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
    logger.info("Analytics rebuild starting")
    logger.info("=" * 60)
    run_analytics()
    logger.info("Analytics rebuild complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
