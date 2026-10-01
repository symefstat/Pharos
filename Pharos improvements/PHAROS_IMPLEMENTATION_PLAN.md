# Pharos Implementation Plan

Companion to `PHAROS_CONTENT_IMPROVEMENTS.md`. Maps all 40 feedback items to concrete code changes, with current state, target files, effort, and blockers.

## How to read this

- **State** — `greenfield` (build from scratch) · `partial` (exists but in the wrong layer — usually a prompt or the offline eval, not a runtime gate) · `wiring` (mechanism exists, just needs surfacing/enforcing) · `relabel` (copy-only string change).
- **Effort** — S (hours) · M (1–2 days) · L (3+ days or new subsystem).
- **Blocked** — needs the S&P / PitchBook connector authorized in claude.ai → Settings → Connectors before it can fetch real data. Code + seam can be built first; data lights up on connect.

## Architecture facts that shape everything

1. **Two frontends.** Legacy Streamlit (`Home.py`, one 128 KB file) is being superseded by React (`frontend/src/`) + FastAPI (`backend/app/`). **React is canonical** — do surface work there and treat `Home.py` edits as optional/secondary.
2. **Storage is Supabase (Postgres), no ORM.** Schema is hand-applied `.sql` files in `SQL Tables/`. The article schema is **duplicated across 11 near-identical `*_articles.sql` files** — any new article column needs a bulk `ALTER` migration (follow the `feed_provenance_column.sql` template) plus threading through `home_news/parser.py` `HomeNewsItem`/`to_row()`.
3. **Content generation** = feed agents classify → `analytics/tech_layer.py` builds lifecycle placements → `analytics/strategist.py` builds a pack, calls the Strategist (Toqan) agent per `Agents_prompt/Strategist_Agent.md`, parses JSON, upserts to `strategist_briefs`. **There is no gate between generation and publication.**
4. **Prompts are the source of record but deployed in Toqan.** Editing `Agents_prompt/*.md` documents the intent; the live prompt must be re-pasted into Toqan to take effect (a known pending manual step).
5. Repo/storage keys still say **lodestar**; only the surface brand is **Pharos**. Don't rename internal keys.

---

## P0 — Publication blockers

### 1. Editorial approval gate — `greenfield` · M
No publication state exists; `Strategist.generate()` (`analytics/strategist.py:509-566`) upserts and the brief is instantly live.
- Add `status` (`draft`/`approved`) + `approved_by`/`approved_at` to `strategist_briefs` (`SQL Tables/strategist_briefs.sql`); default new rows to `draft`.
- Gate the read path: `Strategist.latest()`/`recent()` (`strategist.py:474-506`) and `backend/app/briefing.py:61` serve only `approved` (unless an admin preview flag is set).
- Add an admin approve endpoint following the pattern in `backend/app/actions.py` / `theses.py`.
- Only gate high-impact actions (from `_ACTIONS`, `strategist.py:68`: enter/scale/exit). Ties to #38.

### 2. Fact / interpretation / recommendation / evidence-gap / falsifier structure — `partial` · M
A signal already has `implication` (interpretation), `action`/`action_rationale`, and `falsifier`. **Missing: a separate `observed_facts` field and an `evidence_gaps` field** (facts and interpretation are currently fused in `implication`).
- Add `observed_facts` + `evidence_gaps` keys in `_normalize_structured()` (`strategist.py:119-136`).
- Add them to OUTPUT FORMAT + field rules in `Agents_prompt/Strategist_Agent.md:28-57`.
- Render in `brief_to_markdown()` (`strategist.py:300-325`), `brief_to_pdf()` (`:416-442`), and `frontend/src/pages/Briefing.tsx`.

