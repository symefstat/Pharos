import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Radar as RadarIcon, ScanSearch, Plus, X } from "lucide-react";
import { api } from "../lib/api";
import type { RadarCandidate, RadarPayload, RadarScan, TrackedCoord } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useResource } from "../lib/useResource";
import { PageChrome } from "../components/PageChrome";
import { Card, CardBody, SectionHeading, Badge, Select, StoryLink } from "../components/ui";
import { entityColor } from "../components/viz";
import { useActions, ProgressPanel } from "../components/actions";
import { shortDate } from "../lib/format";

/* Radar — horizon scanning: the technologies Pharos does NOT track yet,
   surfaced from the stories that matched no tracked technology. The page
   mirrors the product's integrity architecture in miniature: the Scout agent
   only PROPOSES; a deterministic evidence gate decides what surfaces; a human
   decides what gets tracked. Nothing here ever auto-joins the registry. */

export default function RadarPage() {
  const { tick } = useActions();
  // loader identity must be stable — useResource refetches when it changes,
  // and an inline arrow re-created per render loops the effect (nav freeze).
  const loader = useCallback(() => api.radar(), []);
  const resource = useResource(loader, { key: `radar:${tick}` });
  return (
    <PageChrome
      title="Radar"
      subtitle="Technologies we don't track yet — surfaced from the evidence, before you knew to ask"
      resource={resource}
    >
      {(data) => <RadarBody data={data} refresh={resource.refresh} />}
    </PageChrome>
  );
}

