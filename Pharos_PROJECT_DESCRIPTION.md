# Lodestar — Project Description (in depth)

> **How to use this file:** the definitive written account of the project —
> for CV generation, portfolio pages, interview prep, or onboarding a
> collaborator. Everything here is grounded in the actual repository and its
> test suite — nothing is invented. Updated 2026-07-11 — covering the Radar
> horizon-scanning system, the Analyst, the technology-dossier platform, and
> the persona-focused product positioning shipped after launch.

---

## One-line pitch

**Lodestar** is a solo-built, production-deployed technology- and
market-intelligence platform that ingests news across 10 domains, classifies
every story through **Management-of-Technology (MOT) theory** with a fleet of
**19 LLM agents**, turns the stream into a daily strategist briefing, dated
technology lifecycles, and a **tamper-evident, self-grading forecast ledger**
— and **detects technologies it doesn't yet track**: a horizon-scanning
**Radar** reads unmatched news plus arXiv research abstracts, corroborates
every candidate through a deterministic evidence gate, and puts its own
detections on the graded record. *The intelligence that grades itself —
including its own radar.*

## 60-second version

Most "market intelligence" tools either summarize news with no theory of *why
a development matters*, or emit black-box scores with no track record.
Lodestar takes the opposite stance on both. Every story is classified against
**named MOT frameworks** (S-curves and dominant design, diffusion and the
chasm, standards battles, appropriability, real options). Articles roll up
into **tracked technologies** with dated lifecycle stage-transitions, turning
a news feed into leading indicators. And the system holds itself accountable
in ways almost no commercial product does: every Strategist signal ships with
an explicit **falsifier** ("what would prove this wrong"), an automated
**falsifier watch** scans incoming news for that disproving evidence and
raises it, forecasts are **locked when made** and graded in the open with
accuracy, **Brier score**, and calibration curves, the **world-graded record
is separated from self-referential consistency checks**, and the whole ledger
is **immutable at the database level** with daily digest anchoring so even
the operator can't silently rewrite history. Beyond the tracked universe, the
**Radar** scans the ~70% of ingested stories that match no tracked technology
— plus recent arXiv abstracts, because papers lead the news by years — has a
Scout agent propose candidates, corroborates each against a deterministic
evidence gate (5+ stories from 3+ publishers over 7+ days, or 3+ papers for
research-stage signals), and locks a **graded 90-day detection call** the
moment a human promotes one. A commissioned **Analyst** writes
ledger-gradable deep-dive reports with database-computed exhibits and an
interrogation mode.

~42k lines of Python (pure-function analytics core, FastAPI service,
pipelines, vector store) + ~15k lines of React/TypeScript, 811 no-network
unit tests across 61 modules, 19 versioned LLM-agent prompts, deployed with a
6-hour automated pipeline.

---

## The problem it solves

Technology and market signals are scattered across domains that incumbents
silo (EVs, chips, AI/energy, biotech, defense, fintech…). Strategy teams,
analysts, and investors need three things existing tools don't combine:
**leading indicators tied to a defensible framework** (not sentiment scores),
**a persistent memory of when a technology's read changed** (ChatGPT has
none), and **accountability** — knowing what the tool has gotten right, wrong,
and what it *cannot* predict. Lodestar's edge deliberately lives in the
record-keeping machinery — falsifiers, dated transitions, a graded ledger —
because a competitor can copy a UI in a quarter but cannot copy a multi-year
graded track record at any price.

## Context

Personal flagship project built alongside an **MSc in Management of
Technology** (Technology Dynamics, High-Tech Marketing, Technology Strategy &
Entrepreneurship, Financial Management, Business Analytics, Emerging &
Breakthrough Technologies). The coursework is the theoretical backbone; the
build is its end-to-end engineering into a shipped product — including a
formal pre-launch review by a six-perspective "council" (security, SRE,
product, code quality, calibration science, target user) whose findings were
worked off as a graded execution plan.

---

## What it does — the product surfaces

