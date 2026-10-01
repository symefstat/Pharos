"""
The Analyst — commissioned, accountable analysis on any topic.

Ask answers a question from the top-12 relevant items in seconds; the Analyst
is the opposite contract: it sweeps everything Lodestar tracks about a topic —
classified stories across all feeds, lifecycle stages and transitions, nearby
forecasts (with falsifiers and resolved outcomes), capital moves, the funding
signal, financials — and produces a stored, decision-ready note that ends in a
posture with a falsifier. The central call can then be locked into the ledger
and graded like every other forecast: analysis that goes on the record.

Trust architecture (the same discipline as the rest of the product):
- The agent writes ONLY prose. Every exhibit (tables, trend, players) is
  computed HERE from the database and rendered natively — a plot can't
  hallucinate.
- Citations are stories only ([S#], range-checked); a [T#] theory tag anywhere
  rejects the report. Theory is applied by name in prose.
- The posture block is parsed and validated (posture/confidence/falsifier/
  date all required) before anything is stored.

Pure pieces (pack formatting, exhibits, posture parsing, validation) are
unit-tested; `run_analysis` does the I/O.
"""

from __future__ import annotations

import logging
import os
import re
from collections import Counter
from datetime import date

logger = logging.getLogger(__name__)

ENV_KEY = "TOQAN_ANALYST"
REPORTS_TABLE = "analyst_reports"
PROMPT_VERSION = "analyst-v1"

MAX_STORIES = 25
THIN_COVERAGE_BELOW = 8       # matched stories under this → the pack says "thin"
MAX_WORDS = 800               # validator ceiling (contract says 550; allow slack)

_CIT_RE = re.compile(r"\[S(\d+)\]")
_THEORY_TAG_RE = re.compile(r"\[T\d+\]")
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

POSTURES = ("invest", "watch", "partner", "defend", "avoid")


# ── posture block ──────────────────────────────────────────────────────────────

def normalize_citations(text: str) -> str:
    """'[S2, S4]' / '[S2,S4]' → '[S2][S4]' (pure). Agents group citations
    despite the contract; normalizing at ingest keeps the phantom check honest
    (grouped tags would otherwise bypass it) and the chip renderer simple."""
    def _expand(m: re.Match) -> str:
        nums = re.findall(r"\d+", m.group(0))
        return "".join(f"[S{n}]" for n in nums)

    return re.sub(r"\[S\d+(?:\s*,\s*S?\d+)+\]", _expand, text or "")


def parse_posture(text: str) -> dict | None:
    """Extract the structured posture block (pure). None when any required
    field is missing/unparseable — the caller rejects the report.

    Tolerant of markdown DECORATION only (bold field names, list bullets,
    blockquotes, stray backticks) — the content requirements stay strict."""
    def grab(field: str) -> str | None:
        m = re.search(rf"^[>\s*-]*\**\s*{field}\s*\**\s*:\s*(.+)$",
                      text or "", re.MULTILINE | re.IGNORECASE)
        return m.group(1).strip().strip("*`").strip() if m else None

    posture_raw = (grab("POSTURE") or "").lower()
    posture = next((p for p in POSTURES if p in posture_raw), None)
    conf_m = re.search(r"(\d{1,3})\s*%", grab("CONFIDENCE") or "")
    confidence = int(conf_m.group(1)) if conf_m else None
    wrong_if = grab("WRONG IF")
    resolve_m = re.search(r"(\d{4}-\d{2}-\d{2})", grab("RESOLVE BY") or "")
    addressee = grab("ADDRESSEE")

    if not (posture and confidence and 1 <= confidence <= 99
            and wrong_if and resolve_m and addressee):
        return None
    return {
        "posture": posture,
        "addressee": addressee,
        "confidence": confidence / 100,
        "falsifier": wrong_if,
        "resolve_by": resolve_m.group(1),
    }


def validate_report(text: str, n_stories: int) -> str | None:
    """Reject an unusable report (pure). Error string, or None when it passes."""
    t = (text or "").strip()
    if len(t) < 200:
        return "too short"
    if len(t.split()) > MAX_WORDS:
        return f"over the length ceiling ({len(t.split())} words)"
    if _THEORY_TAG_RE.search(t):
        return "theory [T#] tags are forbidden — frameworks belong in prose"
    phantoms = [m for m in _CIT_RE.findall(t) if not (1 <= int(m) <= n_stories)]
    if phantoms:
        return f"phantom citations: S{', S'.join(sorted(set(phantoms)))}"
    if parse_posture(t) is None:
        return "posture block missing or incomplete (POSTURE/ADDRESSEE/CONFIDENCE/WRONG IF/RESOLVE BY)"
    return None