function RadarBody({ data, refresh }: { data: RadarPayload; refresh: () => void }) {
  const { isAuthed } = useAuth();
  const { jobForSlot } = useActions();
  const job = jobForSlot("radar");
  const fresh = data.candidates.filter((c) => c.status === "new");
  const promoted = data.candidates.filter((c) => c.status === "promoted");

  return (
    <div className="space-y-6">
      {/* How it works — three glanceable steps instead of a paragraph. */}
      <Card>
        <CardBody>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <RadarIcon className="h-4 w-4 text-brand" />
              <h2 className="text-[14.5px] font-semibold">How Radar works</h2>
            </div>
            {isAuthed && <ScanButton />}
          </div>
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <RadarStep
              n={1}
              title="Scan everything we don't track"
              body="Every refresh reads the news stories that match no tracked technology — plus fresh arXiv research abstracts, because papers lead the news by years."
            />
            <RadarStep
              n={2}
              title="Demand independent evidence"
              body={
                <>
                  A candidate only appears with{" "}
                  <span className="font-semibold text-ink-soft">
                    {data.gate.mentions}+ stories from {data.gate.sources} publishers over{" "}
                    {data.gate.spread_days}+ days
                  </span>
                  {data.gate.papers != null && (
                    <>
                      {" "}
                      — or <span className="font-semibold text-ink-soft">{data.gate.papers}+ research
                      papers</span> for early, research-stage signals
                    </>
                  )}
                  . One splashy headline is never enough.
                </>
              }
            />
            <RadarStep
              n={3}
              title="You decide what gets tracked"
              body="Nothing joins the registry on its own. An admin starts tracking a candidate, and from there it earns its place like every other technology."
            />
          </div>
          {/* internal config hints are admin-only (H3) */}
          {isAuthed && !data.scout_configured && (
            <p className="mt-3 text-[12px] text-faint">
              Scout agent not configured (TOQAN_SCOUT) — showing deterministic tag themes instead
              of named candidates.
            </p>
          )}
        </CardBody>
      </Card>
      {/* Directed scan — ask the Scout a question over the same evidence. */}
      {isAuthed && <BriefBox />}
      {job && job.steps.length > 0 && <ProgressPanel job={job} />}

      {/* Transparency strip — the machine's receipts, rejections included. */}
      {data.last_scan && <ScanStrip scan={data.last_scan} />}

      {/* Emergence map — candidates plotted among the tracked reference. */}
      {data.candidates.filter((c) => c.status !== "dismissed").length > 0 && (
        <Card>
          <CardBody>
            <SectionHeading
              title="Emergence map"
              description="Where each candidate sits among the technologies we already track — market signal × research signal, 30 days"
            />
            <EmergenceMap
              candidates={data.candidates.filter((c) => c.status !== "dismissed")}
              tracked={data.last_scan?.tracked_coords ?? []}
            />
          </CardBody>
        </Card>
      )}

      {fresh.length === 0 && promoted.length === 0 ? (
        <Card>
          <CardBody>
            <p className="py-6 text-center text-[13px] text-faint">
              No candidates yet — Radar populates on the next Refresh all (or an admin scan).
            </p>
          </CardBody>
        </Card>
      ) : (
        <>
          {fresh.length > 0 && (
            <section>
              <SectionHeading
                title="On the radar"
                description="Evidence-gated candidates awaiting a human decision"
              />
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {fresh.map((c) => (
                  <CandidateCard key={c.key} c={c} domains={data.domains} refresh={refresh} />
                ))}
              </div>
            </section>
          )}
          {promoted.length > 0 && (
            <section>
              <SectionHeading
                title="Promoted into tracking"
                description="Radar candidates now on the technology registry"
              />
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {promoted.map((c) => (
                  <CandidateCard key={c.key} c={c} domains={data.domains} refresh={refresh} />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function useWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((es) => setW(es[0].contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

const GATE = { stories: 5, papers: 3 }; // mirrors the backend gate constants

/* Emergence map — the page's one picture: every candidate plotted against the
   tracked registry on the axes the gate actually measures. Tracked dots are
   muted reference (click → dossier); candidates are loud and labeled. The gate
   thresholds render as faint lines, so the chart explains the rules. */
function EmergenceMap({
  candidates,
  tracked,
}: {
  candidates: RadarCandidate[];
  tracked: TrackedCoord[];
}) {
  const navigate = useNavigate();
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<{ x: number; y: number; label: string; sub: string } | null>(null);

  const height = 320;
  const m = { top: 18, right: 24, bottom: 42, left: 52 };
  const plotW = Math.max(0, width - m.left - m.right);
  const plotH = height - m.top - m.bottom;

  const cPts = candidates.map((c) => ({
    kind: "candidate" as const,
    key: c.key,
    label: c.label,
    domain: c.domain_hint ?? "other",
    stories: c.evidence.mentions,
    papers: c.evidence.papers ?? 0,
    research: !!c.evidence.research_stage,
  }));
  const tPts = tracked.map((t) => ({
    kind: "tracked" as const,
    key: t.tech,
    label: t.label,
    domain: t.domain,
    stories: t.stories,
    papers: t.papers,
    research: false,
  }));
  // 15% headroom so the most extreme dot never sits clipped on the plot edge
  const maxS =
    1.15 * Math.max(GATE.stories * 2, ...cPts.map((p) => p.stories), ...tPts.map((p) => p.stories));
  const maxP =
    1.15 * Math.max(GATE.papers * 2, ...cPts.map((p) => p.papers), ...tPts.map((p) => p.papers));
  // sqrt scales: the interesting action is near the origin, one 85-story
  // outlier must not flatten everything else against the axis
  const xOf = (v: number) => m.left + (Math.sqrt(v) / Math.sqrt(maxS)) * plotW;
  const yOf = (v: number) => m.top + plotH - (Math.sqrt(v) / Math.sqrt(maxP)) * plotH;

  // resolve exact-overlap stacks (many tracked techs share small counts)
  const taken: { x: number; y: number }[] = [];
  const place = (x0: number, y0: number, r: number) => {
    let x = x0;
    let y = y0;
    for (let k = 1; taken.some((q) => Math.hypot(q.x - x, q.y - y) < r + 3) && k <= 8; k++) {
      x = x0 + Math.cos(k * 2.4) * k * 4;
      y = y0 - Math.abs(Math.sin(k * 2.4)) * k * 3;
    }
    taken.push({ x, y });
    return { x, y };
  };
  const placed = [...tPts, ...cPts].map((p) => {
    const r = p.kind === "candidate" ? 8 : 4.5;
    const { x, y } = place(xOf(p.stories), Math.min(yOf(p.papers), m.top + plotH - 3), r);
    return { ...p, x, y, r };
  });

  const AXIS = "var(--color-chart-axis)";
  const LABEL = "var(--color-chart-label)";
  const INK2 = "var(--color-chart-ink-2)";
  const SURFACE = "var(--color-surface)";

  return (
    <div ref={ref} className="relative mt-3 w-full">
      {width > 0 && (
        <svg width={width} height={height} className="block" role="img">
          {/* gate thresholds — the chart explains the surfacing rules */}
          <line x1={xOf(GATE.stories)} x2={xOf(GATE.stories)} y1={m.top} y2={m.top + plotH}
                stroke={AXIS} strokeDasharray="3 4" />
          <text x={xOf(GATE.stories) + 5} y={m.top + 10} fontSize={10} fill={LABEL}>
            news gate ({GATE.stories} stories)
          </text>
          <line x1={m.left} x2={m.left + plotW} y1={yOf(GATE.papers)} y2={yOf(GATE.papers)}
                stroke={AXIS} strokeDasharray="3 4" />
          {/* label sits below the line at the quiet left end — candidate labels
              live above their dots, so above-the-line space near it is taken */}
          <text x={m.left + 6} y={yOf(GATE.papers) + 13} fontSize={10} fill={LABEL}>
            research gate ({GATE.papers} papers)
          </text>
          {/* axes */}
          <line x1={m.left} x2={m.left + plotW} y1={m.top + plotH} y2={m.top + plotH} stroke={AXIS} />
          <line x1={m.left} x2={m.left} y1={m.top} y2={m.top + plotH} stroke={AXIS} />
          <text x={m.left + plotW / 2} y={height - 8} fontSize={11} fill={LABEL} textAnchor="middle">
            market signal — stories / 30d
          </text>
          <text x={14} y={m.top + plotH / 2} fontSize={11} fill={LABEL} textAnchor="middle"
                transform={`rotate(-90 14 ${m.top + plotH / 2})`}>
            research signal — arXiv papers / 30d
          </text>
          {/* tracked reference dots (muted), then candidates on top */}
          {placed.map((p) => (
            <circle
              key={`${p.kind}:${p.key}`}
              cx={p.x}
              cy={p.y}
              r={p.r}
              fill={entityColor(p.domain, "domain")}
              fillOpacity={p.kind === "candidate" ? 0.9 : 0.3}
              stroke={p.kind === "candidate" ? SURFACE : "none"}
              strokeWidth={2}
              className={p.kind === "tracked" ? "cursor-pointer" : "cursor-default"}
              onPointerMove={() =>
                setTip({
                  x: p.x,
                  y: p.y,
                  label: p.label,
                  sub: `${p.stories} stories · ${p.papers} papers · ${
                    p.kind === "tracked" ? "tracked — click for dossier" : "radar candidate"
                  }`,
                })
              }
              onPointerLeave={() => setTip(null)}
              onClick={() => p.kind === "tracked" && navigate(`/tech/${p.key}`)}
            />
          ))}
          {/* the two most extreme reference dots get a faint name — they anchor
              the axes ("that's what a lot of papers/stories looks like") */}
          {(() => {
            const tr = placed.filter((p) => p.kind === "tracked");
            if (!tr.length) return null;
            const topP = tr.reduce((a, b) => (b.papers > a.papers ? b : a));
            const topS = tr.reduce((a, b) => (b.stories > a.stories ? b : a));
            const marks = topP === topS ? [topP] : [topP, topS];
            return marks.map((p) => (
              <text
                key={`ref:${p.key}`}
                x={Math.min(Math.max(p.x, m.left + 30), width - 34)}
                y={p.y - p.r - 5}
                fontSize={10}
                fill={LABEL}
                textAnchor="middle"
                stroke={SURFACE}
                strokeWidth={3}
                paintOrder="stroke"
              >
                {p.label}
              </text>
            ));
          })()}
          {/* label the candidates only — the reference stays quiet */}
          {placed
            .filter((p) => p.kind === "candidate")
            .map((p, i) => (
              <text
                key={`l:${p.key}`}
                x={Math.min(Math.max(p.x, m.left + 30), width - 30)}
                y={p.y - p.r - 6 - (i % 2) * 11}
                fontSize={10.5}
                fontWeight={600}
                fill={INK2}
                textAnchor="middle"
                stroke={SURFACE}
                strokeWidth={3}
                paintOrder="stroke"
              >
                {p.label}
              </text>
            ))}
        </svg>
      )}
      {tip && (
        <div
          className="pointer-events-none absolute z-10 max-w-[240px] rounded-lg border border-line bg-surface px-2.5 py-1.5 shadow-md"
          style={{ left: Math.min(tip.x + 10, Math.max(width - 250, 0)), top: tip.y - 44 }}
        >
          <p className="text-[12px] font-semibold leading-tight">{tip.label}</p>
          <p className="num text-[11px] text-muted">{tip.sub}</p>
        </div>
      )}
      <p className="mt-2 text-[11.5px] text-faint">
        <span className="mr-3 inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-brand opacity-90" /> radar candidates
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-brand opacity-30" /> tracked technologies
          (click one for its dossier)
        </span>
        {tracked.length === 0 && (
          <span className="ml-2 text-faint">— tracked reference appears after the next scan</span>
        )}
      </p>
    </div>
  );
}

function RadarStep({ n, title, body }: { n: number; title: string; body: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-canvas p-3.5">
      <div className="flex items-center gap-2">
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-soft text-[11px] font-semibold text-brand">
          {n}
        </span>
        <h3 className="text-[12.5px] font-semibold">{title}</h3>
      </div>
      <p className="mt-1.5 text-[12px] leading-relaxed text-muted">{body}</p>
    </div>
  );
}

/** Four trailing weekly mention counts as tiny bars — momentum at a glance. */
function MomentumBars({ weekly }: { weekly: number[] }) {
  const max = Math.max(1, ...weekly);
  const building = weekly[weekly.length - 1] >= weekly[0];
  return (
    <span
      className="inline-flex items-end gap-[2px] rounded-md border border-line bg-canvas px-1.5 py-0.5"
      title={`mentions per week (oldest → newest): ${weekly.join(" · ")}`}
    >
      {weekly.map((n, i) => (
        <span
          key={i}
          className="w-[5px] rounded-[1px]"
          style={{
            height: `${3 + (n / max) * 10}px`,
            background: building ? "var(--color-seq-500)" : "var(--color-chart-axis)",
          }}
        />
      ))}
    </span>
  );
}

function StatPill({ children, brand }: { children: React.ReactNode; brand?: boolean }) {
  return (
    <span
      className={
        "num inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium " +
        (brand ? "bg-brand-soft text-brand" : "border border-line bg-canvas text-muted")
      }
    >
      {children}
    </span>
  );
}

/** The scout's [S#] tags reference its private reading pack, not anything on
 *  this page — for readers they are pure noise, so display strips them. */
function stripCitations(text: string): string {
  return text
    .replace(/\s*\[S\d+\]/g, "")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function ScanButton() {
  const { run, jobForSlot } = useActions();
  const job = jobForSlot("radar");
  const running = job?.status === "running";
  return (
    <button
      onClick={() => run({ slot: "radar", label: "Radar scan", path: "/api/radar/scan" })}
      disabled={running}
      className="inline-flex items-center gap-2 rounded-lg bg-brand px-3 py-1.5 text-[13px] font-medium text-white transition-colors hover:opacity-90 disabled:opacity-60"
    >
      <ScanSearch className="h-3.5 w-3.5" />
      {running ? "Scanning…" : "Scan now"}
    </button>
  );
}

/** Directed scan: type a question, the Scout answers it over the same
 *  evidence — candidates come back through the identical gate. */
function BriefBox() {
  const { run, jobForSlot } = useActions();
  const [brief, setBrief] = useState("");
  const job = jobForSlot("radar");
  const running = job?.status === "running";
  const go = () => {
    const q = brief.trim();
    if (!q || running) return;
    run({ slot: "radar", label: "Directed scan", path: "/api/radar/scan", body: { brief: q } });
  };
  return (
    <Card>
      <CardBody className="py-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <ScanSearch className="h-4 w-4 shrink-0 text-brand" />
          <input
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && go()}
            maxLength={200}
            placeholder='Direct the Scout — e.g. "anything emerging in energy storage?"'
            className="min-w-0 flex-1 rounded-lg border border-line bg-canvas px-3 py-2 text-[13px] outline-none transition-colors placeholder:text-faint focus:border-brand focus:ring-2 focus:ring-brand/15"
          />
          <button
            onClick={go}
            disabled={running || !brief.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-2 text-[13px] font-medium text-white transition-colors hover:opacity-90 disabled:opacity-60"
          >
            {running ? "Scanning…" : "Scan for this"}
          </button>
        </div>
        <p className="mt-2 text-[11.5px] text-faint">
          Same evidence, same gate — the Scout just answers your question instead of free-scanning.
          Nothing surfaces without corroboration.
        </p>
      </CardBody>
    </Card>
  );
}

/** The last scan's receipts. The rejected count matters most — it shows the
 *  evidence gate filtering the agent for real. */
function ScanStrip({ scan }: { scan: RadarScan }) {
  return (
    <p className="num px-1 text-[12px] text-faint">
      Last scan {shortDate(scan.at)}
      {scan.brief ? (
        <>
          {" "}
          · brief: <span className="text-muted">“{scan.brief}”</span>
        </>
      ) : null}{" "}
      · read {scan.corpus.toLocaleString()} unmatched stories
      {scan.papers > 0 ? ` + ${scan.papers} research abstracts` : ""} ·{" "}
      {scan.proposed} proposed · {scan.surfaced} surfaced ·{" "}
      <span className="text-muted">{scan.rejected} rejected by the evidence gate</span>
    </p>
  );
}

function CandidateCard({
  c,
  domains,
  refresh,
}: {
  c: RadarCandidate;
  domains: string[];
  refresh: () => void;
}) {
  const { isAuthed } = useAuth();
  const navigate = useNavigate();
  const [domain, setDomain] = useState(
    domains.includes(c.domain_hint ?? "") ? (c.domain_hint as string) : domains[0] ?? "",
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ev = c.evidence;

  const promote = async () => {
    setBusy(true);
    setErr(null);
    const res = await api.trackTechnology(c.label, domain, c.keywords);
    if (!res.ok) {
      setBusy(false);
      setErr(res.error ?? "tracking failed");
      return;
    }
    await api.radarSetStatus(c.key, "promoted");
    setBusy(false);
    refresh();
    if (res.technology?.key) navigate(`/tech/${res.technology.key}`);
  };

  const dismiss = async () => {
    setBusy(true);
    const res = await api.radarSetStatus(c.key, "dismissed");
    setBusy(false);
    if (res.ok) refresh();
    else setErr(res.error ?? "dismiss failed");
  };

  return (
    <Card>
      <CardBody className="flex h-full flex-col">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-[14.5px] font-semibold">{c.label}</h3>
          {c.domain_hint && <Badge>{c.domain_hint}</Badge>}
          {/* papers-only evidence: earlier than the news cycle, and honest about it */}
          {ev.research_stage && <Badge variant="brand">research-stage</Badge>}
          {/* came back from a dismissal because the evidence clearly outgrew it */}
          {c.status === "new" && ev.resurfaced && (
            <Badge variant="warn">
              resurfaced — {ev.resurfaced.was} → {ev.resurfaced.now} signals
            </Badge>
          )}
          {c.status === "promoted" && <Badge variant="up">tracked</Badge>}
          {/* promoted rows live on the registry now — link straight to the dossier
              (same slugified key: track_technology slugifies the same label) */}
          {c.status === "promoted" && (
            <Link
              to={`/tech/${c.key}`}
              className="text-[12px] font-medium text-brand hover:underline"
            >
              View dossier →
            </Link>
          )}
        </div>
        {c.status === "promoted" && ev.ledger_pred_id && (
          <p className="mt-1.5 text-[11.5px] text-faint">
            Detection call locked on{" "}
            <Link to="/ledger" className="font-medium text-brand hover:underline">
              the ledger
            </Link>{" "}
            — graded in 90 days: still above the evidence floor, or a splash?
          </p>
        )}
        {c.why && (
          <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
            {stripCitations(c.why)}
          </p>
        )}
        {/* the gate's receipts as glanceable pills — a papers-only candidate
            shows its research receipts, not a row of news zeros */}
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          {ev.mentions > 0 && <StatPill>{ev.mentions} stories</StatPill>}
          {ev.sources > 0 && <StatPill>{ev.sources} publishers</StatPill>}
          {(ev.papers ?? 0) > 0 && <StatPill brand>{ev.papers} research papers</StatPill>}
          <StatPill>
            {shortDate(ev.first_seen)} → {shortDate(ev.last_seen)}
          </StatPill>
          {(ev.weekly?.some((n) => n > 0) ?? false) && <MomentumBars weekly={ev.weekly!} />}
          {ev.found_via && <StatPill brand>found via: “{ev.found_via}”</StatPill>}
        </div>
        {(ev.adjacent?.length ?? 0) > 0 && (
          <p className="mt-2 flex flex-wrap items-center gap-1.5 text-[11.5px] text-faint">
            adjacent to
            {(ev.adjacent ?? []).map((a) => (
              <Link
                key={a.tech}
                to={`/tech/${a.tech}`}
                title={`${a.n} stories mention both`}
                className="rounded-md bg-brand-soft px-1.5 py-0.5 font-medium text-brand hover:underline"
              >
                {a.label}
              </Link>
            ))}
          </p>
        )}
        {ev.stories.length > 0 && (
          <div className="mt-3">
            <p className="text-[10.5px] font-medium uppercase tracking-[0.07em] text-faint">
              In the news
            </p>
            <ul className="mt-1.5 space-y-1.5 border-l-2 border-line pl-3">
              {ev.stories.slice(0, 3).map((s, i) => (
                <li key={i} className="text-[12.5px] leading-snug">
                  <StoryLink href={s.url}>{s.title}</StoryLink>
                  <span className="text-faint">
                    {" "}
                    — {s.source ?? "?"}
                    {s.date ? `, ${shortDate(s.date)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {(ev.paper_items?.length ?? 0) > 0 && (
          <div className="mt-3">
            <p className="text-[10.5px] font-medium uppercase tracking-[0.07em] text-faint">
              In research (arXiv)
            </p>
            <ul className="mt-1.5 space-y-1.5 border-l-2 border-brand/30 pl-3">
              {(ev.paper_items ?? []).slice(0, 2).map((s, i) => (
                <li key={i} className="text-[12.5px] leading-snug">
                  <StoryLink href={s.url}>{s.title}</StoryLink>
                  <span className="text-faint">
                    {" "}
                    — {s.source ?? "arXiv"}
                    {s.date ? `, ${shortDate(s.date)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {isAuthed && c.status === "new" && (
          <div className="mt-auto flex flex-wrap items-center gap-2 pt-3.5">
            <Select value={domain} onChange={setDomain} options={domains.map((d) => [d, d] as [string, string])} />
            <button
              onClick={promote}
              disabled={busy || !domain}
              className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-2.5 py-1.5 text-[12.5px] font-medium text-white transition-colors hover:opacity-90 disabled:opacity-60"
            >
              <Plus className="h-3.5 w-3.5" /> Start tracking
            </button>
            <button
              onClick={dismiss}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-[12.5px] font-medium text-ink-soft transition-colors hover:border-line-strong hover:text-ink disabled:opacity-60"
            >
              <X className="h-3.5 w-3.5" /> Dismiss
            </button>
          </div>
        )}
        {err && <p className="mt-2 text-[12px] text-down">{err}</p>}
      </CardBody>
    </Card>
  );
}