### 3. Separate curated / news-derived / verified-transition stage — `wiring` · M
Most-developed area. All three values exist internally (`tech_layer.py`: news-derived `display_stage()`; curated anchor floor `apply_anchors()`; graded `detect_transitions()`) **but `display_stage()` returns the anchor-floored value, so anchor and news stages are conflated on the surface.** The "just crossed" bug: an anchor floor raises the stage, `snapshot()` persists it, and it flows into `detect_transitions()` as if it were live movement (the code even comments on this at `tech_layer.py:399-407`).
- Keep news-derived and anchor stages as **distinct fields** through `apply_anchors()`/`display_stage()` (`tech_layer.py:187-271`); surface all three separately in `frontend/src/pages/Tech.tsx` / `Mot.tsx`.
- Suppress transition language when a change was anchor-driven, in `detect_transitions()` (`:299-368`) and the pack builder (`strategist.py:726-757`).
- Temper "crossed the chasm"/"jumped" wording in `mot_analyst.py:297-320`.

### 4. Expose evidence behind every curated anchor — `partial` · M
Anchors are a hardcoded Python dict (`analytics/tech_anchors.py`, `ANCHORS`) carrying `as_of`, `confidence`, free-text `evidence`, `lifecycle_fit` — but **no source links, no author/reviewer, no next-review date**.
- Extend each anchor dict with `sources` (named + URLs), `reviewer`, `reasoning`, `next_review`.
- Surface in the Tech/MOT detail view. Consumer is `apply_anchors()` (`tech_layer.py:187-243`).
- Optional later: migrate anchors from Python dict → a DB table for editability.

### 5. Validate publication vs event dates — `partial` · M
Only `published_at` (DATE) and `fetched_at` (= `retrieved_at`) exist. **No `event_date`, no `effective_date`, and no future-date rejection** — a future `published_at` is stored (only past/stale items are dropped, `parser.py:222,242-246`).
- Bulk migration adding `event_date`, `effective_date` to all 11 article tables.
- Parse them in `_build_item` (`parser.py:286-292`); add a future-`published_at` reject right after line 292.
- Thread through `HomeNewsItem`/`to_row()`.

### 6. Deduplicate underlying events — `partial` · L
**Each article is its own stored row; there is no persisted event entity.** The only event concept is ephemeral read-time title-Jaccard clustering (`analytics/events.py::cluster_events`, not written back).
- Add an `events` table + `event_id` FK on article rows.
- Promote `cluster_events` into a write step (new stage in `home_news_run.py`); strengthen the signature (`events.py:25-28`) beyond title tokens (add companies/tags/date).
- Downstream: signals and deals key off `event_id`, not article rows. This is the backbone for #7 and #28.

