#!/usr/bin/env python3
"""
Alert on stage transitions the moment they CONFIRM.

A transition confirms when its destination stage holds for a second consecutive
snapshot (run == 2 in detect_transitions) — alerting on exactly that value
notifies once per move, with a deep link to the technology's dossier page.
Backward moves never alert. Delivered via email + ALERT_WEBHOOK (both degrade
to logged-not-sent).

Run daily, after the tech-history snapshot job — the same slot as alerts_run.py.
If a day's run is skipped, that day's confirmations are logged by the next
snapshot cycle's ledger but not re-alerted (deliberate: no state table needed).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

from config import Config

logger = logging.getLogger("transition_alerts_run")

WHY_ENV_KEY = "TOQAN_TRANSITION_WHY"


def _explain(transitions: list[dict]) -> list[dict]:
    """Attach an agent-written 'why' line (Transition Explainer) to each
    freshly-confirmed transition, grounded in that technology's recent matched
    stories. Fail-open: no key / no stories / a dead agent / a phantom [S#]
    all mean the transition alerts without a why — never blocked, never faked."""
    import re

    api_key = os.getenv(WHY_ENV_KEY)
    if not api_key or not transitions:
        return transitions
    try:
        from analytics.aggregator import PulseAggregator
        from analytics.tech_layer import match_technologies
        from db import get_supabase
        from technologies import registry
        from toqan.client import ToqanAgent

        # Merged registry, so self-serve tracked technologies get whys too.
        reg = registry(get_supabase())
        rows = PulseAggregator().all_recent(days=30)
        agent = ToqanAgent(api_key=api_key, agent_name="Transition Explainer Agent",
                           max_poll_attempts=36)
        out = []
        for t in transitions:
            matched = [r for r in rows if t.get("technology") in match_technologies(r, reg)]
            matched.sort(key=lambda r: str(r.get("published_at") or ""), reverse=True)
            matched = matched[:10]
            if not matched:
                out.append(t)
                continue
            lines = [f"TRANSITION: {t.get('label')} — {t.get('dimension')} "
                     f"{t.get('from')} → {t.get('to')} (confirmed {t.get('as_of')})", "",
                     "RECENT STORIES (cite as [S#]):"]
            for i, r in enumerate(matched, 1):
                lines.append(f"[S{i}] ({str(r.get('published_at') or '?')[:10]}) {r.get('title')}")
            try:
                why = re.sub(r"<think>.*?</think>", "",
                             agent.ask("\n".join(lines)) or "",
                             flags=re.DOTALL | re.IGNORECASE).strip()
                # phantom-citation guard — a why that cites outside the pack is dropped
                phantoms = [m for m in re.findall(r"\[S(\d+)\]", why)
                            if not (1 <= int(m) <= len(matched))]
                if why and len(why) < 500 and not phantoms:
                    out.append({**t, "why": why})
                else:
                    logger.warning("Transition why rejected for %s (%s).",
                                   t.get("technology"),
                                   "phantom citations" if phantoms else "shape")
                    out.append(t)
            except Exception as e:
                logger.warning("Transition why failed for %s (%s).", t.get("technology"), e)
                out.append(t)
        return out
    except Exception as e:
        logger.warning("Transition explainer unavailable (%s) — alerting without whys.", e)
        return transitions


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_dotenv()
    try:
        Config.validate()
    except ValueError as e:
        logger.error("%s — set them in .env before running.", e)
        return 1

    from datetime import date

    from analytics.delivery import any_failed, app_url, deliver
    from analytics.digest import format_transition_alerts, just_confirmed
    from analytics.tech_layer import TechAnalyst

    failed = False
    fresh = just_confirmed(TechAnalyst().transitions())
    if fresh:
        fresh = _explain(fresh)          # agent 'why' lines — fail-open
        body = format_transition_alerts(fresh, app_url())
        subject = ("Lodestar: stage transition confirmed"
                   if len(fresh) == 1 else
                   f"Lodestar: {len(fresh)} stage transitions confirmed")
        sent = deliver(subject, body)
        logger.info("Transition alerts (%d): email=%s webhook=%s",
                    len(fresh), sent["email"], sent["webhook"])
        failed = failed or any_failed(sent)
    else:
        logger.info("No freshly-confirmed stage transitions.")

    # Graduations: a technology's FIRST at-or-above-floor snapshot — the
    # payoff moment of the Radar -> tracking pipeline. Fail-open end to end.
    try:
        from db import get_supabase

        from analytics.radar import CANDIDATES_TABLE, detect_graduations, format_graduations

        sb = get_supabase()
        hist = (sb.table("technology_stage_history")
                .select("technology,label,as_of,maturity_stage,article_count")
                .execute().data or [])
        grads = detect_graduations(hist, date.today().isoformat())
        if grads:
            try:
                promoted = {r["key"] for r in
                            (sb.table(CANDIDATES_TABLE).select("key")
                             .eq("status", "promoted").execute().data or [])}
            except Exception:
                promoted = set()
            for g in grads:
                g["from_radar"] = g["technology"] in promoted
            subject = ("Lodestar: a technology earned its place on the S-curve"
                       if len(grads) == 1 else
                       f"Lodestar: {len(grads)} technologies earned their place on the S-curve")
            sent = deliver(subject, format_graduations(grads, app_url()))
            logger.info("Graduation alerts (%d): email=%s webhook=%s",
                        len(grads), sent["email"], sent["webhook"])
            failed = failed or any_failed(sent)
        else:
            logger.info("No graduations today.")
    except Exception as e:
        logger.warning("Graduation check skipped: %s", e)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
