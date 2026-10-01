#!/usr/bin/env python3
"""
Push Lodestar watchlist alerts to a webhook (Slack/Discord-style).

Computes alerts for tracked technologies / entities / feeds — new material stories
and technology stage transitions — and POSTs them to ALERT_WEBHOOK as {"text": …}.
Safe to run from cron / GitHub Actions; no-ops if the watchlist is empty or no
webhook is configured. Run after analytics_run.py.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import requests
from dotenv import load_dotenv

from config import Config
from analytics.entity_moves import format_move_alerts
from analytics.watchlist import Watchlist, format_alerts

logger = logging.getLogger("alerts_run")


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_dotenv()
    try:
        Config.validate()
    except ValueError as e:
        logger.error("%s — set them in .env before running.", e)
        return 1

    hours = int(os.getenv("ALERT_WINDOW_HOURS", "8"))
    wl = Watchlist()
    alerts = wl.alerts(hours=hours)

    # Competitor moves (Phase 3 🏢) — non-fatal: a failure here must never block
    # the regular watchlist alerts.
    try:
        moves = wl.entity_moves(hours=hours)
    except Exception:
        logger.warning("Entity move scan failed (non-fatal)", exc_info=True)
        moves = []
    # Dedupe within the run: a story that already fired a watchlist alert above
    # shouldn't be posted a second time as a move.
    alerted_urls = {a.get("url") for a in alerts if a.get("url")}
    moves = [m for m in moves if not (m.get("url") and m["url"] in alerted_urls)]

    if not alerts and not moves:
        logger.info("No alerts.")
        return 0

    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts = []
    if alerts:
        parts.append(format_alerts(alerts, as_of=as_of))
    if moves:
        parts.append(format_move_alerts(moves))
    body = "\n\n".join(parts)
    webhook = os.getenv("ALERT_WEBHOOK")
    if not webhook:
        logger.warning("%d alert(s) + %d move(s) but ALERT_WEBHOOK is not set — not sent:\n%s",
                       len(alerts), len(moves), body)
        return 0
    try:
        resp = requests.post(webhook, json={"text": body}, timeout=15)
        resp.raise_for_status()
        logger.info("Sent %d alert(s) and %d competitor move(s) to the webhook.",
                    len(alerts), len(moves))
    except Exception as e:
        logger.error("Failed to post alerts: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
