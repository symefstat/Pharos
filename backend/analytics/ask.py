"""
Ask Lodestar — a conversational analyst over the feeds + MOT theory.

Given a question (and short chat history), retrieve the most relevant recent
developments (keyword match) and MOT theory passages (RAG), build a labelled
pack, and ask the Toqan Ask agent for a grounded, cited answer. The agent is
only ever called on a user question — never on render.

`_relevant_stories` is pure (unit-tested); retribackend/eval/agent call hit the network.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, timedelta

from supabase import Client

from db import get_supabase
from analytics.aggregator import PulseAggregator, _normalize_url
from analytics.events import _STOP
from toqan.client import ToqanAgent
from vectordb.store import MotKnowledgeBase
from vectordb.news_store import NewsVectorStore

logger = logging.getLogger(__name__)

ENV_KEY = "TOQAN_ASK"
# Ask runs inside a web request (sync endpoint / SSE worker thread), so it gets
# its own, much smaller poll budget than the pipeline's 25-min default: a slow
# Toqan spell must not pin server threads for 25 min each — that exhausts the
# ~40-thread pool and takes down /api/health with it. 36 × 5s = 3 min.
_ASK_MAX_POLL_ATTEMPTS = int(os.getenv("TOQAN_ASK_MAX_POLL_ATTEMPTS", "").strip() or 36)
# Cosine-similarity floor for news relevance. Calibrated against real queries:
# on-topic news scores ≥0.53, off-topic (e.g. a history/theory question) ≤0.32,
# so 0.45 keeps relevant developments and drops loosely-related noise.
_NEWS_SIM_FLOOR = 0.45
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CIT_RE = re.compile(r"\[([ST])(\d+)\]")


def _question_tokens(question: str) -> set:
    return {t for t in _TOKEN_RE.findall((question or "").lower())
            if len(t) >= 3 and t not in _STOP}


# Lifecycle/stage intent — when the question is about where technologies sit on
# their curve, the answer must come from Lodestar's OWN tracked state, not from
# external stage frameworks the agent happens to know (the Gartner-answer bug).
# "s-curve" tokenizes to {"curve"}; "lifecycle stage" to {"lifecycle", "stage"}.
_STAGE_INTENT = {"stage", "stages", "lifecycle", "maturity", "transition",
                 "transitions", "chasm", "diffusion", "adoption", "curve",
                 # horizon-scan intent — "anything new/emerging?" should ground
                 # in the tracked state + radar candidates, not model memory
                 "radar", "emerging", "emerge", "new", "novel", "upcoming"}
# Recency intent — claims about what happened lately must be grounded in the
# retrieved pack ([S#] / tracked state), never in web research or model memory.
_RECENCY_RE = re.compile(
    r"\b(recent(ly)?|latest|today|right now|currently"
    r"|this (week|month|quarter|year)|last (week|month|quarter)"
    r"|past \d+ (days?|weeks?|months?))\b", re.IGNORECASE)


def _stage_question(question: str) -> bool:
    return bool(_question_tokens(question) & _STAGE_INTENT)


def _recency_question(question: str) -> bool:
    return bool(_RECENCY_RE.search(question or ""))


def _relevant_stories(rows: list[dict], question: str, top: int = 12) -> list[dict]:
    """Recent stories most relevant to the question (pure keyword overlap on
    title + summary + companies + tags; material stories get a small boost)."""
    qtokens = _question_tokens(question)
    if not qtokens:
        return []
    scored = []
    for r in rows:
        hay = " ".join([
            str(r.get("title") or ""), str(r.get("summary") or ""),
            " ".join(str(c) for c in (r.get("companies") or [])),
            " ".join(str(t) for t in (r.get("tags") or [])),
        ]).lower()
        hits = sum(1 for t in qtokens if t in hay)
        if hits:
            material = 1 if (r.get("business_impact") or "").lower() == "material" else 0
            scored.append((hits + material, str(r.get("published_at") or ""), r))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [r for _, _, r in scored[:top]]


def _merge_stories(vec: list[dict], kw: list[dict], limit: int) -> list[dict]:
    """Merge the vector-retrieved and keyword-retrieved story lists, deduped by
    normalized URL, capped at `limit`. Vector hits (semantic relevance) rank
    first; keyword hits fill the remainder — so exact-token matches a query
    embedding may under-rank (a ticker, a code name) still make the pack. Pure;
    unit-tested. Either input may be empty (the other becomes the fallback)."""
    merged: list[dict] = []
    seen: set[str] = set()
    for r in list(vec) + list(kw):
        key = _normalize_url(r.get("url") or "") or (r.get("title") or "")
        if key in seen:
            continue
        seen.add(key)
        merged.append(r)
        if len(merged) >= limit:
            break
    return merged


def _neutralize_phantom_citations(answer: str, n_stories: int, n_theory: int) -> str:
    """Range-check every [S#]/[T#] in the answer against the retrieved set
    (labels are positional: S1..Sn, T1..Tk). Out-of-range references are
    replaced with a visible "[unverified]" marker and logged, so a hallucinated
    citation can never render as if it pointed at a real source. In-range
    citations pass through untouched."""
    phantoms: list[str] = []

    def _check(m: re.Match) -> str:
        kind, idx = m.group(1), int(m.group(2))
        limit = n_stories if kind == "S" else n_theory
        if 1 <= idx <= limit:
            return m.group(0)
        phantoms.append(f"{kind}{idx}")
        return "[unverified]"

    guarded = _CIT_RE.sub(_check, answer or "")
    if phantoms:
        logger.warning("Ask: neutralized %d phantom citation(s) outside the retrieved set: %s",
                       len(phantoms), sorted(set(phantoms)))
        guarded += ("\n\n_Note: some citations referenced sources that were not in the "
                    "retrieved set and were marked [unverified]._")
    return guarded


def _truncate(text, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _finalize(raw: str, n_stories: int, n_theory: int) -> tuple[str, str]:
    """Split the agent's raw output into (answer, thinking).

    The agent emits its reasoning trace in a leading <think>…</think> block; we
    surface that separately (the UI's collapsible "Thinking" panel) and keep it
    out of the cited answer, then run the phantom-citation guard on the answer."""
    m = _THINK_RE.search(raw or "")
    thinking = re.sub(r"</?think>", "", m.group(0)).strip() if m else ""
    answer = _THINK_RE.sub("", raw or "").strip()
    answer = _neutralize_phantom_citations(answer, n_stories, n_theory)
    return answer or "_(no answer)_", thinking


class AskLodestar:
    def __init__(self, client: Client | None = None):
        self.client = client or get_supabase()
        self.pulse = PulseAggregator(self.client)
        self.kb = MotKnowledgeBase(self.client)

    def answer(self, question: str, history: list[dict] | None = None,
               days: int = 30, k_theory: int = 6, max_stories: int = 12) -> dict:
        api_key = os.getenv(ENV_KEY)
        if not api_key:
            raise RuntimeError(f"{ENV_KEY} is not set in .env — the Ask agent cannot be called.")

        stories = self._news(question, days, max_stories)
        passages = self._theory(question, k_theory)
        tracked = self._tracked_state() if _stage_question(question) else ""
        pack = self._build_pack(question, history or [], stories, passages,
                                self._financial_context(), tracked=tracked)
        raw = ToqanAgent(api_key=api_key, agent_name="Ask Lodestar Agent",
                         max_poll_attempts=_ASK_MAX_POLL_ATTEMPTS).ask(pack)
        answer, thinking = _finalize(raw, len(stories), len(passages))
        return {
            "answer": answer, "thinking": thinking,
            "stories": self._story_sources(stories),
            "theory": self._theory_sources(passages),
        }

    def answer_events(self, question: str, history: list[dict] | None = None,
                      days: int = 30, k_theory: int = 6, max_stories: int = 12):
        """Generator form of answer(): yields event dicts as each stage happens,
        so the API can stream them (SSE) for a live 'thinking' experience.

        Events: {"type": "stage", "label": …}   — a step began
                {"type": "meta", "stories": …, "theory": …}  — retrieved sources
                {"type": "tick", "elapsed": n}   — still waiting on the agent (n s)
                {"type": "done", "answer", "thinking", "stories", "theory"}
                {"type": "error", "message": …}
        Toqan has no token stream, so the answer arrives whole at the end; the
        stages + tick timer are real (retrieval genuinely runs in this order)."""
        import queue
        import threading

        api_key = os.getenv(ENV_KEY)
        if not api_key:
            yield {"type": "error", "message": f"{ENV_KEY} is not set in .env."}
            return

        yield {"type": "stage", "label": "Retrieving recent news…"}
        stories = self._news(question, days, max_stories)
        yield {"type": "stage", "label": "Matching MOT theory…"}
        passages = self._theory(question, k_theory)
        tracked = ""
        if _stage_question(question):
            yield {"type": "stage", "label": "Reading Lodestar's tracked lifecycle state…"}
            tracked = self._tracked_state()
        yield {"type": "meta",
               "stories": self._story_sources(stories),
               "theory": self._theory_sources(passages)}
        yield {"type": "stage",
               "label": f"Reasoning over {len(stories)} developments + {len(passages)} passages…"}

        pack = self._build_pack(question, history or [], stories, passages,
                                self._financial_context(), tracked=tracked)
        q: "queue.Queue" = queue.Queue()
        box: dict = {}

        def _run():
            try:
                box["raw"] = ToqanAgent(api_key=api_key, agent_name="Ask Lodestar Agent",
                                        max_poll_attempts=_ASK_MAX_POLL_ATTEMPTS).ask(
                    pack, poll_callback=lambda e: q.put(("tick", e)))
            except Exception as exc:  # surfaced as an error event below
                box["err"] = str(exc)
            q.put(("done", None))

        threading.Thread(target=_run, daemon=True).start()
        while True:
            kind, val = q.get()
            if kind == "done":
                break
            yield {"type": "tick", "elapsed": val}

        if "err" in box:
            yield {"type": "error", "message": box["err"]}
            return
        answer, thinking = _finalize(box.get("raw", ""), len(stories), len(passages))
        yield {"type": "done", "answer": answer, "thinking": thinking,
               "stories": self._story_sources(stories),
               "theory": self._theory_sources(passages)}

    def _news(self, question: str, days: int, max_stories: int) -> list[dict]:
        """News retrieval, relevance-gated by semantic similarity.

        Vector search is the relevance judge (only hits at/above _NEWS_SIM_FLOOR
        count). If it finds relevant news, keyword hits top up the list. If the
        index is available but nothing clears the floor, return nothing rather
        than let the keyword branch drag in loosely-related stories — a theory/
        history question shouldn't surface off-topic developments. Keyword is
        used alone only when the vector path is unavailable (no embeddings/index)."""
        vec, ok = self._vector_stories(question, k=max_stories, days=days)
        recent = self.pulse.all_recent(days=days)
        if vec:
            return _merge_stories(vec, _relevant_stories(recent, question, top=max_stories), max_stories)
        if not ok:
            return _relevant_stories(recent, question, top=max_stories)
        return []

    @staticmethod
    def _story_sources(stories: list[dict]) -> list[dict]:
        return [{"label": f"S{i}", "title": s.get("title"), "url": s.get("url"),
                 "feed": s.get("_feed_label"), "published_at": s.get("published_at")}
                for i, s in enumerate(stories, 1)]

    @staticmethod
    def _theory_sources(passages: list[dict]) -> list[dict]:
        return [{"label": f"T{i}", "source_file": p.get("source_file"),
                 "similarity": float(p.get("similarity") or 0),
                 "chunk_text": _truncate(p.get("chunk_text"), 900)}
                for i, p in enumerate(passages, 1)]

    def _vector_stories(self, question: str, k: int, days: int) -> tuple[list[dict], bool]:
        """Relevance-gated news from the vector index: only hits at/above
        _NEWS_SIM_FLOOR, mapped to the row shape `_build_pack` expects.

        Returns (stories, ok). ok=False means embeddings/index were unavailable,
        so the caller should fall back to keyword retrieval; ok=True with an empty
        list means the index worked but nothing was relevant enough."""
        try:
            from vectordb.embedder import embed_query

            since = (date.today() - timedelta(days=days)).isoformat()
            hits = NewsVectorStore(self.client).search(embed_query(question), k=k, since=since)
            rel = [h for h in hits if float(h.get("similarity") or 0) >= _NEWS_SIM_FLOOR]
            return [{
                "title": h.get("title"), "summary": h.get("summary"), "url": h.get("url"),
                "_feed_label": h.get("feed_label"), "published_at": h.get("published_at"),
                "business_impact": h.get("business_impact"), "companies": h.get("companies") or [],
            } for h in rel], True
        except Exception as e:
            logger.warning("Ask: news vector retrieval failed (%s) — falling back to keyword.", e)
            return [], False

    def _theory(self, question: str, k: int) -> list[dict]:
        try:
            from vectordb.embedder import embed_query
            return self.kb.search(embed_query(question), k=k)
        except Exception as e:
            logger.warning("Ask: theory retrieval failed (%s) — proceeding without it.", e)
            return []

    def _tracked_state(self) -> str:
        """Lodestar's own lifecycle read — the latest per-technology stage
        snapshot plus fresh stage transitions — formatted as a pack block.
        Mirrors the MOT surface's discipline: technologies below the evidence
        floor make no stage claims (listed as watching), and backward moves are
        excluded. Best-effort: returns '' when the history table is unavailable,
        and the pack simply omits the block."""
        try:
            from analytics.tech_layer import EVIDENCE_FLOOR, HISTORY_TABLE, TechAnalyst

            rows = (self.client.table(HISTORY_TABLE).select("*")
                    .order("as_of", desc=True).limit(400).execute().data or [])
            if not rows:
                return ""
            latest: dict[str, dict] = {}
            for r in rows:  # ordered as_of desc → first row per tech is newest
                t = r.get("technology")
                if t and t not in latest:
                    latest[t] = r
            placed = {t: r for t, r in latest.items()
                      if int(r.get("article_count") or 0) >= EVIDENCE_FLOOR}
            if not placed:
                return ""
            as_of = max(str(r.get("as_of") or "") for r in placed.values())
            lines = [f"Current stages (as of {as_of}; news-anchored, evidence floor "
                     f"≥{EVIDENCE_FLOOR} stage-classified articles/30d):"]
            for t, r in sorted(placed.items(), key=lambda x: str(x[1].get("label") or x[0])):
                lines.append(
                    f"- {r.get('label') or t} ({r.get('domain') or '?'}): "
                    f"maturity={r.get('maturity_stage')}, adoption={r.get('adoption_stage')}, "
                    f"articles(30d)={r.get('article_count')}")
            watching = sorted(str(r.get("label") or t) for t, r in latest.items()
                              if t not in placed)
            if watching:
                lines.append("Watching (below the evidence floor — no stage claims): "
                             + ", ".join(watching))
            trans = [t for t in TechAnalyst(self.client).transitions()
                     if t.get("technology") in placed and not t.get("backward")][:12]
            if trans:
                lines.append("Recent stage transitions (pending = awaiting a confirming "
                             "snapshot; contested = destination stage lacked a clear majority):")
                for t in trans:
                    status = ("contested" if t.get("contested")
                              else "confirmed" if t.get("confirmed") else "pending")
                    lines.append(f"- {t.get('label')}: {t.get('dimension')} "
                                 f"{t.get('from')} → {t.get('to')} · {t.get('as_of')} · {status}")
            radar = self._radar_state()
            if radar:
                lines.append(radar)
            return "\n".join(lines)
        except Exception as e:
            logger.warning("Ask: tracked lifecycle state unavailable (%s).", e)
            return ""

    def _radar_state(self) -> str:
        """Radar candidates as a pack block — so 'anything new/emerging?' can be
        answered from what the horizon scan actually surfaced, instead of the
        agent guessing. Candidates are NOT tracked technologies; the block says
        so explicitly. Best-effort: '' when the table is missing/empty."""
        try:
            from analytics.radar import list_candidates

            cands = [c for c in list_candidates(self.client)
                     if c.get("status") in ("new", "promoted")][:8]
            if not cands:
                return ""
            lines = ["Radar candidates (surfaced by the horizon scan and evidence-gated, "
                     "but NOT tracked technologies — no stage claims; a 'promoted' one "
                     "is newly tracked and still earning its placement):"]
            for c in cands:
                ev = c.get("evidence") or {}
                receipts = (f"{ev.get('mentions', 0)} stories · "
                            f"{ev.get('sources', 0)} publishers")
                if ev.get("papers"):
                    receipts += f" · {ev['papers']} arXiv papers"
                lines.append(f"- {c.get('label')} [{c.get('status')}]: {receipts} "
                             f"since {ev.get('first_seen', '?')}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning("Ask: radar state unavailable (%s).", e)
            return ""

    def _financial_context(self) -> dict:
        """Real company financials + price series, so the agent can answer money
        questions ("is X investing in R&D?", "did the market react?") with numbers
        instead of guessing. Best-effort — empty if the enrichment never ran."""
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
            logger.warning("Ask: financial context unavailable (%s).", e)
            return {"financials": [], "prices": {}}

    @staticmethod
    def _build_pack(question: str, history: list[dict], stories: list[dict],
                    passages: list[dict], fin_ctx: dict | None = None,
                    tracked: str = "") -> str:
        lines = [f"QUESTION: {question}", ""]
        prior = [h for h in history if h.get("content")][-6:-1]  # exclude the current question
        if prior:
            lines.append("=== CONVERSATION SO FAR ===")
            for h in prior:
                lines.append(f"{h.get('role', 'user').upper()}: {_truncate(h.get('content'), 300)}")
            lines.append("")
        if tracked:
            # First and labelled authoritative: the product's own lifecycle read
            # outranks anything retrieved or remembered for stage questions.
            lines += ["=== LODESTAR TRACKED LIFECYCLE STATE (authoritative — attribute "
                      "in prose as \"Lodestar's tracked data\", never as [S#]/[T#]) ===",
                      tracked, ""]
        lines.append("=== DEVELOPMENTS (cite as [S#]) ===")
        if stories:
            for i, s in enumerate(stories, 1):
                lines.append(
                    f"[S{i}] ({s.get('_feed_label') or '?'}) {s.get('title')} "
                    f"— date={s.get('published_at') or '?'}, impact={s.get('business_impact')}, "
                    f"companies={s.get('companies') or []}"
                )
                if s.get("summary"):
                    lines.append(f"     {_truncate(s.get('summary'), 360)}")
        else:
            lines.append("(no closely-matching developments found in the window)")
        lines += ["", "=== MOT THEORY (cite as [T#]) ==="]
        if passages:
            for i, p in enumerate(passages, 1):
                lines.append(f"[T{i}] {p.get('source_file') or '?'}:")
                lines.append(f"     {_truncate(p.get('chunk_text'), 600)}")
        else:
            lines.append("(none retrieved — no [T#] sources exist, so do NOT cite theory; "
                         "answer without theory citations and state that no theory passages "
                         "could be retrieved, or say the evidence is insufficient)")

        fin = fin_ctx or {}
        if fin.get("financials") or fin.get("prices"):
            from analytics.financials import financial_context
            from tickers import ticker_for
            block = financial_context(
                stories, fin.get("financials") or [], fin.get("prices") or {}, ticker_for
            )
            if block:
                lines += ["", block]

        citable = (["developments as [S#]"] if stories else []) \
            + (["theory as [T#]"] if passages else [])
        cite_instr = (f"Cite {' and '.join(citable)}; " if citable else
                      "Do not use [S#]/[T#] citations — none are available (say so); ")
        lines += ["", "=== TASK ===",
                  "Answer the QUESTION as an analyst writing for investors — lead with the "
                  "read. Ground your claims in the material above and " + cite_instr +
                  "if COMPANY FINANCIALS are given and relevant, cite the R&D intensity or "
                  "price reaction. You may supplement with web research for background or "
                  "theory context only — attribute it in prose (name the source), never "
                  "with an [S#]/[T#] tag, and never base a claim about recent developments "
                  "on it. "
                  "Concise markdown; give catalysts/risks and flag low-confidence or missing evidence."]
        if tracked:
            lines.append(
                "Lifecycle/stage claims MUST come from the LODESTAR TRACKED LIFECYCLE "
                "STATE block above — it is this product's own authoritative read. Do not "
                "substitute external stage frameworks or reports (e.g. Gartner hype "
                "cycles) for it; theory [T#] may explain WHY a stage matters, never "
                "WHERE a technology currently sits.")
        if _recency_question(question):
            lines.append(
                "The question concerns recent events: ground every recent-event claim "
                "in an [S#] development" + (" or the tracked state" if tracked else "") +
                ". If the pack does not cover it, say plainly that Lodestar's feeds "
                "don't cover it — do not fill the gap from web research or general "
                "knowledge.")
        return "\n".join(lines)
