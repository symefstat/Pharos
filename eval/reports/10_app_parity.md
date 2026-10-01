# L10 — App/API parity + interaction correctness (static/offline)

**Date:** 2026-07-02 · **Mode:** static source audit only — app not launched, no network/Supabase/Toqan, `.env` untouched.
**Inputs:** `backend/app/*.py` (incl. uncommitted `mot.py`), `frontend/src/pages/*.tsx` (incl. uncommitted `Mot.tsx`), shared components (`charts.tsx`, `Story.tsx`, `ChordDiagram.tsx`, `actions.tsx`, `ui.tsx`), `frontend/src/lib/api.ts`, and the analytics modules that shape nested payloads.
**Tool:** `eval/app_parity_check.py` (top-level field diff, AST + regex); nested fields and interactions audited by hand below.

---

## 1. Endpoint → page map and emitted fields

| Endpoint | Backend | Page | Top-level fields |
|---|---|---|---|
| `GET /api/capital` | `capital.py:96` | `Capital.tsx` | have_fin, have_prices, row_count, posture, kpis, synthesis, board, board_read, deal_flow, concentration, market_structure(_read), coverage, tracked_tickers, landscape, sector_rollup, market_cap_share, companies, reactions, divergence(_read) |
| `GET /api/forecasts` | `forecasts.py:94` | `Forecasts.tsx` | headline, tagline, summary, track_record, categories, calibration_bins, calibration_verdict, open_table, hero, overdue, resolved, state |
| `POST /api/forecasts/resolve` | `forecasts.py:104` | `Forecasts.tsx` (Resolver) | ok, error |
| `GET /api/explore/trends` | `explore.py:19` | `Explore.tsx` (Trends) | feeds, feed, multi, weighted, empty, headline, kpis, momentum, voice, volume, sentiment, breakdowns{by_company,by_country,by_impact,by_scope,by_tag} |
| `GET /api/explore/entities` | `explore.py:66` | `Explore.tsx` | universe |
| `GET /api/explore/entity` | `explore.py:74` | `Explore.tsx` | entity, read, weighted, total, feeds_count, sentiment, by_feed, series, co_mentions, stories |
| `GET /api/explore/technologies` | `explore.py:94` | `Explore.tsx` (Compare) | technologies[{label,domain,maturity,adoption,articles,entrants,move,scurve}] |
| `GET /api/mot` | `mot.py:54` | `Mot.tsx` | feeds, scope, classified, total, scurve_interpret, **adoption_interpret**, technologies, maturity_order, adoption_order, diffusion, diffusion_interpret, moves, move_order, move_interpret, transitions, convergence(_interpret), comatrix, scorecards, performance_curves, adoption_curves, browse |
| `GET /api/mot/scorecard-read` | `mot.py:35` | `Mot.tsx` (Scorecard) | entity, as_of, read |
| `GET /api/briefing` | `briefing.py:16` | `Briefing.tsx` | calibration{headline,tagline}, strategist{as_of,focus,window_days,read,portfolio,stories}, watchlist{items,alerts}, pulse{stats,top_stories,health} |
| `GET /api/feeds` | `feeds_api.py:23` | `Feeds.tsx` | feeds[{key,label,icon,count,stories}] |
| `POST /api/ask` | `feeds_api.py:54` | `Ask.tsx` | configured, answer, stories, theory |
| `POST /api/actions/*`, `GET /api/actions/status/{jid}` | `actions.py` | all pages via `actions.tsx` | job_id/status/kind; job {id,kind,status,steps,error,started,finished} |

---

## 2. Parity diff — (a) API fields the UI never renders

