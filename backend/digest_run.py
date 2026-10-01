#!/usr/bin/env python3
"""
Send the daily Lodestar briefing digest to every configured channel.

Assembles the latest cached daily strategist read, the honest calibration
tagline, and any freshly-confirmed stage transitions into one plaintext digest,
then delivers it via email (RESEND_API_KEY or SMTP_*, to DIGEST_EMAILS) and the
Slack/Discord-style ALERT_WEBHOOK. Channels degrade to logged-not-sent, so this
is safe from cron on a box with no credentials — it becomes a dry run.

Run after strategist_run/analytics have refreshed (same slot as alerts_run.py).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

from config import Config

logger = logging.getLogger("digest_run")


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_dotenv()
    try:
        Config.validate()
    except ValueError as e:
        logger.error("%s — set them in .env before running.", e)
        return 1

    import analytics.forecasts as fc
    from analytics.delivery import app_url, deliver
    from analytics.digest import digest_message
    from analytics.strategist import Strategist
    from analytics.tech_layer import TechAnalyst
    from backend.app import data

    recent = Strategist(data._supabase()).recent(focus="daily", limit=1)
    row = recent[0] if recent else None

    try:
        tagline = fc.calibration_tagline(fc.calibration_headline(data.predictions()))
    except Exception:
        logger.warning("Calibration tagline unavailable (non-fatal)", exc_info=True)
        tagline = ""
    try:
        transitions = TechAnalyst(data._supabase()).transitions()
    except Exception:
        logger.warning("Transitions unavailable (non-fatal)", exc_info=True)
        transitions = []

    msg = digest_message(row, tagline, transitions, app_url())
    if msg is None:
        logger.info("No strategist read to send — skipping the digest.")
        return 0

    subject, body = msg
    sent = deliver(subject, body)
    logger.info("Digest delivery: email=%s webhook=%s", sent["email"], sent["webhook"])
    # Dry run (nothing configured) exits 0; a configured channel that actually
    # failed exits 1 so cron surfaces it.
    from analytics.delivery import any_failed

    return 1 if any_failed(sent) else 0


if __name__ == "__main__":
    sys.exit(main())
