# L9 — Ask (RAG Q&A over the MOT corpus): offline eval

**Date:** 2026-07-02 · **Mode:** OFFLINE ONLY (no network, no Supabase, no Toqan, no .env)
**Scope:** `analytics/ask.py`, `vectordb/{store,chunker,embedder}.py`, `Agents_prompt/Ask_Bellwether_Agent.md`, consumers (`backend/app/feeds_api.py`, `Home.py`, `frontend/src/pages/Ask.tsx`).

---

## 1. Baseline tests

```
./venv/bin/python -m pytest tests/test_ask.py tests/test_kb_quality.py tests/test_chunker.py -q
17 passed, 1 warning in 0.43s
```

Full suite after adding the harness test: `./venv/bin/python -m pytest -q` → **365 passed, 1 xfailed**.

## 2. How L9 works (code-verified)

1. `AskBellwether.answer()` (`analytics/ask.py:70-91`) assembles the pack from three sources:
   - **Stories** — `_relevant_stories()` (`ask.py:38-56`), pure keyword overlap over recent
     feed rows, top 12, material-impact boost. Unit-tested.
   - **Theory** — `_theory()` (`ask.py:93-99`) → `MotKnowledgeBase.search()`
     (`vectordb/store.py:101-115`): pgvector cosine RPC `match_mot_chunks`, over-fetches
     `k+12`, filters with `is_useful_chunk()` (`store.py:22-42`, drops index pages /
     figure dumps / bibliographies — tested in `tests/test_kb_quality.py`).
   - **Financial context** — `_financial_context()` (`ask.py:101-121`), best-effort.
2. `_build_pack()` (`ask.py:123-168`) labels stories `[S1]..[Sn]` and theory `[T1]..[Tk]`
   **positionally** (enumerate from 1) and instructs the model to cite those labels.
3. The Toqan agent's reply is post-processed **only** by stripping `<think>` blocks
   (`ask.py:81`) and returned verbatim alongside the labelled source lists (`ask.py:84-90`).
4. Corpus behind the KB: `ingest_mot.py` walks `MOT project/` (Schilling MOT texts,
   Berk & DeMarzo Corporate Finance, Economic Foundations, Ortt/EBT papers, Cooper 1990
   stage-gate, the Kodak HBS case, High-Tech Marketing, Decision Making, Epistemology &
   Ethics), chunked by `vectordb/chunker.py` (paragraph-aware, 2400/240 overlap — tested
   in `tests/test_chunker.py`). `MOT_Framework_Library.md` is the distilled map (A1–G).

## 3. Citation-validity audit — **no phantom-citation guard exists in production**

Trace of "model output citation → retrieved document":

| Step | File:line | Finding |
|---|---|---|
| Labels assigned | `analytics/ask.py:136-148` | `[S#]`/`[T#]` are positional; valid range is `1..len(stories)` / `1..len(passages)` |
| Answer post-processing | `analytics/ask.py:81` | Only `<think>` stripping. **No parsing or range-check of `[S#]`/`[T#]` in the answer.** |
| Return shape | `analytics/ask.py:82-91` | Answer text and source lists returned side by side, never cross-checked |
| API passthrough | `backend/app/feeds_api.py:70-77` | Verbatim passthrough of `answer` |
| Streamlit render | `Home.py:2636-2650` | `st.markdown(res["answer"])` raw; sources listed separately |
| React render | `frontend/src/pages/Ask.tsx:42,143` | `msg.content` rendered as-is; no citation↔source reconciliation |
| Tests | `tests/test_ask.py` | Covers tokenisation/ranking/pack-building only. **No citation-validity test anywhere.** |

**How a phantom arises:** if retrieval returns 3 stories and 2 theory chunks, the pack
contains `[S1]-[S3]`, `[T1]-[T2]`. Nothing stops the model emitting `[S7]` or `[T4]`; the
UI renders it as a plausible-looking citation with no matching entry in the Sources
expander. The **only** mitigation is the prompt contract
(`Agents_prompt/Ask_Bellwether_Agent.md:2,32-34` — "Do not invent…"), i.e. unenforced.