### 7. Measure genuine source independence — `partial` · M
No "three sources" rule exists. Closest is `cluster_events` counting distinct `source_name` strings and `multi_source_count` (`events.py:85-91`). No publisher-independence/ownership graph, no primary-source concept — syndicated Reuters counts as one source only by name match.
- On the new event entity (#6), compute: article count, distinct-publisher count, primary-source present (bool), independent-confirmation count.
- Feed those to the proportionality gate (#8) and evidence-strength score (#14).

### 8. Enforce recommendation proportionality — `partial` · M
Verb set is fixed (`_ACTIONS = {enter, scale, defend, partner, wait, exit}`, `strategist.py:68`) with **no link between verb strength and evidence**; a single-source signal can be assigned "exit". The soft verbs (monitor/investigate/prepare/pilot) don't exist.
- Extend `_ACTIONS`/`PORTFOLIO_ACTIONS` (`strategist.py:68,253`) with soft verbs.
- Add a post-parse downgrade in `_normalize_structured()` (`:108-137`) keyed on independent-source count (#7) + confidence: 1 source → monitor; 2 independent → investigate/prepare; sources+quant → act; act+irreversible → route to human gate (#1).
- Mirror the ladder in `Strategist_Agent.md`.

### 9. Block unsupported causal language — `partial` · S
The overclaim lexicon **already exists but runs offline only** (`eval/judges/strategist_eval.py:301-321`, `OVERCLAIM_TERMS` + `_OVERCLAIM_RE`, target ≤10%). It never gates a live brief. ("locks in" is currently excluded — add it.)
- Promote the lexicon/regex into a runtime validator called inside `_parse_read()`/`_normalize_structured()` (`strategist.py:818-837`/`:108-170`): reject or auto-soften banned terms unless confidence=high AND ≥2 independent sources.

### 10. Make every forecast gradable — `partial` · M
No generation-time gradability gate. `resolve_by` always exists, but there's **no check for a present threshold, named data source, unambiguous scope, or that the falsifier resolves before the resolution date.** Falsifier-quality checking is eval-only (`strategist_eval.py::check_falsifiers`).
- Add `gradability_error(pred)` in `analytics/forecasts.py` (alongside `manual_resolution_error`, `:698-714`); call it in `forecast_run.py` before insert, rejecting ungradable forecasts.
- Depends partly on #24's new structured fields (threshold, data source, scope).

---

## P1 — Analytical quality

### 11. Hard evidence gates per MOT framework — `partial` · M
Gates exist as **prompt preconditions** ("EVIDENCE BEFORE LABELS", `Strategist_Agent.md:59-65`), not code. The lens classifier assigns `strategic_move` with no hard gate.
- Turn preconditions into code that downgrades a label to "early evidence"/watch when unmet — in `_normalize_structured()` (using each signal's `sources`/`standards`) and/or the interpret functions in `mot_analyst.py:197,297,355,435` and `analytics/lens.py`.

### 12. Re-evaluate 14 technology placements — `manual` · M (human work)
This is a human review task, not code. Provide the scaffold: a review template capturing correct maturity/adoption stage, primary evidence, scope, disagreements, confidence, is-it-a-technology. Output feeds updated `tech_anchors.py` entries (#4) and `technologies.py`.

### 13. Stop treating media volume as momentum — `relabel` + `partial` · M
Article-count "momentum" is everywhere: `analytics/trends.py` (`momentum`), `mot_analyst.py:382-443`, `backend/app/explore.py:32-78`, `frontend` (`Explore.tsx MomentumCard`, `Radar.tsx MomentumBars`), `Home.py:1097-1172`.
- **Relabel** article-count metric to **"media attention"** across those surfaces.
- Reserve **"market momentum"** for non-media signals (revenue/orders/funding/patents/hiring/regulatory). Most of those need external data (see #30 / connector) — so this is relabel-now, enrich-later.

### 14. Evidence-strength score — `greenfield` · M
No such score. Build one on the event entity (#6/#7): primary vs secondary, independent-event count, quantitative-evidence present, recency, source agreement, contradictory evidence, directness. **Keep separate from model confidence** (which already exists as `confidence_num`). New module in `analytics/`, surfaced per signal.

### 15. Require contradictory evidence — `partial` · S/M
No counter-evidence field. Add "what points the other way / why the main read survives / residual uncertainty" to the signal structure (extends #2), prompt, and render. If no counter-search was done, say so explicitly.

### 16. Improve source hierarchy — `partial` · M
Only publisher **authority tier** exists (`analytics/weights.py`, `SOURCE_TIERS` t1/t2/unknown). **No document-TYPE classification** (regulatory filing / company filing / standards body / peer-reviewed / wire / trade / press release / aggregator) and no stored `source_type` on citations.
- Add a `source_type` taxonomy in `weights.py`; store `source_type` on article rows (bulk migration); populate in `_build_item`; display beside citations in `provenance.py::citation` (`:61-67`) and the Briefing source list.

### 17. Human-verify the gold set — `greenfield` (analysis) · L (human + code)
Confusion matrices already exist (`eval/scoring.py::accuracy`). **Missing: Cohen's kappa, blind multi-reviewer flow, written labeling guidance, per-domain (per-feed) accuracy.** Frontend already admits it's provisional (`Methodology.tsx:141,167`).
- Write labeling-guidance doc; run 2 blind annotators into a second-annotator file; add `cohens_kappa` + `per_domain` to `eval/scoring.py`; adjudicate disagreements. Until done, keep calling it "provisional evaluation set" (#40).

### 18. Re-run Strategist eval — `wiring` · S (then human review)
Harness exists (`eval/judges/strategist_eval.py`: grounding, references, falsifiers, overclaim, 3-judge theory-fidelity/falsifier panel). **Missing judges: recommendation proportionality, genuine source independence, contradiction handling.** Add those three functions, then re-run over current output and compare to baselines (see `lodestar-eval` skill / memory).

### 19. "Do not publish" outcome — `greenfield` · S
Doesn't exist; `generate()` even raises when there are no stories (`strategist.py:525-527`). Add a "no decisive signal this period" verdict to OUTPUT FORMAT (`Strategist_Agent.md:52-57`), a `no_publish`/`threshold_met` flag in `_normalize_structured()`, honored by render/serve paths. Pairs with the approval gate (#1).

### 20. Improve scenarios — `partial` · M
Scenarios are three free-text strings (`scenarios:{base,bull,bear}`, ≤25 words each). Change the shape to objects with probability range, key assumptions, trigger, leading indicators, strategic consequence, recommended response — in `_normalize_structured()` (`strategist.py:158-161`), the prompt (`:48,57`), both renderers, and `Briefing.tsx`.

---

## P1 — Forecast record

### 21. External forecasts as the headline — `wiring` · S
Mechanism exists: `records_by_basis` splits external (manual) vs internal (auto) vs quarantined (`forecasts.py:892-903`), and `calibration_headline`/`tagline` already hold back accuracy until the external record resolves. **Just make "N externally verifiable calls open; zero resolved" lead** the TrackRecord hero and Briefing (`frontend/src/pages/TrackRecord.tsx`), with internal accuracy demoted to a secondary consistency measure.

### 22. Baseline comparison per category — `wiring` · S
Already implemented: `naive_baseline` returns base rate, baseline accuracy, baseline Brier, Brier skill, accuracy edge; `track_record_by_category` carries them per category (`forecasts.py:750-783,906-922`). **Missing: confidence/Wilson intervals and an explicit "no demonstrated skill" verdict string.** Add both to `naive_baseline`/`calibration_verdict` and render per category in `TrackRecord.tsx`.

### 23. Remove duplicate/conflicting forecasts — `partial` · M
Paraphrase detection exists (`claims_similar`, Jaccard ≥0.5) but only at generation dedupe; grouping-by-tech only for `stage_advance_tech` (`ledger.py:147-178`). Add proposition-level grouping across kinds and apply `claims_similar` at ledger display/insert so differently-worded same-calls collapse.

### 24. Align forecast / falsifier / resolution contract — `partial` · M
Present as columns: claim, made_on, resolve_by, confidence(=probability). **In `params` only (not first-class): threshold, falsifier.** **Missing entirely: scope, authoritative data source, explicit grading rule** (grading is implicit in `resolve_*` code).
- Add `scope`, `data_source`, `grading_rule`, and promote `threshold`/`falsifier` to columns in `SQL Tables/predictions.sql`; update `_mk` factory (`forecasts.py:91-115`) and `_row` projection (`ledger.py:58-87`). Enables #10.

### 25. Demonstrate historical digest anchoring — `wiring` · S
**Contrary to the feedback's framing, a real append-only digest chain already exists** (`ledger.py::anchor_digest`/`digest_history`, table `ledger_digests.sql` with an update/delete guard trigger). Work is mostly **populating and exposing** it in `TrackRecord.tsx` — show the daily anchor chain, not just today's checksum.

---

## P2 — Investment & capital

### 26. Rename the Capital event study — `relabel` · S
"Market confirmed"/"shrugged" live in the surface only (`Home.py:2043-2073`; `Capital.tsx:1459` "shrugged"/"re-priced"). Rename the section to **"Three-day price movement around reported events"** and drop confirm/reject framing. Internal keys `confirmed`/`shrugged` (`financials.py:198-201`) can stay.

### 27. Benchmark-adjusted returns — `greenfield` · L · **BLOCKED (partial)**
**No market/sector/beta/abnormal-return calc exists** — the code is explicit it's a raw move (`financials.py:604-609`). Prices come from free **yfinance** (`finance/client.py`).
- Market/sector index series can come from yfinance too (add index tickers) — that part is **not** blocked.
- Beta and consensus need the S&P/PitchBook connector → **blocked** until authorized.
- Compute abnormal returns in `event_reaction`/`deal_reactions` (`financials.py:65-171`).

### 28. One economic event as the unit — `partial` · M
Already deduped on `(symbol, event_date)` ("one event = one row", `financials.py:125-171`) — good. Gap: it takes only the **first** mapped company (`break` at line 169). Reconcile with the #6 event entity so one event → one reaction → the full set of affected companies with roles (#29).

### 29. Fix company-event attribution — `partial` · M
Companies are a flat `companies TEXT[]` with **no roles**; only article-level `scope` hints at why multiple are named. Add per-company roles (primary/counterparty/competitor/supplier/incidental) — structured column (JSONB) on article rows populated in `_build_item`, consumed in `deal_reactions` so reactions attach only to the primary company/counterparty, not every mention.

### 30. Deepen company analysis — `partial` · L · **BLOCKED**
Today only market_cap, revenue, R&D, capex, cash, a crude P/S (`company_financials.sql`, `company_scorecard` `financials.py:613-637`). **Missing: gross/operating/net margins, net income, free cash flow (= operating cash flow − capex), enterprise value, forward/historical valuation, consensus revisions, unit economics, bull/base/bear valuation.**
- yfinance can supply FCF, margins, net income, and EV from its income/cashflow statements — build these first (**not blocked**): add fields in `finance/client.py::fundamentals` (`:151-237`), migrate `company_financials.sql`, compute in `company_scorecard`, surface in `backend/app/capital.py` + `Capital.tsx CompanyDeepDive` (`:793-859`).
- Consensus revisions, forward valuation, analyst estimates → **blocked** on the S&P/PitchBook connector. Build behind a clean data seam that lights up on connect.

### 31. Separate strategic vs stock attractiveness — `greenfield` · M
No such separation exists. Add distinct scores — technology outlook / competitive position / value-capture / financial quality / valuation / investment conclusion — as new reducers in `financials.py` and a payload section in `capital.py` + `Capital.tsx`. Depends on #30's financials.

---

## P2 — Radar

### 32. Rename initial Radar signal — `relabel` · S
Rename the initial "emerging technology" framing to **"untracked attention"** until evidence is stronger. Labels come from the Scout agent + the `research_stage` flag; surface strings in `frontend/src/pages/Radar.tsx:558` and `Home.tsx:101-102`.

### 33. Define what qualifies as a technology — `partial` · M
Event-shaped tags are excluded (`_EVENT_TAGS`, `radar.py:51-57`) and vague tokens blocked (`_GENERIC_TOKENS`) — **but only in the fallback path**, not for agent proposals. Add a tech-vs-non-tech check in `parse_scout`/`dedupe_against_registry` (`radar.py:152-194,345-360`) to exclude/reclassify trends, business models, regulations, applications; tighten the Scout prompt.

### 34. Radar promotion criteria — `wiring` · S
Gates already exist: NEWS gate (≥5 mentions, ≥3 publishers, ≥7-day spread) OR RESEARCH gate (≥3 papers), then admin promotion + evidence floor 15 (`radar.py:37-44`, `backend/app/radar.py:66-134`). Extend `corroborate` to also require a precise definition, ≥1 non-media signal, named companies/groups, a strategic reason, and a measurable 90-day forecast before a candidate is promotable.

### 35. Semantic research-paper matching — `partial` · M
Matching is pure keyword/substring (`_keyword_hits`/`_kw_res`, `radar.py:197-214`; `match_technologies` also substring). A semantic stack already exists but is unused here (`vectordb/embedder.py`, `news_embeddings`). Swap keyword matching for embedding similarity, reusing `vectordb/embedder.py`.

### 36. Measure detection lead time honestly — `partial` · M
Radar records its own `first_seen`/`promoted_on` and a durability call (`detection_call_fields`, `radar.py:437-473`) but **does not compare against external milestones**. Add comparison vs first technical publication (arXiv — already integrated), first funding event (`funding_rounds` table), first major coverage, first deployment. Needs an external-milestone source for some columns.

---

## P2 — Editorial & positioning

### 37. Narrow the primary audience — `relabel` · S
Set one primary reader (corporate technology-strategy teams; investors secondary) in `frontend/src/pages/Home.tsx:39,47` and `Pharos_PROJECT_DESCRIPTION.md`.

### 38. Reduce recommendation strength until validated — `partial` · S
Prefer investigate/validate/monitor/prepare/pilot; reserve enter/exit/scale/commit for human-reviewed analysis. Implemented via #8's ladder + #1's gate.

### 39. Content corrections log — `greenfield` · M
Does not exist. New table (near `predictions_tombstones.sql`), backend route, and a frontend page recording original claim / correction / reason / date / affected forecasts / whether scores changed.

### 40. Precise credibility labels — `relabel` · S
String swaps: "gold set" → "provisional evaluation set" (`Methodology.tsx:141,167,343`); "market signal" → "media-attention signal" (`Radar.tsx:112,270`, `mot_analyst.py:304,314`); "market confirmed" → "stock moved positively in the event window" (`Home.py:2060`); "well-calibrated" → "internal categories currently appear calibrated; external record pending" (`calibration_verdict`, `forecasts.py:948`; `glossary.ts:30`); "detected before the market" → "detected before addition to the Pharos registry" (`Home.tsx:101-102`).

---

## External-data dependencies (the free-cash-flow question)

| Item | Needs | Source | Status |
|---|---|---|---|
| #30 FCF, margins, net income, EV | Cash-flow & income statement lines | **yfinance** (already integrated) | Build now |
| #30 consensus revisions, forward valuation | Analyst estimates | **S&P / PitchBook connector** | Blocked on auth |
| #27 abnormal return | Market + sector index series | **yfinance** (add index tickers) | Build now |
| #27 / #31 beta, competitive data | Beta, fundamentals | **S&P / PitchBook connector** | Blocked on auth |
| #35 paper matching | Embeddings | Existing `vectordb/` | Build now |
| #36 lead-time milestones | Funding/deploy dates | `funding_rounds` + external | Partial |

**Free cash flow** is not looked up — it's derived: `FCF = operating cash flow − capex`, both available from yfinance's cash-flow statement. So #30's FCF/margins/EV can be built immediately; only consensus/forward/beta wait on the connector.

---

## Recommended execution order

The feedback's own "first four weeks" shortlist (#3, #2, #6, #7+#11, #1) is the highest-leverage start — and none of it needs external data. Suggested waves:

- **Wave A — Relabels (S, no risk, no data):** #26, #32, #37, #40, #13(labels), #21, #22-verdict, #25-expose. Ships credibility fast.
- **Wave B — The shortlist (structural gates):** #3, #2, #9, #1, #19, #8. The core "stop presenting inference as fact" work.
- **Wave C — Event backbone:** #6 → then #7, #28, #29, #14 (all build on the event entity).
- **Wave D — Analytical depth:** #5, #16, #11, #15, #20, #4, #24, #10, #23.
- **Wave E — Capital/finance (yfinance parts):** #30(FCF/margins/EV), #27(index), #31, #35.
- **Wave F — Connector-gated:** #30(consensus), #27(beta) — once S&P/PitchBook is authorized.
- **Human tracks (parallel, not code-blocking):** #12 (14 placements), #17 (gold set), #18 (re-run eval), #39 (corrections log process).

**Blocked until connector auth:** #27 (beta), #30 (consensus/forward valuation), #31 (competitive data). Everything else is buildable now.