# ── exhibits — computed from data, never by the agent ─────────────────────────

def build_exhibits(stories: list[dict], tracked: list[dict],
                   capital: dict, funding: dict | None) -> dict:
    """The report's visual evidence, straight from the database (pure).
    Rendered natively by the frontend; the agent only refers to them."""
    by_month: Counter = Counter()
    for s in stories:
        d = str(s.get("published_at") or "")[:7]
        if len(d) == 7:
            by_month[d] += 1
    players: Counter = Counter()
    from analytics.entities import normalize
    for s in stories:
        for c in s.get("companies") or []:
            name = normalize(str(c))
            if name:
                players[name] += 1
    return {
        "mention_trend": [{"month": m, "count": c} for m, c in sorted(by_month.items())],
        "stage_table": [{
            "tech": t.get("tech"), "label": t.get("label"),
            "maturity": t.get("maturity"), "adoption": t.get("adoption"),
            "watching": bool(t.get("watching")), "articles": t.get("articles"),
        } for t in tracked],
        "capital_split": capital.get("counts", {"commitment": 0, "option": 0}),
        "players": [{"name": n, "mentions": c} for n, c in players.most_common(8)],
        "funding": ({"rounds": funding["rounds"], "early": funding["early"],
                     "late": funding["late"], "read": funding.get("read")}
                    if funding else None),
    }


# ── pack assembly ──────────────────────────────────────────────────────────────

def format_pack(topic: str, stories: list[dict], tracked: list[dict],
                forecasts: list[dict], capital: dict, funding: dict | None,
                theory: list[dict], fin_block: str | None, today: str) -> str:
    """The Analyst's briefing pack (pure). Theory passages are included for
    reasoning but deliberately UNLABELED — there is nothing to cite them as."""
    thin = len(stories) < THIN_COVERAGE_BELOW
    lines = [f"COMMISSIONED TOPIC: {topic}",
             f"AS OF: {today}",
             f"COVERAGE: {'thin — say so up front' if thin else 'adequate'} "
             f"({len(stories)} matched stories)", ""]

    lines.append("=== STORIES (cite as [S#]) ===")
    if stories:
        for i, s in enumerate(stories, 1):
            lines.append(f"[S{i}] ({str(s.get('published_at') or '?')[:10]}, "
                         f"{s.get('_feed_label') or '?'}) {s.get('title')}")
            if s.get("summary"):
                summary = " ".join(str(s["summary"]).split())[:300]
                lines.append(f"     {summary}")
    else:
        lines.append("(none — the feeds do not cover this topic)")

    if tracked:
        lines += ["", "=== TRACKED LIFECYCLE STATE (authoritative for stages) ==="]
        for t in tracked:
            if t.get("watching"):
                lines.append(f"- {t.get('label')}: WATCHING — below the evidence floor, no stage claim")
            else:
                lines.append(f"- {t.get('label')}: maturity={t.get('maturity')} · "
                             f"adoption={t.get('adoption')} · {t.get('articles')} articles/30d")

    if forecasts:
        lines += ["", "=== NEARBY FORECASTS (locked; outcomes where resolved) ==="]
        for f in forecasts[:8]:
            status = f.get("outcome") or f.get("status")
            conf = f" @ {round(float(f['confidence']) * 100)}%" if f.get("confidence") else ""
            lines.append(f"- [{status}] {f.get('claim')}{conf}")

    c, o = capital.get("counts", {}).get("commitment", 0), capital.get("counts", {}).get("option", 0)
    if c + o:
        lines += ["", f"=== CAPITAL MOVES (30d) === {c} commitments vs {o} real options"]
        for m in (capital.get("commitment") or [])[:4] + (capital.get("option") or [])[:4]:
            lines.append(f"- ({m.get('kind')}) {m.get('title')}")

    if funding:
        lines += ["", "=== FUNDING SIGNAL (independent of news) ===",
                  f"{funding['rounds']} rounds/12mo · {funding['early']} early vs "
                  f"{funding['late']} late" + (f" · {funding['read']}" if funding.get("read") else "")]

    if fin_block:
        lines += ["", fin_block]

    if theory:
        lines += ["", "=== THEORY BACKGROUND (apply by NAME in prose — there is no tag to cite) ==="]
        for p in theory[:4]:
            chunk = " ".join(str(p.get("chunk_text") or "").split())[:400]
            lines.append(f"- {chunk}")

    lines += ["", "Write the commissioned report per your instructions."]
    return "\n".join(lines)