### MOT (`/api/mot` ↔ `Mot.tsx`)
1. **`adoption_interpret` — dead, and a duplicate.** Emitted at `backend/app/mot.py:168` but never referenced anywhere in the frontend. Worse: it is byte-identical to `diffusion_interpret` — both are `ma.interpret_diffusion(diffusion)` (`mot.py:168` and `mot.py:173`). The adoption-lifecycle card (`Mot.tsx:111-121`) is the only interpreted-chart card with **no Insight line**; the intended field probably wanted a distinct interpretation (or `interpret_tech`-style read of the adoption placements), not a copy.
2. **`diffusion[].top` — meaningful missing exhibit.** `diffusion_points` names the top technologies per adopter category (`analytics/mot_analyst.py:225`), but `DiffusionStrip` (`Mot.tsx:226-253`) renders only `stage`+`count`. The "who is in each adopter group" answer is computed, shipped, and dropped. `z`/`y` are also unused (the UI draws its own bars) and `crossed` is **recomputed client-side** as `i >= 2` (`Mot.tsx:236`) instead of using the payload flag — consistent with `_POST_CHASM` (`analytics/mot_analyst.py:71`) today, drift risk tomorrow (see §5).
3. **Backward transitions fetched but silently invisible.** `detect_transitions` deliberately keeps backward moves — "downranked, never dropped" (`analytics/tech_layer.py`, detect_transitions docstring) — and commit `da155e5` put them behind an expander in Streamlit. `TransitionsList` filters them out with `transitions.filter((t) => !t.backward)` (`Mot.tsx:256`) and renders **nothing else** — no expander, no count. The re-estimation-noise signal is lost in the React port. `technology`, `domain`, `as_of`, `suspect` per-transition fields are also unused.
4. `technologies[].move` and `[].articles` — never rendered on this page (the placement table `Mot.tsx:463-498` shows domain/maturity/adoption/regime/coverage/entrants, no move column; charts use `coverage`). `move` is shown in Explore-Compare, not here.
5. `convergence[].strength` and `bridges[].feeds` (per-domain mention split, `analytics/entity_tracker.py:140-142`) unused — `ConvergenceList` shows `entity (mentions)` only (`Mot.tsx:330`).
6. `scope` — metadata echo, fine to ignore.

### Capital (`/api/capital` ↔ `Capital.tsx`)
7. `have_fin` / `have_prices` (`capital.py:37-38`) — never read; the UI gates §2–§4/§8 on `landscape.length > 0` (`Capital.tsx:276,294,320,456`) and §6 on `divergence != null` (`Capital.tsx:379`). Behaviorally equivalent, but when financials exist and simply produce zero plottable points the sections vanish with **no explanatory empty state** (Streamlit told you to run `financials_run.py`).
8. **`posture` mostly dropped.** Only `.flag` and `.n` are read (`Capital.tsx:162,181`); `stance`, `maturity`, `commitment`, `option` unused, and `PostureCallout` renders `null` for the `"aligned"` flag (`Capital.tsx:185`) — a healthy posture produces no exhibit at all, so the E2 stance line ("balanced posture in a growth field") never appears.
9. `board.counts.unclear`, `board.shown` (`analytics/mot_analyst.py:869-874`), `concentration.total`, `divergence.n`, `divergence.divergence_rate` (`analytics/financials.py:174+`), `coverage.untracked_mentions` — unused rollup stats.
10. Per-item: `Move.kind`/`Move.published_at`; `Reaction.symbol/event_date/base_date/post_date/feed` (tooltip shows company/pct/direction/title only, `charts.tsx:424-439` — the event date would make the event study auditable); `companies[].revenue` (`api.ts:121`).

### Forecasts (`/api/forecasts` ↔ `Forecasts.tsx`)
11. **`headline`, `tagline`, `state` — three top-level fields entirely unused** (`backend/app/forecasts.py:79-80,90`). They duplicate Briefing's calibration banner; on Forecasts the scorecard recomputes from `track_record` instead. Dead weight (headline includes per-category verdicts never shown anywhere).
12. **`open_table` columns `Horizon` and `Type` never rendered** (`analytics/forecasts.py:463-465` vs `OpenTable` at `Forecasts.tsx:200-217`). `Type` ("judgment" vs "auto") is meaningful — it is the only marker of which open calls a human will eventually have to grade.
13. `hero[].horizon` (`backend/app/forecasts.py:43`), `overdue[].confidence/category/resolve_by` (Resolver shows only the claim, `Forecasts.tsx:133`), `resolved[].resolution_note` and `.confidence` (`Forecasts.tsx:260-275` shows outcome/claim/category/dates; the note distinguishing "manually graded" is lost).

