import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  BookOpen,
  FlaskConical,
  Gauge,
  History,
  Navigation,
  ShieldCheck,
} from "lucide-react";
import { api } from "../lib/api";
import type { BacktestPayload, BacktestReport } from "../lib/api";
import { useResource } from "../lib/useResource";
import { Card, CardBody, SectionHeading, Badge } from "../components/ui";

/* Methodology — the public trust document. Prose-first: how a stage call is
   made, the measured accuracy numbers (including the misses), how the forecast
   ledger stays honest, and what this product deliberately does not claim.
   No auth, no data fetch — every figure below is copied from the 2026-07-02
   eval scorecard (eval/reports/30_scorecard.md) or from the code it describes;
   nothing here is a live metric. Update this page when the eval is re-run. */

const P = ({ children }: { children: ReactNode }) => (
  <p className="text-[13.5px] leading-relaxed text-ink-soft [&+&]:mt-3">{children}</p>
);

const LI = ({ children }: { children: ReactNode }) => (
  <li className="text-[13.5px] leading-relaxed text-ink-soft">{children}</li>
);

const UL = ({ children }: { children: ReactNode }) => (
  <ul className="mt-3 list-disc space-y-2 pl-5">{children}</ul>
);

const Strong = ({ children }: { children: ReactNode }) => (
  <strong className="font-semibold text-ink">{children}</strong>
);

