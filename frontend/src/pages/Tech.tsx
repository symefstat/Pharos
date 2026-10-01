/**
 * Technology Dossier — one URL per tracked technology (/tech/:key).
 *
 * The product loop on a single page, in narrative order: where the technology
 * stands (anchored placement) → how the read changed (stage history) → the
 * evidence (stories, measured curve) → what we predict (open forecasts with
 * falsifiers) → how past calls resolved (receipts) → who's moving (capital).
 * Same assembly as the MD/PDF export (backend /api/mot/tech/{key}), so the
 * page and the download can never disagree.
 */
import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  BookCheck,
  Compass,
  Download,
  FileText,
  FlaskConical,
  Newspaper,
  Wallet,
  Radar as RadarIcon,
} from "lucide-react";
import { api, apiUrl } from "../lib/api";
import type { DossierCapitalMove, DossierForecast, TechDossier } from "../lib/api";
import { useResource } from "../lib/useResource";
import { PageChrome } from "../components/PageChrome";
import { Card, CardBody, SectionHeading, Badge, StoryLink, Dot, Rich } from "../components/ui";
import { pct, shortDate } from "../lib/format";

const cap = (s: string | null | undefined) => (s ? s.replace(/-/g, " ") : "—");

export default function TechPage() {
  const { key = "" } = useParams();
  const loader = useCallback(() => api.techDossier(key), [key]);
  const resource = useResource<TechDossier>(loader, { key: `tech:${key}` });

  return (
    <PageChrome
      title={resource.data?.label ?? "Technology dossier"}
      subtitle="Signal → lifecycle stage → forecast → graded outcome, on one page"
      resource={resource}
    >
      {(d) => <Dossier d={d} />}
    </PageChrome>
  );
}

