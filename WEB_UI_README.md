# Lodestar — new web UI (FastAPI + React)

A professional replacement for the Streamlit app (`Home.py`), built as:

- **`backend/`** — a thin **FastAPI** layer that imports the project's existing
  pure analytics (`analytics.*`, `tickers`, `finance`, `db`) **unchanged** and
  returns their output as JSON. No analytics logic is duplicated or rewritten.
- **`frontend/`** — a **Vite + React + TypeScript + Tailwind v4** single-page app
  that renders that JSON with a real component/design system and **Recharts**
  charts (replacing Altair).

> **Status: all 7 tabs migrated.** Briefing, Ask, MOT Analyst, Capital, Forecasts,
> Explore (Trends / Entities / Compare) and Feeds are all live end-to-end against
> Supabase, with client-side routing (`react-router`). `Home.py` (Streamlit) is now
> redundant and can be retired once you're happy. Each tab follows the same pattern —
> see _The repeatable recipe_ below.

---

## Why this architecture

The hard part of this app — the MOT lens, capital posture, financials, forecasts —
is **pure Python that already returns plain dicts/lists** (e.g.
`analytics.financials.landscape_points()`, `analytics.mot_analyst.capital_board()`).
Streamlit was only ever the *rendering* layer. So the migration is:

```
Supabase ─► analytics.* (unchanged) ─► FastAPI (JSON) ─► React (charts/tables)
```

Crucially, where Streamlit called `*_chart()` helpers to build **Altair objects**,
the API instead returns the **underlying data** (the points / rollups / timelines)
and the React side draws the chart. The numbers are identical; only rendering moved.

---

## Prerequisites

- **Python** venv at `./venv` (the project's existing one) with the project deps.
- **Node** ≥ 20 (installed via Homebrew: `brew install node`).
- A populated **`.env`** at the project root (`SUPABASE_URL`, `SUPABASE_KEY`) —
  the same one `Home.py` uses.

One-time backend dep install (FastAPI + uvicorn on top of the existing venv):

```bash
./venv/bin/python -m pip install -r backend/requirements.txt
```

> Note: in this copied project dir, `./venv/bin/pip` resolves to a *different*
> environment. Always install with **`./venv/bin/python -m pip ...`** so packages
> land in the interpreter that actually runs the app.

Frontend deps are already installed in `frontend/node_modules`. To reinstall:
`cd frontend && npm install`.

---

## Run it

**One command (recommended)** — starts both servers from anywhere:

```bash
./start_web_ui.sh         # then open http://localhost:5173 · Ctrl-C stops both
```

**Or two terminals:**

```bash
# 1. backend (from the project root, so .env + the analytics package resolve)
./venv/bin/python -m uvicorn backend.app.main:app --reload --port 8000
# 2. frontend
cd frontend && npm run dev
```

Open **http://localhost:5173**. The Vite dev server proxies `/api/*` to the
backend, so there are no CORS issues and the browser talks to one origin.

Quick checks:

```bash
curl localhost:8000/api/health      # {"status":"ok","supabase_configured":true}
curl localhost:8000/api/capital     # the full Capital payload
```

For production: `cd frontend && npm run build` emits a static SPA to
`frontend/dist/` that any static host (or FastAPI's `StaticFiles`) can serve
behind the same gateway as the API.

---

## Layout

```
backend/
  requirements.txt          # fastapi + uvicorn (installed on top of venv)
  app/
    main.py                 # FastAPI app, CORS, /api/health, /api/refresh, routers
    data.py                 # Supabase reads (rows/financials/prices/predictions) + TTL cache
    capital.py              # /api/capital      (render_capital)
    forecasts.py            # /api/forecasts    (render_forecasts) + POST /resolve
    explore.py              # /api/explore/*    (trends, entities, entity, technologies)
    mot.py                  # /api/mot          (render_framework)
    briefing.py             # /api/briefing     (calibration + strategist + watchlist + pulse)
    feeds_api.py            # /api/feeds + POST /api/ask

frontend/
  vite.config.ts            # Tailwind plugin + /api proxy → :8000
  src/
    lib/
      api.ts                # typed client + every payload interface (mirror the backend)
      useResource.ts        # generic data hook (+ refresh)
      format.ts theme.ts utils.ts
    components/
      ui.tsx                # Card, Kpi, Badge, SectionHeading, Segmented, Select, …
      layout.tsx            # Sidebar (NavLink) + Topbar + AppLayout
      PageChrome.tsx        # per-page frame: Topbar + loading/error/ready states
      charts.tsx            # Recharts: scatter, S-curve, donut, stacked/area/line/bars, calibration
      Story.tsx             # StoryRow / StoryCard
    pages/                  # Briefing, Ask, Mot, Capital, Forecasts, Explore, Feeds
    App.tsx                 # <Routes> over AppLayout
```

Each endpoint maps **1:1** to its Streamlit `render_*()`. Where Streamlit called the
`*_chart()` (Altair) builders, the API returns the underlying data and React redraws
with Recharts.

---

## Caching & freshness

`backend/app/data.py` holds a small in-process TTL cache mirroring Streamlit's
`@st.cache_data` (rows 5 min, financials/prices 15 min). The **Refresh** button
in the top bar calls `POST /api/refresh`, which clears the cache so the next
request re-reads Supabase.

---

## Migrating the next tab (the repeatable recipe)

Say you want the **🔭 MOT Analyst** tab (`Home.py :: render_framework()`) next:

1. **Find the pure data functions it calls.** In `render_framework()` they're
   things like `analytics.mot_analyst.tech_scurve_*`, `capital_board`, etc. Ignore
   the `*_chart()` (Altair) calls — you'll redraw those in React.
2. **Add a router** `backend/app/mot.py` with `GET /api/mot` that calls those
   data functions (reuse `data.rows()` / `data.financials()` / `data.prices()`)
   and returns a JSON dict. Register it in `main.py` with `app.include_router(...)`.
3. **Add types + a hook** in `frontend/src/lib/` (copy `api.ts`'s Capital types
   and `useCapital.ts`).
4. **Build the page** `frontend/src/pages/Mot.tsx` reusing `components/ui.tsx`
   and adding any new chart to `components/charts.tsx`.
5. **Enable it in the sidebar** (`components/layout.tsx`: set `enabled: true`) and
   add lightweight routing (e.g. `react-router-dom`) to switch pages — currently
   the shell renders Capital directly.

Because the analytics layer is shared and pure, each tab is "expose data → draw
data" with no business-logic rewrite. Most of the remaining effort is chart work.

### Verify a migrated tab renders

```bash
# warm the cache, then render headlessly and eyeball the screenshot
curl -s localhost:5173/api/<endpoint> >/dev/null
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --disable-gpu --force-device-scale-factor=2 \
  --window-size=1280,2400 --virtual-time-budget=10000 \
  --screenshot=/tmp/page.png http://localhost:5173/
```