### Explore (`/api/explore/*` ↔ `Explore.tsx`)
14. **`breakdowns.by_impact`, `.by_scope`, `.by_tag` — computed, serialized, never rendered.** Backend builds all five marginals (`explore.py:39-42`); the page renders only `by_company` and `by_country` (`Explore.tsx:186,192`). 3/5 of the breakdown work is dead payload and three missing exhibits.
15. `voice.total`, `voice.n_entities` (`analytics/trends.py:180`) unused — the long-tail size would qualify the share-of-voice chart. `momentum[].recent/.prior` unused (tooltip shows pct/thin only). `feed`/`weighted` echoes unused (client state is the source of truth — fine).
16. `entity.sentiment.neutral` unused (`Explore.tsx:250` shows positive/negative only).

### Briefing (`/api/briefing` ↔ `Briefing.tsx`)
17. `strategist.focus`, `strategist.window_days` (`briefing.py:38-39`) unused.
18. `pulse.stats.top_countries` (`analytics/aggregator.py:222`) unused; `top_companies` is a fallback that is effectively dead since `quick_stats` always emits `top_companies_weighted` (`Briefing.tsx:281`).
19. `health[].env_key` and `[].last_rollup` unused — `last_rollup` is even declared in the `FeedHealth` type (`api.ts:495`) but the table (`Briefing.tsx:319-349`) has no column for it.
20. **`Signal.standards` typed but never rendered** (`api.ts:437`): the strategist's standards-war read (`leader`/`basis`/`read`) has no exhibit in `SignalCard` (`Briefing.tsx:195-230`). `portfolio[].titles` also unused (badges show `action ×count` only).
21. `calibration.headline.verdict` and `.categories` unused on this page (accuracy/brier/resolved/open only) — acceptable, Forecasts covers depth.

### Feeds / Ask
22. `/api/feeds` ships **raw, unslimmed rows** (`feeds_api.py:38-45` slices to 48 but keeps every column — content, lens rationale, fetched_at, …) while `StoryCard` uses ~8 fields; contrast `/api/mot` browse which slims explicitly (`mot.py:144-160`). Payload-size issue, not correctness.
23. `ask.configured` unused (`Ask.tsx` renders the answer text regardless — degradation message rides in `answer`, so this is benign).
24. **Dead frontend module:** `frontend/src/lib/useCapital.ts` is imported nowhere (superseded by `useResource`); delete candidate.

## 2b. UI reads of fields the API doesn't send (ghost reads)

**None found.** The checker's `data.<x>` scan is clean, and manual tracing of nested access confirms: `Story` renderers handle both `_feed_label` (raw rows: aggregator `all_recent`, `mot.py` browse) and `feed_label` (slim rows: `PulseAggregator._slim`, entity stories) — `Story.tsx:30,55,75`. `motScorecardRead` may return `{read: null}` without `as_of`/`entity`; the consumer guards on `read` (`Mot.tsx:369,407`). All Capital/Forecasts/Explore nested reads were matched against the producing analytics functions (`landscape_points`, `sector_rollup`, `market_cap_share`, `capital_kpis`, `company_scorecard`, `deal_reactions`, `consensus_divergence`, `open_forecast_table`, `track_record`, `voice_share`, `profile`, `co_occurrence_matrix`, `domain_convergence`, `diffusion_points`, `scorecard`, `detect_transitions`, `quick_stats`, `feeds_health`) — every read field exists. Unit conventions also line up (`pct` for 0–100 backend values, `ratioPct` for 0–1: `kpis.top_rd.pct` is pre-scaled ×100 in `financials.py:527` and rendered with `pct`; `rd_intensity`/`investment_intensity`/`confidence` are ratios rendered with `ratioPct`).

## 2c. Conditionally-dead usages
- `CoMatrixHeatmap` is now only the `< 3 labels` fallback of the chord diagram (`Mot.tsx:162-166`); with `top=14` co-occurrence it is nearly unreachable except on tiny corpora — intentional, keep.
- `PostureCallout` renders nothing for `flag ∈ {"aligned","none"}` (`Capital.tsx:161-185`) — see finding 8.
- `s.top_companies` fallback in `Briefing.tsx:281` — unreachable with current backend (see 18).

---

## 3. Interaction audit — every control, wired or not