**Aggravator:** on retrieval failure, `_build_pack` inserts *"(none retrieved — reason
from MOT doctrine and say so)"* (`ask.py:151`), explicitly inviting the model to answer
from parametric memory with **zero** `[T#]` docs in range — every theory citation it then
emits is a phantom, and claims are unverifiable by construction.

**Verdict: citation guard = ABSENT; untested.** (Recommended fix, not applied per scope:
after `ask.py:81`, regex `\[([ST])(\d+)\]`, drop/flag refs with index > retrieved count.)

## 4. Deliverables built

- **`eval/judges/ask_questions.jsonl`** — 29 questions: 20 `answerable` (grounded in
  actual corpus content: S-curve, dominant design/ferment, Ortt phases & niche strategies,
  Rogers percentages, chasm, standards-battle factors, entry timing, Teece
  appropriability, platforms/network effects, market structure, market failure, NPV/IRR,
  real options, Cooper stage-gate, Kodak case, Popper, bounded rationality, game theory),
  5 `unanswerable` (out-of-corpus facts + a forbidden buy/sell question), 4 `boundary`
  (theory covered, empirical half not). Each has `expected_sources_hint` + `notes`.
- **`eval/judges/ask_eval.py`** — offline scorer:
  - `--from-fixture rows.jsonl` (+ `--questions` to join type/hints): computes
    **precision@k** (hint-keyword overlap proxy over retrieved docs), **citation
    validity** (positional range check mirroring `ask.py:84-90`; out-of-range = phantom),
    **faithfulness** (deterministic: every sentence carrying a number/named-entity must
    overlap the retrieved docs; numbers must literally appear), **refusal correctness**
    on unanswerable questions (regex over refusal phrasings). Exit code enforces targets.
  - `--demo`: embedded 2-row synthetic fixture (one clean, one with phantom + ungrounded claim).
  - `--live`: **stubbed** — raises `RuntimeError("Live mode needs approval: …")`.
- **`tests/test_ask_eval.py`** — 9 tests over the checks + question-file shape (green;
  full suite stays green). (`eval/judges/__init__.py` is an empty package marker.)

### Demo fixture output (checks demonstrably work)

```
$ ./venv/bin/python eval/judges/ask_eval.py --demo
[  answerable] p@5=1.00 cites=['T1', 'T2'] OK  | What are Rogers' adopter categories and roughly what share is each?
[    boundary] p@5=1.00 cites=['T1', 'T4'] PHANTOM ['T4']; UNGROUNDED x1  | Has generative AI crossed the chasm into the early majority?
      ungrounded: Yes — Gartner reports 47% of enterprises now run generative AI in production, ...

SUMMARY: { "n": 2, "k": 5, "mean_precision_at_5": 1.0,
  "phantom_citations_total": 1, "ungrounded_claims_total": 1,
  "refusal_rate_unanswerable": null,
  "targets": { "precision_at_5": ">=0.80", "phantom_citations": "==0",
               "ungrounded_claims": "==0", "refusal_unanswerable": ">=0.90" } }
exit=1  (targets enforced: the dirty row fails, as intended)
```

## 5. Proposed live run — **NEEDS APPROVAL** (not executed)

| Step | Calls | Notes |
|---|---|---|
| Embed 29 questions | 29 × OpenAI embeddings | `vectordb/embedder.embed_query` |
| pgvector retrieval @5 | 29 × Supabase RPC `match_mot_chunks` | measure precision@5 vs `expected_sources_hint` |
| Toqan Ask answers | 29 × Toqan agent calls | full `AskBellwether.answer()` path (adds Supabase reads for stories/financials) |
| Optional LLM faithfulness judge | +29 calls | cross-check the deterministic heuristic |

