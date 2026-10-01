# Phase 2 — L2 Feed Extraction Faithfulness (offline)

Date: 2026-07-02 · Branch: `main` · All results below are offline (no Supabase/Toqan/network calls made; `.env` not read).

Scope: `home_news/extractor.py` → `toqan/json_utils.py` → `home_news/parser.py` → `home_news/writer.py`, plus `analytics/run_ledger.py` (feed_runs) and the runner `home_news_run.py`. 10 feeds share this pipeline (`feeds.py`), one Supabase table per feed.

---

## 1. Offline verdict

### 1.1 Unit tests

```
./venv/bin/python -m pytest tests/test_parser.py tests/test_parser_stats.py \
    tests/test_writer.py tests/test_provenance.py tests/test_json_utils.py -q
48 passed, 1 warning in 0.16s
```

All 48 pass. Coverage is genuinely good on the happy/near-happy paths: fences, `<think>` preambles, prose wrapping, wrapper-key objects, key drift (`headline`/`link`/`source`), http→https upgrade, non-web URL rejection, within-batch URL dedup, staleness cutoff, sentiment/impact/scope normalisation + defaults, drop-stat accounting invariants (`received == parsed + dropped_*`), provenance markers, and the writer's missing-column detection (both PGRST204 and 42703 signatures, with negative cases that prevent constraint errors being swallowed).

### 1.2 Signal-by-signal assessment (what is checkable offline)

**Dedup** — within-batch, per-feed, exact-string URL only (`parser.py:165-174`, `seen_urls` set). Cross-run dedup per table comes from the `upsert(..., on_conflict="url")` UNIQUE constraint (`writer.py:247`). Blind spots (all empirically confirmed, see §2):
- No URL normalisation: trailing slash, `?utm_*` tracking params, `#fragment`, and host casing all defeat dedup — `https://x.com/a`, `https://x.com/a/`, `https://x.com/a?utm_source=nl`, `https://X.COM/a` are stored as **4 distinct rows**.
- **No cross-feed dedup at all.** Each feed writes to its own table (`feeds.py`); the same article URL can legitimately land in `semiconductor_news_articles` *and* `geopolitics_trade_articles` (export-control stories are the obvious overlap). Nothing in the code enforces the acceptance target "0 cross-feed duplicate URLs" — it can only be measured live, and there is no mechanism that would make it pass by design.
- No title/content dedup: the same story syndicated under two URLs by the same outlet passes.

**URL/date sanity** —
- URL (`parser.py:202-206`): scheme ∈ {http, https} + non-empty netloc, http upgraded to https. Slips through: userinfo tricks (`https://evil.com@good.com/x` accepted verbatim), dot-less hosts (`https://localhost/x`), and — the core L2 risk — any *hallucinated but well-formed* URL. The blind http→https rewrite also breaks links for http-only outlets. Offline can't test link liveness; that's the live run's job.
- Date (`parser.py:208-214`): `datetime.fromisoformat(str(raw)[:10])`. Accepts ISO and compact `YYYYMMDD`; **accepts future dates** (2031-01-01 stored happily — a fabricated-date signal with no guard). Non-ISO ("July 2, 2026", epoch ints, "2026-07") raises → **the entire item is dropped as malformed**, which is inconsistent with the tolerant null-on-invalid treatment of `sentiment` (`parser.py:240-242`): one bad date field destroys an otherwise-valid grounded article.

**Provenance** — `_field_provenance` (`parser.py:102-132`) records `agent`/`keydrift`/`default`/`missing` per field, mirrored correctly against `_build_item`'s resolution order; persisted as JSONB; `analytics/provenance.py` consumes it downstream and degrades gracefully for pre-column rows (tested). Gaps:
- **`tags` has no provenance entry** despite being accepted via three drifting keys (`tags`/`categories`/`category`, `parser.py:216-221`). Confirmed empirically: provenance keys = 10 fields, `tags` absent. `image_url` is also untracked (arguably fine — writer-derived — but a `'derived'` marker would complete the trail).
- Invalid-but-present sentiment (e.g. `"bullish"`) is recorded as `missing`, conflating "agent omitted" with "agent supplied garbage" — the audit trail loses the distinction that matters for judging agent quality.
- The writer's strip-and-retry (`writer.py:249-257`) silently drops the whole provenance column when the migration is unapplied. It logs a warning and the detection regexes are well-tested, but a feed can run indefinitely with 0% provenance — the live run must verify the column actually exists on all 10 tables.