def gather(client, topic: str, days: int = 180) -> dict:
    """All I/O for one commission. Each part degrades independently."""
    from analytics.ask import AskLodestar
    from analytics.mot_analyst import capital_moves
    from analytics.tech_layer import match_technologies
    from technologies import registry

    ask = AskLodestar(client)
    stories = ask._news(topic, days=days, max_stories=MAX_STORIES)

    reg = registry(client)
    keys: set[str] = set()
    probe = {"title": topic, "summary": topic, "companies": [], "tags": []}
    keys |= set(match_technologies(probe, reg))
    for s in stories:
        keys |= set(match_technologies(s, reg))

    tracked: list[dict] = []
    try:
        from analytics.tech_layer import TechAnalyst, display_stage

        for p in TechAnalyst(client).current_placements(days=30):
            if p.get("tech") in keys:
                tracked.append({
                    "tech": p["tech"], "label": p.get("label"),
                    "maturity": None if p.get("watching") else display_stage(p),
                    "adoption": None if p.get("watching") else display_stage(p, "adoption"),
                    "watching": bool(p.get("watching")),
                    "articles": p.get("stage_articles") or 0,
                })
    except Exception as e:
        logger.warning("Analyst: placements unavailable (%s)", e)

    forecasts: list[dict] = []
    try:
        from backend.app import data

        toks = {w for w in re.findall(r"[a-z0-9]+", topic.lower()) if len(w) >= 4}
        for p in data.predictions():
            hay = f"{p.get('claim') or ''} {p.get('subject') or ''}".lower()
            if p.get("subject") in keys or sum(1 for t in toks if t in hay) >= 2:
                forecasts.append(p)
    except Exception as e:
        logger.warning("Analyst: forecasts unavailable (%s)", e)

    capital = {"commitment": [], "option": [], "counts": {"commitment": 0, "option": 0}}
    try:
        moves = capital_moves(stories)
        capital = {
            "commitment": [m for m in moves if m["kind"] == "commitment"],
            "option": [m for m in moves if m["kind"] == "option"],
            "counts": {"commitment": sum(1 for m in moves if m["kind"] == "commitment"),
                       "option": sum(1 for m in moves if m["kind"] == "option")},
        }
    except Exception as e:
        logger.warning("Analyst: capital read failed (%s)", e)

    funding = None
    try:
        from analytics.funding import funding_read, funding_summary, tech_funding

        rows: list[dict] = []
        for k in keys:
            rows += tech_funding(client, k) or []
        summary = funding_summary(rows, date.today())
        if summary:
            stage = next((t.get("maturity") for t in tracked if t.get("maturity")), None)
            summary["read"] = funding_read(rows, stage, date.today())
            funding = summary
    except Exception as e:
        logger.warning("Analyst: funding unavailable (%s)", e)

    theory = ask._theory(topic, k=4)

    fin_block = None
    try:
        from analytics.financials import financial_context
        from tickers import ticker_for

        ctx = ask._financial_context()
        fin_block = financial_context(stories, ctx.get("financials") or [],
                                      ctx.get("prices") or {}, ticker_for) or None
    except Exception as e:
        logger.warning("Analyst: financial context unavailable (%s)", e)

    return {"stories": stories, "tracked": tracked, "forecasts": forecasts,
            "capital": capital, "funding": funding, "theory": theory,
            "fin_block": fin_block}


def run_analysis(client, topic: str, created_by: str) -> dict:
    """Commission one report: gather → agent → validate → store. Returns the
    stored row, or raises with a human-readable reason (surfaced in the job)."""
    from toqan.client import ToqanAgent

    api_key = os.getenv(ENV_KEY)
    if not api_key:
        raise RuntimeError(f"{ENV_KEY} is not set — create the Analyst agent from "
                           "Agents_prompt/Analyst_Agent.md and add its key to .env")

    today = date.today().isoformat()
    parts = gather(client, topic)
    pack = format_pack(topic, parts["stories"], parts["tracked"], parts["forecasts"],
                       parts["capital"], parts["funding"], parts["theory"],
                       parts["fin_block"], today)

    raw = ToqanAgent(api_key=api_key, agent_name="Analyst Agent",
                     max_poll_attempts=int(os.getenv("TOQAN_ANALYST_MAX_POLL_ATTEMPTS", "").strip() or 120)
                     ).ask(pack)
    report = normalize_citations(_THINK_RE.sub("", raw or "").strip())

    err = validate_report(report, len(parts["stories"]))
    if err:
        raise RuntimeError(f"report rejected: {err}")
    posture = parse_posture(report)

    row = {
        "topic": topic,
        "report": report,
        "posture": posture,
        "exhibits": build_exhibits(parts["stories"], parts["tracked"],
                                   parts["capital"], parts["funding"]),
        "citations": [{"label": f"S{i}", "title": s.get("title"), "url": s.get("url"),
                       "feed": s.get("_feed_label"),
                       "published_at": str(s.get("published_at") or "")[:10] or None}
                      for i, s in enumerate(parts["stories"], 1)],
        "coverage": "thin" if len(parts["stories"]) < THIN_COVERAGE_BELOW else "adequate",
        "as_of": today,
        "created_by": created_by,
        "prompt_version": PROMPT_VERSION,
    }
    res = client.table(REPORTS_TABLE).insert(row).execute()
    stored = (res.data or [row])[0]
    logger.info("Analyst: stored report %s for topic %r", stored.get("id"), topic)
    return stored


