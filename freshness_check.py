#!/usr/bin/env python3
"""
Freshness / health monitor — catch a silently stalled pipeline.

Alerts (via ALERT_WEBHOOK, same channel as alerts_run.py) when a feed's newest row
is older than 2× its refresh interval, or a feed has no rows at all — the failure
modes the 6h cron can hit without anything erroring loudly. Meant as the final step
of the refresh workflow. Read-only on Supabase.

Exit code: 0 when all feeds are fresh (or an alert was successfully sent); 1 when
feeds are stale but no alert channel is configured / the post failed — so a stall is
never silent (it surfaces as a red workflow run even without a webhook).
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
from db import get_supabase
from feeds import FEEDS

logger = logging.getLogger("freshness_check")

REFRESH_INTERVAL_HOURS = 6   # the feed cron cadence (.github/workflows/home_news_refresh.yml)
STALE_FACTOR = 2             # alert when the newest row is older than FACTOR × interval


def stale_feeds(newest_by_feed: dict, now: datetime, *,
                interval_hours: float = REFRESH_INTERVAL_HOURS,
                factor: float = STALE_FACTOR) -> list[dict]:
    """Pure. `newest_by_feed`: {feed_key: newest_datetime | None}. Returns one entry
    per stale/empty feed — {feed, age_hours|None, reason}. A feed is stale when its
    newest row is older than factor×interval hours; empty when it has no rows at all.
    `now` (tz-aware) is injected so this is testable without the clock."""
    threshold = interval_hours * factor
    out: list[dict] = []
    for feed, latest in newest_by_feed.items():
        if latest is None:
            out.append({"feed": feed, "age_hours": None, "reason": "no rows at all"})
            continue
        age = (now - latest).total_seconds() / 3600.0
        if age > threshold:
            out.append({"feed": feed, "age_hours": round(age, 1),
                        "reason": f"newest row {age:.1f}h old (> {threshold:.0f}h threshold)"})
    return out


def format_alert(stale: list[dict], as_of: str) -> str:
    lines = [f"⚠️ *Lodestar freshness* — {len(stale)} stalled feed(s) as of {as_of}:"]
    lines += [f"• `{s['feed']}` — {s['reason']}" for s in stale]
    return "\n".join(lines)


def _parse_ts(v):
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _newest_by_feed(sb) -> dict:
    """Newest `fetched_at` per *configured* feed table (None if empty/unreadable).
    Only feeds with an API key set are checked — a feed with no key isn't being
    refreshed in this environment, so an empty table is expected, not a stall."""
    out: dict = {}
    for feed in FEEDS:
        if not feed.api_key:
            continue
        try:
            rows = (sb.table(feed.table).select("fetched_at")
                    .order("fetched_at", desc=True).limit(1).execute().data or [])
            out[feed.key] = _parse_ts(rows[0]["fetched_at"]) if rows else None
        except Exception as e:
            logger.warning("freshness: could not read %s: %s", feed.table, e)
            out[feed.key] = None  # unreadable counts as a problem worth flagging
    # The Strategist brief is the Briefing page's centerpiece, and analytics_run.py
    # deliberately never fails the workflow on a Strategist error — so a revoked
    # key/broken agent would otherwise serve an ever-staler read with every run
    # green (H8). Watch it exactly like a feed, under the same 2×interval rule.
    if os.getenv("TOQAN_STRATEGIST"):
        try:
            rows = (sb.table("strategist_briefs").select("generated_at")
                    .eq("focus", "daily").order("generated_at", desc=True)
                    .limit(1).execute().data or [])
            out["strategist-brief"] = _parse_ts(rows[0]["generated_at"]) if rows else None
        except Exception as e:
            logger.warning("freshness: could not read strategist_briefs: %s", e)
            out["strategist-brief"] = None
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_dotenv()
    try:
        Config.validate()
    except ValueError as e:
        logger.error("%s — set them in .env before running.", e)
        return 1

    now = datetime.now(timezone.utc)
    stale = stale_feeds(_newest_by_feed(get_supabase()), now)
    if not stale:
        logger.info("All %d feeds fresh.", len(FEEDS))
        return 0

    body = format_alert(stale, now.strftime("%Y-%m-%d %H:%M UTC"))
    webhook = os.getenv("ALERT_WEBHOOK")
    if not webhook:
        logger.error("%d stale feed(s) but ALERT_WEBHOOK is not set — surfacing as a "
                     "failed run:\n%s", len(stale), body)
        return 1
    try:
        requests.post(webhook, json={"text": body}, timeout=15).raise_for_status()
        logger.info("Sent freshness alert for %d stale feed(s).", len(stale))
        return 0
    except Exception as e:
        logger.error("Failed to post freshness alert: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