export default function MethodologyPage() {
  return (
    <>
      <header className="sticky top-0 z-10 border-b border-line bg-surface/85 px-8 py-4 backdrop-blur">
        <h1 className="text-[18px] font-semibold leading-tight tracking-tight text-ink">
          Methodology
        </h1>
        <p className="mt-0.5 text-[12.5px] text-muted">
          How Pharos makes its calls and how accurate they measure — including the misses.
        </p>
      </header>

      <main className="mx-auto w-full max-w-[880px] flex-1 px-8 py-7">
        <div className="space-y-7">
          {/* a. What Pharos is */}
          <Card>
            <CardBody>
              <SectionHeading
                icon={<Navigation className="h-4 w-4" />}
                title="What Pharos is"
              />
              <P>
                Pharos is a technology-strategy intelligence tool. It reads public technology
                news through established Management-of-Technology frameworks — the technology
                S-curve, diffusion of innovation, and technology strategy — to place tracked
                technologies on their lifecycle, and it logs falsifiable forecasts that are graded
                in the open. This page explains how every call is produced and how good those
                calls have measured so far, misses included.
              </P>
            </CardBody>
          </Card>

          {/* b. How a stage call is made */}
          <Card>
            <CardBody>
              <SectionHeading
                icon={<FlaskConical className="h-4 w-4" />}
                title="How a stage call is made"
                description="From a news headline to a lifecycle placement, step by step."
              />
              <P>
                <Strong>
                  Labels are made from the headline and a one-sentence summary — not the article
                  body.
                </Strong>{" "}
                Each news item is classified by a dedicated lens agent that sees only the item's
                title, company names, tags, and a one-sentence summary. It does not fetch the
                article and does not search the web. Each item is classified independently
                against three lenses: <Strong>maturity stage</Strong> (where the technology sits
                on its S-curve), <Strong>adoption stage</Strong> (which adopter group the market
                has reached), and <Strong>strategic move</Strong> (what strategy the story
                represents). When two stages are genuinely balanced, the rubric breaks the tie to
                the earlier stage, so ambiguity never manufactures a false "decisive transition".
              </P>
              <P>
                A technology's displayed stage then combines two signals:
              </P>
              <UL>
                <LI>
                  <Strong>News signal.</Strong> The modal (most common) stage across the
                  technology's classified items in the rolling 30-day window, per axis.
                </LI>
                <LI>
                  <Strong>Curated anchors.</Strong> Our world-truth benchmark measured the news
                  signal as a systematically <em>early</em> level estimator: across 39 scoreable
                  stage-axes it never over-placed a technology and under-placed 23 — news reports
                  novelty, so even abundant coverage reads earlier than the world. Each tracked
                  technology therefore carries a dated, curated anchor stage used as a{" "}
                  <Strong>floor</Strong>: the displayed stage is the later of the anchor and the
                  news-derived stage. News can still advance a technology beyond its anchor (the
                  change-detection job it is good at); it can never drag one below it.
                </LI>
              </UL>
              <P>
                Confidence is stated, not implied. A placement resting on fewer than 10
                stage-classified articles in the window is flagged <Strong>thin</Strong>, and
                narrative verdicts are hedged as "indicative" when the modal stage lacks a clear
                majority. A snapshot with no majority stage is marked <Strong>contested</Strong>.
                A <Strong>backward</Strong> stage move (near-impossible in the world) is flagged
                suspect rather than headlined, and single-snapshot flips are debounced — a move
                must persist to a second snapshot before it is reported as a transition.
              </P>
              <P>
                The measured benchmark curves shown alongside placements use only published
                figures with a per-datapoint source audit trail
                (IEA/OWID, IRENA, BloombergNEF, SEC filings); years without a published figure
                are omitted, never interpolated.
              </P>
            </CardBody>
          </Card>

          {/* c. Measured accuracy */}
          <Card>
            <CardBody>
              <SectionHeading
                icon={<Gauge className="h-4 w-4" />}
                title="Measured accuracy — the honest numbers"
                description="From the 2026-07-02 evaluation, scored against pre-committed targets."
              />
              <P>
                Pharos's classification layer was evaluated on 2026-07-02 against a 199-row
                gold set, with every target committed before scoring. The results, including the
                misses:
              </P>
              <UL>
                <LI>
                  <Strong>
                    Maturity-stage accuracy: 69.2% exact (95% CI 61–76%) against a ≥70%
                    pre-committed target, and 82.9% within one stage against a ≥90% target — both
                    misses.
                  </Strong>
                </LI>
                <LI>
                  <Strong>Adoption-stage accuracy: 71.9% exact</Strong> (target ≥65% — pass){" "}
                  <Strong>and 86.3% within one stage</Strong> (target ≥90% — miss).
                </LI>
                <LI>
                  Business-impact and scope classification: 94.5% and 95.9% (both ≥80% targets —
                  pass).
                </LI>
                <LI>
                  When stage calls are wrong, they are mostly wrong by one adjacent stage (80% of
                  maturity stage-to-stage errors, 95% of adoption) — but 44% of all maturity
                  errors involve the "not applicable" boundary, a known prompt weakness.
                </LI>
              </UL>
              <P>
                <Strong>The gold set is provisional.</Strong> 0 of its 199 rows have been
                human-signed; a 36-row human review is the pending tiebreaker. Until that review
                lands, the accuracy figures above are measured against triage-corrected labels,
                not independently verified ground truth — a caveat that cuts both ways.
              </P>
              <P>
                The same evaluation audited the layers around the classifier. Extraction: 3
                fabricated details were found in a 94-item sample (84.0% strictly grounded vs a
                ≥90% target); a pre-write groundedness check has since been added. The
                Strategist's use of theory scored 1.6/3 on fidelity against a ≥2.0 target, with 2
                confirmed misapplications, before its prompt was rewritten — the rewrite has not
                yet been re-measured, so 1.6/3 stands as the number of record.
              </P>
              <P>
                Forecast integrity passed everything: all 118 forecast fingerprints recompute
                exactly, resolution showed zero look-ahead violations, and the accuracy and
                calibration math recomputes exactly (measuring slightly under-confident — the
                honest direction to err).
              </P>
            </CardBody>
          </Card>

          {/* c2. Backtest — the method replayed over settled history */}
          <BacktestSection />

          {/* d. The forecast ledger */}
          <Card>
            <CardBody>
              <SectionHeading
                icon={<ShieldCheck className="h-4 w-4" />}
                title="The forecast ledger"
                description="Locked when made, graded in the open, verifiable by anyone."
              />
              <P>
                Every forecast is <Strong>locked when made</Strong>: the claim, confidence,
                made-on date, and resolve-by date are fingerprinted at creation, and resolved
                outcomes cannot be edited. The public ledger payload ships with a digest so an
                outside reader can verify the history without trusting us — the recipe, quoted
                from the code:
              </P>
              <p className="mt-3 rounded-lg border border-line bg-canvas px-4 py-3 font-mono text-[12px] leading-relaxed text-ink-soft">
                sha256 of the canonical JSON of the `forecasts` array exactly as delivered:
                json.dumps(forecasts, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False).encode('utf-8')
              </p>
              <P>
                A different digest means a different history. The grading rules:
              </P>
              <UL>
                <LI>
                  <Strong>Objective resolvers.</Strong> Data-driven forecast kinds are auto-graded
                  against the data itself; only judgment (Strategist) calls are graded manually,
                  and once a forecast is resolved its outcome is locked.
                </LI>
                <LI>
                  <Strong>Minimum resolve window.</Strong> Event-window forecasts cannot resolve
                  as a hit until at least 7 days have elapsed — a forecast must test the future,
                  not the made-day state.
                </LI>
                <LI>
                  <Strong>Price-call quarantine.</Strong> Price-direction calls are deliberate
                  coin flips (pinned at 50% confidence), so they are excluded from the pooled
                  headline accuracy and Brier score — pooling them would mechanically drag the
                  headline toward 50% with zero change in skill. They still get their own honest
                  category row, and the counts reconcile: headline resolved + quarantined resolved
                  = all resolved.
                </LI>
                <LI>
                  <Strong>External vs internal basis.</Strong> The record is split by what a
                  forecast is graded against. <em>External</em> forecasts are graded against the
                  world and are the citable headline; <em>internal</em> forecasts are graded
                  against Pharos's own data and measure self-consistency, not skill. Nothing is
                  hidden — only re-headlined. Unknown kinds default to internal, the conservative
                  bucket.
                </LI>
                <LI>
                  <Strong>Paraphrase dedupe.</Strong> Consecutive runs often restate the same call
                  in different words; near-paraphrases are detected by token overlap and blocked
                  from double-counting in the track record.
                </LI>
                <LI>
                  <Strong>Headline accuracy floor.</Strong> A single accuracy percentage is too
                  swingy on a small base, so every surface withholds the headline % until at
                  least 10 forecasts have resolved — below that, the raw hit/miss tally carries
                  the record.
                </LI>
                <LI>
                  <Strong>Falsifier watch.</Strong> Every judgment call carries a stated "wrong
                  if" condition, and an automated watch scans incoming news for candidate
                  refuting evidence. The watch is detection-only: it surfaces our exposure in the
                  open, but grading stays human.
                </LI>
              </UL>
              <P>
                The full ledger — every forecast ever logged, open and resolved, quarantined
                included but flagged — is on the{" "}
                <Link to="/ledger" className="font-medium text-brand hover:underline">
                  Track record
                </Link>{" "}
                page, with the digest and a JSON download.
              </P>
            </CardBody>
          </Card>

          {/* d2. Where agents write — and where they never do */}
          <Card>
            <CardBody>
              <SectionHeading
                icon={<FlaskConical className="h-4 w-4" />}
                title="Where AI agents write — and where they never do"
                description="Every agent-composed surface is labeled, validated, and has a deterministic fallback."
              />
              <P>
                Beyond classification, three agents compose prose in the product — each is
                disclosed here because a trust document should say where generated text appears:
              </P>
              <UL>
                <LI>
                  <Strong>The dossier "Analyst read"</Strong> is agent-composed once per data
                  refresh (never on page load) from that dossier's own sections. Output is
                  validated before storage — a citation pointing outside the dossier's story list
                  rejects the whole narrative — and a rejected or missing narrative falls back to
                  a deterministic, template-composed read. The page labels which one you're seeing.
                </LI>
                <LI>
                  <Strong>Falsifier alerts are agent-ranked</Strong>: a judge classifies each
                  candidate article as triggers / partial / unrelated so the alert leads with
                  signal. Grading stays human; every candidate stays in the database regardless
                  of the judge's verdict — nothing is hidden, only ordered.
                </LI>
                <LI>
                  <Strong>Stage-transition alerts carry an agent-written "why"</Strong> grounded
                  in the technology's matched stories, with the same citation validation. When
                  the coverage doesn't explain a move, the agent is instructed to say exactly
                  that rather than invent a catalyst.
                </LI>
              </UL>
              <P>
                Agents never touch: outcome grading, accuracy/Brier/calibration math, the stage
                placement itself (anchors + evidence floors are deterministic), or the funding
                corroboration below. A missing agent key degrades every one of these features to
                its deterministic behavior.
              </P>
              <P>
                <Strong>The funding signal.</Strong> Dossiers carry a second evidence stream
                that is independent of news classification: ingested funding rounds, with the
                early (seed–B) vs late (C+, growth, M&amp;A/IPO) mix compared against the
                news-derived stage. The comparison is a fixed rule (not a model), makes no claim
                below 3 phase-classified rounds in 12 months, and is display-only — funding never
                moves a stage placement.
              </P>
            </CardBody>
          </Card>

          {/* e. Known limitations */}
          <Card>
            <CardBody>
              <SectionHeading
                icon={<AlertTriangle className="h-4 w-4" />}
                title="Known limitations"
                description="What this product deliberately does not claim."
              />
              <UL>
                <LI>
                  <Strong>Free data only.</Strong> Pharos runs entirely on freely available
                  sources — public news feeds, published statistics, and regulatory filings. No
                  paid data terminals, no proprietary datasets.
                </LI>
                <LI>
                  <Strong>Headline-based classification.</Strong> Stage labels derive from the
                  headline and a one-sentence summary, not the article body. That keeps the
                  pipeline cheap and reproducible, but it means the classifier sees what editors
                  chose to foreground — the accuracy numbers above measure exactly this setup.
                </LI>
                <LI>
                  <Strong>A provisional gold standard.</Strong> The accuracy figures are measured
                  against a gold set that no human has yet signed off (0 of 199 rows); a 36-row
                  human review is the pending tiebreaker.
                </LI>
                <LI>
                  <Strong>A thin track record, for now.</Strong> Forecasts resolve on their own
                  clock, and the headline accuracy is withheld until at least 10 have resolved.
                  Until enough calls mature, the ledger's value is its verifiable locking, not a
                  long history.
                </LI>
                <LI>
                  <Strong>A curated technology universe.</Strong> Pharos tracks a hand-picked
                  registry of technologies with curated stage anchors (revisited quarterly). It is
                  a deep read on that universe, not a scan of everything.
                </LI>
              </UL>
            </CardBody>
          </Card>

          <p className="flex items-center gap-2 pb-2 text-[12px] text-faint">
            <BookOpen className="h-3.5 w-3.5" />
            Accuracy figures are from the 2026-07-02 evaluation and are restated, not live; this
            page is updated when the evaluation is re-run.
          </p>
        </div>
      </main>
    </>
  );
}

