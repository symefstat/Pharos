#!/usr/bin/env python3
"""
Falsifier alert loop — detect candidate evidence that a Strategist falsifier
may have triggered, persist it, and push NEW events to ALERT_WEBHOOK.

Every open Strategist forecast carries a falsifier ("wrong if: …"); this scans
the last day of news for articles matching those falsifiers (vector similarity
primary, keyword overlap fallback — analytics.falsifier_watch). Candidates are
upserted into `falsifier_events` (idempotent), so each article alerts at most
once per forecast. DETECTION ONLY: no forecast is ever auto-resolved here —
grading stays with a human in Track record.

The same run also drives THESIS watch (analytics.thesis_watch): the admin's
private thesis book scanned against the same news window, each match labeled
"confirms" or "falsifies" and alerted with a distinct 🧭 prefix. Non-fatal by
design — a thesis-watch failure (or unapplied 'SQL Tables/theses.sql') never
breaks the falsifier loop.

Safe to run from cron / GitHub Actions (after alerts_run.py); no-ops if there
are no open falsifiers, no matches, or the falsifier_events table hasn't been
created yet (a log line points at the SQL to apply).
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

from config import Config
from analytics.falsifier_watch import (
    FalsifierWatch,
    apply_verdicts,
    format_falsifier_alerts,
    parse_judge_verdicts,
)

logger = logging.getLogger("falsifier_run")

JUDGE_ENV_KEY = "TOQAN_FALSIFIER_JUDGE"


def _judge_events(events: list[dict]) -> list[dict]:
    """Rank the alert inbox with the Falsifier Judge agent: 'triggers' leads,
    'partial' follows, 'unrelated' is dropped from the ALERT (never from the
    persisted events). Fail-open — no key, a dead agent, or unparseable output
    all mean the events alert unjudged, exactly as before."""
    api_key = os.getenv(JUDGE_ENV_KEY)
    if not api_key or not events:
        return events
    try:
        from toqan.client import ToqanAgent

        lines = ["Candidates to judge:"]
        for i, e in enumerate(events):
            lines.append(f"{i}. FALSIFIER: {e.get('falsifier')}")
            lines.append(f"   ARTICLE ({e.get('published_at') or '?'}): "
                         f"{e.get('article_title')}")
        raw = ToqanAgent(api_key=api_key, agent_name="Falsifier Judge Agent",
                         max_poll_attempts=36).ask("\n".join(lines))
        verdicts = parse_judge_verdicts(raw, len(events))
        if not verdicts:
            logger.warning("Falsifier judge returned nothing usable — alerting unjudged.")
            return events
        judged = apply_verdicts(events, verdicts)
        dropped = len(events) - len(judged)
        if dropped:
            logger.info("Falsifier judge dropped %d 'unrelated' candidate(s) from the alert.",
                        dropped)
        return judged
    except Exception as e:
        logger.warning("Falsifier judge failed (%s) — alerting unjudged.", e)
        return events


def _post_alert(body: str, what: str, count: int) -> bool:
    """Deliver an alert via email + ALERT_WEBHOOK (analytics.delivery). Each
    channel degrades to logged-not-sent; False only when a CONFIGURED channel
    actually failed — an unconfigured dry run stays a clean exit."""
    from analytics.delivery import any_failed, deliver

    subject = f"Lodestar: {count} {what} alert{'s' if count != 1 else ''}"
    sent = deliver(subject, body)
    logger.info("%s alerts (%d): email=%s webhook=%s", what, count,
                sent["email"], sent["webhook"])
    return not any_failed(sent)


def run_falsifier_watch(window_days: int) -> int:
    """The public falsifier loop — the run's primary leg (its exit code)."""
    watch = FalsifierWatch()
    candidates = watch.detect(days=window_days)
    if not candidates:
        logger.info("No falsifier evidence candidates.")
        return 0
    logger.info("%d candidate match(es) across open falsifiers.", len(candidates))

    fresh = watch.persist(candidates)
    if not fresh:
        logger.info("No NEW falsifier events (all previously seen, or table missing).")
        return 0

    # Judge the inbox (agent, fail-open) — everything stays persisted either way.
    fresh = _judge_events(fresh)
    if not fresh:
        logger.info("All new events judged 'unrelated' — nothing worth an alert.")
        return 0

    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return 0 if _post_alert(format_falsifier_alerts(fresh, as_of=as_of),
                            "falsifier", len(fresh)) else 1


def run_thesis_watch(window_days: int) -> None:
    """The private thesis-book leg — same engine, distinct 🧭 alerts.

    Deliberately non-fatal: any failure here (including the theses/thesis_events
    tables not being created yet) is logged and swallowed, so thesis monitoring
    can never break the public falsifier loop it rides along with."""
    try:
        from analytics.thesis_watch import ThesisWatch, format_thesis_alerts

        watch = ThesisWatch()
        candidates = watch.detect(days=window_days)
        if not candidates:
            logger.info("No thesis evidence candidates.")
            return
        logger.info("%d candidate match(es) across active theses.", len(candidates))

        fresh = watch.persist(candidates)
        if not fresh:
            logger.info("No NEW thesis events (all previously seen, or table missing).")
            return

        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        _post_alert(format_thesis_alerts(fresh, as_of=as_of), "thesis", len(fresh))
    except Exception as e:
        logger.warning("Thesis watch failed (non-fatal): %s", e)


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_dotenv()
    try:
        Config.validate()
    except ValueError as e:
        logger.error("%s — set them in .env before running.", e)
        return 1

    window_days = int(os.getenv("FALSIFIER_WINDOW_DAYS", "1"))
    rc = run_falsifier_watch(window_days)
    run_thesis_watch(window_days)
    return rc


if __name__ == "__main__":
    sys.exit(main())
