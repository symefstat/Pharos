"""
The Strategist — Lodestar's theory-grounded analyst.

Reads the day's material developments through Management-of-Technology (MOT)
theory and returns a tight strategic read that cites both the developments
([S#]) and the retrieved MOT passages ([T#]). Generated on a schedule (or the
🧭 tab's Generate button), cached in `strategist_briefs`, and read instantly by
the UI. The agent is NEVER called on page render — only by generate().

Replaces the old Executive Brief: the Brief said "what happened"; the Strategist
says "what it means, per the theory" (see backend/Agents_prompt/Strategist_Agent.md and
docs/MOT_Framework_Library.md).
"""

from __future__ import annotations

import logging
import os
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from supabase import Client

from db import get_supabase
from analytics.aggregator import PulseAggregator
from analytics.entities import normalize as normalize_entity
from toqan.client import ToqanAgent
from toqan.json_utils import parse_json_object
from vectordb.store import MotKnowledgeBase

logger = logging.getLogger(__name__)

STRATEGIST_TABLE = "strategist_briefs"
ENV_KEY = "TOQAN_STRATEGIST"
DEFAULT_FOCUS = "daily"

# The decision lens the Strategist writes for. Echoed into the data pack so the
# agent ties every signal to a client move; edit here (and in Strategist_Agent.md)
# to retarget the deliverable.
MANDATE = (
    "CLIENT: a Prosus-style technology investor/operator allocating capital and "
    "defending a portfolio across these domains. For each decisive signal give the "
    "theory-grounded read AND the recommended move (enter/scale/defend/partner/"
    "wait/exit), its impact size, horizon, and the observable that would falsify it."
)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

# Fixed framing appended to every theory-retrieval query so the KB surfaces the
# frameworks the doctrine reasons with, not just topic keywords.
_THEORY_FRAMING = (
    "Management of technology strategic analysis: technology S-curve and "
    "discontinuities, dominant design, diffusion of innovation and crossing the "
    "chasm, standards battles and network effects, appropriability and "
    "complementary assets, entry timing, market structure and regulation of "
    "market failure, real options and staged investment."
)