/* ── Backtest — the method replayed over settled technology history ──────────
   Data comes from /api/methodology/backtest (backtest_run.py's committed
   results). Renders nothing until the study exists — the page stays static
   otherwise, and an API failure must never break the trust document. */
function BacktestSection() {
  const { data } = useResource<BacktestPayload>(api.methodologyBacktest, {
    key: "methodology:backtest",
  });
  if (!data || data.reports.length === 0) return null;
  const s = data.summary;
  return (
    <Card>
      <CardBody>
        <SectionHeading
          icon={<History className="h-4 w-4" />}
          title="Backtest — would the method have called it?"
          description="The same lens, rollup, and confirmation rules replayed over archived news for technologies whose lifecycle is settled history."
        />
        <P>
          Historical headlines (GDELT archive) are classified with the <Strong>same MOT lens
          agent</Strong> the live product uses, rolled up to a quarterly modal stage (evidence
          floor ≥5 classified items), and a stage is <Strong>called</Strong> only after holding
          for two consecutive quarters — the production debounce. Calls are compared with
          documented milestones; misses and uncorroborated calls are shown with the hits.
        </P>
        <P>
          <Strong>
            Result: {s.hits}/{s.milestones} milestones called across {s.cases} technologies ·{" "}
            {s.false_calls} uncorroborated call{s.false_calls === 1 ? "" : "s"}.
          </Strong>
        </P>
        <div className="mt-4 space-y-5">
          {data.reports.map((r) => (
            <BacktestCase key={r.key} r={r} />
          ))}
        </div>
        <P>
          <Strong>Limitations.</Strong> GDELT sampling is a coarse, English-only slice of each
          quarter's coverage; milestone dates are curated judgments (each links its public
          source); and the lens prompt is today's — this measures the current method on old
          news, not what Pharos would have shipped at the time. Reproduce with{" "}
          <code className="rounded bg-canvas px-1.5 py-0.5 text-[12px]">python backtest_run.py</code>.
        </P>
      </CardBody>
    </Card>
  );
}