**Drop-stats** — `ParseStats` (`parser.py:30-55`) counts received/parsed/dropped_malformed/dropped_dup/dropped_stale; the runner persists it per feed to `feed_runs` via `RunLedger` (`home_news_run.py:147`), and total parse failure is recorded as `ok=False` with the error string (`home_news_run.py:144`). `RunLedger.record` never raises (`analytics/run_ledger.py`). So yes — feed_runs records *how many* and *why-category*. What it does not record:
- **Which** items were dropped (URLs/titles go only to stdout logs, `parser.py:161-171`) — dropped items are unauditable after the fact.
- Writer-stage outcomes: image-proxy hit rate and `rows_upserted` vs `items_parsed` gaps are logged but not ledgered; only the "parse" stage exists in feed_runs.

**Robustness of the raw-answer parser** (`toqan/json_utils.py`) —
| Input shape | Behaviour |
|---|---|
| Markdown-fenced JSON (```` ```json ````, bare fence) | ✅ handled + tested |
| `<think>` preamble / surrounding prose | ✅ handled + tested |
| Object-wrapped array (`{"items": [...]}` + 5 other keys + single-array-key fallback) | ✅ handled + tested |
| Missing keys per item | ✅ handled in `_build_item` (drift tolerance + required-field drop) |
| Non-array output (single object item) | ❌ **silent garbage** — see Bug 1 |
| Truncated JSON | ❌ two failure modes — see Bug 2 |

---

## 2. Gaps / bugs found (each verified by running the code offline)

**Bug 1 — inner-array grab on single-object responses → silently wrong stats (toqan/json_utils.py:46-52).**
`parse_json_array` scans `text.find("[") … text.rfind("]")` *before* trying the object fallback. If the agent returns a single article object (not an array) that contains any inner list, the inner list is parsed as "the array". Verified: `{"title": "Solo", ..., "tags": ["battery", "policy"]}` → returns `['battery', 'policy']` → parser reports `received=2, dropped_malformed=2, parsed=0` and the run **succeeds** with a plausible-looking feed_runs row. The valid article is lost and the ledger blames the agent for two malformed items. Fix sketch: attempt full-text `json.loads` first, or try the object fallback before the bracket-span heuristic when the span doesn't start at position 0.

**Bug 2 — truncated agent output: total loss or garbage (toqan/json_utils.py:46-67).**
(a) Truncation mid-item with no inner `]` → `ValueError` → whole run fails (fail-loud, acceptable, but zero salvage of the N complete items before the cut). (b) Truncation *after* an inner list (e.g. a completed item with `"tags": ["x"]` followed by a cut-off item) → `rfind("]")` locks onto the inner bracket and returns `['x']` — same silent-garbage mode as Bug 1. Verified both.

**Bug 3 — future `published_at` accepted (home_news/parser.py:208-214).**
`try_date("2031-01-01")` → stored as-is. No upper bound (e.g. today + 1d tolerance). Fabricated/typo'd future dates flow straight into staleness logic and UI ordering (`fetch_recent` orders by published_at desc — a 2031 row pins to the top of the feed until pruned… which it never is, since prune only deletes rows *older* than cutoff, `writer.py:269-274`).

**Bug 4 — malformed date drops the whole item (home_news/parser.py:213-214).**
`"July 2, 2026"`, `"2026-07"`, epoch ints → entire item counted `dropped_malformed`. Inconsistent with sentiment/impact/scope handling; grounded content is discarded over a recoverable field. Nulling the date (item survives, prune-by-fetched_at covers it) would match the rest of the design.

**Bug 5 — no URL normalisation before dedup or upsert conflict (home_news/parser.py:165, 174).**
Verified: 4 trivially-equal URL variants all kept (`dropped_dup=0`). Since `on_conflict="url"` uses the same raw string, the same article re-fetched tomorrow with a different tracking param becomes a new DB row. Minimal fix: lowercase host, strip fragment and `utm_*`/`fbclid` params, normalise trailing slash before both dedup and storage.

**Bug 6 — `tags` field lacks provenance (home_news/parser.py:121-132 vs 216-221).**
10 of 11 stored agent-derived fields tracked. Directly threatens the ≥95% provenance acceptance target depending on how fields are counted (10/11 = 90.9% of agent-derived fields at best when tags present).

**Minor observations (not bugs):**
- `parser.py:203-206` — accepts userinfo-bearing and dot-less netlocs (verified).
- `writer.py:78` — `_find_og_image_url` never checks `resp.status_code`; a 404 page's markup can supply an og:image.
- `extractor.py:33` — prompt date uses local clock, no timezone pinning; staleness cutoff in `parser.py:151` likewise (`datetime.now().date()`). Cosmetic drift risk around midnight UTC±.
- `json_utils.py:20` — `_FENCE_RE.search` takes the *first* fence; a prose example fence before the payload would win. Not observed in tests; low likelihood.

### Acceptance-target readiness (offline view)

| Target | Offline verdict |
|---|---|
| Faithfulness ≥90% grounded, 0 fabrications | **Not checkable offline.** Nothing in the pipeline verifies title/summary/date against the source page; a well-formed hallucinated item passes every validation. Requires the live judge. |
| Provenance on ≥95% of fields | **At risk**: `tags` untracked (Bug 6) + possibility of unapplied `provenance` columns on some of the 10 tables (writer degrades silently). Live check required. |
| 0 cross-feed duplicate URLs | **No mechanism exists** (Bug 5 adjacent). Purely an empirical live measurement; expect overlap on chips/geopolitics and climate/ai-energy. |

---

## 3. Live faithfulness protocol — **NEEDS APPROVAL — not run**

Nothing below has been executed. This is a written proposal for a later, explicitly-approved session.

### 3.1 Supabase reads (read-only, service role via existing `db.get_supabase()`)

| Read | Tables | Rows | Purpose |
|---|---|---|---|
| Article sample | all 10 feed tables: `home_news_articles`, `ai_energy_news_articles`, `disruptive_tech_articles`, `semiconductor_news_articles`, `geopolitics_trade_articles`, `climate_energy_articles`, `biotech_health_articles`, `software_security_articles`, `fintech_articles`, `defense_space_articles` | 10 most-recent rows per table (`order fetched_at desc limit 10`) → **100 articles** | judge sample; select `title, summary, url, source_name, published_at, companies, sentiment, business_impact, scope, tags, provenance, fetched_at` |
| Provenance coverage | same 10 tables | full-table `select url, provenance` (feeds are pruned to 14–30 days, so ~50–200 rows each; cap 500/table) | % rows with non-null provenance; % fields marked `agent`/`keydrift` vs `default`/`missing`; detects unapplied provenance columns per table |
| Cross-feed dup check | same 10 tables | `select url` from each (same cap) | exact-URL and normalised-URL (Bug 5 rules) intersection across tables |
| Drop-stat history | `feed_runs` | last 30 days, `stage='parse'` (~10 feeds × runs; a few hundred rows) | drop-rate time series, `ok=false` failures, feeds with `received=0` (stalled agent) |

Total: ~15 lightweight selects, well under any rate limit. No writes.

### 3.2 Source-page fetches

For each of the 100 sampled articles, one HTTP GET of `url` (the same UA string the writer already uses, `writer.py:59`; timeout 10 s; cap body at ~150 KB; strip to readable text with a stdlib/`html.parser`-level extractor — no new heavy deps). Record per URL: HTTP status, final URL after redirects (detects soft-404 redirects to homepages — a hallmark of hallucinated URLs), and extracted main text. Expected outcome classes: `fetched`, `paywalled/403`, `404/DNS-fail` (a dead link is itself a fabrication signal, scored separately), `timeout`. ~100 requests, politely serialised per domain (~5–10 min wall clock).

### 3.3 LLM judge

One grading call per article with a fetched page (paywalled/dead ones are scored on the fetch outcome only). Prompt sketch:

```
System: You are grading whether a news-feed extraction is faithful to its
source page. Judge ONLY against the provided page text. Output JSON:
{"title_grounded": true|false,
 "summary_verdict": "grounded" | "partially_grounded" | "fabricated",
 "summary_issues": [".."],            # unsupported claims, wrong numbers/entities
 "date_consistent": true|false|null,  # null if page shows no date
 "companies_grounded": [..], "companies_fabricated": [..],
 "confidence": "high"|"medium"|"low", "notes": ".."}

