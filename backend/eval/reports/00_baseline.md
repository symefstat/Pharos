# Phase 0 — Baseline (offline)

Date: 2026-07-02 · Branch: `main` · All results below are offline (no Supabase/Toqan calls made).

## 1. Unit suite (regression floor)

```
./venv/bin/python -m pytest -q
341 passed, 1 warning in 0.92s
```

- **341/341 pass.** 31 test modules confirmed (matches the plan's inventory).
- One benign `DeprecationWarning` from `supabase`'s `gotrue` dependency — not ours, no action.

## 2. Offline harness (fixture run)

```
./venv/bin/python backend/eval_run.py --gold backend/eval/gold_labels.example.jsonl \
    --from-fixture backend/eval/predictions.fixture.jsonl
```

Scorecard renders correctly: per-field accuracy + confusion detail, extraction
completeness, and provenance breakdown all present. Fixture numbers (maturity
66.7%, adoption 100%, business_impact 100%, scope 75% on n=4) are a smoke test of
the harness, not a quality signal — the example gold set is 4 rows.

## 3. Repo inventory — plan paths vs reality

All plan paths hold. Notes:

| Plan reference | Status |
|---|---|
| `backend/Agents_prompt/*.md` (13 agents) | ✅ 13 files: 10 feed extractors (Chips = `Semiconductor_News_Feed_Agent.md`) + MOT Lens + Strategist + Ask (`Ask_Bellwether_Agent.md`) |
| `home_news/` extractor→parser→writer | ✅ all three present |
| `analytics/lens.py, rollup.py, tech_layer.py, mot_analyst.py, financials.py, forecasts.py, strategist.py, ask.py` | ✅ all present |
| `finance/` | ✅ at repo **root** (`finance/client.py`), not under `analytics/` — plan wording ambiguous, no drift |
| `backend/app/*.py` | ✅ 9 modules (main, data, briefing, capital, explore, feeds_api, forecasts, mot, actions) |
| `frontend/src/pages/*.tsx` | ✅ 7 pages (Ask, Briefing, Capital, Explore, Feeds, Forecasts, Mot) |
| `eval_run.py, lens_ab.py, gold_seed.py, freshness_check.py` | ✅ all at root |
| `docs/MOT_Framework_Library.md`, `STRATEGIC_COUNCIL_PROMPT.md` | ✅ present |
| `Skills/` | ✅ council, find-skills, skill-creator, superpowers, xlsx |
| `backend/eval/rubrics/` | ✅ prompt_quality.md, mot_scholar.md, falsifier.md already written |
| `backend/eval/judges/`, `backend/eval/gold_labels.jsonl` | ⬜ not yet created (Phase 1 work, as planned) |
| RAG (`vectordb`/pgvector) | referenced from `analytics/ask.py` and `analytics/strategist.py` |

Uncommitted working-tree changes noted at session start (`backend/app/mot.py`,
`frontend/src/pages/Mot.tsx`, `frontend/src/components/ChordDiagram.tsx`,
frontend package files) — the eval runs against the tree as-is.

### ⭐ L3 head start: the seed file already exists

`backend/eval/gold_labels.seed.jsonl` contains **200 real seeded rows** (real URLs, titles,
summaries, lens guesses), stratified across all 10 feeds (7–25 rows each) and all
maturity stages (research 11 · emerging 41 · growth 41 · dominant-design 33 ·
mature 29 · n/a 45). It **validates clean**:

```
./venv/bin/python backend/eval_run.py --validate-gold --gold backend/eval/gold_labels.seed.jsonl
→ 200 labels, no problems.
```

**Consequence:** the live `gold_seed.py` Supabase read is already done — no live
call needed to start L3. The critical path is now the **human review** of those
200 rows (correcting the lens's pre-filled guesses, per the file's own warning
against rubber-stamping) → save as `backend/eval/gold_labels.jsonl`. No `verified` flags
are set yet — 0/200 reviewed.

## 4. Freshness/health snapshot

**Deferred** — `freshness_check.py` needs a live Supabase read. Per ground rules,
will be proposed alongside the other live steps for explicit approval.

## 5. Acceptance targets (pre-committed)

| Layer | Metric | Target |
|---|---|---|
| **L1 Prompts** | Schema/consumer drift (GATE) | **0 mismatches** across all 13 prompts |
| | Rubric score per prompt | **≥ 80% of max (Green)**, no prompt Red |
| **L2 Extraction** | Faithfulness (judged sample, live) | **≥ 90%** of sampled items fully grounded, **0 fabricated** entities/numbers |
| | Provenance coverage | **≥ 95%** of fields carry provenance |
| | Dedup | **0** cross-feed duplicate URLs in sample |
| **L3 MOT Lens** ⭐ | Gold set | **≥ 150 human-verified** labels, `--validate-gold` clean |
| | maturity_stage | exact **≥ 70%**, within-1-stage **≥ 90%** |
| | adoption_stage | exact **≥ 65%**, within-1-stage **≥ 90%** |
| | business_impact | exact **≥ 80%** |
| | scope | exact **≥ 80%** |
| | Error profile | **≥ 80%** of stage errors adjacent (no wild misses) |
| **L4 Rollup** | Recompute vs stored drift | **0** (exact within harness tolerance) |
| **L5 Tech layer** | Placement/transition fixtures | **100% pass** |
| | Cross-surface stage disagreement (MOT Analyst vs Capital vs Briefing) | **0** |
| **L6 Financials** | Fundamentals vs source (5 tickers, live) | within **±5%** |
| | FX normalization + event-study baseline (last close strictly pre-event) | **100% correct** |
| **L7 Forecasts** | Look-ahead violations | **0** |
| | Brier/calibration hand-check (≥5 records) | **exact match** |
| | Price-direction quarantine | **100%** quarantined |
| **L8 Strategist** | Numeric-claim grounding | **≥ 95%** traceable to cited sources, **0 hallucinated numbers** |
| | Theory fidelity (mot_scholar rubric) | mean **≥ 2.0/3**, **0** outright misapplications |
| | Falsifier quality (falsifier rubric) | mean **≥ 9/12**; **0** signals missing a falsifier or scoring 0 on "refuting" |
| | Overclaim rate | **≤ 10%** of signals |
| **L9 Ask** | Retrieval precision@5 | **≥ 0.80** |
| | Phantom citations | **0** |
| | Ungrounded claims | **0** |
| | Refusal on unanswerable questions | **≥ 90%** correct |
| **L10 App** | API fields unrendered by UI | **0** meaningful fields dropped |
| | Filters/toggles that demonstrably change the view | **100%** (no silent no-ops) |
| | Cross-tab stage/entity contradictions | **0** |

## 6. Phase 0 verdict

Offline floor is **green**: full unit suite passes, harness renders end-to-end,
gold seeding is further along than the plan assumed. Ready for Phase 1
(one sub-agent per layer, offline signals only; live steps to be proposed
separately for approval).

---

## 7. Freshness snapshot (added 2026-07-02, live step A1 — EXECUTED)

`./venv/bin/python backend/freshness_check.py` → **All 10 feeds fresh.** No stale feeds.