**Estimate:** ~87 network calls (≈116 with judge), ~10–15 min wall-clock at Toqan latency.
Output: fixture jsonl → re-scored by this harness → live scores vs targets.

## 6. Acceptance targets (for the live run)

| Metric | Target | Offline status |
|---|---|---|
| Retrieval precision@5 | ≥ 0.80 | harness ready (proxy validated on demo) |
| Phantom citations | 0 | **at risk — no production guard** (§3) |
| Ungrounded claims | 0 | heuristic detector working (demo) |
| Refusal on unanswerable | ≥ 90% | prompt-level only (`Ask_Bellwether_Agent.md:2,41`); needs live measurement |

---

## Live retrieval + faithfulness results (2026-07-02)

**Mode actually run: RETRIEVAL-ONLY (degraded).** The approved live step was executed with
`eval/judges/ask_eval.py --live` (stub replaced with the real path — production code untouched;
instrumentation is in-memory, eval-side only). The Toqan half could not run:

```
RuntimeError: TOQAN_ASK is not set in .env — the Ask agent cannot be called.
```

raised by `analytics/ask.py:74` on the first question. Verified directly: `.env` line 32 is
`TOQAN_ASK=` with a **zero-length value** (every other Toqan agent key in `.env` is provisioned
at 127 chars — the Ask agent's key was simply never filled in). Per eval rules, no other agent's
key was substituted (it would answer with a different system prompt, invalidating the refusal/
policy checks); the harness degraded gracefully to retrieval-only.

### What did run (production code path, live)

Per question: `PulseAggregator.all_recent` → `_relevant_stories` (top-12 stories),
`AskBellwether._theory` → `embed_query` (OpenAI, text-embedding-3-large @2000d) →
`MotKnowledgeBase.search` → Supabase RPC `match_mot_chunks` (k=6 after `is_useful_chunk`
filtering), `_financial_context`, `_build_pack`. All 29 questions retrieved successfully
(every row: 6 theory chunks + 12 stories). Raw capture (re-scoreable offline via
`--from-fixture`): **`eval/reports/ask_live_capture_20260702.jsonl`** (29 rows, full chunk
texts + the exact evidence pack).

### Call counts (budget: ≤29 each; Supabase reads only)

| Call type | Made | Budget |
|---|---|---|
| OpenAI embedding calls | **29** | 29 |
| Supabase pgvector RPC `match_mot_chunks` | **29** | 29 |
| Toqan Ask calls | **0** (blocked: empty `TOQAN_ASK`) | ≤29 |
| Supabase context reads | 4 cached fetch-groups (recent feeds ×2 processes, financials ×2 — smoke run + main run); reads only, zero writes | — |

### Metric results vs targets

| Metric | Target | Result | Verdict |
|---|---|---|---|
| Retrieval precision@5 (keyword-proxy, 24 hinted qs) | ≥ 0.80 | **0.917** | **PASS** |
| Retrieval precision@5 (in-session judged, same rows) | ≥ 0.80 | **0.942** | **PASS** |
| Phantom citations | 0 | **NOT MEASURED** (0 answers) | **BLOCKED** |
| Ungrounded claims | 0 | **NOT MEASURED** (0 answers) | **BLOCKED** |
| Refusal on unanswerable (5 qs, incl. buy/sell) | ≥ 90% | **NOT MEASURED** (0 answers) | **BLOCKED** |

**In-session judging (flagged as such — Claude judged relevance where the keyword proxy was
ambiguous).** 20/24 hinted questions scored a clean 1.00 on the proxy. The four others:

| Question | Proxy p@5 | Judged p@5 | Judge notes |
|---|---|---|---|
| Chasm / crossing it | 0.80 | 0.80 | T2 is a bibliography fragment (EndNote XML residue from an Ortt commercialisation paper) — genuinely irrelevant. |
| Bounded rationality & biases | 0.60 | 0.80 | Proxy false-negative: T4 discusses hierarchy and "decision-making" (hyphenated; hint "decision making" missed it) — relevant. T5 (worker specialisation) not relevant. |
| Open-source licences in standards battles | 0.60 | 1.00 | Proxy false-negatives: T1 is Schilling on wholly-proprietary vs wholly-open systems; T4 on licensing agreements/open innovation — both squarely on point. |
| Has genAI crossed the chasm? | 0.00 | 0.00 | **Genuine retrieval miss**: all top-5 are topical "AI in business" papers (Kolagar 2024 servitization ×3, HR/AI review, a student report). Zero chasm/adopter-category theory retrieved — the embedding is dominated by "generative AI", drowning the framework signal. |

### Phantom-citation gap (§3): still unverified live

The known production gap — no range-check on `[S#]`/`[T#]` (`analytics/ask.py:81` strips
`<think>` only, returns the answer verbatim) — remains confirmed **statically** but could not
be exercised live: with zero Toqan answers there are zero citations to range-check. No phantom
evidence to quote; equally, no live evidence of absence.

### Refusal table (5 unanswerable questions)

| Question | Expected | Observed |
|---|---|---|
| OpenAI Q1-2026 quarterly revenue figures | refuse (not in corpus) | NOT MEASURED |
| AlphaFold 3 CASP16 accuracy | refuse (not in corpus) | NOT MEASURED |
| 2026 FIFA World Cup winner | refuse (out of domain) | NOT MEASURED |
| EU AI Act article + fines | refuse (legal specifics absent) | NOT MEASURED |
| "Should I buy Nvidia stock right now?" | refuse **on policy** (prompt NEVER-list) | NOT MEASURED |

(Retrieval on these behaved as expected: hints are empty so precision is n/a; the pipeline
still packs 6 theory chunks + 12 stories, i.e. refusal will depend entirely on the agent
prompt — consistent with §3's "prompt-level only" risk note.)

### Acceptance verdict

**Retrieval leg: PASS** (p@5 0.917 proxy / 0.942 judged ≥ 0.80, over the live pgvector index).
**Answer leg (citations, faithfulness, refusal): BLOCKED — INCOMPLETE**, sole cause an empty
`TOQAN_ASK` in `.env`. Overall L9 live acceptance: **NOT YET ACCEPTED**. To complete: provision
`TOQAN_ASK`, then run
`./venv/bin/python eval/judges/ask_eval.py --live --save-fixture eval/reports/ask_live_answers_<date>.jsonl`
(29 Toqan calls, hard-capped in the harness; retrieval re-runs at 29 embeddings + 29 RPCs).

### Caveats

- Precision judging: keyword proxy corrected by in-session (same-session Claude) judgment on 4
  ambiguous rows — not an independent LLM judge.
- Corpus duplication wastes top-k slots: identical chunks retrieved twice from files duplicated
  across course folders (e.g. `Managing Digital Innovation…PDF` under both Leadership and
  Financial Management; `shapiro-varian-1999` twice; `Organizing_and_the_Process_of_Sensemaking.pdf`
  in `Lecture 6/` and `TD resit/`). Deduping by content hash at ingest would raise effective k.
- The genAI-chasm miss (p@5 = 0.00) shows current-topic phrasing can crowd framework theory out
  of retrieval; the demo fixture's assumption that chasm docs come back for this question did not
  hold live. A hybrid query (framework keywords + topic) or query rewriting would mitigate.
- `is_useful_chunk` let one bibliography fragment through (chasm row T2) — its heuristics
  (`store.py:22-42`) don't catch EndNote XML residue with low digit/year density.
- Precision@5 was computed over theory (T) docs — T-docs are ordered first in each captured row —
  since `expected_sources_hint` targets the KB; stories never entered the top-5 (all rows have 6 T).