function BacktestCase({ r }: { r: BacktestReport }) {
  return (
    <div className="rounded-xl border border-line bg-canvas/60 p-4">
      <p className="text-[13.5px] font-semibold text-ink">
        {r.label}{" "}
        <span className="num font-normal text-faint">
          {r.window[0]} → {r.window[1]} · {r.n_classified}/{r.n_items} headlines classified
        </span>
      </p>
      {r.notes && <p className="mt-1 text-[12px] italic text-muted">{r.notes}</p>}
      <ul className="mt-2.5 space-y-2">
        {r.comparison.map((c, i) => (
          <li key={i} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[12.5px] leading-snug">
            {c.hit ? (
              c.lag_quarters != null && c.lag_quarters <= 0 ? (
                <Badge variant="up">{c.lag_quarters === 0 ? "same quarter" : `${-c.lag_quarters}q early`}</Badge>
              ) : (
                <Badge variant="neutral">{c.lag_quarters}q late</Badge>
              )
            ) : (
              <Badge variant="down">MISS</Badge>
            )}
            <span className="text-ink">{c.event}</span>
            <span className="num text-faint">
              milestone {c.quarter} · called {c.called_quarter ?? "never"} ·{" "}
              <a
                href={c.source}
                target="_blank"
                rel="noopener noreferrer"
                className="underline decoration-line hover:text-ink"
              >
                source
              </a>
            </span>
          </li>
        ))}
      </ul>
      {r.false_calls.length > 0 && (
        <p className="mt-2 text-[12px] text-muted">
          Uncorroborated: {r.false_calls.map((c) => `${c.stage} called ${c.quarter}`).join(" · ")}
        </p>
      )}
    </div>
  );
}
