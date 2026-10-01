# L5 — Technology Layer Eval (S-curve placement, stage transitions, cross-surface consistency)

**Date:** 2026-07-02 · **Mode:** offline only (no network, no Supabase, no Toqan, .env untouched)
**Scope:** `analytics/tech_layer.py`, `analytics/mot_analyst.py`, `backend/app/{mot,capital,briefing,explore}.py`, frontend Mot/Capital/Briefing pages, git history.

---

## 1. Baseline test run

```
./venv/bin/python -m pytest tests/test_tech_layer.py tests/test_mot_analyst.py tests/test_benchmarks_ferment.py -q
→ 53 passed, 1 warning in 0.66s
```

Full suite after adding golden tests:

```
./venv/bin/python -m pytest -q
→ 356 passed, 1 xfailed in 1.07s      (341 pre-existing all still pass; +15 new pass, +1 xfail by design)
```

## 2. How the layer works (read of the code)

**Centroid → x placement** (`analytics/tech_layer.py::_dimension_stats`, lines 71–100):
per technology and dimension (maturity: 6 stages, adoption: 5), off-vocabulary and
`n/a` articles are excluded; `centroid = Σ(stage_index · count) / n`;
`committed = order[clamp(round(centroid))]` (Python banker's rounding at exact halves);
`mixed = modal_share ≤ 0.5 OR modal ≠ committed` (the fade guard for bimodal spreads).
`display_stage(p, dim)` (lines 156–167) = committed, falling back to bare modal — the
declared single source of truth for "which stage to show".
Chart x: `backend/app/mot.py::norm` = `centroid / (len(order) − 1)` (0..1); the Altair
charts (`mot_analyst.tech_scurve_chart` / `adoption_curve_chart`) band the dot by
`committed_of(p)` and fade when `mixed`. Label and dot agree by construction because
both derive from the same centroid.

**Direction-aware, debounced transitions** (`tech_layer.py::_latest_change` +
`detect_transitions`, lines 170–257): history snapshots per tech, newest first; the
latest classified stage is anchored, blanks are skipped (gaps don't reset the run),
and the first earlier differing stage defines the move. Grading:
`backward` (new stage ranks earlier on a near-monotonic axis; unknown legacy labels
default to not-backward), `confirmed` (run ≥ 2 snapshots — the debounce),
`contested` (destination snapshot `*_mixed`), `suspect = backward ∨ ¬confirmed ∨ contested`.
Moves settled longer than `_TRANSITION_FRESH_SNAPSHOTS = 4` drop off. Nothing is
dropped for distrust — only sunk in the sort (backward hardest, then contested, then
pending; maturity before adoption at equal trust).

## 3. Golden-fixture tests added — `tests/test_tech_layer_golden.py`

Previously untested behavior, now pinned with fixed inputs → exact outputs (16 tests):

**(a) Centroid → placement, boundaries** — endpoints (centroid 0.0 / 5.0 / 4.0);
exact-half ties resolved by **banker's rounding** (0.5→research, 1.5→growth,
2.5→growth, 3.5→mature — asymmetric but every tie is also `mixed`, so it is faded,
never asserted); underscore/case normalization of raw classifier strings; a full
bimodal `placements()` snapshot (3 emerging + 2 mature → centroid 2.2, committed
'growth' — a stage no single article chose, `mixed=True`, `display_stage`='growth').

**(b) Debounce** — flapping input (A,B,A,B,A) yields exactly ONE pending
(`confirmed=False, suspect=True`) move anchored on the latest snapshot, never a
confirmed one, in either phase; freshness boundary pinned (run==4 shown, run==5
dropped); coverage gap inside a run neither resets it nor reads as a change;
unclassified-latest and single-snapshot histories emit nothing.

**(c) Direction-awareness** — a regression that has *held* 2 snapshots is
`confirmed` yet still `backward`+`suspect` and sorts below an older, unconfirmed
forward move; backward flag works on the adoption axis; unknown legacy labels
(`'ferment'`) are not judged backward (no crash); full trust ordering pinned:
clean > pending > contested > backward.

**(d) Cross-surface** — chart band == `display_stage()` == Compare's
`scurve_position` source on both curves for a bimodal fixture (≠ bare modal — the
historical drift case); the inline fallback copies in `mot_analyst` agree with
`display_stage` on all fallback shapes.

**What the golden tests caught (1 real finding, marked xfail — production untouched):**
`test_snapshot_persists_displayed_stage_not_modal` (strict xfail).
`TechAnalyst.snapshot()` (`tech_layer.py` lines 275–291) persists the **bare modal**
(`p["maturity"]`, `p["adoption"]`) to `technology_stage_history`, while every display
surface shows the centroid-**committed** stage via `display_stage()`. On a bimodal
spread (modal='emerging', committed='growth') the transitions feed, watchlist alerts
and Strategist transition context therefore speak in stages **no surface displays**.
Mitigation already in the code: exactly when modal ≠ committed, `mixed=True` is
persisted alongside → the resulting transition is `contested` → `suspect` → it is
downranked and never watchlist-alerted (`watchlist.py` only alerts non-suspect
moves). Residual exposure: the MOT transitions panel and Strategist context can
still show modal-based from/to labels that disagree with the placement table for the
same tech/day. Everything else passed on first run (one test assertion of mine was
initially miscalibrated against `interpret_tech`'s narration rules and was corrected
— not a production issue).

## 4. Cross-surface consistency trace (static)

| Surface | Stage source | Path |
|---|---|---|
| MOT Analyst (`/api/mot`) | `display_stage(p)` / `display_stage(p,"adoption")` over `placements(classified)`; chart x from same centroid | `backend/app/mot.py:92-93,98,102` |
| Explore / Compare (`/api/explore/technologies`) | `display_stage` + `ma.scurve_position` (centroid) | `backend/app/explore.py:106-107` |
| Briefing → Strategist read | agent context built with `display_stage` at generation time; transitions from `detect_transitions` with backward moves explicitly excluded/noted | `analytics/strategist.py:673-688,655-671` |
| Briefing → Watchlist alerts | `TechAnalyst.transitions()` → same `detect_transitions`; **only non-suspect** moves alert | `analytics/watchlist.py:68-72,131` |
| Capital (`/api/capital`) | does **not** display a per-technology stage. `capital_posture` computes a *field-level* modal maturity over capital-move articles (different unit of analysis, bare modal via `_modal_confident`) used only to set the over-extension/timid flag, hedged below n=3 or ≤50% plurality; frontend renders only the flag text ("early/uncertain" / "mature"), never a named tech stage | `analytics/mot_analyst.py:905-929`, `frontend/src/pages/Capital.tsx:161-185` |
| Streamlit legacy (`Home.py`) | `display_stage` (placement table 1452, Compare 2570-2571) | consistent |

**Verdict: single source of truth for per-technology stage display = `tech_layer.display_stage()`.**
The commit `636f2a2` ("Unify stage display + harden against drift") is intact — no
drift has crept back into any display surface. Two caveats:

1. **N copies of the fallback expression** — `p.get("committed_stage") or p.get("maturity")`
   is inlined twice in `analytics/mot_analyst.py` (`scurve_position` line 46,
   `interpret_tech` line 714), presumably to avoid a circular import. Currently
   byte-identical semantics (now pinned by a golden test), but it is the one
   drift-prone duplication left.
2. **The only code path that can disagree**: the modal-vs-committed history snapshot
   described in §3 (the xfail). It never affects a *placement* display, only the
   from/to wording of transitions on bimodal snapshots, and those are always graded
   contested/suspect.

**Uncommitted modifications checked:** `backend/app/mot.py` diff only changes feed
*scoping* (filter rows/transitions/benchmark-curves to the selected feed) — stage
derivation still flows through `display_stage`; no new stage copy.
`frontend/src/pages/Mot.tsx` diff only swaps the co-mention heatmap for a
`ChordDiagram` — no stage display change. Neither reintroduces drift.

**Acceptance targets:** golden fixtures 100% pass (15/15, plus 1 intentional strict
xfail) ✅ · cross-surface *displayed*-stage disagreement paths found = **0** ✅
(1 documented non-display path: history/transitions wording, mitigated).

## 5. NEEDS APPROVAL — proposed live checks (not executed)

1. **Live cross-surface stage diff:** with server creds, fetch `/api/mot`,
   `/api/explore/technologies`, and the latest Strategist context rows; join on tech
   label and assert maturity/adoption strings are identical across surfaces
   (expected: 0 mismatches).
2. **History-table audit for the xfail finding:** query `technology_stage_history`
   for rows where `maturity_mixed = true` and check how often the persisted modal
   stage differs from the committed stage recomputable from that day's corpus —
   quantifies real-world exposure of the modal-vs-committed gap.
3. **Snapshot-cadence check:** confirm the daily snapshot job actually runs daily
   (gaps change what "run ≥ 2 snapshots" means in wall-clock time for the debounce).