| Page | Control | Wired? | Evidence |
|---|---|---|---|
| Mot | Feed scope `Select` | **YES — server-side, all panels** | `Mot.tsx:41` loader depends on `scope` → refetch `/api/mot?scope=`; backend filters rows **at the source** (`mot.py:69`), so S-curve, counts, diffusion, moves, convergence, co-mention, scorecards, browse all inherit; transitions (`mot.py:117-118`) and benchmark curves (`mot.py:139-141`) scoped by label. The **uncommitted diff** is exactly this fix — at HEAD only diffusion+moves were scoped and every other panel was a silent no-op. Commit it or the fix is lost. |
| Mot | "Classify new" button | YES | POST `/api/actions/classify` (`Mot.tsx:86`); job completion bumps `tick` → `useResource` refetch (`useResource.ts:44-50`) |
| Mot | Performance/Adoption curve `Select`s | YES (client) | `CurvePicker` picks from payload (`Mot.tsx:340-346`) |
| Mot | Scorecard entity `Select` | YES | client-side card pick + per-entity refetch of `/api/mot/scorecard-read` (`Mot.tsx:363-374`) |
| Mot | "Generate analyst's read" | YES | POST `/api/actions/scorecard/{entity}`; `tick` in the effect deps re-pulls the read when the job lands (`Mot.tsx:374`) |
| Mot | Browse-by-lens `Segmented` + value `Select` | YES (client) | filter at `Mot.tsx:444-447`; dim switch re-derives values with safe fallback (`Mot.tsx:446`) |
| Mot | Chord hover | YES | ribbon isolation (`ChordDiagram.tsx:53-59,71`) |
| Capital | Company deep-dive `select` | YES (client) | `Capital.tsx:121-141` |
| Capital | Topbar Refresh | YES | `refresh()` busts server cache then refetches (`useResource.ts:26`) |
| Explore | Trends/Entities/Compare `Segmented` | YES | URL-param tab switch (`Explore.tsx:54-55,73-86`) |
| Explore/Trends | Range `Segmented` (30/90/180/1Y) | YES — refetch | `useAsync` deps `[days, feed, weighted]` (`Explore.tsx:96-99`) |
| Explore/Trends | Feed `Select` | YES — refetch | backend filters `feed_keys` (`explore.py:25`) — every panel (volume, sentiment, momentum, voice, breakdowns) is feed-scoped |
| Explore/Trends | Weighted/Raw `Segmented` | YES, **narrow by design** | refetches, but backend uses `weighted` only in `voice_share` (`explore.py:32`); only the share-of-voice panel changes. The caption says so (`Explore.tsx:160`) — not a no-op, but a user may expect the breakdowns to change too. |
| Explore/Entities | Range `Segmented` + entity `Select` | YES — refetch | universe + profile both depend on `days`; profile on `selected` (`Explore.tsx:206-217`) |
| Explore/Compare | mode `Segmented`, entity `Select`s, tech `Select`s | YES | entity → per-side refetch (`Explore.tsx:333-334`); tech → client pick (`Explore.tsx:416-417`) |
| Explore | Topbar Refresh | YES | cache-bust then remount via `key` tick (`Explore.tsx:57-59,83-85`) |
| Feeds | Feed tab buttons | YES (client) | `Feeds.tsx:27,40` |
| Feeds | "Refresh {feed}" | YES | POST `/api/actions/feed/{key}` → tick → refetch (`Feeds.tsx:55`) |
| Forecasts | Category filter chips | YES (client) | `Forecasts.tsx:180-196` |
| Forecasts | hit/partial/miss graders | YES | POST `/api/forecasts/resolve` then `resource.refresh()` (`Forecasts.tsx:236-240`); backend also clears the server cache (`forecasts.py:120`) |
| Briefing | "Refresh all data" / "Regenerate strategist" | YES | `ActionButton` → job → toast → tick-driven page refetch (`actions.tsx:52-107`) |
| Ask | input / example prompts / Send | YES | POST `/api/ask` (`Ask.tsx:31-52`) |
| Ask | Topbar Refresh | YES, repurposed | clears the chat thread (`Ask.tsx:62`) — semantic overload of "refresh", but deliberate |

**Verdict: no silent no-op controls remain in the current working tree.** The one historical offender (MOT feed scope, which at HEAD only filtered diffusion+moves) is fixed by the uncommitted `backend/app/mot.py` change — this fix must be committed.

---

## 4. Cross-tab consistency — where names come from

