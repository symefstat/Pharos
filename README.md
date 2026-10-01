<div align="center">

# 🧭 Lodestar

### Theory-grounded, cross-domain technology & market intelligence

*Ingests news across 10 domains → classifies every item through **Management-of-Technology theory** with a fleet of LLM agents → turns it into analyst-grade briefings, an **accountable (self-scoring) forecast ledger**, and a consultant-style capital view.*

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-SPA-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-Postgres%20%2B%20pgvector-3FCF8E?logo=supabase&logoColor=white)
![LLM Agents](https://img.shields.io/badge/LLM%20agents-13-8A2BE2)
![RAG](https://img.shields.io/badge/RAG-pgvector%20%2B%20OpenAI-412991?logo=openai&logoColor=white)

</div>

---

## What is this?

Most "market intelligence" tools do one of two things: summarize news without a theory of *why a development matters*, or emit black-box scores with no track record. **Lodestar takes a different stance:**

- **Theory first.** Every story is classified against *named* Management-of-Technology (MOT) frameworks — S-curves, diffusion / crossing the chasm, standards battles, real options — not vibes or sentiment.
- **Technology is the unit of analysis.** Articles roll up into *tracked technologies* with **dated lifecycle stage-transitions**, turning a news stream into leading indicators.
- **It holds itself accountable.** Forecasts are *locked when made* and scored objectively against the system's own data with accuracy, **Brier score**, and **calibration curves** — and it's explicit about what it *can't* predict.

The result is a single product that produces a daily strategist briefing, a consultant-grade capital view, and a graded forecast record across **10 domains** — EV/Mobility, AI & Energy, Disruptive Tech, Chips, Geopolitics & Trade, Climate & Energy, Biotech & Health, Software & Cyber, Fintech & Digital Assets, and Defense & Space.

> Built solo as the applied component of an **MSc in Management of Technology** — the coursework is the theoretical backbone; this is the engineering of it into a working product.

---

## ✨ Features — the 7 surfaces

| | Surface | What it does |
|---|---|---|
| 🧭 | **Briefing** | A theory-grounded **Strategist** read: a deck of decisive *signals*, each with its MOT lens, recommended action, business impact, horizon, value-capture path, an explicit **falsifier**, sources, and confidence — plus cross-domain convergence, base/bull/bear scenarios, and a watchlist. Exports to Markdown/PDF. |
| 💬 | **Ask** | Conversational **RAG Q&A** over the classified feeds *and* an MOT theory corpus, answering with grounded citations. |
| 🔭 | **MOT Analyst** | The discipline's signature exhibits: a **technology S-curve / lifecycle map** with dated stage transitions, diffusion/chasm positioning, a strategic-move matrix, a cross-domain co-mention chord, and a per-entity **MOT scorecard**. |
| 💰 | **Capital & Economics** | A consultant "pyramid": executive synthesis + KPIs → an **investment-landscape 2×2** (investment intensity × valuation, bubble = market cap) → sector rollup → real-option-vs-commitment deal posture → a **market-validation event study** (did the stock actually re-price?) → per-company deep-dive. |
| 🔮 | **Forecasts** | An **accountable forecast ledger**: falsifiable, locked-when-made predictions, resolved objectively against the system's own data, scored with accuracy + **Brier** + a **calibration curve**, broken out **per category** so noise can't flatter the record. |
| 🔍 | **Explore** | Trends (momentum, volume, sentiment), Entities (co-mentions, cross-feed tracking), and Compare. |
| 📰 | **Feeds** | The raw, MOT-classified feeds with per-field provenance. |

**The MOT lens, applied to *every* story:** maturity / S-curve stage · adoption / diffusion stage (Rogers · Moore chasm) · strategic move (standards battle, entry timing, appropriability, platform, disruption) · business impact (stock materiality) · scope.

---

## 🏗 Architecture

```
Toqan LLM feed agents (1 per domain) ─► home_news/ (extractor → parser → writer)
        │                                            │
        ▼                                            ▼
  Supabase (Postgres + pgvector + Storage) ──  one table per feed
        │
        ├─ analytics/lens.py        → MOT-lens classification columns
        ├─ analytics/rollup.py      → never-pruned daily metrics
        ├─ analytics/mot_analyst.py → technology S-curve + stage transitions
        ├─ analytics/financials.py  → capital landscape (yfinance, free)
        ├─ analytics/forecasts.py   → falsifiable, self-scoring forecast ledger
        └─ analytics/strategist.py ─┐
  vectordb/ (pgvector RAG over MOT corpus) ─┤
                                            ▼
                          Toqan Strategist agent → cached briefs
        │
        ▼
  Pure analytics return plain dicts/lists ──► FastAPI (JSON API) ──► React SPA
                                          └─► Streamlit (original UI)
```

**The core design principle is *pure-function-first*:** all heavy logic lives in tested, side-effect-free Python functions that return plain dicts/lists, and the UI is a *rendering* layer only. That decoupling is what let the UI migrate from **Streamlit** to a **FastAPI + React/TypeScript** stack with **zero rewrite of business logic** — the same analytics were simply re-exposed as JSON and the charts redrawn in Recharts. The numbers are identical; only rendering moved.

---

## 🧰 Tech stack

| Layer | Technology |
|---|---|
| **Analytics core** | Python 3.11 · pandas — pure, unit-tested functions |
| **LLM agents** | 13 Toqan (Claude-powered) agents — 10 feed extractors + an **MOT Lens** classifier + a **Strategist** + an **Ask** analyst, each driven by a versioned system prompt |
| **RAG / embeddings** | OpenAI `text-embedding-3-large` over an MOT theory corpus; **pgvector** similarity search via a Postgres RPC |
| **Data** | **Supabase** — Postgres + pgvector + Storage; one table per feed plus analytics tables (rollup, brief cache, stage history, watchlist, forecast ledger, financials, prices) |
| **Financials** | `yfinance` (free, no paid data) — fundamentals + daily prices for a 57-company registry across 8 sectors, FX-normalized to USD |
| **UI (new)** | Vite · **React** · **TypeScript** · **Tailwind v4** · **Recharts** · react-router |
| **UI (original)** | Streamlit · Altair |
| **API** | **FastAPI** + uvicorn — a thin JSON layer over the unchanged analytics package, with in-process TTL caching |
| **Automation** | **GitHub Actions** — full ingest → classify → analyze → forecast pipeline on a 6-hour schedule |
| **Quality** | pytest (pure, no-network unit tests) · an **eval harness** with gold labels + scoring · `pre-commit` secret-scanning |

---

## 📐 The MOT theory backbone

Lodestar operationalizes named frameworks into computable classifications — not decorative labels:

- **S-curves & dominant design** — Schilling; Anderson–Tushman
- **Diffusion & crossing the chasm** — Rogers; Moore
- **Standards battles, timing, appropriability, complementary assets, platforms** — van de Kaa; Teece; Gawer
- **Market structure, failure & regulation**
- **Finance: investment appraisal & real options** — Berk–DeMarzo
- **Epistemic rigor** — falsifiability (every signal carries a falsifier) and calibration over confidence

---

## 🚀 Quickstart

> Full step-by-step setup (SQL migrations, agent creation, env keys) is in the collapsible section below.

```bash
# 1. Python env
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in SUPABASE_URL + SUPABASE_KEY (required)

# 2. Run the original Streamlit app
streamlit run Home.py

# — or — the new FastAPI + React web UI:
./start_web_ui.sh             # then open http://localhost:5173
```

The refresh pipeline (also runnable from the app's **Refresh all** button, or on a schedule via GitHub Actions):

```bash
python home_news_run.py   # fetch all feeds
python lens_run.py        # MOT-lens classify new rows (idempotent)
python analytics_run.py   # rebuild rollup + regenerate the Strategist read
python financials_run.py  # enrich tracked tickers (free) → Capital tab
python forecast_run.py    # generate + resolve forecasts → Forecasts tab
```

<details>
<summary><b>Full setup — SQL migrations, Toqan agents, environment variables</b></summary>

### Prerequisites
- Python 3.11
- A **Supabase** project (URL + service-role key)
- An **OpenAI** API key (MOT-corpus embeddings + Strategist theory retrieval)
- **Toqan** agents (one per feed + MOT Lens + Strategist + Ask), each with an API key

### 1. Apply the SQL
Run the files in `SQL Tables/` in order in the Supabase SQL editor — one table per feed, then `mot_lens_columns.sql`, the never-pruned `feed_daily_metrics` rollup, `strategist_briefs`, `technology_stage_history`, `watchlist`, `mot_knowledge_base` (RAG), `company_financials`, `stock_prices`, and `predictions` (the forecast ledger). The required-for-core ones are marked **★** in the file list.

### 2. Create the Toqan agents
Create each agent on the Toqan platform, paste the matching file from `Agents_prompt/` as its system prompt, then copy each agent's API key into `.env`. The feed registry (key → table → prompt → env key) is the single source of truth in [`feeds.py`](feeds.py) — adding a feed is one `Feed(...)` entry + a prompt + a key.

### 3. `.env`
Copy `.env.example` → `.env` and fill it in. Only `SUPABASE_URL` and `SUPABASE_KEY` are hard-required; a feed with no key shows an empty tab, and the Strategist degrades gracefully without `OPENAI_API_KEY` (reasoning from doctrine, skipping theory citations). **Never commit `.env`** — it's gitignored and a `pre-commit` secret scan guards against leaks (`pip install pre-commit && pre-commit install`).

### 4. Ingest the MOT corpus (one-time, for RAG)
```bash
python ingest_mot.py          # needs OPENAI_API_KEY + the corpus folder; --reset for a clean reload
```

</details>

---

## 🗂 Project structure

```
analytics/        Pure analytics core — lens, rollup, mot_analyst, financials,
                  forecasts, strategist, trends, entities, events, weights …
backend/          FastAPI service — one router per surface over the analytics core
frontend/         Vite + React + TypeScript SPA (typed API client, hooks, Recharts)
home_news/        Feed ingestion (extractor → parser → writer)
vectordb/         MOT-corpus RAG (chunker, embedder, pgvector store)
finance/          yfinance client (financials + prices)
eval/             Gold-label eval harness + scoring
Agents_prompt/    Versioned system prompts for all 13 Toqan agents
SQL Tables/        Supabase schema migrations
tests/            Pure, no-network unit tests
Home.py           Original Streamlit app (7 tabs)
*_run.py          Pipeline entrypoints (home_news, lens, analytics, financials, forecast, alerts)
```

---

## 🧪 Testing & quality

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Pure, no-network unit tests cover the parsing/normalization/reducer logic, the MOT analyst, financials, trends, the forecast resolver, and the Strategist's pure logic. An **eval harness** (`eval/`) scores MOT-lens output against gold labels. Edits are compile-checked with `python -m py_compile`, and a `pre-commit` hook scans for secrets.

---

## 🌐 The web UI (FastAPI + React)

All 7 tabs are migrated end-to-end to a React/TypeScript SPA backed by FastAPI — see [`WEB_UI_README.md`](WEB_UI_README.md) for the architecture and the "repeatable recipe" used to migrate each tab. The Vite dev server proxies `/api/*` to the backend (no CORS), and `npm run build` emits a static SPA that any host (or FastAPI's `StaticFiles`) can serve behind the same gateway as the API.

---

## ⚠️ Honest constraints

News + free financials only (no paid deal data or order books); price-direction is treated as ~unforecastable and **quarantined**; the forecast track record is thin until calls resolve over months; financial multiples are deliberately crude (P/S, FX-approximate). These are stated explicitly in-product — the honesty/calibration posture is a deliberate design choice, not an omission.

---

<div align="center">
<sub>Solo project · ~23k LOC Python · ~5k LOC TypeScript · 13 LLM agents · 10 domains · MSc Management of Technology</sub>
</div>
# LODESTAR