function Dossier({ d }: { d: TechDossier }) {
  const p = d.placement;
  return (
    <div className="space-y-7">
      {/* ── 1 · Where it stands ─────────────────────────────────────────── */}
      <Card>
        <CardBody>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to="/mot"
              className="inline-flex items-center gap-1 text-[12px] font-medium text-muted no-underline hover:text-ink"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> All technologies
            </Link>
            <span className="text-faint">·</span>
            <Badge variant="brand">{d.domain}</Badge>
            <span className="ml-auto flex items-center gap-2">
              <ExportButton fmt="md" tech={d.tech} icon={<FileText className="h-3.5 w-3.5" />} />
              <ExportButton fmt="pdf" tech={d.tech} icon={<Download className="h-3.5 w-3.5" />} />
            </span>
          </div>
          <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-ink">{d.label}</h2>
          {p.watching ? (
            <div className="mt-2 max-w-3xl">
              <p className="text-[13.5px] leading-relaxed text-muted">
                <Badge variant="warn">watching</Badge>{" "}
                <span className="ml-1">
                  {p.evidence} stage-classified article{p.evidence === 1 ? "" : "s"} in the last 30
                  days — below the evidence floor of {p.evidence_floor}, so Pharos makes{" "}
                  <em>no stage claim</em> for this technology yet.
                </span>
              </p>
              {/* progress to the floor — the watching phase gets a visible finish line */}
              <div className="mt-2.5 flex items-center gap-3">
                <div className="h-1.5 w-56 max-w-full overflow-hidden rounded-full bg-canvas">
                  <div
                    className="h-full rounded-full bg-brand transition-[width]"
                    style={{
                      width: `${Math.min(100, Math.round((p.evidence / Math.max(1, p.evidence_floor)) * 100))}%`,
                    }}
                  />
                </div>
                <span className="num text-[11.5px] text-faint">
                  {p.evidence} / {p.evidence_floor} toward a place on the curve
                </span>
              </div>
            </div>
          ) : (
            <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px] text-ink-soft">
              <span>
                Maturity{" "}
                <Badge variant="brand" className="ml-1 capitalize">{cap(p.maturity)}</Badge>
              </span>
              <span>
                Adoption{" "}
                <Badge variant="brand" className="ml-1 capitalize">{cap(p.adoption)}</Badge>
              </span>
              <span className="num text-muted">
                {p.evidence} stage-classified articles / 30d (floor {p.evidence_floor})
              </span>
              {p.anchored && (
                <span className="text-muted">
                  anchored to a curated assessment{p.anchor_as_of ? ` (${p.anchor_as_of})` : ""} —
                  news can advance the stage, never lower it
                </span>
              )}
              {p.thin_signal && <Badge variant="warn">thin signal</Badge>}
            </div>
          )}
          {p.lifecycle_note && (
            <p className="mt-2 max-w-3xl text-[12.5px] leading-relaxed text-muted">{p.lifecycle_note}</p>
          )}
          <p className="mt-3 border-t border-line pt-2.5 text-[11.5px] text-faint">
            As of {d.as_of} · the exported dossier carries this exact assembly.
          </p>
        </CardBody>
      </Card>

      {/* ── 1a · Origin: Radar — detection provenance for promoted candidates.
             The evidence that earned the promotion travels with the tech, and
             the graded detection call is one click away. ───────────────────── */}
      {d.radar_origin && (
        <Card>
          <CardBody className="py-4">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-brand">
                <RadarIcon className="h-3.5 w-3.5" /> Origin: Radar
              </span>
              <span className="num text-[12px] text-muted">
                surfaced {d.radar_origin.first_detected} on {d.radar_origin.mentions} stories ·{" "}
                {d.radar_origin.sources} publishers
                {d.radar_origin.papers > 0 ? ` · ${d.radar_origin.papers} research papers` : ""}
              </span>
              {d.radar_origin.research_stage && <Badge variant="brand">research-stage at detection</Badge>}
            </div>
            {d.radar_origin.why && (
              <p className="mt-1.5 max-w-3xl text-[12.5px] leading-relaxed text-muted">
                {d.radar_origin.why.replace(/\s*\[S\d+\]/g, "")}
              </p>
            )}
            <p className="mt-1.5 text-[11.5px] text-faint">
              {d.radar_origin.found_via && (
                <>
                  Found via the brief “{d.radar_origin.found_via}” ·{" "}
                </>
              )}
              {d.radar_origin.ledger_pred_id ? (
                <>
                  the promotion locked a graded detection call —{" "}
                  <Link to="/ledger" className="font-medium text-brand hover:underline">
                    see it on the ledger
                  </Link>
                </>
              ) : (
                <Link to="/radar" className="font-medium text-brand hover:underline">
                  see the Radar page
                </Link>
              )}
            </p>
          </CardBody>
        </Card>
      )}

      {/* ── 1b · The analyst read — agent narrative when cached, composed
             deterministic verdict otherwise ──────────────────────────────── */}
      {(d.agent_read || d.read.length > 0) && (
        <Card>
          <CardBody>
            <SectionHeading
              icon={<Compass className="h-4 w-4" />}
              title="Analyst read"
              description={
                d.agent_read
                  ? `Agent-composed from this dossier's data (${d.agent_read.as_of}) — grounded in the sections below, citations checked.`
                  : "The composed verdict — every sentence names the evidence it rests on."
              }
            />
            <div className="max-w-3xl space-y-2.5">
              {(d.agent_read
                ? d.agent_read.text.split(/\n{2,}/).filter((s) => s.trim())
                : d.read
              ).map((para, i) => (
                <p key={i} className="text-[13.5px] leading-relaxed text-ink-soft">
                  <Rich text={para} />
                </p>
              ))}
            </div>
            {d.players.length > 0 && (
              <div className="mt-4 flex flex-wrap items-center gap-1.5 border-t border-line pt-3">
                <span className="mr-1 text-[11.5px] font-medium text-muted">
                  Key players (mentions, 30d):
                </span>
                {d.players.map((pl) => (
                  <span
                    key={pl.name}
                    className="inline-flex items-center gap-1 rounded-md border border-line bg-canvas px-1.5 py-0.5 text-[11.5px] text-ink"
                  >
                    {pl.name} <span className="num text-faint">{pl.mentions}</span>
                  </span>
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {/* ── 2 · How the read changed ────────────────────────────────────── */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<FlaskConical className="h-4 w-4" />}
            title="Stage history"
            description="Dated transitions between snapshots — when the read changed, not just what happened."
          />
          {d.transitions.length === 0 ? (
            <p className="text-[13px] text-muted">No stage transitions recorded yet.</p>
          ) : (
            <ul className="space-y-2">
              {d.transitions.map((t, i) => (
                <li key={i} className="flex flex-wrap items-baseline gap-2 text-[13px]">
                  <span className="num text-faint">{t.as_of ?? "—"}</span>
                  <span className="capitalize text-muted">{t.dimension}</span>
                  <span className="font-medium capitalize text-ink">
                    {cap(t.from)} → {cap(t.to)}
                  </span>
                  {t.backward ? (
                    <Badge variant="down">backward — suspect</Badge>
                  ) : t.contested ? (
                    <Badge variant="warn">contested</Badge>
                  ) : t.confirmed ? (
                    <Badge variant="up">confirmed</Badge>
                  ) : (
                    <Badge variant="neutral">pending</Badge>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      {/* ── 3 · The evidence ────────────────────────────────────────────── */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardBody>
            <SectionHeading
              icon={<Newspaper className="h-4 w-4" />}
              title="Recent coverage"
              description="The matched stories behind the placement — checkable at the source."
            />
            {d.stories.length === 0 ? (
              <p className="text-[13px] text-muted">No matched stories in the window.</p>
            ) : (
              <ul className="space-y-2">
                {d.stories.map((s, i) => (
                  <li key={i} className="text-[12.5px] leading-snug">
                    {s.url ? (
                      <StoryLink href={s.url}>{s.title}</StoryLink>
                    ) : (
                      <span className="text-ink">{s.title}</span>
                    )}
                    <span className="ml-1.5 text-faint">
                      {s.source ?? "?"}{s.date ? ` · ${shortDate(s.date)}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardBody>
            <SectionHeading
              icon={<FlaskConical className="h-4 w-4" />}
              title="Measured world curve"
              description="A published series for this technology — the observed shape behind the placement."
            />
            {!d.measured_curve ? (
              <p className="text-[13px] text-muted">
                No measured benchmark curve is maintained for this technology.
              </p>
            ) : (
              <>
                <p className="text-[13px] font-medium text-ink">
                  {d.measured_curve.label}
                  {d.measured_curve.unit ? (
                    <span className="ml-1 font-normal text-muted">({d.measured_curve.unit})</span>
                  ) : null}
                </p>
                <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
                  {d.measured_curve.series.map((pt) => (
                    <span key={pt.year} className="num text-[12.5px] text-ink-soft">
                      {pt.year}: <span className="font-semibold text-ink">{pt.value.toLocaleString()}</span>
                    </span>
                  ))}
                </div>
                {d.measured_curve.direction_note && (
                  <p className="mt-2 text-[12px] text-muted">{d.measured_curve.direction_note}</p>
                )}
                <p className="mt-2 text-[11.5px] text-faint">
                  Source: {d.measured_curve.source?.org ?? "?"}
                  {d.measured_curve.source?.publication ? ` — ${d.measured_curve.source.publication}` : ""}
                  {d.measured_curve.source?.url ? (
                    <>
                      {" · "}
                      <a
                        href={d.measured_curve.source.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline decoration-line hover:text-ink"
                      >
                        link
                      </a>
                    </>
                  ) : null}
                </p>
              </>
            )}
          </CardBody>
        </Card>
      </div>

      {/* ── 3b · Funding signal — the independent evidence stream ────────── */}
      {d.funding && (
        <Card>
          <CardBody>
            <SectionHeading
              icon={<Wallet className="h-4 w-4" />}
              title="Funding signal — independent of news"
              description="Round-stage mix from ingested funding data — a second read on the lifecycle stage that does not derive from headlines."
            />
            <div className="flex flex-wrap items-baseline gap-x-5 gap-y-2 text-[13px] text-ink-soft">
              <span className="num">
                <span className="font-semibold text-ink">{d.funding.rounds}</span> round
                {d.funding.rounds === 1 ? "" : "s"} / {Math.round(d.funding.window_days / 30)}mo
              </span>
              {d.funding.total_usd > 0 && (
                <span className="num">
                  <span className="font-semibold text-ink">
                    {d.funding.total_usd >= 1e9
                      ? `$${(d.funding.total_usd / 1e9).toFixed(1)}B`
                      : `$${Math.round(d.funding.total_usd / 1e6)}M`}
                  </span>{" "}
                  disclosed
                </span>
              )}
              <span className="num">
                {d.funding.early} early (seed–B) / {d.funding.late} late (C+, growth, M&A/IPO)
              </span>
            </div>
            {d.funding.read && (
              <p className="mt-2.5 max-w-3xl rounded-md bg-brand-soft/40 px-3 py-2 text-[12.5px] leading-relaxed text-ink-soft">
                {d.funding.read}
              </p>
            )}
            {d.funding.latest.length > 0 && (
              <ul className="mt-3 space-y-1.5">
                {d.funding.latest.map((r, i) => (
                  <li key={i} className="text-[12px] leading-snug">
                    <span className="num text-faint">{r.announced_on ?? "—"}</span>{" "}
                    <span className="font-semibold text-ink">{r.company}</span>{" "}
                    <span className="text-muted">
                      {r.round_type}
                      {r.amount_usd ? ` · $${(r.amount_usd / 1e6).toFixed(0)}M` : " · undisclosed"}
                    </span>
                    {r.source_url && (
                      <>
                        {" "}
                        <StoryLink href={r.source_url}>source</StoryLink>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 border-t border-line pt-2 text-[11px] text-faint">
              Display-only corroboration — funding never moves the stage placement itself.
            </p>
          </CardBody>
        </Card>
      )}

      {/* ── 4 · What we predict ─────────────────────────────────────────── */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<BookCheck className="h-4 w-4" />}
            title="Open forecasts"
            description="Locked when made, each with the falsifier that would prove it wrong."
          />
          {d.open_forecasts.length === 0 ? (
            <p className="text-[13px] text-muted">No open forecasts on this technology.</p>
          ) : (
            <PrioritizedForecasts forecasts={d.open_forecasts} />
          )}
        </CardBody>
      </Card>

      {/* ── 5 · How past calls resolved ─────────────────────────────────── */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<BookCheck className="h-4 w-4" />}
            title="Resolved receipts"
            description="Graded outcomes — immutable once written, misses included."
          />
          {d.resolved_forecasts.length === 0 ? (
            <p className="text-[13px] text-muted">
              No forecasts on this technology have resolved yet.
            </p>
          ) : (
            <ul className="space-y-2.5">
              {d.resolved_forecasts.map((f, i) => (
                <li key={i} className="text-[12.5px] leading-snug">
                  <Badge variant={f.outcome === "hit" ? "up" : f.outcome === "miss" ? "down" : "neutral"}>
                    {(f.outcome ?? "—").toUpperCase()}
                  </Badge>
                  <span className="ml-2 text-ink">{f.claim}</span>
                  <span className="ml-1.5 text-faint">
                    {f.confidence != null ? `called at ${pct(f.confidence * 100, 0)}` : ""}
                    {f.resolved_on ? ` · resolved ${shortDate(f.resolved_on)}` : ""}
                  </span>
                  {f.evidence && <p className="mt-0.5 text-[12px] text-muted">{f.evidence}</p>}
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      {/* ── 6 · Who's moving ────────────────────────────────────────────── */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<Wallet className="h-4 w-4" />}
            title="Capital moves"
            description="Deals and funding among this technology's matched stories — conviction bets vs hedged options."
          />
          {d.capital.counts.commitment + d.capital.counts.option === 0 ? (
            <p className="text-[13px] text-muted">
              No clearly-typed capital moves matched this technology in the window.
            </p>
          ) : (
            <div className="grid gap-6 md:grid-cols-2">
              <CapitalColumn
                title="Full commitments"
                subtitle="large, irreversible — acquisitions, big capex"
                dot="var(--color-commit)"
                moves={d.capital.commitment}
                total={d.capital.counts.commitment}
              />
              <CapitalColumn
                title="Real options"
                subtitle="staged, reversible — funding rounds, pilots, partnerships"
                dot="var(--color-option)"
                moves={d.capital.option}
                total={d.capital.counts.option}
              />
            </div>
          )}
        </CardBody>
      </Card>

      <p className="text-[11.5px] leading-relaxed text-faint">{d.methodology}</p>
    </div>
  );
}

/* Several near-identical open calls used to compete for attention; the reader
   had to decide what mattered. Now the page decides: ONE primary lifecycle
   call (with its falsifier — the downside is part of the call), ONE capital/
   competitive implication, and the rest behind an expander. Nothing is
   hidden — just ranked. */
const LIFECYCLE_KINDS = ["stage_advance_tech", "stage_advance"];
const CAPITAL_KINDS = ["deal_flow", "posture_persist", "reactivity"];

function prioritizeForecasts(fs: DossierForecast[]) {
  const conf = (f: DossierForecast) => f.confidence ?? 0;
  const sorted = (a: DossierForecast[]) => [...a].sort((x, y) => conf(y) - conf(x));
  const primary =
    sorted(fs.filter((f) => LIFECYCLE_KINDS.includes(f.kind ?? "")))[0] ??
    sorted(fs.filter((f) => f.kind === "manual"))[0] ??
    sorted(fs)[0];
  const capital = sorted(fs.filter((f) => CAPITAL_KINDS.includes(f.kind ?? ""))).find(
    (f) => f !== primary,
  );
  const rest = fs.filter((f) => f !== primary && f !== capital);
  return { primary, capital, rest };
}

function PrioritizedForecasts({ forecasts }: { forecasts: DossierForecast[] }) {
  const [showRest, setShowRest] = useState(false);
  const { primary, capital, rest } = prioritizeForecasts(forecasts);
  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
        {primary && (
          <div className="md:col-span-1">
            <p className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-brand">
              The call
            </p>
            <ForecastCard f={primary} emphasis />
          </div>
        )}
        {capital && (
          <div className="md:col-span-1">
            <p className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-muted">
              Capital &amp; competition
            </p>
            <ForecastCard f={capital} />
          </div>
        )}
      </div>
      {rest.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setShowRest((v) => !v)}
            className="text-[12.5px] font-medium text-brand hover:underline"
          >
            {showRest ? "Hide" : "Show"} {rest.length} additional call
            {rest.length === 1 ? "" : "s"} {showRest ? "↑" : "↓"}
          </button>
          {showRest && (
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {rest.map((f, i) => (
                <ForecastCard key={i} f={f} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ForecastCard({ f, emphasis }: { f: DossierForecast; emphasis?: boolean }) {
  return (
    <div
      className={
        "rounded-xl border bg-surface p-3.5 " +
        (emphasis ? "border-brand/40 shadow-[0_1px_6px_rgba(58,92,208,0.08)]" : "border-line")
      }
    >
      <p className="text-[12.5px] font-medium leading-snug text-ink">{f.claim}</p>
      <p className="num mt-1.5 text-[11.5px] text-muted">
        {f.confidence != null ? `${pct(f.confidence * 100, 0)} confidence` : "—"}
        {f.horizon ? ` · ${f.horizon}` : ""}
        {f.resolve_by ? ` · resolves by ${shortDate(f.resolve_by)}` : ""}
      </p>
      {f.falsifier && (
        <div
          className="mt-2 rounded-md border border-line bg-canvas px-2.5 py-1.5"
          style={{ borderLeftColor: "var(--color-status-serious)", borderLeftWidth: 3 }}
        >
          <p className="text-[9.5px] font-semibold uppercase tracking-[0.08em] text-status-serious">
            Wrong if
          </p>
          <p className="mt-0.5 text-[11.5px] leading-relaxed text-ink-soft">{f.falsifier}</p>
        </div>
      )}
    </div>
  );
}

function CapitalColumn({
  title,
  subtitle,
  dot,
  moves,
  total,
}: {
  title: string;
  subtitle: string;
  dot: string;
  moves: DossierCapitalMove[];
  total: number;
}) {
  return (
    <div>
      <p className="flex items-center gap-1.5 text-[12.5px] font-semibold text-ink">
        <Dot color={dot} /> {title} <span className="num font-normal text-faint">{total}</span>
      </p>
      <p className="text-[11px] text-muted">{subtitle}</p>
      <ul className="mt-2 space-y-1.5">
        {moves.map((m, i) => (
          <li key={i} className="text-[12px] leading-snug">
            {m.companies.length > 0 && (
              <span className="font-semibold text-ink">{m.companies[0]} · </span>
            )}
            {m.url ? <StoryLink href={m.url}>{m.title}</StoryLink> : <span className="text-muted">{m.title}</span>}
            {m.published_at && <span className="num ml-1 text-faint">{shortDate(m.published_at)}</span>}
          </li>
        ))}
        {total > moves.length && (
          <li className="text-[11.5px] text-faint">+ {total - moves.length} more in the window</li>
        )}
      </ul>
    </div>
  );
}

function ExportButton({ fmt, tech, icon }: { fmt: "md" | "pdf"; tech: string; icon: React.ReactNode }) {
  return (
    <a
      href={apiUrl(`/api/mot/dossier?tech=${encodeURIComponent(tech)}&fmt=${fmt}`)}
      className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12px] font-medium text-ink-soft no-underline transition-colors hover:border-line-strong hover:text-ink"
    >
      {icon} {fmt.toUpperCase()}
    </a>
  );
}