| Vocabulary | Source(s) | Verdict |
|---|---|---|
| Maturity/adoption/move stage names | Single source: `ma.MATURITY_ORDER/ADOPTION_ORDER/MOVE_ORDER` shipped in the payload (`mot.py:170-175`) and used for every axis/matrix | ✅ consistent — **except** `DiffusionStrip` hardcodes its own copy of the 5 adopter stages and its own chasm index `i>=2` (`Mot.tsx:227,236`) instead of `data.adoption_order` + `point.crossed`. Values match `_POST_CHASM` today; it's a drift-prone divergent copy. |
| Displayed stage per tech | Both `/api/mot` (`mot.py:92-93`) and `/api/explore/technologies` (`explore.py:106-107`) go through `display_stage()` over `placements(data.rows(days=30))` | ✅ same stage names on MOT and Explore-Compare |
| **"Coverage" number per tech** | MOT placement table shows `coverage` = `stage_articles` (fallback `articles`) (`mot.py:86-87`, `Mot.tsx:490`); Explore-Compare's "Coverage" KPI shows `articles` (`explore.py:109`, `Explore.tsx:456`) | ⚠️ **same label, different metric** — for a contested tech the two tabs display different "Coverage" numbers. Rename one (e.g. "Classified articles" in Compare) or emit the same field. |
| S-curve position | MOT: `stage_centroid` fallback `MO.index(p["maturity"])` (`mot.py:82-84`); Explore-Compare: `ma.scurve_position` fallback `committed_stage → maturity` (`mot_analyst.py:38-47`) | ⚠️ minor: different fallback (bare modal vs committed) when the centroid is missing; identical when centroid exists. Prefer `scurve_position` in `mot.py` too. |
| Entity names | All go through `normalize_entity`; universes differ **by design** (Explore = rollup-weighted 30–180d, MOT scorecards = classified 30d top-40, Capital = capital rows) | ✅ names consistent; windows intentionally differ |
| Calibration numbers | Briefing banner and Forecasts scorecard both derive from `data.predictions()` via `analytics.forecasts` (`briefing.py:23-25`, `forecasts.py:29-33`) | ✅ single source; no contradiction possible |
| Feed identity in selects | MOT scope keyed by feed **label** (`Mot.tsx:61` ↔ `_feed_label` compare `mot.py:69`); Explore trends keyed by feed **key** (`Explore.tsx:103` ↔ `explore.py:25`) | ✅ both wired correctly, but the mixed key/label convention is fragile — a renamed label silently empties the MOT scope. |
| Sentiment dot colors | `Story.tsx:6-10` hardcodes hex values also present in `theme.ts` | cosmetic duplicate |

---

## 5. Static checker — `eval/app_parity_check.py`

Run: `./venv/bin/python eval/app_parity_check.py`. Output (2026-07-02, current tree):

```
== GET /api/capital  ↔  pages/Capital.tsx ==        UNUSED: have_fin, have_prices
== GET /api/forecasts ↔  pages/Forecasts.tsx ==     UNUSED: headline, state, tagline
== GET /api/explore/trends ↔ Explore.tsx ==         all referenced
== GET /api/explore/entity ↔ Explore.tsx ==         all referenced
== GET /api/explore/entities ↔ Explore.tsx ==       all referenced
== GET /api/explore/technologies ↔ Explore.tsx ==   all referenced
== GET /api/mot ↔ pages/Mot.tsx ==                  UNUSED: adoption_interpret, scope [echo]
== GET /api/mot/scorecard-read ↔ Mot.tsx ==         all referenced
== GET /api/briefing ↔ pages/Briefing.tsx ==        all referenced
== GET /api/feeds ↔ pages/Feeds.tsx ==              all referenced
== POST /api/ask ↔ pages/Ask.tsx ==                 UNUSED: configured
== ghost reads ==                                   none found
Total top-level unused-field findings: 8; ghost reads: 0
```

**Honest error modes** (also documented in the script header): token-match usage is optimistic — `trends.feed`/`weighted` read as "used" because `.feed`/`.weighted` appear on *other* objects (FP); fields renamed through spreads (`{...t, x: t.ax}`) or dynamic keys (`r[dim]`) are invisible (FN); ghost-read scan only sees a variable literally named `data`; nested keys (everything in §2 items 2–21) are out of the tool's scope and were audited manually. Treat the tool as a regression tripwire for top-level drift, not a substitute for this report.