def _truncate(text, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


_CONFIDENCE = {"high", "medium", "low"}
_ACTIONS = {"enter", "scale", "defend", "partner", "wait", "exit"}
_IMPACT = {"high", "medium", "low"}
_HORIZON = {"near", "mid", "long"}
_RANK = {"high": 3, "medium": 2, "low": 1}


def _coerce(v, allowed: set, default: str) -> str:
    v = str(v or "").strip().lower()
    return v if v in allowed else default


def _coerce_confidence(v) -> str:
    return _coerce(v, _CONFIDENCE, "medium")


def _coerce_confidence_num(v) -> float | None:
    """Granular calibrated probability (prompt v3): a float in [0.55, 0.90],
    snapped to 0.05 steps. None when absent/garbled — consumers fall back to
    the coarse high/medium/low label map. Pure."""
    try:
        p = float(v)
    except (TypeError, ValueError):
        return None
    if not 0.0 < p < 1.0:
        return None
    return min(0.90, max(0.55, round(p * 20) / 20))


def _norm_standards(v) -> dict | None:
    """Normalize a signal's standards-battle scorecard (C1, van de Kaa), or None."""
    if not isinstance(v, dict):
        return None
    leader = str(v.get("leader") or "").strip()
    basis = [str(x).strip() for x in (v.get("basis") or []) if str(x).strip()]
    read = str(v.get("read") or "").strip()
    if not (leader or basis or read):
        return None
    return {"leader": leader, "basis": basis, "read": read}


def _normalize_structured(obj: dict) -> dict:
    """Validate/coerce the agent's structured brief into the shape the UI renders.

    Tolerant: missing/garbled fields default rather than raise, so a slightly
    off-spec answer still renders cleanly instead of crashing the Briefing.
    Signals are sorted by impact then confidence (the consultant ranking).
    """
    signals = []
    for s in (obj.get("signals") or []):
        if not isinstance(s, dict):
            continue
        signals.append({
            "title": str(s.get("title") or "").strip(),
            "lens": str(s.get("lens") or "").strip(),
            "implication": str(s.get("implication") or "").strip(),
            "action": _coerce(s.get("action"), _ACTIONS, "wait"),
            "action_rationale": str(s.get("action_rationale") or "").strip(),
            "impact": _coerce(s.get("impact"), _IMPACT, "medium"),
            "horizon": _coerce(s.get("horizon"), _HORIZON, "mid"),
            "value_capture": str(s.get("value_capture") or "").strip(),
            "standards": _norm_standards(s.get("standards")),
            "falsifier": str(s.get("falsifier") or "").strip(),
            "sources": [str(x).strip() for x in (s.get("sources") or []) if str(x).strip()],
            "confidence": _coerce_confidence(s.get("confidence")),
            # Granular calibrated probability (prompt v3) — carried alongside the
            # label so the forecast ledger gets real numbers instead of the
            # coarse high→0.75/medium→0.55 map. None when the agent omits it.
            "confidence_num": _coerce_confidence_num(s.get("confidence_num")),
        })
    signals.sort(key=lambda s: (_RANK[s["impact"]], _RANK[s["confidence"]]), reverse=True)

    convergence = []
    for c in (obj.get("convergence") or []):
        if not isinstance(c, dict):
            continue
        convergence.append({
            "theme": str(c.get("theme") or "").strip(),
            "implication": str(c.get("implication") or "").strip(),
            "feeds": [str(x).strip() for x in (c.get("feeds") or []) if str(x).strip()],
            "sources": [str(x).strip() for x in (c.get("sources") or []) if str(x).strip()],
        })
    watch = []
    for w in (obj.get("watch") or []):
        if not isinstance(w, dict):
            continue
        watch.append({
            "item": str(w.get("item") or "").strip(),
            "why": str(w.get("why") or "").strip(),
            "horizon": str(w.get("horizon") or "").strip().lower(),
        })
    sc = obj.get("scenarios") if isinstance(obj.get("scenarios"), dict) else {}
    scenarios = {k: str(sc.get(k) or "").strip() for k in ("base", "bull", "bear")}
    if not any(scenarios.values()):
        scenarios = {}
    return {
        "format": "structured",
        "bottom_line": str(obj.get("bottom_line") or "").strip(),
        "confidence": _coerce_confidence(obj.get("confidence")),
        "signals": signals,
        "convergence": convergence,
        "scenarios": scenarios,
        "watch": watch,
    }


def diff_briefs(previous: dict | None, current: dict) -> dict:
    """Compare two structured reads by signal title → {new, dropped, changed}.

    `changed` flags signals whose action or confidence shifted. Used by the
    Briefing's "what changed since last time" panel. Pure."""
    def by_title(read) -> dict:
        if not isinstance(read, dict):
            return {}
        return {
            (s.get("title") or "").strip().lower(): s
            for s in (read.get("signals") or []) if isinstance(s, dict) and s.get("title")
        }
    prev, curr = by_title(previous), by_title(current)
    new = [curr[t]["title"] for t in curr if t not in prev]
    dropped = [prev[t]["title"] for t in prev if t not in curr]
    changed = []
    for t in curr:
        if t not in prev:
            continue
        p, c = prev[t], curr[t]
        if p.get("confidence") != c.get("confidence") or p.get("action") != c.get("action"):
            changed.append({
                "title": c["title"],
                "from_action": p.get("action"), "to_action": c.get("action"),
                "from_confidence": p.get("confidence"), "to_confidence": c.get("confidence"),
            })
    return {"new": new, "dropped": dropped, "changed": changed}


# ── decision owner & persona (pure) ──────────────────────────────────────────
# The prompt contract makes every action_rationale open with its addressee
# class ("if you operate EU payment rails, …"). These lift that owner out of
# the prose so the UI can show it as a labeled chip and filter by persona —
# computed at serve time, so stored reads gain the fields without regeneration.
_ADDRESSEE_RES = [
    re.compile(r"^if you(?:'re| are)?(?: still)?(?: an?| the)? ?(.{4,80}?)(?:,| — | – | - |: )",
               re.IGNORECASE),
    re.compile(r"^([a-z][a-z '&/-]{3,60}?(?:investors?|operators?|processors?|manufacturers?"
               r"|developers?|suppliers?|builders?|insurers?|utilities|oems|incumbents?"
               r"|startups?|funds?))\b[ ,]", re.IGNORECASE),
]


def extract_addressee(rationale: str) -> str | None:
    """The decision owner named at the head of an action rationale, or None."""
    text = (rationale or "").strip()
    if not text:
        return None
    for rx in _ADDRESSEE_RES:
        m = rx.match(text)
        if m:
            owner = m.group(1).strip().rstrip(".,;")
            owner = re.sub(r"^(are|'re)\s+(an?|the)\s+", "", owner, flags=re.IGNORECASE)
            return owner if len(owner) >= 4 else None
    return None


_INVEST_RE = re.compile(
    r"\binvest|investor|fund|portfolio|\blp\b|allocat|exposure|stake|valuation", re.IGNORECASE)
_OPERATE_RE = re.compile(
    r"\boperat|build|deploy|run\b|suppl|manufactur|process(or|ing)|sell|ship\b|procure"
    r"|integrat|adopt|migrat|switch|negotiat|\boem\b|develop\b", re.IGNORECASE)


def persona_of(sig: dict) -> str:
    """'strategy' | 'investment' | 'both' — which persona a signal addresses,
    judged on its rationale + value-capture text. Ambiguous/neither → 'both'
    (a filter must never hide a signal it can't confidently classify)."""
    hay = " ".join([str(sig.get("action_rationale") or ""),
                    str(sig.get("value_capture") or "")])
    inv = bool(_INVEST_RE.search(hay))
    op = bool(_OPERATE_RE.search(hay))
    if inv and not op:
        return "investment"
    if op and not inv:
        return "strategy"
    return "both"


# Order actions read as a decision board (offensive → hold → defensive).
PORTFOLIO_ACTIONS = ["enter", "scale", "partner", "defend", "wait", "exit"]


def portfolio_summary(read: dict) -> list[dict]:
    """Tally recommended actions across signals into a decision board (pure).

    Returns [{action, count, titles}] in PORTFOLIO_ACTIONS order — the portfolio
    posture the per-signal actions imply, which the client mandate asks for."""
    if not isinstance(read, dict):
        return []
    buckets: dict[str, list[str]] = {}
    for s in (read.get("signals") or []):
        a = str(s.get("action") or "").strip().lower()
        if a in _ACTIONS:
            buckets.setdefault(a, []).append(s.get("title") or "")
    ordered = [a for a in PORTFOLIO_ACTIONS if a in buckets]
    ordered += [a for a in buckets if a not in PORTFOLIO_ACTIONS]
    return [{"action": a, "count": len(buckets[a]), "titles": buckets[a]} for a in ordered]


def brief_to_markdown(read: dict, as_of: str | None = None, focus: str | None = None) -> str:
    """Render a cached read as a clean, shareable Markdown brief (pure).

    Handles the structured shape (bottom line / signals / convergence / watch)
    and the markdown/legacy fallbacks. Used by the Briefing's download button.
    """
    lines = ["# Lodestar — Strategist Briefing"]
    meta = []
    if as_of:
        meta.append(f"As of {as_of}")
    if focus and focus != DEFAULT_FOCUS:
        meta.append(f"Focus: {focus}")
    if meta:
        lines.append("_" + " · ".join(meta) + "_")
    lines.append("")

    if not isinstance(read, dict):
        return "\n".join(lines + [str(read), ""])

    if read.get("format") == "structured":
        if read.get("bottom_line"):
            lines += [f"**Bottom line:** {read['bottom_line']}", ""]
        if read.get("confidence"):
            lines += [f"_Overall confidence: {read['confidence']}_", ""]
        if read.get("signals"):
            lines.append("## Decisive signals")
            lines.append("")
            for s in read["signals"]:
                lines.append(f"### {s.get('title', '')}")
                tags = " · ".join(x for x in [
                    s.get("lens"),
                    f"impact: {s.get('impact')}" if s.get("impact") else "",
                    f"horizon: {s.get('horizon')}" if s.get("horizon") else "",
                    f"confidence: {s.get('confidence')}" if s.get("confidence") else "",
                    f"sources: {', '.join(s.get('sources') or [])}" if s.get("sources") else "",
                ] if x)
                if tags:
                    lines.append(f"_{tags}_")
                if s.get("implication"):
                    lines.append(s["implication"])
                if s.get("action"):
                    rat = f" — {s['action_rationale']}" if s.get("action_rationale") else ""
                    lines.append(f"- **Action:** {s['action']}{rat}")
                if s.get("value_capture"):
                    lines.append(f"- **Value capture:** {s['value_capture']}")
                std = s.get("standards")
                if std and (std.get("leader") or std.get("read")):
                    basis = f" (leads on {', '.join(std['basis'])})" if std.get("basis") else ""
                    lead = f"{std.get('leader', '')}{basis}" if std.get("leader") else ""
                    lines.append(f"- **Standards battle:** {lead}{' — ' if lead and std.get('read') else ''}{std.get('read', '')}")
                if s.get("falsifier"):
                    lines.append(f"- **Falsifier:** {s['falsifier']}")
                lines.append("")
        board = portfolio_summary(read)
        if board:
            lines.append("## Portfolio implications")
            for b in board:
                lines.append(f"- **{b['action'].title()}** ({b['count']}): {', '.join(t for t in b['titles'] if t)}")
            lines.append("")
        if read.get("scenarios"):
            sc = read["scenarios"]
            if any(sc.values()):
                lines.append("## Scenarios")
                for k in ("base", "bull", "bear"):
                    if sc.get(k):
                        lines.append(f"- **{k.title()}:** {sc[k]}")
                lines.append("")
        if read.get("convergence"):
            lines.append("## Cross-domain convergence")
            for c in read["convergence"]:
                feeds = " + ".join(c.get("feeds") or [])
                tail = f" ({feeds})" if feeds else ""
                lines.append(f"- **{c.get('theme', '')}**{tail} — {c.get('implication', '')}")
            lines.append("")
        if read.get("watch"):
            lines.append("## What to watch")
            for w in read["watch"]:
                hz = f" [{w.get('horizon')}]" if w.get("horizon") else ""
                lines.append(f"- **{w.get('item', '')}**{hz} — {w.get('why', '')}")
            lines.append("")
    elif read.get("markdown"):
        lines.append(read["markdown"])
    elif read.get("top_line") or read.get("headline"):
        lines.append(f"**{read.get('top_line') or read.get('headline')}**")
    else:
        lines.append(str(read))

    return "\n".join(lines).rstrip() + "\n"


_PDF_REPL = {"—": "-", "–": "-", "→": "->", "↑": "^", "↓": "v", "≤": "<=", "≥": ">=",
             "•": "-", "·": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "..."}


def _latin1(s) -> str:
    s = "".join(_PDF_REPL.get(ch, ch) for ch in str(s or ""))
    return s.encode("latin-1", "replace").decode("latin-1")


def brief_to_pdf(read: dict, as_of: str | None = None, focus: str | None = None) -> bytes:
    """Render the structured read as a clean PDF (fpdf2, pure-python). Text is
    sanitised to latin-1 so the core fonts suffice (no bundled TTF needed)."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()

    def heading(text, size=13):
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", size)
        pdf.multi_cell(0, size * 0.5, _latin1(text), new_x="LMARGIN", new_y="NEXT")

    def body(text, size=10, style=""):
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(0, 5, _latin1(text), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 17)
    pdf.multi_cell(0, 9, "Lodestar - Strategist Briefing", new_x="LMARGIN", new_y="NEXT")
    meta = [m for m in (f"As of {as_of}" if as_of else "",
                        f"Focus: {focus}" if focus and focus != DEFAULT_FOCUS else "") if m]
    if meta:
        body(" | ".join(meta), size=9, style="I")

    if not isinstance(read, dict):
        body(str(read))
        return bytes(pdf.output())

    if read.get("format") != "structured":
        body(read.get("markdown") or read.get("top_line") or read.get("headline") or str(read))
        return bytes(pdf.output())

    pdf.ln(2)
    if read.get("bottom_line"):
        body(f"Bottom line: {read['bottom_line']}", size=11, style="B")
    if read.get("confidence"):
        body(f"Overall confidence: {read['confidence']}", size=9, style="I")

    board = portfolio_summary(read)
    if board:
        heading("Portfolio posture")
        body("  ".join(f"{b['action'].upper()} x{b['count']}" for b in board))

    if read.get("signals"):
        heading("Decisive signals")
        for s in read["signals"]:
            body(s.get("title", ""), size=11, style="B")
            tags = " | ".join(x for x in [
                s.get("lens"),
                f"impact: {s.get('impact')}" if s.get("impact") else "",
                f"horizon: {s.get('horizon')}" if s.get("horizon") else "",
                f"confidence: {s.get('confidence')}" if s.get("confidence") else "",
                f"sources: {', '.join(s.get('sources') or [])}" if s.get("sources") else "",
            ] if x)
            if tags:
                body(tags, size=8, style="I")
            if s.get("implication"):
                body(s["implication"])
            if s.get("action"):
                rat = f" - {s['action_rationale']}" if s.get("action_rationale") else ""
                body(f"Action: {s['action']}{rat}", style="B")
            if s.get("value_capture"):
                body(f"Value capture: {s['value_capture']}")
            std = s.get("standards")
            if std and (std.get("leader") or std.get("read")):
                basis = f" (leads on {', '.join(std['basis'])})" if std.get("basis") else ""
                body(f"Standards: {std.get('leader', '')}{basis} {std.get('read', '')}")
            if s.get("falsifier"):
                body(f"Falsifier: {s['falsifier']}")
            pdf.ln(1)

    sc = read.get("scenarios") or {}
    if any(sc.values()):
        heading("Scenarios")
        for k in ("base", "bull", "bear"):
            if sc.get(k):
                body(f"{k.title()}: {sc[k]}")

    if read.get("convergence"):
        heading("Cross-domain convergence")
        for c in read["convergence"]:
            feeds = " + ".join(c.get("feeds") or [])
            tail = f" ({feeds})" if feeds else ""
            body(f"- {c.get('theme', '')}{tail}: {c.get('implication', '')}")

    if read.get("watch"):
        heading("What to watch")
        for w in read["watch"]:
            hz = f" [{w.get('horizon')}]" if w.get("horizon") else ""
            body(f"- {w.get('item', '')}{hz}: {w.get('why', '')}")

    return bytes(pdf.output())


class Strategist:
    def __init__(self, client: Client | None = None):
        self.client = client or get_supabase()
        self.pulse = PulseAggregator(self.client)
        self.kb = MotKnowledgeBase(self.client)

    # ── read side ─────────────────────────────────────────────────────────────
    def latest(self, focus: str = DEFAULT_FOCUS) -> Optional[dict]:
        """Most recent cached read for `focus`, or None."""
        try:
            resp = (
                self.client.table(STRATEGIST_TABLE)
                .select("*")
                .eq("focus", focus)
                .order("as_of", desc=True)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning("Could not read %s: %s", STRATEGIST_TABLE, e)
            return None

    def recent(self, focus: str = DEFAULT_FOCUS, limit: int = 2) -> list[dict]:
        """The last `limit` cached reads for `focus`, newest first — powers the
        'what changed since last time' diff."""
        try:
            resp = (
                self.client.table(STRATEGIST_TABLE)
                .select("*")
                .eq("focus", focus)
                .order("as_of", desc=True)
                .limit(limit)
                .execute()
            )
            return resp.data or []
        except Exception as e:
            logger.warning("Could not read %s: %s", STRATEGIST_TABLE, e)
            return []

    # ── generation ──────────────────────────────────────────────────────────--
    def generate(
        self,
        focus: str = DEFAULT_FOCUS,
        days: int = 14,
        max_stories: int = 18,
        k_theory: int = 8,
    ) -> dict:
        """Gather developments + theory, call the agent, parse + cache the read."""
        api_key = os.getenv(ENV_KEY)
        if not api_key:
            raise RuntimeError(
                f"{ENV_KEY} is not set in .env — the Strategist agent cannot be called."
            )

        stories = self._gather_stories(focus, days=days, max_stories=max_stories)
        if not stories:
            raise RuntimeError(
                "No material developments to reason over yet — refresh the feeds first."
            )

        passages = self._retrieve_theory(focus, stories, k=k_theory)
        tech_ctx = self._tech_context(days=days)
        fin_ctx = self._financial_context()
        # Yesterday's brief (strictly before today, so a same-day regeneration
        # doesn't compare against itself) — lets the agent mark each signal
        # new / carried-over / updated and explain action or confidence flips.
        today = datetime.now(timezone.utc).date().isoformat()
        prior = next(
            (r for r in self.recent(focus, limit=2) if str(r.get("as_of") or "") < today),
            None,
        )
        pack = self._build_pack(focus, stories, passages, tech_ctx, fin_ctx, prior)

        # The Strategist's spell is the heaviest in the product and has blown
        # the 25-min default twice under load (2026-07-09) while succeeding on
        # quiet scheduled runs — give it its own, longer ceiling. Env-tunable;
        # 480 polls × 5s = 40 min.
        agent = ToqanAgent(
            api_key=api_key,
            agent_name="Strategist Agent",
            max_poll_attempts=int(
                os.getenv("TOQAN_STRATEGIST_MAX_POLL_ATTEMPTS", "").strip() or 480),
        )
        read = self._parse_read(agent.ask(pack))

        as_of = datetime.now(timezone.utc).date().isoformat()
        row = {
            "as_of": as_of,
            "focus": focus,
            "strategic_read": read,
            "stories": [self._slim_story(i, s) for i, s in enumerate(stories, 1)],
            "theory": [self._slim_passage(i, p) for i, p in enumerate(passages, 1)],
            "window_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.client.table(STRATEGIST_TABLE).upsert(row, on_conflict="as_of,focus").execute()
        logger.info("Strategist read cached for %s (focus=%s)", as_of, focus)
        return row

    # ── story gathering ─────────────────────────────────────────────────────--
    def _gather_stories(self, focus: str, *, days: int, max_stories: int) -> list[dict]:
        rows = self.pulse.targeted_recent(
            days=days, business_impact="material", require_lens=False, limit_per_feed=60
        )
        # If material stories are thin, widen to contextual so the read isn't bare.
        if len(rows) < 6:
            extra = self.pulse.targeted_recent(
                days=days, business_impact="contextual", require_lens=False, limit_per_feed=40
            )
            seen = {s.get("url") for s in rows}
            rows += [r for r in extra if r.get("url") not in seen]

        if focus and focus != DEFAULT_FOCUS:
            filtered = self._filter_by_focus(rows, focus)
            rows = filtered or rows  # fall back to all if the focus filter empties

        rows.sort(
            key=lambda r: (str(r.get("published_at") or ""), str(r.get("fetched_at") or "")),
            reverse=True,
        )
        return rows[:max_stories]

    @staticmethod
    def _filter_by_focus(rows: list[dict], focus: str) -> list[dict]:
        needle = focus.strip().lower()
        norm_focus = normalize_entity(focus).lower()
        out = []
        for r in rows:
            hay = " ".join([
                str(r.get("title") or ""),
                str(r.get("summary") or ""),
                str(r.get("_feed_label") or ""),
                str(r.get("_feed_key") or ""),
                " ".join(str(c) for c in (r.get("companies") or [])),
            ]).lower()
            companies_norm = {normalize_entity(str(c)).lower() for c in (r.get("companies") or [])}
            if needle in hay or (norm_focus and norm_focus in companies_norm):
                out.append(r)
        return out

    # ── theory retrieval ────────────────────────────────────────────────────--
    def _retrieve_theory(self, focus: str, stories: list[dict], *, k: int) -> list[dict]:
        try:
            from vectordb.embedder import embed_query
        except Exception as e:  # openai not installed / import failure
            logger.warning("Strategist: embedder unavailable (%s) — skipping theory.", e)
            return []
        query = self._theory_query(focus, stories)
        try:
            return self.kb.search(embed_query(query), k=k)
        except Exception as e:  # missing OPENAI_API_KEY, KB empty, RPC error, …
            logger.warning("Strategist: theory retrieval failed (%s) — proceeding without it.", e)
            return []

    @staticmethod
    def _theory_query(focus: str, stories: list[dict]) -> str:
        if focus and focus != DEFAULT_FOCUS:
            topic = focus
        else:
            tags: Counter = Counter()
            comps: Counter = Counter()
            for s in stories:
                for t in (s.get("tags") or []):
                    tags[str(t).lower()] += 1
                for c in (s.get("companies") or []):
                    comps[normalize_entity(str(c))] += 1
            topic = ", ".join(
                [t for t, _ in tags.most_common(8)] + [c for c, _ in comps.most_common(6)]
            ) or "cross-domain technology developments"
        return f"{topic}. {_THEORY_FRAMING}"

    # ── technology trajectories (the unit of analysis, fed to the agent) ──────-
    def _tech_context(self, days: int) -> dict:
        """Current technology placements + recent stage transitions, so the agent
        reasons over trajectories (the decisive events), not just today's articles."""
        try:
            from analytics.tech_layer import TechAnalyst
            ta = TechAnalyst(self.client)
            return {"placements": ta.current_placements(days=days), "transitions": ta.transitions()}
        except Exception as e:
            logger.warning("Strategist: technology context unavailable (%s).", e)
            return {"placements": [], "transitions": []}

    def _financial_context(self) -> dict:
        """Real company financials + price series from Supabase, so the Capital
        signals (E1/E2) cite numbers instead of reasoning blind. Best-effort."""
        try:
            financials = (self.client.table("company_financials")
                          .select("entity,symbol,rd_intensity").execute().data or [])
            prices: dict = {}
            start = 0
            while True:
                chunk = (self.client.table("stock_prices").select("symbol,day,close")
                         .order("symbol").order("day").range(start, start + 999).execute().data or [])
                for r in chunk:
                    prices.setdefault(r["symbol"], []).append({"date": r["day"], "close": r["close"]})
                if len(chunk) < 1000:
                    break
                start += 1000
            return {"financials": financials, "prices": prices}
        except Exception as e:
            logger.warning("Strategist: financial context unavailable (%s).", e)
            return {"financials": [], "prices": {}}

    # ── pack building ───────────────────────────────────────────────────────--
    def _build_pack(
        self, focus: str, stories: list[dict], passages: list[dict],
        tech_ctx: Optional[dict] = None, fin_ctx: Optional[dict] = None,
        prior: Optional[dict] = None,
    ) -> str:
        as_of = datetime.now(timezone.utc).date().isoformat()
        lines = [
            f"AS OF: {as_of}",
            f"FOCUS: {focus}",
            MANDATE,
            "",
            "=== DEVELOPMENTS (cite as [S#]) ===",
        ]
        for i, s in enumerate(stories, 1):
            feed = s.get("_feed_label") or "?"
            also = s.get("_also_in") or []
            lens_bits = []
            for col, name in (
                ("maturity_stage", "maturity"),
                ("adoption_stage", "adoption"),
                ("strategic_move", "move"),
            ):
                if s.get(col):
                    lens_bits.append(f"{name}={s.get(col)}")
            lens = (" | lens: " + ", ".join(lens_bits)) if lens_bits else ""
            also_txt = f" | also in: {', '.join(also)}" if also else ""
            lines.append(
                f"[S{i}] ({feed}) {s.get('title')} "
                f"— src={s.get('source_name') or '?'}, date={s.get('published_at') or '?'}, "
                f"sentiment={s.get('sentiment')}, impact={s.get('business_impact')}, "
                f"scope={s.get('scope')}, companies={s.get('companies') or []}{also_txt}{lens}"
            )
            if s.get("summary"):
                lines.append(f"     {_truncate(s.get('summary'), 400)}")
            if s.get("lens_rationale"):
                lines.append(f"     lens rationale: {_truncate(s.get('lens_rationale'), 200)}")

        lines += ["", "=== MOT THEORY PASSAGES (cite as [T#]) ==="]
        if passages:
            for i, p in enumerate(passages, 1):
                sim = float(p.get("similarity") or 0)
                lines.append(f"[T{i}] {p.get('source_file') or '?'} (relevance {sim:.2f}):")
                lines.append(f"     {_truncate(p.get('chunk_text'), 700)}")
        else:
            lines.append("(none retrieved — reason from your MOT doctrine and say so)")

        # Technology trajectories — the unit of analysis. Transitions are the most
        # decisive events; lead with them when present.
        ctx = tech_ctx or {}
        transitions = ctx.get("transitions") or []
        placements = ctx.get("placements") or []
        if transitions or placements:
            lines += ["", "=== TECHNOLOGY TRAJECTORIES (units of analysis) ==="]
            if transitions:
                # Forward moves are the signal; backward moves are near-impossible on these
                # monotonic axes (re-estimation noise) — summarise them as a count so the model
                # isn't anchored by a long list of non-events.
                forward = [t for t in transitions if not t.get("backward")]
                backward = [t for t in transitions if t.get("backward")]
                lines.append(
                    "STAGE TRANSITIONS (forward moves only; flagged ones are watch-items, NOT "
                    "decisive: PENDING = one snapshot old, not yet confirmed; CONTESTED = no "
                    "majority stage behind it):"
                )
                for t in forward[:12]:
                    if t.get("contested"):
                        conf = " — CONTESTED (no majority stage; watch-item, not decisive)"
                    elif t.get("confirmed") is False:
                        conf = " — PENDING (one snapshot old; not yet confirmed)"
                    else:
                        ms = t.get("modal_share")
                        conf = f" (modal share {ms:.0%})" if isinstance(ms, (int, float)) else ""
                    lines.append(
                        f"  - {t.get('label')}: {t.get('dimension')} "
                        f"{t.get('from')} → {t.get('to')} (as of {t.get('as_of')}){conf}"
                    )
                if not forward:
                    lines.append("  - (none — no trustworthy forward moves this snapshot)")
                if backward:
                    lines.append(
                        f"  NOTE: {len(backward)} backward 'regression' move(s) this snapshot "
                        "(stage moved backward on a near-monotonic axis) — treat as re-estimation "
                        "noise, NOT events; omitted from the list above."
                    )
            if placements:
                from analytics.tech_layer import display_stage
                lines.append("CURRENT PLACEMENTS (committed lifecycle stage per tracked "
                             "technology — where the S-curve dot sits, i.e. the centroid of "
                             "its stage spread, not a thin plurality):")
                for p in placements[:18]:
                    flags = []
                    if p.get("mixed"):
                        flags.append("maturity contested")
                    if p.get("adoption_mixed"):
                        flags.append("adoption contested")
                    flag_txt = f"  [{'; '.join(flags)}]" if flags else ""
                    lines.append(
                        f"  - {p.get('label')}: maturity={display_stage(p)}, "
                        f"adoption={display_stage(p, 'adoption')}, move={p.get('move')}, "
                        f"players={p.get('entrants')}, articles={p.get('articles')}{flag_txt}"
                    )

        # Real company financials — let Capital signals (E1/E2) cite numbers.
        fin = fin_ctx or {}
        if fin.get("financials") or fin.get("prices"):
            from analytics.financials import financial_context
            from tickers import ticker_for
            block = financial_context(
                stories, fin.get("financials") or [], fin.get("prices") or {}, ticker_for
            )
            if block:
                lines += ["", block]

        # Prior brief — yesterday's signals, compact, so the agent can apply its
        # DAY-OVER-DAY CONTINUITY rules (mark signals new / carried-over /
        # updated and explain any action or confidence flip vs yesterday).
        prev_read = (prior or {}).get("strategic_read")
        if isinstance(prev_read, dict):
            prev_signals = [s for s in (prev_read.get("signals") or []) if isinstance(s, dict)]
            if prev_signals:
                lines += ["", f"=== PRIOR BRIEF (yesterday, as of {prior.get('as_of')}) ==="]
                for s in prev_signals:
                    lines.append(
                        f"  - {_truncate(s.get('title') or '?', 100)} "
                        f"— action={s.get('action') or '?'}, "
                        f"confidence={s.get('confidence') or '?'}"
                    )

        lines += [
            "",
            "=== TASK ===",
            "Return the structured JSON brief per your instructions (bottom_line, "
            "confidence, signals[] — each with action/impact/horizon/falsifier — "
            "convergence[], scenarios{base,bull,bear}, watch[]). Put the [S#] ids "
            "each signal rests on in `sources`; likewise give each convergence "
            "item a `sources` array of the [S#] ids it draws on. Cite theory as [T#]. Treat a "
            "technology STAGE TRANSITION as a top-tier decisive signal; reference "
            "technologies by name. Where COMPANY FINANCIALS are given, ground "
            "Capital signals (E1/E2) in them — cite the R&D intensity or the measured "
            "price reaction. End every signal in a client action. JSON only.",
        ]
        return "\n".join(lines)

    # ── parsing + slimming ──────────────────────────────────────────────────--
    @staticmethod
    def _parse_read(raw: str) -> dict:
        """Parse the Strategist answer into a structured brief.

        Preferred: the structured JSON object (bottom_line + signals + …), which
        the UI renders as a consultant card deck. Falls back to a legacy
        headline/markdown object or, last, the raw prose as {"markdown": ...}.
        Only raises on empty input.
        """
        obj = parse_json_object(raw)
        if isinstance(obj, dict) and (obj.get("bottom_line") or obj.get("signals")):
            return _normalize_structured(obj)
        if isinstance(obj, dict) and (
            obj.get("markdown") or obj.get("headline") or obj.get("top_line")
        ):
            return obj  # legacy structured/markdown shapes
        md = _THINK_RE.sub("", raw or "").strip()
        if not md:
            raise ValueError("Empty Strategist response")
        return {"markdown": md}

    @staticmethod
    def _slim_story(idx: int, s: dict) -> dict:
        return {
            "label": f"S{idx}",
            "title": s.get("title"),
            "url": s.get("url"),
            "source_name": s.get("source_name"),
            "published_at": s.get("published_at"),
            "summary": s.get("summary"),
            "companies": s.get("companies") or [],
            "sentiment": s.get("sentiment"),
            "business_impact": s.get("business_impact"),
            "scope": s.get("scope"),
            "feed_label": s.get("_feed_label"),
            "feed_icon": s.get("_feed_icon"),
            "also_in": s.get("_also_in") or [],
            "maturity_stage": s.get("maturity_stage"),
            "adoption_stage": s.get("adoption_stage"),
            "strategic_move": s.get("strategic_move"),
            "lens_rationale": s.get("lens_rationale"),
        }

    @staticmethod
    def _slim_passage(idx: int, p: dict) -> dict:
        return {
            "label": f"T{idx}",
            "source_file": p.get("source_file"),
            "similarity": float(p.get("similarity") or 0),
            "chunk_text": _truncate(p.get("chunk_text"), 1200),
        }