# ── follow-up interrogation — the author defends the published note ─────────────

FOLLOWUP_MAX_WORDS = 300      # contract says ≤150; validator allows slack


def format_followup(report_row: dict, question: str,
                    history: list[dict] | None = None) -> str:
    """The follow-up pack (pure): the stored report + its citations + the
    question, with the rules inlined so behavior holds server-side even before
    the Toqan prompt is updated. The published call is immutable — a material
    gap gets acknowledged and answered with 're-commission', never a revision."""
    lines = [f"FOLLOW-UP QUESTION on report #{report_row.get('id')} "
             f"(“{report_row.get('topic')}”, {report_row.get('as_of')})", ""]
    prior = [h for h in (history or []) if h.get("content")][-4:]
    if prior:
        lines.append("=== DISCUSSION SO FAR ===")
        for h in prior:
            content = " ".join(str(h.get("content") or "").split())[:280]
            lines.append(f"{str(h.get('role', 'user')).upper()}: {content}")
        lines.append("")
    lines += ["=== THE PUBLISHED REPORT (immutable — you are its author) ===",
              report_row.get("report") or "", ""]
    cits = report_row.get("citations") or []
    if cits:
        lines.append("=== ITS SOURCES (the ONLY citable [S#] set) ===")
        for c in cits:
            lines.append(f"[{c.get('label')}] ({c.get('published_at') or '?'}, "
                         f"{c.get('feed') or '?'}) {c.get('title')}")
        lines.append("")
    lines += [f"QUESTION: {question}", "",
              "=== TASK ===",
              "Answer as the report's author defending and explaining the published "
              "call — direct, ≤150 words, no restating the report. Cite only [S#] "
              "from ITS SOURCES above; never [T#]; numbers verbatim from the report/"
              "sources; no new claims about events outside them (no web research). "
              "The published call STANDS AS WRITTEN: if the question raises something "
              "material that your pack did not cover, say so honestly and recommend "
              "commissioning an updated report — never revise the posture in chat."]
    return "\n".join(lines)


def validate_followup(text: str, n_citations: int) -> str | None:
    """Reject an unusable follow-up answer (pure)."""
    t = (text or "").strip()
    if len(t) < 20:
        return "too short"
    if len(t.split()) > FOLLOWUP_MAX_WORDS:
        return f"over the length ceiling ({len(t.split())} words)"
    if _THEORY_TAG_RE.search(t):
        return "theory [T#] tags are forbidden"
    phantoms = [m for m in _CIT_RE.findall(t) if not (1 <= int(m) <= n_citations)]
    if phantoms:
        return f"phantom citations: S{', S'.join(sorted(set(phantoms)))}"
    return None


def answer_followup(client, report_id: int, question: str,
                    history: list[dict] | None = None) -> dict:
    """One interrogation turn: fetch the report, build the pack, ask the same
    Analyst agent, validate. The answer is conversation — never stored; the
    record is the report."""
    from toqan.client import ToqanAgent

    api_key = os.getenv(ENV_KEY)
    if not api_key:
        raise RuntimeError(f"{ENV_KEY} is not set")
    rows = (client.table(REPORTS_TABLE).select("*")
            .eq("id", report_id).limit(1).execute().data or [])
    if not rows:
        raise LookupError(f"no report {report_id}")
    report_row = rows[0]

    raw = ToqanAgent(api_key=api_key, agent_name="Analyst Agent (follow-up)",
                     max_poll_attempts=36).ask(
        format_followup(report_row, question, history))
    answer = normalize_citations(_THINK_RE.sub("", raw or "").strip())
    err = validate_followup(answer, len(report_row.get("citations") or []))
    if err:
        raise RuntimeError(f"answer rejected: {err}")
    return {"answer": answer, "report_id": report_id}