---

## 6. Acceptance targets

| Target | Result |
|---|---|
| 0 meaningful unrendered API fields | **FAIL** — 8 top-level (checker) + ~16 meaningful nested (§2); worst: `diffusion[].top`, backward `transitions`, `open_table.Type/Horizon`, `breakdowns.by_impact/by_scope/by_tag`, duplicated `adoption_interpret`, `posture.stance`, `Signal.standards` |
| 100% of filters demonstrably change the view | **PASS (statically)** — every control traced to a refetch or client filter (§3); depends on the uncommitted `mot.py`+`Mot.tsx` diff being committed |
| 0 cross-tab contradictions | **NEAR-PASS** — one label-level contradiction ("Coverage" = different metrics on MOT vs Explore-Compare) + two drift-prone divergent copies (DiffusionStrip stage list/chasm; scurve fallback) |

## 7. Proposed live pass — **NEEDS APPROVAL** (not executed)

Static analysis cannot prove pixels; it needs DB creds (Supabase via `.env`) to show real data. On approval:
1. `/run` — start API (`./venv/bin/python -m uvicorn backend.app.main:app --port 8000`) + `npm run dev` in `frontend/`, or `./start_web_ui.sh`.
2. Screenshot each tab (Briefing, Explore×3 subtabs, MOT, Capital, Forecasts, Feeds, Ask) at default state.
3. Exercise every §3 control and re-screenshot: MOT scope through **each** feed (assert classified count, S-curve dots, convergence list, browse all change), Trends 30d↔1Y + per-feed + weighted↔raw (assert voice chart alone changes on the last), Entities/Compare selections, Forecasts category chips, Feeds tab switch.
4. `curl` each endpoint and diff live JSON keys against §1 (catches fields only emitted with data present: `kpis`, `landscape`, `divergence` non-null paths).
5. `/verify` the MOT scope fix end-to-end: pick a feed with few stories and confirm *every* panel shrinks (the HEAD bug would leave S-curve/scorecards/browse global).
6. One background action (`Classify new` or per-feed refresh) to observe job polling → toast → auto-refetch. **Not** `refresh-all` (spends agent/API quota).

---
*Files: this report + `eval/app_parity_check.py`. No production code modified.*

---

## 8. Live pass results (2026-07-02) — EXECUTED (read-only)

Backend `uvicorn :8000` + Vite `:5173` against production DB (reads only). Driver:
Playwright headless Chromium (script preserved in session scratchpad; results in
`eval/reports/screenshots/interaction_results.json`; screenshots in `eval/reports/screenshots/`).
§7 step 6 (background actions) intentionally SKIPPED — would spend Toqan quota.

**Tabs:** all 7 render real data, **0 console errors** anywhere. Briefing shows the full
strategist read (5 signals, falsifiers, scenarios), 89% accuracy / 0.12 Brier hero,
347 items (7d), all 10 feeds 100% classified. MOT shows 1,955 classified items,
all panels populated incl. the new chord diagram.

**Interactions: 21 exercised, 21 wired.**
- MOT scope select: all 11 options → **11 distinct views** (SVG node count varies
  193→133 per feed; every panel shrinks — the working-tree scope fix works end-to-end;
  §7 step 5 verified).
- Explore: Entities/Compare subtabs change view; 1Y/30d and Raw/Weighted toggles all
  change content (Weighted changes the voice panel, per design).
- Forecasts: category chips filter the table ("All" clicked while already active —
  expected no-op, not a defect).
- Feeds: feed switch changes view.

**Live JSON key-diff vs §1 static list:** matches. Notably the dead fields are confirmed
emitted in production: `forecasts.headline/tagline/state`, `mot.adoption_interpret`
(still byte-identical to `diffusion_interpret`), `capital.have_fin/have_prices`,
`explore.breakdowns.by_impact/by_scope/by_tag` present and unrendered.

**Verdict vs targets:** interactions **100% wired — PASS** (supersedes the static
suspicion); dead-field target still **FAIL** (8 top-level + nested, unchanged);
cross-tab "Coverage" contradiction still open.
