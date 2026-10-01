"""
Dossier Analyst agent — the cached, agent-written narrative per technology.

The deterministic analyst read (analytics/dossier._analyst_read) is honest but
template-shaped; this agent reasons ACROSS the dossier's sections (funding vs
coverage tension, player concentration, what the nearest falsifier implies) and
writes the verdict the page opens with. Generated once per refresh — never on
page load — and cached in `tech_narratives`; the deterministic read remains the
fallback, so a missing TOQAN_DOSSIER key or a bad agent day costs nothing.

Pack building and output validation are pure (unit-tested). The phantom-citation
guard mirrors analytics/ask.py: an [S#] outside the pack's story list marks the
narrative invalid and it is NOT stored — a hallucinated citation must never
render as if it pointed at a real source.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

ENV_KEY = "TOQAN_DOSSIER"
NARRATIVES_TABLE = "tech_narratives"
PROMPT_VERSION = "dossier-v1"
_CIT_RE = re.compile(r"\[S(\d+)\]")
# Toqan agents emit a leading <think>…</think> reasoning trace regardless of
# the output contract — strip it before validation/storage (mirrors ask.py).
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_thinking(raw: str) -> str:
    return _THINK_RE.sub("", raw or "").strip()
# Agent calls run inside the refresh job — cap each spell well under the
# pipeline default so one slow tech can't eat the whole run's budget.
_MAX_POLL_ATTEMPTS = int(os.getenv("TOQAN_DOSSIER_MAX_POLL_ATTEMPTS", "").strip() or 60)


def build_pack(d: dict) -> str:
    """The compact per-technology data pack the agent reasons over (pure).
    Everything comes from the already-assembled dossier dict — the agent sees
    exactly what the page shows, nothing more."""
    pl = d["placement"]
    lines = [f"TECHNOLOGY: {d['label']} ({d['domain']}) — as of {d['as_of']}", ""]

    lines.append("=== PLACEMENT ===")
    if pl["watching"]:
        lines.append(f"WATCHING — below the evidence floor: {pl['evidence']} stage-classified "
                     f"articles/30d (floor {pl['evidence_floor']}). No stage claim is made.")
    else:
        lines.append(f"maturity={pl['maturity']} · adoption={pl['adoption']} · "
                     f"evidence={pl['evidence']} articles/30d (floor {pl['evidence_floor']})"
                     + (" · thin signal" if pl["thin_signal"] else ""))
        if pl["anchored"]:
            lines.append(f"anchored to a curated assessment"
                         + (f" ({pl['anchor_as_of']})" if pl["anchor_as_of"] else "")
                         + " — news can advance the stage, never lower it")

    if d["transitions"]:
        lines += ["", "=== STAGE TRANSITIONS (newest first) ==="]
        for t in d["transitions"][:5]:
            status = ("contested" if t["contested"]
                      else "confirmed" if t["confirmed"] else "pending")
            lines.append(f"- {t['as_of']}: {t['dimension']} {t['from']} → {t['to']} ({status})")

    if d.get("players"):
        lines += ["", "=== TOP PLAYERS (mentions/30d) ==="]
        lines.append(" · ".join(f"{p['name']} ({p['mentions']})" for p in d["players"]))

    cap = d["capital"]
    if cap["counts"]["commitment"] + cap["counts"]["option"] > 0:
        lines += ["", "=== CAPITAL MOVES (30d) ==="]
        lines.append(f"{cap['counts']['commitment']} commitments vs "
                     f"{cap['counts']['option']} real options")

    fu = d.get("funding")
    if fu:
        lines += ["", "=== FUNDING SIGNAL (independent of news) ==="]
        lines.append(f"{fu['rounds']} rounds/12mo · {fu['early']} early vs {fu['late']} late"
                     + (f" · {fu['read']}" if fu.get("read") else ""))

    if d["open_forecasts"]:
        lines += ["", "=== OPEN FORECASTS (locked) ==="]
        for f in d["open_forecasts"][:4]:
            conf = f" @ {round(f['confidence'] * 100)}%" if f.get("confidence") is not None else ""
            lines.append(f"- {f['claim']}{conf} · resolves by {f['resolve_by']}")
            if f.get("falsifier"):
                lines.append(f"  wrong if: {f['falsifier']}")

    if d["resolved_forecasts"]:
        hits = sum(1 for f in d["resolved_forecasts"] if f.get("outcome") == "hit")
        misses = sum(1 for f in d["resolved_forecasts"] if f.get("outcome") == "miss")
        lines += ["", f"=== RECORD === {hits} hit / {misses} miss "
                      f"across {len(d['resolved_forecasts'])} resolved"]

    if d["stories"]:
        lines += ["", "=== RECENT STORIES (cite as [S#]) ==="]
        for i, s in enumerate(d["stories"], 1):
            lines.append(f"[S{i}] ({s.get('date') or '?'}, {s.get('source') or '?'}) {s.get('title')}")

    lines += ["", "Write the dossier verdict per your instructions."]
    return "\n".join(lines)


def validate(narrative: str, n_stories: int) -> str | None:
    """Reject an unusable narrative (pure). Returns an error string, or None
    when it passes: non-trivial prose, no phantom [S#], no JSON/code fences."""
    text = (narrative or "").strip()
    if len(text) < 80:
        return "too short"
    if text.startswith("{") or text.startswith("[") or "```" in text:
        return "not prose"
    phantoms = [m for m in _CIT_RE.findall(text) if not (1 <= int(m) <= n_stories)]
    if phantoms:
        return f"phantom citations: S{', S'.join(sorted(set(phantoms)))}"
    return None


def generate_narratives(client, dossiers: list[dict], *, api_key: str | None = None,
                        log=None) -> dict:
    """Generate + store a narrative per dossier dict. Returns counts. Each tech
    degrades independently — one failure never blocks the rest, and an invalid
    narrative is dropped (the page falls back to the deterministic read)."""
    from toqan.client import ToqanAgent

    key = api_key or os.getenv(ENV_KEY)
    say = log or (lambda m, ok=True: logger.info(m))
    if not key:
        say(f"Dossier narratives skipped — {ENV_KEY} is not set.", ok=True)
        return {"generated": 0, "skipped": len(dossiers), "failed": 0}

    agent = ToqanAgent(api_key=key, agent_name="Dossier Analyst Agent",
                       max_poll_attempts=_MAX_POLL_ATTEMPTS)
    generated = failed = 0
    for d in dossiers:
        try:
            raw = strip_thinking(agent.ask(build_pack(d)))
            err = validate(raw, len(d["stories"]))
            if err:
                failed += 1
                say(f"✗ {d['label']}: narrative rejected ({err})", ok=False)
                continue
            client.table(NARRATIVES_TABLE).upsert({
                "tech_key": d["tech"],
                "as_of": d["as_of"],
                "narrative": raw,
                "prompt_version": PROMPT_VERSION,
            }, on_conflict="tech_key,as_of").execute()
            generated += 1
            say(f"✓ {d['label']}: narrative stored")
        except Exception as e:
            failed += 1
            say(f"✗ {d['label']}: {e}", ok=False)
    return {"generated": generated, "skipped": 0, "failed": failed}


def latest_narrative(client, tech_key: str) -> dict | None:
    """Most recent stored narrative for one technology, or None (also when the
    table is missing — the dossier then shows the deterministic read only)."""
    try:
        rows = (client.table(NARRATIVES_TABLE).select("*")
                .eq("tech_key", tech_key)
                .order("as_of", desc=True).limit(1)
                .execute().data or [])
        return rows[0] if rows else None
    except Exception as e:
        logger.warning("Narratives unavailable for %s (%s) — apply "
                       "'SQL Tables/tech_narratives.sql' to enable them.", tech_key, e)
        return None