1. **Home** — the pitch page, positioned for a **primary persona**
   (corporate strategy & technology-intelligence teams): a decision-promise
   headline, three honest differentiators ("Receipts, not opinions" /
   "Locked now. Graded in public." / "Detected before the watchlist"), a
   **live worked example** ("Radar surfaced Agentic AI before it entered the
   tracked universe…") drawn from the API, a stat band, and door cards with
   live teaser stats. Never shows an error — the front door degrades to clean
   static orientation.
2. **🧭 Briefing** — the daily theory-grounded **Strategist** read: decisive
   signals, each carrying its MOT lens, a recommended action **addressed to a
   named reader class** ("if you are a payments processor…"), impact, horizon,
   value-capture path, an explicit **falsifier**, source chips with
   **outlet-tier disclosure**, and a calibrated confidence (granular 0.55–0.90
   probability, not a label). Signals carry **day-over-day continuity
   markers** (new / carried over / updated — with flips explained). A
   browser-local **mandate panel** (your domains, interests, role) re-ranks
   signals and badges the ones "addressed to you"; a zero-setup **persona
   lens** (All / Operators / Investors) filters signals by the decision owner
   lifted from each rationale's addressee clause at serve time, and every card
   carries its **decision owner and decision window** as chips. Watched
   entities surface their **competitor strategic moves** inline. A "New on
   the radar" strip surfaces the horizon scan's freshest candidates.
3. **💬 Ask** — conversational RAG over the classified feeds *and* an MOT
   theory corpus, with strict citation discipline: `[S#]`/`[T#]` chips bound
   to the actual retrieved set, a phantom-citation guard that neutralizes
   out-of-range references, relevance floors on both news and theory
   retrieval, and instructed abstention over decoration. Its grounding pack
   includes the tracked lifecycle state **and the live radar candidates**, so
   "anything emerging?" is answered from evidence, not model memory. A second
   tab hosts **the Analyst**: commissioned, ledger-gradable deep-dive reports
   (posture + falsifier + resolve-by, database-computed exhibits the agent
   never draws itself, [T#] theory tags banned) with a follow-up
   **interrogation mode** — the published call stands as written.
4. **🔭 MOT Analyst** — the discipline's signature exhibits: the technology
   **S-curve** with dated stage transitions (contested and backward moves
   flagged, not hidden), diffusion/chasm placement, a strategic-move matrix,
   a **standards-battle tracker** (per-battle leader timelines and factor
   citation counts — installed base / complementary goods / openness /
   timing), **measured adoption & performance curves built from 47 real,
   individually-cited datapoints** (IEA, IRENA, BloombergNEF, SEC filings —
   nothing interpolated), an **evidence floor**: technologies with under 15
   supporting articles are honestly listed as "watching — insufficient
   evidence" rather than placed, per-entity MOT scorecards, **exportable
   technology dossiers** (Markdown/PDF one-pagers with transitions,
   falsifiers, coverage, and citations), full **technology dossier pages**
   (`/tech/:key`: anchored placement with a watching progress bar, Radar
   origin panel, agent-written narrative with deterministic fallback, stage
   history, receipts, capital and funding panels), and admin **self-serve
   technology tracking**.
5. **📡 Radar** — horizon scanning for technologies Lodestar does *not* track
   yet. The Scout agent reads the unmatched news corpus plus recent arXiv
   abstracts and proposes named candidates; a **deterministic evidence gate**
   (5+ stories / 3+ publishers / 7+ days, or 3+ research papers) corroborates
   every proposal before it may surface — the transparency strip counts the
   rejections. An **emergence map** plots candidates among the tracked
   registry on market-signal × research-signal axes with the gate thresholds
   drawn in. Directed briefs let an analyst ask the Scout a question over the
   same evidence. Promotion is always a human decision — and it **locks a
   graded 90-day detection call on the public ledger** ("still above the
   evidence floor, or a splash?"), so the radar itself earns a track record.
   Dismissals have memory: a candidate whose evidence at least doubles comes
   back for a fresh decision. Cross-scan identity merging, word-boundary
   evidence matching, and momentum/adjacency analytics keep the candidate set
   honest.
6. **💰 Capital & Economics** — a consultant pyramid: executive synthesis →
   investment-landscape 2×2 (intensity × valuation, bubble = market cap) →
   sector rollup → real-option-vs-commitment deal posture → a
   **market-validation event study** (did the stock actually re-price on a
   deal we called material? — deduped to one reaction per company-event) →
   per-company deep-dive. Free data only, and captioned as such.
7. **🔮 Track record** — the trust artifact. Every forecast locked when made
   and graded in the open, with the headline split by **resolution basis**:
   the **world-graded (external) record** — Strategist calls resolved against
   public events, the only record an outsider can independently verify —
   headlines; the internal consistency record (grading the system's own
   future labels) is demoted and labeled; price-direction calls are
   quarantined as ~unforecastable; until the first external call resolves, a
   prominent banner states the record is **building** ("218 calls locked,
   first resolution due 10 Sep 2026") so internal figures can never read as
   proven skill. **Radar detection calls** are their own graded category.
   Accuracy + Brier + calibration curve + naive-baseline comparisons per
   category. The **falsifier watch** card
   shows candidate disproving evidence found in the news (detection only —
   grading stays human). A private, admin-only **thesis book** lets the
   operator register investment theses whose falsifiers/confirmers are
   scanned by the same engine — kept fully outside the public ledger. The
   whole history downloads as JSON with a recomputable sha256 digest.
8. **🔍 Explore** — Trends (momentum with thin-base honesty, share of voice,
   volume, sentiment), Entity dossiers with side-by-side compare, and the
   classified story stream (per-field provenance, admin refresh).
9. **📐 Methodology** — a public prose page a skeptical analyst can audit:
   how a stage call is made (stated plainly: **labels derive from headline +
   one-sentence summary, not article bodies**), the *measured* accuracy
   numbers including the misses (e.g. maturity 69.2% vs a ≥70% pre-committed
   target), gold-set caveats, the full ledger discipline, and known
   limitations.
10. **⚖️ Legal** — Terms (informational product, never buy/sell advice),
   Privacy (personalization lives in the visitor's browser and never leaves
   it), About + the attribution posture (headline + one-sentence summary +
   link, always crediting the original publisher).

Plus an admin-only **Prosus portfolio lens** and dark mode (light/dark/system,
colorblind-validated palettes).

---

## Architecture

```
Toqan LLM feed agents (1 per domain) ─► home_news/ (extractor → parser → writer)
        │                                            │
        ▼                                            ▼
  Supabase (Postgres + pgvector + Storage) ── one table per feed
        │
        ├─ analytics/lens.py           → MOT-lens classification columns
        ├─ analytics/rollup.py         → never-pruned daily metrics
        ├─ analytics/tech_layer.py     → technology placements + stage history
        ├─ analytics/financials.py     → capital landscape + event study (yfinance)
        ├─ analytics/forecasts.py      → locked, self-scoring forecast ledger
        ├─ analytics/falsifier_watch.py→ disproving-evidence detection
        ├─ analytics/standards.py      → standards-battle timelines
        ├─ analytics/radar.py          → horizon scan: Scout + evidence gate
        ├─ analytics/arxiv_feed.py     → research-signal stream (arXiv Atom)
        ├─ analytics/analyst.py        → commissioned, ledger-gradable reports
        ├─ analytics/delivery.py       → digests, transition & graduation alerts
        └─ analytics/strategist.py ────┐
  vectordb/ (pgvector RAG, news + MOT corpus, relevance floors) ─┤
                                                                 ▼
                                   Toqan Strategist agent → cached briefs
        │                                (fed yesterday's brief for continuity)
        ▼
  Pure analytics (plain dicts/lists) ──► FastAPI ──► React/TypeScript SPA
                                          │  rate limits · auth · TTL cache with
                                          │  stale-serving · health that pings the DB
  GitHub Actions (6h): ingest → classify → analyze → forecast → falsifier watch
                       → alerts → freshness check → daily ledger-digest anchor
  mcp_server.py: FastMCP stdio server — dossiers/briefing/track-record as tools
```

**Pure-function-first** remains the load-bearing principle: all heavy logic is
side-effect-free, tested Python returning plain dicts/lists; IO seams take
injected clients. It paid off twice — first in a Streamlit → FastAPI/React
migration with zero business-logic rewrite, then in a one-day, multi-agent
refactor sprint where ~100 files changed and 686 tests kept everything honest.

**Trust architecture** (the part competitors don't have):

- **DB-level immutability** — a Postgres trigger blocks UPDATE/DELETE on any
  resolved forecast; even the service-role key can't silently rewrite the
  record. Sanctioned maintenance requires an atomic tombstone-first RPC.
- **Daily digest anchoring** — each pipeline run appends the ledger's sha256
  to an append-only table; the public payload ships the chain, so a rewrite
  of past rows is detectable after the fact, not just at download time.
- **Resolution-basis split** — world-graded vs self-referential records are
  never pooled in a headline number.
- **Detection ≠ resolution** — the falsifier watch surfaces evidence but never
  grades; outcomes are written once, by objective resolvers or a human.

---

## Tech stack

| Layer | Technology |
|---|---|
| **Analytics core** | Python 3.11 — pure, unit-tested functions (811 tests across 61 modules, no network) |
| **LLM agents** | 19 Toqan (Claude-powered) agents — 11 feed extractors + MOT Lens classifier + Strategist + Ask analyst + commissioned Analyst + Dossier narrator + Falsifier Judge + Transition Explainer + Radar Scout — each driven by a versioned, eval-tuned system prompt |
| **Prompt discipline** | Output contracts (strict JSON), evidence-before-labels preconditions, calibrated-language rules (no "confirms" on ≤2 datapoints), sparse-pack rules (never pad), worked good/bad examples, day-over-day continuity, granular probability calibration |
| **RAG / embeddings** | OpenAI `text-embedding-3-large`; pgvector similarity via Postgres RPC over both a news index and the MOT theory corpus, with calibrated relevance floors and a phantom-citation guard |
| **Data** | Supabase — Postgres + pgvector + Storage; 43 SQL files (one table per feed + rollup, stage history, ledger, tombstones, digest anchors, falsifier/thesis events, watchlist, tracked technologies, radar candidates & scan log, analyst reports, tech narratives, funding rounds) |
| **Financials** | yfinance (free) — fundamentals + daily prices, 57-company registry across 8 sectors, FX-normalized with dated provenance |
| **API** | FastAPI + uvicorn — thin JSON layer; per-IP sliding-window rate limits, HMAC-signed bearer admin auth (timing-safe, fails closed), TTL cache with a background warmer that serves stale-good data through outages, health checks that actually ping the DB |
| **UI** | Vite · React · TypeScript · Tailwind v4 · react-router — a token-driven design system with machine-validated (colorblind-safe) light & dark palettes, hand-built SVG charts with table twins and keyboard access (no chart library) |
| **Automation** | GitHub Actions — the full pipeline every 6h with concurrency guards, idempotent upserts, per-stage degradation, freshness monitoring (feeds *and* the Strategist brief), webhook alerts |
| **Quality** | pytest · a gold-label eval harness with pre-committed accuracy targets, drift checks, and A/B prompt tooling · pre-commit secret scanning (gitleaks) |

---

## Quantified scope

- **~42,000 lines of Python**; **~15,400 lines of TypeScript/React**.
- **811 unit tests across 61 modules** — pure, no-network, ~10s for the suite.
- **19 LLM agents / 19 versioned prompts** behind a single feed registry
  (adding a domain = one entry + one prompt + one key).
- **10 news domains + an arXiv research stream · 43 SQL files · 14 SPA pages
  · 57-company financial registry across 8 sectors.**
- **47 measured datapoints** across 4 real adoption/performance series, each
  individually cited in an audit document.
- One 2,800-line Streamlit monolith retired in favor of the modular
  pure-analytics + FastAPI + React architecture; the dead chart library was
  removed entirely (flagship page bundle: 380 kB → 38 kB).

---

## Hard problems solved (engineering)

- **Accountability as architecture, not copy.** Locked-when-made forecasts,
  objective resolvers with zero look-ahead (event windows bounded by each
  claim's own resolve-by date), paraphrase-aware dedupe so reworded claims
  can't double-count, DB-level immutability with tombstoned maintenance, and
  daily digest anchoring — honesty enforced by triggers and hashes, not
  promises.
- **The falsifier loop.** Every signal states what would disprove it; a
  detection engine (vector similarity + keyword corroboration, idempotent
  event storage) scans each pipeline run's news for that evidence and raises
  it — "we told you what would prove us wrong, and we told you when it
  happened." Reused wholesale for private investment-thesis monitoring.
- **A web tier that survives its dependencies.** LLM polling budgets split by
  context (25 min for pipelines, 3 min for web requests) so one slow agent
  can't exhaust the thread pool; stale-serving caches that refuse to
  overwrite good data with outage-empty results; health checks that report
  degradation without triggering restart loops; per-IP rate limiting on every
  expensive or abusable route.
- **Pure-function-first at scale.** The same analytics core survived a UI
  rewrite and a 100-file multi-agent refactor day unchanged in behavior — the
  test suite (which grew 533 → 686 that day) is the proof.
- **Chart honesty as a discipline.** Hand-built SVG exhibits with table
  twins, machine-validated palettes (protanopia ΔE checks), no truncated
  axes, thin-data quarantines, outlier pinning with true values, and the
  removal of every seeded/"illustrative" series in favor of cited real data.
- **Eval-driven prompt engineering.** A gold-label harness with
  pre-committed targets caught real regressions (a "v4" prompt rewrite
  measured worse and was reverted); prompts carry output contracts, worked
  counter-examples, and calibrated-language rules that ban overclaiming
  verbs on thin evidence.

## Hard problems solved (domain / analytical)

- **Operationalized named MOT frameworks into computable classifications** —
  S-curves & dominant design, diffusion & the chasm, standards battles
  (leader + factor evidence over time), entry timing, appropriability &
  complementary assets, platforms, market failure & regulation, real options
  vs commitment — applied to every story, with precondition rules so a label
  can't be used without its evidence.
- **Technology as the unit of analysis** — dated, persistent stage-transition
  history that a chat model structurally cannot provide, gated by an
  evidence floor so lifecycle claims never rest on a handful of headlines.
- **Epistemic rigor as a product feature** — falsifiability on every claim,
  calibration over confidence, world-graded vs self-referential records kept
  separate, source-tier disclosure, and honest statements (in-product and on
  a public Methodology page) of the measured error rates and of what the
  system cannot predict.
- **Cross-domain convergence detection** across 10 domains incumbents silo,
  with corroboration cues ("also in") feeding confidence calibration.
- **A dual-signal emergence model** — market signal (news mentions across
  independent publishers) × research signal (arXiv abstracts, which lead the
  news by years) — with separate gates per signal, so a research-stage
  candidate can surface on papers alone, honestly flagged as such.

---

## What this demonstrates (skills to mine for CV bullets)

- **End-to-end product ownership, solo** — data ingestion, schema design,
  LLM-agent orchestration, analytics, API, security hardening, a polished
  React front end, CI/CD, and a production deploy.
- **Applied AI / LLM systems** — multi-agent orchestration, eval harnesses
  with gold labels and pre-committed targets, RAG with citation guarantees,
  prompt engineering as a versioned, tested artifact.
- **Software architecture** — pure-function-first design, graceful
  degradation, idempotency, provenance, and two major refactors absorbed
  with zero behavioral drift.
- **Security & reliability engineering** — auth, rate limiting, input
  validation, DB-level integrity constraints, tamper-evidence, health/
  observability, failure-mode design.
- **Domain depth** — translating MOT theory and corporate finance into
  working analytical machinery, not decorative labels.
- **Product judgment** — a six-perspective pre-launch review run as a graded
  execution plan; honesty and calibration built as the core differentiator.

---

## Suggested CV bullets (adapt freely)

**Concise (resume line items):**

- Designed, built, and shipped **Lodestar**, a solo full-stack
  technology-intelligence platform (~57k LOC: Python analytics core, FastAPI,
  React/TypeScript SPA; 811 tests) that classifies cross-domain news through
  Management-of-Technology theory using **19 orchestrated LLM agents** and
  pgvector RAG, deployed with a 6-hour automated pipeline.
- Engineered a **tamper-evident, self-grading forecast ledger** — predictions
  locked when made, graded with accuracy/Brier/calibration, world-graded
  record separated from self-referential checks, **database-trigger
  immutability and daily digest anchoring** so history rewrites are
  detectable.
- Built a **falsifier-watch engine**: every AI-generated claim ships with its
  disproving condition, and a vector+keyword detector scans incoming news and
  alerts when that evidence appears — accountability no comparable product
  offers.
- Ran **eval-driven prompt engineering** with gold labels and pre-committed
  accuracy targets; caught and reverted a regressing prompt rewrite; enforced
  calibrated-language and evidence-precondition rules in production prompts.
- Built a **self-grading horizon-scanning system (Radar)**: an LLM Scout
  proposes emerging technologies from unmatched news + arXiv abstracts, a
  deterministic evidence gate corroborates every candidate (rejections
  counted publicly), and human promotion locks an auto-resolving 90-day
  detection call — giving the scanner itself a graded track record.
- Modeled **technology (not articles) as the unit of analysis**: dated
  S-curve lifecycle transitions with evidence floors, measured
  adoption/performance curves from 47 individually-cited public datapoints,
  and exportable per-technology dossiers.

**One-liner (project header):**

> **Lodestar** — production-deployed, theory-grounded technology-intelligence
> platform (Python · FastAPI · React/TS · Supabase/pgvector · 19 LLM agents ·
> RAG): cross-domain news + arXiv research → MOT classification → dated
> technology lifecycles, a horizon-scanning Radar with graded detections, and
> a tamper-evident, self-grading forecast ledger.

---

## Honest constraints (include for a credible, senior tone)

News + free financials only (no paid deal data or order books). Lens labels
derive from headline + one-sentence summary, not article bodies — and the
measured accuracy of exactly that setup is published on the Methodology page
(maturity 69.2% vs a ≥70% pre-committed target at last eval, gold set
provisional pending human sign-off). Price direction is treated as
~unforecastable and quarantined. The world-graded track record is thin until
calls resolve over months — the ledger currently proves the *discipline*;
time will prove (or disprove) the *skill* — the first world-graded call
resolves 10 September 2026, and the product says so in a banner rather than
letting internal figures imply otherwise. Radar's research signal reads arXiv
only, so fields that publish elsewhere (clinical journals, defense) register
low on that axis by construction. Radar detections are likewise unproven
until their 90-day grades land. All of this is stated in-product: the honesty
posture is the design, not an apology.
