#!/usr/bin/env python3
"""
Offline eval harness for L9 (Ask — RAG Q&A over the MOT corpus).

Modes
-----
--from-fixture FIXTURE.jsonl   Score canned rows (no network). Each row:
    {"question": str,
     "type": "answerable|unanswerable|boundary",     # optional; else joined from --questions
     "retrieved_docs": [{"label": "S1"|"T1", "source_file"/"title": str, "text": str}, ...],
     "answer": str,
     "citations": ["S1", "T2", ...]}                 # optional; else parsed from answer

--demo                         Run the embedded 2-row synthetic fixture (one clean row,
                               one row with a phantom citation + ungrounded claim).

--live                         APPROVED 2026-07-02 — runs the repo's real Ask pipeline per
                               question (OpenAI embedding + Supabase pgvector RPC + Toqan Ask
                               agent via analytics/ask.py). Supabase is READ-ONLY on this path.
                               Hard cap: 29 Toqan calls. Use --save-fixture to persist raw rows
                               (re-scoreable offline with --from-fixture), --limit/--offset to
                               smoke-test / resume without exceeding the call budget.

Checks (all deterministic, no LLM):
  * retrieval precision@k  — a retrieved doc is "relevant" if it contains any keyword from
                             the question's expected_sources_hint (keyword-overlap proxy).
  * citation validity      — every [S#]/[T#] in the answer must index into the retrieved
                             set (S# <= number of S-docs, T# <= number of T-docs).
                             Out-of-range refs are PHANTOM citations. This guard does NOT
                             exist in production (analytics/ask.py returns the answer verbatim).
  * faithfulness           — heuristic: every sentence carrying a number or a named entity
                             must overlap the retrieved docs (numbers must appear in some
                             doc; entities/content-words must overlap). Violations are
                             "ungrounded claims".
  * refusal correctness    — on type=unanswerable, the answer must be a refusal
                             ("evidence insufficient" / "not in the pack" / declines advice).

Usage:
    ./venv/bin/python eval/judges/ask_eval.py --demo
    ./venv/bin/python eval/judges/ask_eval.py --questions eval/judges/ask_questions.jsonl \
        --from-fixture path/to/fixture.jsonl [--k 5] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CIT_RE = re.compile(r"\[([ST])(\d+)\]")
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?%?")
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
TOKEN_RE = re.compile(r"[a-z0-9]+")
# Capitalised word NOT at sentence start = crude named-entity proxy.
ENTITY_RE = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z]{2,})\b")
REFUSAL_RE = re.compile(
    r"(not enough|insufficient|does not (contain|cover|include)|"
    r"no (relevant )?(information|evidence|passages?|data)|"
    r"cannot (answer|conclude|say)|can't (answer|say)|unable to answer|"
    r"not (covered|present|available) in (the|this) (pack|corpus|material)|"
    r"outside (the|this|my) (pack|corpus|scope|material)|"
    r"(don't|do not) (have|provide) .{0,40}(advice|information|data)|"
    r"(won't|will not|can't|cannot) (give|provide|offer) .{0,30}(buy|sell|investment) advice)",
    re.IGNORECASE,
)

_STOP = {"the", "and", "for", "that", "this", "with", "from", "have", "has", "are",
         "was", "were", "will", "would", "should", "could", "does", "into", "than",
         "then", "them", "they", "their", "there", "what", "which", "when", "where",
         "about", "over", "under", "also", "such", "more", "most", "some", "only",
         "very", "each", "both", "between", "because", "while", "after", "before"}


def _tokens(text: str) -> set[str]:
    return {t for t in TOKEN_RE.findall((text or "").lower()) if len(t) >= 3 and t not in _STOP}


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


# ── Checks ────────────────────────────────────────────────────────────────────

def parse_citations(answer: str) -> list[str]:
    """All [S#]/[T#] refs in the answer text, in order (deduped)."""
    seen, out = set(), []
    for kind, num in CIT_RE.findall(answer or ""):
        ref = f"{kind}{int(num)}"
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def citation_validity(citations: list[str], retrieved_docs: list[dict]) -> dict:
    """A citation is valid iff its index maps into the retrieved set of that kind.

    Mirrors the production labelling in analytics/ask.py:84-90 (S1..Sn, T1..Tk,
    positional). Anything out of range is a PHANTOM — production has no such guard.
    """
    labels = {str(d.get("label", "")).upper() for d in retrieved_docs}
    n_s = sum(1 for lb in labels if lb.startswith("S"))
    n_t = sum(1 for lb in labels if lb.startswith("T"))
    phantoms = []
    for ref in citations:
        kind, idx = ref[0], int(ref[1:])
        limit = n_s if kind == "S" else n_t
        if idx < 1 or idx > limit:
            phantoms.append(ref)
    return {"citations": citations, "phantom_citations": phantoms,
            "n_retrieved_s": n_s, "n_retrieved_t": n_t}


def retrieval_precision_at_k(retrieved_docs: list[dict], hints: list[str], k: int) -> float | None:
    """Keyword-overlap proxy: doc is relevant if any hint keyword appears in its
    text/title/source_file. Returns None when there are no hints (unanswerable)."""
    if not hints:
        return None
    top = retrieved_docs[:k]
    if not top:
        return 0.0
    hints_lc = [h.lower() for h in hints]
    rel = 0
    for d in top:
        hay = " ".join(str(d.get(f) or "") for f in ("text", "chunk_text", "title", "source_file")).lower()
        if any(h in hay for h in hints_lc):
            rel += 1
    return rel / len(top)


def faithfulness(answer: str, retrieved_docs: list[dict]) -> dict:
    """Heuristic groundedness: each sentence with a number or named entity must
    overlap the retrieved docs. Numbers must literally appear in some doc; a
    sentence's entities/content words must share tokens with the doc pool."""
    doc_text = " ".join(
        str(d.get(f) or "") for d in retrieved_docs for f in ("text", "chunk_text", "title", "source_file")
    )
    doc_tokens = _tokens(doc_text)
    doc_numbers = set(NUM_RE.findall(doc_text))
    ungrounded = []
    for sent in SENT_SPLIT_RE.split(answer or ""):
        sent = sent.strip()
        if not sent or REFUSAL_RE.search(sent):
            continue  # refusals aren't claims
        clean = CIT_RE.sub("", sent)  # citation indices are not evidence
        nums = NUM_RE.findall(clean)
        ents = ENTITY_RE.findall(clean)
        if not nums and not ents:
            continue  # no checkable claim in this sentence
        num_ok = all(n in doc_numbers for n in nums) if nums else True
        ent_ok = bool(_tokens(" ".join(ents)) & doc_tokens) if ents else True
        # generic hedging entities shouldn't fail a sentence on their own
        if ents and not ent_ok and not nums:
            content_overlap = len(_tokens(clean) & doc_tokens)
            ent_ok = content_overlap >= 4
        if not (num_ok and ent_ok):
            ungrounded.append(sent[:160])
    return {"ungrounded_claims": ungrounded}


def refusal_check(answer: str, qtype: str) -> dict:
    refused = bool(REFUSAL_RE.search(answer or ""))
    correct = None
    if qtype == "unanswerable":
        correct = refused
    elif qtype == "answerable":
        correct = not refused  # refusing an answerable question is also a miss
    return {"refused": refused, "refusal_correct": correct}


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_row(row: dict, k: int) -> dict:
    answer = row.get("answer", "")
    docs = row.get("retrieved_docs", [])
    qtype = row.get("type", "answerable")
    hints = row.get("expected_sources_hint", [])
    citations = row.get("citations") or parse_citations(answer)
    out = {"question": row.get("question", "")[:100], "type": qtype}
    out.update(citation_validity(citations, docs))
    out["precision_at_k"] = retrieval_precision_at_k(docs, hints, k)
    out.update(faithfulness(answer, docs))
    out.update(refusal_check(answer, qtype))
    return out


def summarize(rows: list[dict], k: int) -> dict:
    precs = [r["precision_at_k"] for r in rows if r["precision_at_k"] is not None]
    unans = [r for r in rows if r["type"] == "unanswerable"]
    refused_ok = [r for r in unans if r["refusal_correct"]]
    return {
        "n": len(rows),
        "k": k,
        f"mean_precision_at_{k}": round(sum(precs) / len(precs), 3) if precs else None,
        "phantom_citations_total": sum(len(r["phantom_citations"]) for r in rows),
        "ungrounded_claims_total": sum(len(r["ungrounded_claims"]) for r in rows),
        "refusal_rate_unanswerable": round(len(refused_ok) / len(unans), 3) if unans else None,
        "targets": {f"precision_at_{k}": ">=0.80", "phantom_citations": "==0",
                    "ungrounded_claims": "==0", "refusal_unanswerable": ">=0.90"},
    }


# ── Embedded synthetic fixture (demonstrates the checks) ─────────────────────

DEMO_FIXTURE = [
    {   # Clean row: valid citations, grounded numbers, good retrieval.
        "question": "What are Rogers' adopter categories and roughly what share is each?",
        "type": "answerable",
        "expected_sources_hint": ["Rogers", "innovators", "early adopters", "early majority", "laggards", "2.5"],
        "retrieved_docs": [
            {"label": "T1", "source_file": "Schilling_Ch13.pdf",
             "text": "Rogers split adopters into innovators (2.5%), early adopters (13.5%), "
                     "early majority (34%), late majority (34%) and laggards (16%). Early "
                     "adopters are opinion leaders who bring new ideas into the social system."},
            {"label": "T2", "source_file": "High_Tech_Marketing_notes.pdf",
             "text": "Moore's chasm sits between the early adopters and the early majority; "
                     "pragmatists demand a whole product and references from their peers."},
        ],
        "answer": "Rogers distinguishes five adopter categories: innovators (2.5%), early "
                  "adopters (13.5%), early majority (34%), late majority (34%) and laggards "
                  "(16%) [T1]. Early adopters act as opinion leaders [T1], and Moore locates "
                  "the chasm between them and the pragmatist early majority [T2].",
    },
    {   # Dirty row: phantom [T4] (only 2 T-docs retrieved) + ungrounded 47%/Gartner claim.
        "question": "Has generative AI crossed the chasm into the early majority?",
        "type": "boundary",
        "expected_sources_hint": ["chasm", "early majority", "pragmatists", "adoption"],
        "retrieved_docs": [
            {"label": "T1", "source_file": "High_Tech_Marketing_notes.pdf",
             "text": "Crossing the chasm requires a beachhead segment, a whole product, and "
                     "credible commitments; most technologies die between the visionaries and "
                     "the pragmatists."},
            {"label": "T2", "source_file": "Schilling_Ch13.pdf",
             "text": "The early majority adopt only once the technology is proven and the "
                     "switching risk is low; they wait for a dominant design."},
        ],
        "answer": "Yes — Gartner reports 47% of enterprises now run generative AI in "
                  "production, which puts adoption well past the early majority threshold. "
                  "The chasm framework says pragmatists need a whole product [T1], and "
                  "enterprise copilots now qualify [T4].",
    },
]


# ── Live mode (approved 2026-07-02) ──────────────────────────────────────────
#
# Runs the production pipeline itself (analytics/ask.py) — no reimplementation.
# Eval-side instrumentation only, applied in-memory:
#   * counts every embedding call, pgvector RPC, and Toqan call (hard cap 29 Toqan);
#   * caches the two read-only Supabase context fetches (recent feed rows,
#     financials) across questions so 29 questions don't re-read them 29 times —
#     the per-question path (embed -> match_mot_chunks RPC -> Toqan) is untouched;
#   * captures the raw theory passages, the matched stories, and the exact pack
#     sent to the agent, so citations/claims are checked against what the model
#     actually saw.

TOQAN_CALL_CAP = 29


def _extract_evidence(pack: str) -> str:
    """The evidence portion of the pack (developments + theory + financials),
    i.e. everything the model saw except the question/history and the task
    directive — used as the grounding pool for faithfulness."""
    start = pack.find("=== DEVELOPMENTS")
    end = pack.find("=== TASK ===")
    if start == -1:
        return pack
    return pack[start: end if end != -1 else len(pack)]


def run_live(questions_path: Path, k: int, as_json: bool,
             save_path: Path | None, limit: int | None, offset: int) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    import os

    import analytics.ask as ask_mod
    import vectordb.embedder as embedder_mod
    from analytics.ask import AskLodestar, _relevant_stories

    counters = {"embedding_calls": 0, "pgvector_rpc_calls": 0, "toqan_calls": 0,
                "supabase_context_fetches": 0}

    # Degrade gracefully if the Ask agent key is not provisioned: run the
    # production retrieval path (stories + embed + pgvector + pack build) and
    # score precision@k only; answer-dependent checks are reported NOT MEASURED.
    degraded = not os.getenv(ask_mod.ENV_KEY)
    if degraded:
        print(f"WARNING: {ask_mod.ENV_KEY} is not set in .env — the Ask agent cannot be called. "
              "Degrading to RETRIEVAL-ONLY (no Toqan calls; citation/faithfulness/refusal "
              "checks skipped).", flush=True)

    # Count embedding calls (analytics.ask._theory imports embed_query lazily
    # from vectordb.embedder, so patching the module attribute is sufficient).
    orig_embed = embedder_mod.embed_query
    def _counting_embed(text):
        counters["embedding_calls"] += 1
        return orig_embed(text)
    embedder_mod.embed_query = _counting_embed

    # Count Toqan calls + enforce the approved cap.
    _OrigAgent = ask_mod.ToqanAgent
    class _CountingAgent(_OrigAgent):
        def ask(self, message, poll_callback=None):
            if counters["toqan_calls"] >= TOQAN_CALL_CAP:
                raise RuntimeError(f"Toqan call cap ({TOQAN_CALL_CAP}) reached — refusing further calls.")
            counters["toqan_calls"] += 1
            return super().ask(message, poll_callback)
    ask_mod.ToqanAgent = _CountingAgent

    class _LiveAsk(AskLodestar):
        def __init__(self):
            super().__init__()
            self.recent_cache = None
            self._fin_cache = None
            self.last_passages: list[dict] = []
            self.last_pack = ""
            orig_recent = self.pulse.all_recent
            def _cached_recent(days=30):
                if self.recent_cache is None:
                    self.recent_cache = orig_recent(days=days)
                    counters["supabase_context_fetches"] += 1
                return self.recent_cache
            self.pulse.all_recent = _cached_recent
            orig_search = self.kb.search
            def _counting_search(vec, k=8):
                counters["pgvector_rpc_calls"] += 1
                return orig_search(vec, k=k)
            self.kb.search = _counting_search

        def _theory(self, question, k):
            self.last_passages = super()._theory(question, k)
            return self.last_passages

        def _financial_context(self):
            if self._fin_cache is None:
                self._fin_cache = super()._financial_context()
                counters["supabase_context_fetches"] += 1
            return self._fin_cache

        def _build_pack(self, question, history, stories, passages, fin_ctx=None):  # noqa: N805
            self.last_pack = AskLodestar._build_pack(question, history, stories, passages, fin_ctx)
            return self.last_pack

    questions = _read_jsonl(questions_path)
    if offset:
        questions = questions[offset:]
    if limit is not None:
        questions = questions[:limit]

    ask = _LiveAsk()
    rows: list[dict] = []
    for i, q in enumerate(questions, 1):
        qtext = q["q"]
        print(f"[{i}/{len(questions)}] {q.get('type', '?'):>12} | {qtext[:90]}", flush=True)
        row = {"question": qtext, "type": q.get("type", "answerable"),
               "expected_sources_hint": q.get("expected_sources_hint", [])}
        try:
            if degraded:
                # Same steps, same production methods, minus the agent call
                # (mirrors AskLodestar.answer(), analytics/ask.py:76-81).
                stories = _relevant_stories(ask.pulse.all_recent(days=30), qtext, top=12)
                passages = ask._theory(qtext, 6)
                ask._build_pack(qtext, [], stories, passages, ask._financial_context())
                res = {"answer": ""}
            else:
                res = ask.answer(qtext)
                stories = _relevant_stories(ask.recent_cache or [], qtext, top=12)
            # T-docs first so precision@k measures the pgvector (RAG) retrieval.
            docs = [{"label": f"T{j}", "source_file": p.get("source_file"),
                     "similarity": float(p.get("similarity") or 0),
                     "chunk_text": str(p.get("chunk_text") or "")}
                    for j, p in enumerate(ask.last_passages, 1)]
            docs += [{"label": f"S{j}", "title": s.get("title"),
                      "source_file": s.get("_feed_label"),
                      "text": " ".join(filter(None, [str(s.get("title") or ""),
                                                     str(s.get("summary") or "")]))}
                     for j, s in enumerate(stories, 1)]
            # Exact evidence the model saw (incl. the financials block), so
            # faithfulness doesn't false-flag numbers that were in the pack.
            docs.append({"label": "CTX", "text": _extract_evidence(ask.last_pack)})
            row["retrieved_docs"] = docs
            row["answer"] = res["answer"]
            row["n_theory"] = len(ask.last_passages)
            row["n_stories"] = len(stories)
        except Exception as e:  # keep going: one failed question shouldn't kill the run
            row["error"] = f"{type(e).__name__}: {e}"
            row["retrieved_docs"] = []
            row["answer"] = ""
            print(f"    ERROR: {row['error']}", flush=True)
        rows.append(row)
        if save_path:  # incremental append — partial runs stay rescuable
            with save_path.open("a") as fh:
                fh.write(json.dumps(row) + "\n")

    print("\nCALL COUNTS:", json.dumps(counters), flush=True)
    if degraded:
        precs = []
        for r in rows:
            p = retrieval_precision_at_k(r.get("retrieved_docs", []),
                                         r.get("expected_sources_hint", []), k)
            if p is not None:
                precs.append(p)
            print(f"[{r['type']:>12}] p@{k}={'-' if p is None else f'{p:.2f}'} "
                  f"T={r.get('n_theory', 0)} S={r.get('n_stories', 0)}"
                  f"{'  ERROR: ' + r['error'] if r.get('error') else ''}"
                  f"  | {r['question'][:90]}")
        summary = {
            "n": len(rows), "k": k, "mode": "RETRIEVAL-ONLY (TOQAN_ASK missing)",
            f"mean_precision_at_{k}": round(sum(precs) / len(precs), 3) if precs else None,
            "phantom_citations_total": "NOT MEASURED",
            "ungrounded_claims_total": "NOT MEASURED",
            "refusal_rate_unanswerable": "NOT MEASURED",
        }
        print("\nSUMMARY:", json.dumps(summary, indent=2))
        ok = bool(precs) and (sum(precs) / len(precs)) >= 0.80
        return 0 if ok else 1
    rc = run(rows, questions_path, k, as_json)
    print("CALL COUNTS:", json.dumps(counters), flush=True)
    return rc


# ── CLI ───────────────────────────────────────────────────────────────────────

def run(rows: list[dict], questions_path: Path | None, k: int, as_json: bool) -> int:
    qmeta = {}
    if questions_path:
        for q in _read_jsonl(questions_path):
            qmeta[q["q"]] = q
    scored = []
    for row in rows:
        meta = qmeta.get(row.get("question", ""), {})
        row.setdefault("type", meta.get("type", "answerable"))
        row.setdefault("expected_sources_hint", meta.get("expected_sources_hint", []))
        scored.append(score_row(row, k))
    summary = summarize(scored, k)
    if as_json:
        print(json.dumps({"summary": summary, "rows": scored}, indent=2))
    else:
        for r in scored:
            flags = []
            if r["phantom_citations"]:
                flags.append(f"PHANTOM {r['phantom_citations']}")
            if r["ungrounded_claims"]:
                flags.append(f"UNGROUNDED x{len(r['ungrounded_claims'])}")
            if r["refusal_correct"] is False:
                flags.append("REFUSAL-WRONG")
            p = r["precision_at_k"]
            print(f"[{r['type']:>12}] p@{k}={'-' if p is None else f'{p:.2f}'} "
                  f"cites={r['citations'] or '-'} {'OK' if not flags else '; '.join(flags)}"
                  f"  | {r['question']}")
            for u in r["ungrounded_claims"]:
                print(f"      ungrounded: {u}")
        print("\nSUMMARY:", json.dumps(summary, indent=2))
    ok = (summary["phantom_citations_total"] == 0
          and summary["ungrounded_claims_total"] == 0
          and (summary["refusal_rate_unanswerable"] is None
               or summary["refusal_rate_unanswerable"] >= 0.90)
          and (summary[f"mean_precision_at_{k}"] is None
               or summary[f"mean_precision_at_{k}"] >= 0.80))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offline eval for L9 Ask (RAG Q&A).")
    ap.add_argument("--questions", type=Path, default=None,
                    help="eval/judges/ask_questions.jsonl (joins type/hints onto fixture rows)")
    ap.add_argument("--from-fixture", type=Path, default=None,
                    help="Canned {question, retrieved_docs, answer, citations} rows (offline)")
    ap.add_argument("--demo", action="store_true",
                    help="Score the embedded 2-row synthetic fixture")
    ap.add_argument("--live", action="store_true",
                    help="Real pipeline: embeddings + pgvector + Toqan (approved 2026-07-02; "
                         f"hard cap {TOQAN_CALL_CAP} Toqan calls)")
    ap.add_argument("--save-fixture", type=Path, default=None,
                    help="(live) append raw rows here as JSONL for offline re-scoring")
    ap.add_argument("--limit", type=int, default=None, help="(live) run at most N questions")
    ap.add_argument("--offset", type=int, default=0, help="(live) skip the first N questions")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.live:
        qpath = args.questions or Path(__file__).with_name("ask_questions.jsonl")
        return run_live(qpath, args.k, args.json, args.save_fixture, args.limit, args.offset)
    if args.demo:
        return run([dict(r) for r in DEMO_FIXTURE], args.questions, args.k, args.json)
    if args.from_fixture:
        return run(_read_jsonl(args.from_fixture), args.questions, args.k, args.json)
    ap.error("choose one of --demo, --from-fixture, or --live")
    return 2


if __name__ == "__main__":
    sys.exit(main())
