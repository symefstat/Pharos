"""
Standards-battle tracker — factor scores over time per contested standard.

The Strategist's daily briefs (strategist_briefs.strategic_read) attach a
`standards` scorecard to signals that read as a standards battle: who leads,
and on which of the four classic standards-battle factors (installed base,
complementary goods, openness, timing — the van de Kaa/Shapiro-Varian factor
set; the UI labels them plainly). One brief is one dated observation. This
module harvests every such observation across the brief history and rolls them
up into per-battle timelines, so a contested standard can be watched factor by
factor as the daily reads accumulate — a longitudinal view no single brief has.

Battle grouping: observations are grouped by a normalized battle key derived
from the signal title's main tokens (lowercased, stopwords and generic
battle-words like "standards"/"war" dropped). Two observations belong to the
same battle when their title tokens overlap in ≥2 tokens (≥1 when either side
only has one token). Grouping by leader alone was rejected — the leader is the
*answer*, not the identity of the battle (a lead can flip and it's still the
same battle; one company can lead two different battles). Title tokens are the
most stable battle identity the briefs carry, and the rule is transparent: you
can read the tokens off the title. Day-to-day rewordings of the same battle
("NACS becomes the de-facto charging standard" / "Tesla's NACS charging plug
war") share ≥2 content tokens; distinct battles don't.

Pure — takes brief rows, returns dicts; the backend does the IO.
"""

from __future__ import annotations

import re

# The four factors the Strategist scores a battle on (van-de-Kaa-style set;
# rendered in the UI without scholar names). Counts always carry all four keys
# so the factor chips render a complete scorecard, zeros included.
FACTORS = ("installed base", "complementary goods", "openness", "timing")

# Words that never identify WHICH battle a signal is about — generic English
# plus the vocabulary of writing about standards battles themselves.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "as", "at",
    "by", "its", "his", "her", "their", "is", "are", "be", "with", "over",
    "into", "from", "vs", "versus", "between", "against", "amid", "after",
    "standard", "standards", "battle", "battles", "war", "wars", "race",
    "fight", "format", "contest", "contested", "de", "facto", "defacto",
    "becomes", "becoming", "new", "wins", "winning", "leads", "leading",
}

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-\+\.]*")


def _battle_tokens(text: str) -> frozenset[str]:
    """Normalized content tokens of a signal title — the battle identity."""
    return frozenset(
        t for t in _TOKEN_RE.findall((text or "").lower())
        if len(t) >= 2 and t not in _STOPWORDS
    )


def _factor_of(basis_item: str) -> str | None:
    """Map a free-text basis entry onto one of the four factors (tolerant:
    the prompt constrains the values, but the agent sometimes paraphrases)."""
    b = (basis_item or "").strip().lower()
    if not b:
        return None
    if "install" in b or "user base" in b or b == "base":
        return "installed base"
    if "complement" in b or "ecosystem" in b:
        return "complementary goods"
    if "open" in b:
        return "openness"
    if "timing" in b or "first-mover" in b or "first mover" in b or "entry" in b:
        return "timing"
    return None


def _harvest(briefs: list[dict]) -> list[dict]:
    """Every dated standards observation across the brief history, newest first.
    Deduped on (as_of, title, leader) so multiple focus rows for the same day
    don't double-count the same read."""
    obs: list[dict] = []
    seen: set[tuple] = set()
    for b in briefs or []:
        read = b.get("strategic_read")
        if not isinstance(read, dict):
            continue
        as_of = str(b.get("as_of") or "")[:10] or None
        for s in read.get("signals") or []:
            if not isinstance(s, dict):
                continue
            std = s.get("standards")
            if not isinstance(std, dict):
                continue
            leader = str(std.get("leader") or "").strip()
            basis = [str(x).strip() for x in (std.get("basis") or []) if str(x).strip()]
            read_txt = str(std.get("read") or "").strip()
            if not (leader or basis or read_txt):
                continue
            title = str(s.get("title") or "").strip()
            key = (as_of, title.lower(), leader.lower())
            if key in seen:
                continue
            seen.add(key)
            obs.append({
                "as_of": as_of,
                "leader": leader,
                "basis": basis,
                "read": read_txt,
                "title": title,
            })
    obs.sort(key=lambda o: o["as_of"] or "", reverse=True)
    return obs


def standards_timeline(briefs: list[dict]) -> list[dict]:
    """Roll the brief history up into per-battle standards timelines (pure).

    `briefs` are strategist_briefs rows ({as_of, strategic_read, ...}), any
    order. Returns one dict per contested standard, most recently seen first:

      {battle, observations (newest first: {as_of, leader, basis, read, title}),
       current_leader, factor_counts (all four factors, zeros kept),
       first_seen, last_seen, leader_changes, single_observation}

    Battles with a single observation are still listed, flagged
    `single_observation` so the UI can caveat them.
    """
    observations = _harvest(briefs)

    # Greedy token-overlap grouping (see module docstring for the rationale).
    # Observations arrive newest first, so each battle's first member — whose
    # title becomes the display name — is its most recent phrasing.
    battles: list[dict] = []
    for o in observations:
        toks = _battle_tokens(o["title"]) or _battle_tokens(o["leader"])
        placed = None
        for b in battles:
            if not toks or not b["tokens"]:
                continue
            need = min(2, len(toks), len(b["tokens"]))
            if len(toks & b["tokens"]) >= need:
                placed = b
                break
        if placed is None:
            battles.append({"tokens": set(toks), "obs": [o]})
        else:
            placed["tokens"] |= toks
            placed["obs"].append(o)

    out = []
    for b in battles:
        obs = b["obs"]                          # newest first by construction
        chron = list(reversed(obs))             # oldest first, for change counting
        leaders = [o["leader"] for o in chron if o["leader"]]
        leader_changes = sum(
            1 for i in range(1, len(leaders))
            if leaders[i].lower() != leaders[i - 1].lower()
        )
        factor_counts = {f: 0 for f in FACTORS}
        for o in obs:
            for item in o["basis"]:
                f = _factor_of(item)
                if f:
                    factor_counts[f] += 1
        current_leader = next((o["leader"] for o in obs if o["leader"]), None)
        out.append({
            "battle": obs[0]["title"] or current_leader or "Standards battle",
            "observations": obs,
            "current_leader": current_leader,
            "factor_counts": factor_counts,
            "first_seen": chron[0]["as_of"],
            "last_seen": obs[0]["as_of"],
            "leader_changes": leader_changes,
            "single_observation": len(obs) == 1,
        })
    out.sort(key=lambda x: (x["last_seen"] or "", len(x["observations"])), reverse=True)
    return out