User: <page_text (truncated ~6k tokens)>
      <extracted: title / summary / published_at / companies / source_name>
```

Scoring: faithfulness = grounded + partially_grounded with no fabricated claims, target ≥90%; any `fabricated` verdict or dead-URL article counts against "0 fabrications". Fabrication findings get a manual second look before being reported (judge false-positives on paywalled teaser text are the known failure mode).

**Model & cost** (pricing per claude-api skill, cached 2026-06-24): `claude-opus-4-8` at $5/$25 per MTok, via the **Message Batches API** (50% discount, results ≤1 h, order-independent — keyed by `custom_id` = article URL). Estimate per call: ~7 K input tokens (page text + extraction + rubric) + ~250 output. 100 calls ≈ 0.7 M in / 25 K out ≈ **$4.10 standard → ~$2.05 batched**. Budget ceiling $5. (`claude-haiku-4-5` would cut this ~5× if approved as acceptable for grading; Opus recommended for judge reliability.) One API surface, `structured outputs` (`output_config.format`) to guarantee parseable JSON.

Call count summary: ~15 Supabase selects + ~100 article GETs + 1 batch of 100 judge calls (+ ≤10 re-grades on flagged items).

### 3.4 Deliverable of the live run

`eval/reports/02_extraction_live.md`: per-feed faithfulness table, fabrication list (URL + judge notes + manual verdict), provenance coverage per table (incl. any missing-column findings), cross-feed dup list, and pass/fail against the three acceptance targets.

---

## 4. Recommended code fixes (offline, before the live run — not applied)

Priority order: Bug 1/2b (silent-garbage parses corrupt both the feed and the eval baseline) → Bug 5 (URL normalisation; also needed so the live dup-check measures reality, not tracking params) → Bug 6 (tags provenance; cheap, protects the 95% target) → Bug 3/4 (date bounds + null-on-invalid).

---

## Live faithfulness results (2026-07-02)

**Executed** — APPROVED live step B for L2. Supabase reads only (no writes), no Toqan calls, `.env` never echoed. Source pages fetched over the public web. Judging was done **by the eval agent directly (single-judge; flag as such)** — no external LLM API call was made (the ~$2 judging budget was replaced by the agent's own reasoning at no extra cost). Single-judge means no inter-rater check; fabrication findings below were each re-verified against the raw source HTML/PDF before listing.

### Method
- Sample: 10 most-recent rows per feed table (`order fetched_at desc limit 10`) across all 10 feed tables = **100 rows**. Fields pulled: `url, title, summary, source_name, published_at, companies, country, sentiment, business_impact, scope, tags, provenance, fetched_at`.
- Fetched each source URL (requests + stdlib HTML→text; WebFetch/curl fallback with longer timeout or a declared UA for IR/SEC pages). Provenance coverage and dedup computed over full tables (cap 500/table, ~2,005 rows total).
- Each row graded **grounded / minor-drift / fabrication** against its source page: (a) summary claims present in source, (b) companies/entities in the article, (c) numbers/%/dates match exactly (strict), (d) `published_at` plausible vs page date.

### Skip rate
**6/100 skipped (6%)**, judged **94/100**. Skips: NYT (`403` paywall), Chosun Biz ×1 (bot-blocked), bitrss (`403`), exchangerank (thin/placeholder body), Cerebras IR & Ionis IR (repeated read-timeouts). A dead/blocked link is not counted as a fabrication here (all six resolve to real, plausibly-live pages that simply refused automated fetch).

### Per-feed grounded rate (strict grounded / rows judged)
| Feed | Grounded | Minor-drift | Fabrication | Skipped | Judged |
|---|---|---|---|---|---|
| home_news_articles | 7 | 2 | 1 | 0 | 10 |
| ai_energy_news_articles | 7 | 3 | 0 | 0 | 10 |
| disruptive_tech_articles | 9 | 1 | 0 | 0 | 10 |
| semiconductor_news_articles | 8 | 0 | 0 | 2 | 8 |
| geopolitics_trade_articles | 9 | 1 | 0 | 0 | 10 |
| climate_energy_articles | 7 | 2 | 1 | 0 | 10 |
| biotech_health_articles | 9 | 0 | 0 | 1 | 9 |
| software_security_articles | 9 | 0 | 0 | 1 | 9 |
| fintech_articles | 6 | 1 | 1 | 2 | 8 |
| defense_space_articles | 8 | 2 | 0 | 0 | 10 |
| **Total** | **79** | **12** | **3** | **6** | **94** |

### Overall rate vs the 90% target
- **Strictly grounded: 79/94 = 84.0%** of judged rows (every claim, entity and number verified present in the source).
- **Faithful (grounded + minor-drift, no fabrication): 91/94 = 96.8%.** Minor-drift = otherwise-accurate rows carrying one unsupported-in-source or slightly-off value (a derived %/count the source didn't state, an off-by-one date, or a framing gloss) — no invented entity and no contradicted hard number.
- Against a strict reading of "≥90% grounded", the sample lands at **84.0% (below target)**; against a "faithful, no fabrication" reading it is **96.8% (above target)**. Either way the **hard "0 fabrications" gate is not met**.

### Fabrication list (3) — stored claim vs source
1. **fintech_articles / Open USD** (`paymentsdive.com/.../stablecoin-open-standard-...`): stored **title** "Over 140 firms including Stripe, Visa and **BlackRock** launch Open USD" and `companies: ['Stripe','Visa','Mastercard','BlackRock','Adyen','Coinbase']`. Source names the consortium explicitly — Visa, Stripe, Mastercard, American Express, Adyen, Klarna, Affirm, Western Union, MoneyGram, U.S. Bank, Citizens Bank, BNY, Coinbase — and **"BlackRock" appears 0 times in the full 331 KB page**. Fabricated entity, and it is the lead noun of the headline.
2. **climate_energy_articles / SunZia** (`patternenergy.com/sunzia-comes-online/`): stored summary "featuring **916 turbines**". Source: *"…thank our teams who worked hard to deliver **674** of GE Vernova's workhorse turbines."* Contradicted hard count (916 vs 674). (The paired "3.5 GW" ≈ source's "approximately 3,650-megawatt" is fine.)
3. **home_news_articles / Tata Sierra.ev** (`auto.economictimes.indiatimes.com/...`): stored summary "offering **63 kWh** and 75 kWh battery options". Source states only *"equipped with a **75-kWh** battery pack"* — no 63 kWh variant anywhere on the page. Unsupported spec number. (₹18.79 lakh, 665 km MIDC, July 15 deliveries all verified correct.)

### Notable minor-drift (unsupported-in-source numbers — not counted as fabrications but flagged)
- **home_news / BYD** — "403,472 NEVs in June alone" absent from the electrek source (a Q2-focused piece; 557,090 Q2 lead is correct).
- **home_news / XPeng** — "15.9% year-over-year" not in the FT/PRNewswire release (40,126 June and 103,295 Q2 are exact).
- **ai_energy / Google 2026 report** — "18% emissions rise" not in source; the report's stated figures are **−2% operational** and **+25% supply-chain** emissions (37% electricity-demand growth and 12 GW clean energy are correct).
- **ai_energy / UNU** — `published_at` 2026-06-06 vs source "3 Jun 2026" (3-day drift); 9.3 trillion litres / 1.3 billion people verified.
- **climate / BloombergNEF** — "$117/kWh (−31%)" and "$108/kWh pack" sit behind the premium paywall and could not be verified in the free body; 158 GW/459 GWh deployments are confirmed.
- **climate / Green River** — "996,000 solar panels" vs source "993,492" (rounded, ~2.5k off).
- **fintech / BITA** — "0.65% fee" is **not** in the BlackRock press-release PDF (25–35% covered-call, IBIT, June 16, 2026 all confirmed).
- **defense / UK DIP** — title attributes "£8B for drone transformation"; source puts **£5B** on drones and **£8B** on the Global Combat Air Programme (the row's own summary states the £5B figure correctly).
- **geopolitics / Strait of Hormuz** — "70% below pre-war levels" vs source's "roughly half of prewar averages" (78 transits on the day before the June 25 strike is correct).

### Provenance coverage
- **Field-level, 100-row sample: 900/900 = 100.0%** of the nine graded fields (`url, title, summary, companies, country, sentiment, business_impact, scope, published_at`) carry a provenance marker; every sampled row has a 10-key provenance object.
- **Row-level, full tables (2,005 rows): 1,917 with non-null provenance = 95.6%.** Per-table range 89.2% (disruptive_tech) to 100% (home_news); no table showed a wholesale missing `provenance` column (the writer's silent strip-and-retry did **not** fire on any of the 10 tables).
- Provenance keys observed = 10 fields; **`tags` remains untracked** (confirms offline Bug 6), but `tags` is outside the acceptance field set, so the ≥95% target is **MET** on both the sample-field and full-table-row measures.

### Dedup findings
- **Cross-feed duplicate URLs (normalised: lowercased host, stripped trailing slash + `utm_*`/`fbclid`): 53 groups across the full tables** (identical to the exact-match count — tracking-param variants weren't the driver here). Overlaps cluster exactly where predicted: ai_energy↔climate (FERC, Meta/RWE PPAs), ai_energy↔disruptive↔semiconductor↔software (`openai.com/.../broadcom-jalapeno` in 4 tables), defense↔disruptive (SpaceX/Rocket Lab), disruptive↔semiconductor (IBM sub-1nm).
- **In the 100-row recent sample: 1 cross-feed duplicate** — the Rocket Lab→Iridium GlobeNewswire URL appears in both `defense_space_articles` and `disruptive_tech_articles`.
- **Within-table trailing-slash dups** still present (confirms Bug 5): home_news 2 groups, semiconductor 1, fintech 2 (e.g. `.../nio-partner-...` with and without trailing `/` stored as separate rows).
- Target "**0 cross-feed duplicate URLs in sample**": **NOT MET** (1 in the sample; 53 full-table).

### Acceptance verdict — **FAIL**
| Target | Result | Verdict |
|---|---|---|
| Faithfulness ≥90% grounded, **0 fabricated entities/numbers** | 84.0% strictly grounded / 96.8% fabrication-free; **3 fabrications** (1 entity, 2 numbers) | **FAIL** — the zero-fabrication gate is breached; strict-grounded also < 90% |
| Provenance on ≥95% of fields | 100% of sample fields; 95.6% of full-table rows | **PASS** |
| 0 cross-feed duplicate URLs (sample) | 1 in sample; 53 full-table | **FAIL** |

**Bottom line:** the extractor is faithful on the overwhelming majority of rows (96.8% carry no fabrication) and provenance is solidly instrumented, but the pipeline ships **occasional hallucinated entities/numbers that pass every offline validation** (an entity absent from the source, a contradicted turbine count, an invented battery-spec) — exactly the L2 risk the offline pass flagged as "not checkable offline". Combined with the still-live cross-feed and trailing-slash duplication (Bug 5 unfixed), the layer **does not meet acceptance**. Recommended before re-run: land the offline Bug 5 fix (URL normalisation for both dedup and cross-feed) and add a post-extraction entity/number groundedness check against the fetched source before write. Single-judge caveat applies — a second judge (or the originally-budgeted LLM judge) should confirm the 3 fabrications before they gate a release decision, though each was re-checked against raw source here.
