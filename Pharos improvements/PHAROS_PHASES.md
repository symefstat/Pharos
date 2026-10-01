# Pharos Improvement Phases

Work order for the 40 items in `PHAROS_CONTENT_IMPROVEMENTS.md`. Details and file paths live in `PHAROS_IMPLEMENTATION_PLAN.md`. Do the phases top to bottom — each builds on the last.

---

## Phase A — Relabels (fast, no risk, no data needed)

Pure copy/string changes. Ship credibility immediately.

- [ ] #26 — Rename Capital event study → "Three-day price movement around reported events"; drop "market confirmed/rejected".
- [ ] #32 — Rename initial Radar signal → "untracked attention" (was "emerging technology").
- [ ] #37 — Narrow primary audience to corporate technology-strategy teams; investors secondary.
- [ ] #40 — Precise credibility labels ("gold set" → "provisional evaluation set", "market signal" → "media-attention signal", etc.).
- [ ] #13 — Rename article-count "momentum" → "media attention" everywhere.
- [ ] #21 — Make "N externally verifiable calls open; zero resolved" the headline (mechanism exists).
- [ ] #25 — Expose the existing digest chain in the UI.

## Phase B — Structural gates (the core "stop presenting inference as fact" work)

- [ ] #3 — Separate curated / news-derived / verified-transition stages; suppress anchor-driven "crossed" language.
- [ ] #2 — Add observed-facts + evidence-gaps fields to every signal (interpretation/action/falsifier already exist).
- [ ] #9 — Promote the overclaim lexicon from eval-only to a runtime block.
- [ ] #1 — Editorial approval gate for high-impact recommendations (enter/exit/scale).
- [ ] #19 — Add a "do not publish — nothing meets threshold" outcome.
- [ ] #8 — Recommendation proportionality ladder (monitor → investigate → act → human approval).

## Phase C — Event backbone

Build the persisted event entity first; the rest depend on it.

- [ ] #6 — Deduplicate articles into a first-class underlying-event entity (`events` table + `event_id`).
- [ ] #7 — Genuine source independence (publishers vs articles vs primary vs independent confirmation).
- [ ] #28 — One economic event as the unit of analysis (reconcile with #6).
- [ ] #29 — Company-event roles (primary / counterparty / competitor / supplier / incidental).
- [ ] #14 — Evidence-strength score (separate from model confidence).

## Phase D — Analytical depth

- [ ] #5 — Add event_date / effective_date; reject future publication dates.
- [ ] #16 — Source-type hierarchy + label beside each citation.
- [ ] #11 — Hard MOT-framework evidence gates (downgrade to "early evidence" when unmet).
- [ ] #15 — Require contradictory-evidence field on decisive signals.
- [ ] #20 — Upgrade scenarios (probability / assumptions / trigger / leading indicators / response).
- [ ] #4 — Expose full evidence behind each curated anchor (sources, reviewer, next review).
- [ ] #24 — Align forecast contract (add scope, data source, grading rule; promote threshold/falsifier to columns).
- [ ] #10 — Reject ungradable forecasts at creation time (depends on #24).
- [ ] #23 — Remove duplicate/conflicting forecasts (group by proposition).
- [ ] #22 — Add confidence intervals + "no demonstrated skill" verdict (baselines already exist).

## Phase E — Capital & finance (yfinance parts — NOT blocked)

- [ ] #30a — Free cash flow, margins, net income, enterprise value (all derivable from yfinance).
- [ ] #27a — Benchmark-adjusted returns using market + sector index series (add index tickers to yfinance).
- [ ] #31 — Separate strategic attractiveness from stock attractiveness.
- [ ] #35 — Semantic research-paper matching (reuse existing `vectordb/` embeddings).

## Phase F — Connector-gated (needs S&P / PitchBook authorized first)

> Authorize in claude.ai → Settings → Connectors before starting.

- [ ] #30b — Consensus revisions, forward valuation, analyst estimates.
- [ ] #27b — Beta / beta-adjusted expected return.
- [ ] #36 — Detection lead-time vs external milestones (funding, deployment, coverage).

## Human tracks (parallel — not code-blocking)

Can run alongside any phase; no code dependency.

- [ ] #12 — Manually re-evaluate all 14 tracked technology placements.
- [ ] #17 — Human-verify the gold set (2 blind reviewers, labeling guidance, Cohen's kappa, per-domain performance).
- [ ] #18 — Re-run the Strategist eval; add proportionality / source-independence / contradiction judges.
- [ ] #39 — Content corrections log (new table + page + process).

---

**Reminder:** prompt edits (`Agents_prompt/*.md`) only take effect once re-pasted into Toqan — a manual step. Repo/storage keys stay "lodestar"; only the surface brand is "Pharos".
