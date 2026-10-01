import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  ArrowRightLeft,
  ChevronDown,
  ChevronUp,
  Download,
  FlaskConical,
  History,
  Magnet,
  Plus,
  Search,
  Sparkles,
  Swords,
  Target,
  X,
} from "lucide-react";
import { api, apiUrl } from "../lib/api";
import type {
  MotPayload,
  DiffusionPoint,
  MeasuredCurve,
  Transition,
  Seam,
  MotScorecard,
  StandardsBattle,
  TechPoint,
  TechStageHistory,
  StrategistRead,
} from "../lib/api";
import { useResource } from "../lib/useResource";
import { PageChrome, DefaultSkeleton } from "../components/PageChrome";
import { Card, CardBody, SectionHeading, Badge, Select, Segmented } from "../components/ui";
import { useActions, ProgressPanel } from "../components/actions";
import { useAuth } from "../lib/auth";
import { StoryRow } from "../components/Story";
import { ChordDiagram } from "../components/ChordDiagram";
import {
  ChartFrame,
  Legend,
  MatrixHeat,
  StatTile,
  TimeSeries,
  Tooltip as VizTooltip,
  entityColor,
  registerEntities,
  seqColor,
} from "../components/viz";

const cap = (s: string) => (s ? s.replace(/-/g, " ") : s);
const strip = (s: string) => (s || "").replace(/\*\*/g, "");

/* chart chrome tokens (mirror viz.tsx — charts reference tokens, never hex) */
const INK = "var(--color-chart-ink)";
const INK2 = "var(--color-chart-ink-2)";
const LABEL = "var(--color-chart-label)";
const GRID = "var(--color-chart-grid)";
const AXIS = "var(--color-chart-axis)";
const SURFACE = "var(--color-surface)";

/** Split an agent interpretation into a one-sentence read line + the rest
 *  (density rule: text walls become read line + expander, never a wall). */
function splitRead(text?: string): { lead: string; rest: string } {
  const t = strip(text ?? "").trim();
  if (!t) return { lead: "", rest: "" };
  const m = t.match(/^(.+?[.!?])\s+([\s\S]+)$/);
  return m ? { lead: m[1], rest: m[2] } : { lead: t, rest: "" };
}

function FullRead({ rest }: { rest: string }) {
  if (!rest) return null;
  return (
    <details className="group mt-3">
      <summary className="cursor-pointer select-none text-[11.5px] text-muted transition-colors hover:text-ink">
        <span className="font-medium">Full agent read</span>
        {/* teaser so the fold reads as content, not a footnote; gone once open */}
        <span className="text-faint group-open:hidden">
          {" — "}
          {rest.length > 110 ? `${rest.slice(0, 110).trimEnd()}…` : rest}
        </span>
      </summary>
      <p className="mt-1.5 max-w-3xl text-[12.5px] leading-relaxed text-muted">{rest}</p>
    </details>
  );
}

/** "Show all N" fold used by lists and tables (mirrors HBarList's expander). */
function ShowAll({ expanded, onToggle, total }: { expanded: boolean; onToggle: () => void; total: number }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="mt-2 inline-flex items-center gap-1 text-[11.5px] font-medium text-muted transition-colors hover:text-ink"
    >
      {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
      {expanded ? "Show fewer" : `Show all ${total}`}
    </button>
  );
}

/** Observe rendered width (plain SVG needs real pixels). */
function useWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => setWidth(entries[0]?.contentRect.width ?? 0));
    ro.observe(el);
    setWidth(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

type Tip = { x: number; y: number; body: ReactNode };

/** A dot's recorded provenance on the curve: normalized x of the previous
 *  stage, that stage's name, and the date the current stage began. */
type StageTrail = { x: number; stage: string; since: string };

function Overlay({ tip, width }: { tip: Tip | null; width: number }) {
  if (!tip) return null;
  const flip = width > 0 && tip.x > width - 190;
  return (
    <div
      className="absolute z-10"
      style={{
        left: tip.x,
        top: tip.y,
        transform: flip ? "translate(calc(-100% - 12px), -50%)" : "translate(12px, -50%)",
      }}
    >
      <VizTooltip>{tip.body}</VizTooltip>
    </div>
  );
}

/* ── Stage history — the long-run record behind the 30-day S-curve window ────
   The S-curve dot places from a rolling 30-day news window (change detector);
   this timeline renders technology_stage_history — the never-pruned daily
   snapshot — so maturity/adoption can be tracked over months and years. */

const fmtMonth = (ms: number) =>
  new Date(ms).toLocaleDateString(undefined, { month: "short", year: "2-digit" });
const fmtDay = (ms: number) =>
  new Date(ms).toLocaleDateString(undefined, { month: "short", day: "numeric" });

function StageHistoryTimeline({
  techs,
  order,
  dim,
  from,
  to,
}: {
  techs: TechStageHistory[];
  order: string[];
  dim: "maturity" | "adoption";
  from: string;
  to: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip | null>(null);

  const rows = techs.filter((t) => t[dim].length > 0);
  const LABEL_W = 150;
  const ROW_H = 24;
  const AXIS_H = 22;
  const height = rows.length * ROW_H + AXIS_H;

  // Auto-fit the x-domain to where snapshots actually exist: a young history
  // (weeks of snapshots inside a 1-year window) would otherwise compress into
  // an unreadable sliver at the right edge. The requested window is a MAX;
  // the plot starts at the first real snapshot.
  const DAY = 86400e3;
  const dataStart = rows.reduce(
    (acc, t) => Math.min(acc, Date.parse(t.first_seen || to)),
    Infinity,
  );
  const t1 = Math.max(Date.parse(to), isFinite(dataStart) ? dataStart : 0) + DAY / 2;
  const t0 = Math.max(
    Date.parse(from),
    isFinite(dataStart) ? dataStart - DAY : Date.parse(from),
  );
  const span = Math.max(DAY, t1 - t0);
  const plotW = Math.max(0, width - LABEL_W - 8);
  const x = (iso: string) => LABEL_W + ((Date.parse(iso) - t0) / span) * plotW;

  // ~5 ticks across the fitted span — daily/weekly granularity while the
  // history is young, month-snapped once it spans quarters.
  const ticks: number[] = [];
  const shortSpan = span <= 100 * DAY;
  if (shortSpan) {
    const stepDays = Math.max(1, Math.ceil(span / DAY / 5));
    for (let ms = t0 + DAY; ms <= t1; ms += stepDays * DAY) ticks.push(ms);
  } else {
    const start = new Date(t0);
    start.setUTCDate(1);
    const months = Math.max(1, Math.round(span / (30.44 * DAY)));
    const step = Math.max(1, Math.ceil(months / 5));
    for (let d = new Date(start); d.getTime() <= t1; d.setUTCMonth(d.getUTCMonth() + step)) {
      if (d.getTime() >= t0) ticks.push(d.getTime());
    }
  }
  const fmtTick = shortSpan ? fmtDay : fmtMonth;

  const stageIdx = (s: string) => order.indexOf(s);
  const fill = (s: string) => {
    const i = stageIdx(s);
    return i < 0 ? "var(--color-chart-grid)" : seqColor(order.length <= 1 ? 1 : i / (order.length - 1));
  };

  if (!rows.length) {
    return (
      <p className="py-6 text-center text-[12.5px] text-faint">
        No stage history in this window yet — snapshots accrue daily.
      </p>
    );
  }

  return (
    <div ref={ref} className="relative">
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={`Technology ${dim} stage over time`}>
          {/* month gridlines + axis labels */}
          {ticks.map((ms) => {
            const tx = LABEL_W + ((ms - t0) / span) * plotW;
            return (
              <g key={ms}>
                <line x1={tx} x2={tx} y1={0} y2={height - AXIS_H + 4} stroke={GRID} />
                <text x={tx} y={height - 6} textAnchor="middle" fontSize={10} fill={LABEL}>
                  {fmtTick(ms)}
                </text>
              </g>
            );
          })}
          {rows.map((t, i) => {
            const y = i * ROW_H;
            return (
              <g key={t.tech}>
                {/* baseline track — visible where coverage gaps leave no segment */}
                <line
                  x1={LABEL_W}
                  x2={LABEL_W + plotW}
                  y1={y + ROW_H / 2}
                  y2={y + ROW_H / 2}
                  stroke={GRID}
                  strokeDasharray="2 3"
                />
                <circle cx={8} cy={y + ROW_H / 2} r={3} fill={entityColor(t.domain ?? "", "domain")} />
                <text x={18} y={y + ROW_H / 2 + 3.5} fontSize={11} fill={INK2}>
                  {t.label.length > 20 ? `${t.label.slice(0, 19)}…` : t.label}
                </text>
                {t[dim].map((seg, j) => {
                  const x0 = x(seg.from);
                  const w = Math.max(3, x(seg.to) - x0);
                  return (
                    <rect
                      key={j}
                      x={x0}
                      y={y + 6}
                      width={w}
                      height={ROW_H - 12}
                      rx={2}
                      fill={fill(seg.stage)}
                      onMouseMove={(e) => {
                        const host = ref.current?.getBoundingClientRect();
                        if (!host) return;
                        setTip({
                          x: e.clientX - host.left,
                          y: e.clientY - host.top,
                          body: (
                            <div>
                              <div className="font-medium">{t.label}</div>
                              <div>{cap(seg.stage)}</div>
                              <div className="text-faint">
                                {seg.from === seg.to ? seg.from : `${seg.from} → ${seg.to}`} ·{" "}
                                {seg.snapshots} snapshot{seg.snapshots === 1 ? "" : "s"}
                              </div>
                            </div>
                          ),
                        });
                      }}
                      onMouseLeave={() => setTip(null)}
                    />
                  );
                })}
              </g>
            );
          })}
        </svg>
      )}
      <Overlay tip={tip} width={width} />
      {/* stage legend — the sequential ramp in lifecycle order */}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        {order.map((s) => (
          <span key={s} className="inline-flex items-center gap-1.5 text-[11px] text-muted">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: fill(s) }} />
            {cap(s)}
          </span>
        ))}
      </div>
      {/* young history: the axis is fitted to real snapshots, say so */}
      {isFinite(dataStart) && dataStart > Date.parse(from) + DAY && (
        <p className="mt-1.5 text-[11px] text-faint">
          Recorded history begins {fmtDay(dataStart)} — the timeline extends as daily snapshots
          accrue.
        </p>
      )}
    </div>
  );
}

function StageHistoryCard() {
  const [dim, setDim] = useState<"maturity" | "adoption">("maturity");
  const [days, setDays] = useState("365");
  const loader = useCallback(() => api.motHistory(Number(days)), [days]);
  const res = useResource(loader, { key: `mot-history:${days}` });
  const data = res.data;

  return (
    <Card>
      <CardBody>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <SectionHeading
            icon={<History className="h-4 w-4" />}
            title="Stage history"
            description="Where each technology has sat on its lifecycle, day by day — the long-run record behind the 30-day S-curve window. All feeds; gaps = below the evidence floor."
          />
          <div className="flex items-center gap-2">
            <Segmented
              options={[
                ["maturity", "Maturity"],
                ["adoption", "Adoption"],
              ]}
              value={dim}
              onChange={(v) => setDim(v as "maturity" | "adoption")}
            />
            <Select
              value={days}
              onChange={setDays}
              options={[
                ["180", "6 months"],
                ["365", "1 year"],
                ["730", "2 years"],
                ["1825", "5 years"],
              ]}
            />
          </div>
        </div>
        {res.error && !data ? (
          <p className="py-6 text-center text-[12.5px] text-faint">Stage history unavailable.</p>
        ) : !data ? (
          <div className="h-40 animate-pulse rounded-lg bg-[color:var(--color-chart-grid)]/40" />
        ) : (
          <>
            <StageHistoryTimeline
              techs={data.technologies}
              order={dim === "maturity" ? data.maturity_order : data.adoption_order}
              dim={dim}
              from={data.from}
              to={data.to}
            />
            <p className="mt-2 text-[11px] text-faint">{data.note}</p>
          </>
        )}
      </CardBody>
    </Card>
  );
}

export default function MotPage() {
  const [scope, setScope] = useState("all");
  const loader = useCallback(() => api.mot(scope), [scope]);
  const resource = useResource(loader, { key: `mot:${scope}` });
  return (
    <PageChrome
      title="Technologies"
      subtitle="Management-of-Technology (MOT) frameworks over the classified feeds"
      resource={resource}
      skeleton={<DefaultSkeleton />}
    >
      {(data) => <Mot data={data} scope={scope} setScope={setScope} onChanged={resource.refresh} />}
    </PageChrome>
  );
}

function Mot({
  data,
  scope,
  setScope,
  onChanged,
}: {
  data: MotPayload;
  scope: string;
  setScope: (s: string) => void;
  /** Re-fetch the payload after a registry write (track / archive). */
  onChanged: () => void;
}) {
  const { run, jobForSlot } = useActions();
  const { isAuthed } = useAuth();

  // Recorded stage history (same cache key as the Stage-history card, so the
  // two surfaces share one fetch): per tech, the previous stage segment →
  // a movement trail on the S-curve from where it was to where it sits.
  const histLoader = useCallback(() => api.motHistory(365), []);
  const hist = useResource(histLoader, { key: "mot-history:365" });
  const trails = useMemo(() => {
    const m = new Map<string, StageTrail>();
    const h = hist.data;
    if (!h) return m;
    const order = h.maturity_order;
    for (const t of h.technologies) {
      const segs = t.maturity;
      if (segs.length < 2) continue;
      const prev = segs[segs.length - 2];
      const cur = segs[segs.length - 1];
      const i = order.indexOf(prev.stage);
      if (i < 0) continue;
      m.set(t.tech, { x: i / (order.length - 1), stage: prev.stage, since: cur.from });
    }
    return m;
  }, [hist.data]);

  // Ghost dots: every tracked technology below the evidence floor THIS window
  // still appears on the curve — faint and dashed, placed at its last RECORDED
  // stage (technology_stage_history), never at a live 30-day claim it can't
  // support. The chart shows the whole registry; the styling keeps it honest.
  const ghosts = useMemo<TechPoint[]>(() => {
    const h = hist.data;
    if (!h) return [];
    const live = new Set(
      data.technologies.filter((t) => t.x != null && t.on_curve).map((t) => t.tech),
    );
    const order = h.maturity_order;
    const out: TechPoint[] = [];
    for (const t of h.technologies) {
      if (live.has(t.tech)) continue;
      const segs = t.maturity;
      if (!segs.length) continue;
      const last = segs[segs.length - 1];
      const i = order.indexOf(last.stage);
      if (i < 0) continue;
      out.push({
        tech: t.tech,
        label: t.label,
        domain: t.domain ?? "",
        maturity: last.stage.replace(/-/g, " "),
        adoption: "",
        move: "",
        articles: 0,
        entrants: 0,
        coverage: 0,
        x: i / (order.length - 1),
        mixed: false,
        on_curve: false,
        ax: null,
        adoption_coverage: 0,
        adoption_mixed: false,
        on_adoption_curve: false,
        regime: null,
        thin_signal: false,
        watching: true,
        anchored: false,
        maturity_anchored: false,
        adoption_anchored: false,
        news_maturity: null,
        news_adoption: null,
        anchor_as_of: null,
        lifecycle_fit: true,
        lifecycle_note: null,
        ghost: true,
        ghost_as_of: last.to || t.last_seen,
      });
    }
    return out;
  }, [hist.data, data.technologies]);

  const classifyJob = jobForSlot("mot-classify");
  const classifyRunning = classifyJob?.status === "running";
  const scopeOpts: [string, string][] = [
    ["all", "All feeds"],
    ...data.feeds.map((f) => [f.label, f.label] as [string, string]),
  ];

  // Color follows the entity (the feed/domain), never rank: register the full,
  // unfiltered feed list first so refiltering never repaints survivors.
  registerEntities(
    [...data.technologies.map((t) => t.domain), ...ghosts.map((t) => t.domain), ...data.comatrix.domains],
    "domain",
  );

  // Per-curve views: each curve carries its own anchored flag + preserved
  // news-derived stage so the tooltip can say what the news alone reads.
  // Ghosts (below the floor this window) join at their last recorded stage.
  const maturityTechs: TechPoint[] = [
    ...data.technologies.map((t) => ({
      ...t,
      curve_anchored: t.maturity_anchored,
      news_stage: t.news_maturity,
    })),
    ...ghosts,
  ];

  // Anchor vintage comes from the payload (latest curated anchor date), never a
  // hardcoded month — captions stay honest as the backend re-anchors.
  const anchorAsOf = data.technologies.reduce<string | null>(
    (acc, t) => (t.anchor_as_of && (!acc || t.anchor_as_of > acc) ? t.anchor_as_of : acc),
    null,
  );
  const anchorSuffix = anchorAsOf ? ` (${anchorAsOf})` : "";

  const onCurve = data.technologies.filter((t) => t.x != null && t.on_curve);
  const forwardMoves = data.transitions.filter((t) => !t.backward);

  const scRead = splitRead(data.scurve_interpret);
  const diffRead = splitRead(data.diffusion_interpret);
  const mvRead = splitRead(data.move_interpret);

  const curveTable = (techs: TechPoint[]) => ({
    columns: ["Technology", "Domain", "Stage", "Coverage", "Players"],
    rows: [...techs]
      .filter((t) => t.x != null && (t.on_curve || t.ghost))
      .sort((a, b) => b.coverage - a.coverage)
      .map((t) => [
        t.label,
        t.domain,
        t.ghost ? `${cap(t.maturity)} (last recorded)` : cap(t.maturity) || "—",
        t.ghost ? "below floor" : t.coverage,
        t.ghost ? "—" : t.entrants,
      ]),
  });

  // Strategic-move grid → MatrixHeat (sequential ramp; one hue for magnitude)
  const moveRows = data.maturity_order.filter((mo) => data.moves.some((c) => c.maturity === mo));
  const moveLookup = new Map(data.moves.map((c) => [`${c.maturity}|${c.move}`, c.count]));
  const moveValues = moveRows.map((mo) => data.move_order.map((mv) => moveLookup.get(`${mo}|${mv}`) ?? 0));

  // Table twin for the chord diagram — the same labels × labels co-mention
  // counts the MatrixHeat fallback renders (diagonal blanked).
  const comentionTable =
    data.comatrix.labels.length >= 2
      ? {
          columns: ["Company", ...data.comatrix.labels],
          rows: data.comatrix.labels.map((l, i) => [
            l,
            ...data.comatrix.matrix[i].map((v, j) => (i === j ? "—" : v.toLocaleString())),
          ]),
        }
      : undefined;

  return (
    <div className="space-y-7">
      {/* filter row — one row above everything it scopes */}
      <div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[12.5px] text-muted">
            Read through the S-curve, diffusion, and strategy frameworks · curated stage anchors{anchorSuffix} + 30d news window
          </p>
          <div className="flex items-center gap-2">
            <Select value={scope} onChange={setScope} options={scopeOpts} />
            {isAuthed && (
              <button
                onClick={() => run({ slot: "mot-classify", path: "/api/actions/classify", label: "Classify new" })}
                disabled={classifyRunning}
                className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-[13px] font-medium text-ink-soft transition-colors hover:border-line-strong hover:text-ink disabled:opacity-60"
              >
                <FlaskConical className="h-3.5 w-3.5" />
                {classifyRunning ? "Classifying…" : "Classify new"}
              </button>
            )}
          </div>
        </div>
        {isAuthed && classifyJob && classifyJob.steps.length > 0 && <ProgressPanel job={classifyJob} />}
      </div>

      {/* KPI row — the headline numbers, not charts */}
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Classified items (30d)" value={data.classified.toLocaleString()} />
        <StatTile label="Technologies on curve" value={onCurve.length.toLocaleString()} />
        <StatTile label="Forward stage moves" value={forwardMoves.length.toLocaleString()} />
      </div>

      {/* Index — every tracked technology, one dossier each. The plain front
          door: charts locate, this navigates. */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<FlaskConical className="h-4 w-4" />}
            title="Tracked technologies"
            description="One dossier per technology — signal → stage → forecasts → graded outcomes on a single page."
          />
          <TechIndex techs={data.technologies} />
        </CardBody>
      </Card>

      {/* S-curve */}
      <Card>
        <CardBody>
          <ChartFrame
            title="Technologies on the S-curve"
            read={scRead.lead || `Anchored to curated stage assessments${anchorSuffix}, advanced by the last-30-days news signal.`}
            caption={`Anchored to curated stage assessments${anchorSuffix} + last-30-days news signal · dashed dot = below the evidence floor this window, shown at its last recorded stage · dotted trail = recorded stage move (ring = previous stage) · hollow = thin signal (<10 articles) · dot size = stage coverage · faded = contested · colour = domain`}
            table={curveTable(maturityTechs)}
          >
            <SCurve techs={maturityTechs} stages={data.maturity_order.map(cap)} trails={trails} />
          </ChartFrame>
          <FullRead rest={scRead.rest} />
        </CardBody>
      </Card>

      {/* Stage history — the long-run record behind the 30-day window */}
      <StageHistoryCard />

      {/* Diffusion bell */}
      <Card>
        <CardBody>
          <ChartFrame
            title="Diffusion — adopter categories & the chasm"
            read={diffRead.lead || "How many classified items sit in each adopter group."}
            caption="Counts of adoption-classified news items per adopter group (30d coverage, not installed-base shares) · hover a column for its top players"
            table={{
              columns: ["Adopter group", "Items", "Top players"],
              rows: data.adoption_order.map((stage) => {
                const p = data.diffusion.find((d) => d.stage === stage);
                return [cap(stage), p?.count ?? 0, p?.top || "—"];
              }),
            }}
          >
            <DiffusionStrip points={data.diffusion} order={data.adoption_order} />
          </ChartFrame>
          <FullRead rest={diffRead.rest} />
        </CardBody>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardBody>
            <SectionHeading
              icon={<ArrowRightLeft className="h-4 w-4" />}
              title="Stage transitions"
              description="Technologies that changed lifecycle stage between snapshots · pending = seen on one snapshot, awaiting confirmation · techs below the evidence floor make no claims here."
            />
            <TransitionsList transitions={data.transitions} />
          </CardBody>
        </Card>
        <Card>
          <CardBody>
            <ChartFrame
              title="Strategic moves — maturity × move"
              read={mvRead.lead || "Where strategic plays cluster across the lifecycle."}
              caption="Cell = classified items pairing that maturity stage with that move"
              table={
                data.moves.length
                  ? {
                      columns: ["Maturity", ...data.move_order.map(cap)],
                      rows: moveRows.map((mo, i) => [cap(mo), ...moveValues[i]]),
                    }
                  : undefined
              }
            >
              {data.moves.length ? (
                <MatrixHeat
                  rowLabels={moveRows.map(cap)}
                  colLabels={data.move_order.map(cap)}
                  values={moveValues}
                  format={(v) => v.toLocaleString()}
                  relation="×"
                  cellSize={26}
                  labelWidth={110}
                />
              ) : (
                <p className="py-6 text-center text-[12.5px] text-faint">No strategic-move classifications in scope.</p>
              )}
            </ChartFrame>
            <FullRead rest={mvRead.rest} />
          </CardBody>
        </Card>
      </div>

      {/* Standards battles — factor reads over time per contested standard,
          harvested from the Strategist's daily briefs. Evidence, not magnitude:
          lists, not charts. */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<Swords className="h-4 w-4" />}
            title="Standards battles"
            description="Contested standards read daily by the Strategist — who leads, on which of the four classic factors, and how the lead has moved."
          />
          <StandardsBattles battles={data.standards ?? []} />
        </CardBody>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardBody>
            <SectionHeading
              icon={<Magnet className="h-4 w-4" />}
              title="Convergence radar"
              description="Which sector domains are colliding, and who sits at the seam."
            />
            <ConvergenceList seams={data.convergence} note={data.convergence_interpret} />
          </CardBody>
        </Card>
        <Card>
          <CardBody>
            <ChartFrame
              title="Co-mention network"
              read="Companies named together — ribbon weight = how often, colour = domain."
              caption="Hover a company to isolate its links · top co-mentioned entities, 30d window"
              table={comentionTable}
            >
              {data.comatrix.labels.length >= 3 ? (
                <ChordDiagram
                  labels={data.comatrix.labels}
                  domains={data.comatrix.domains}
                  matrix={data.comatrix.matrix}
                />
              ) : data.comatrix.labels.length >= 2 ? (
                <MatrixHeat
                  rowLabels={data.comatrix.labels}
                  colLabels={data.comatrix.labels}
                  values={data.comatrix.matrix.map((row, i) => row.map((v, j) => (i === j ? null : v)))}
                  format={(v) => v.toLocaleString()}
                  relation="↔"
                  cellSize={20}
                  labelWidth={90}
                />
              ) : (
                <p className="py-8 text-center text-[12.5px] text-faint">Not enough co-mentions yet.</p>
              )}
            </ChartFrame>
          </CardBody>
        </Card>
      </div>

      {/* Scorecard */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<Target className="h-4 w-4" />}
            title="MOT scorecard — score an entity"
            description="The doctrine's seven questions, answered for one player from the classified corpus."
          />
          <Scorecard cards={data.scorecards} />
        </CardBody>
      </Card>

      {/* Measured curves — real published series (replaces the old illustrative
          seed data; every datapoint is cited in MEASURED_CURVES_SOURCES.md). */}
      {data.measured_curves?.length > 0 && (
        <Card>
          <CardBody>
            <SectionHeading
              icon={<FlaskConical className="h-4 w-4" />}
              title="Measured adoption & performance curves"
              description="Real published series for benchmark technologies — the observed shape behind the lifecycle placements."
            />
            <MeasuredCurves curves={data.measured_curves} />
          </CardBody>
        </Card>
      )}

      {/* Browse by lens */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<Search className="h-4 w-4" />}
            title="Browse classified stories by lens"
            description="Filter the classified corpus by any MOT-lens value."
          />
          <BrowseLens rows={data.browse} />
        </CardBody>
      </Card>

      {/* Placement table */}
      <Card>
        <CardBody>
          <SectionHeading
            title={`Placement table — ${data.technologies.filter((t) => t.lifecycle_fit !== false).length} technologies`}
            description={
              <>
                {`Stages anchored to curated assessments${anchorSuffix} + last-30-days news signal · watching = under the ${data.evidence_floor}-article evidence floor (listed, not placed on the curves) · labels derive from headline + summary — see `}
                <Link to="/methodology" className="font-medium text-brand hover:underline">
                  Methodology
                </Link>
              </>
            }
            right={<DossierExport techs={data.technologies} />}
          />
          <PlacementTable techs={data.technologies} floor={data.evidence_floor} onChanged={onChanged} />
          {isAuthed && <TrackTechnologyForm domains={data.tech_domains ?? []} onChanged={onChanged} />}
        </CardBody>
      </Card>
    </div>
  );
}

/* ── Measured curves — real published series, one at a time ─────────────────── */

function MeasuredCurves({ curves }: { curves: MeasuredCurve[] }) {
  const [sel, setSel] = useState(curves[0]?.tech_key ?? "");
  const curve = curves.find((c) => c.tech_key === sel) ?? curves[0];
  if (!curve) return null;

  const fmtVal = (v: number) =>
    v.toLocaleString(undefined, { maximumFractionDigits: v < 10 ? 1 : 0 });
  const rows = curve.series.map((p) => ({ year: String(p.year), value: p.value }));

  return (
    <>
      <div className="mb-4">
        <Segmented
          value={curve.tech_key}
          onChange={setSel}
          options={curves.map((c) => [c.tech_key, c.label] as [string, string])}
        />
      </div>
      <ChartFrame
        title={`${curve.label} (${curve.unit})`}
        read={curve.direction_note}
        table={{
          columns: ["Year", `Value (${curve.unit})`],
          rows: curve.series.map((p) => [String(p.year), fmtVal(p.value)]),
        }}
        caption={
          <>
            Source: {curve.source.org} — {curve.source.publication} (retrieved{" "}
            {curve.source.retrieved}) ·{" "}
            <a
              href={curve.source.url}
              target="_blank"
              rel="noreferrer"
              className="underline decoration-line hover:text-ink"
            >
              original data
            </a>{" "}
            · Real published figures only — every datapoint is individually cited in the
            project's measured-curves source log; nothing is interpolated or estimated.
          </>
        }
      >
        <TimeSeries
          data={rows}
          xKey="year"
          series={[{ key: "value", label: curve.label }]}
          height={240}
          formatY={fmtVal}
        />
      </ChartFrame>
    </>
  );
}

/* ── S-curve — the product's signature custom SVG ───────────────────────────
   Token-driven restyle: categorical colour by domain (fixed order, colour
   follows the entity), 2px logistic guide, recessive hairline grid, ≥ 24px
   hover/focus hit targets on every dot, direct labels for the flagship techs,
   legend below. */
function SCurve({
  techs,
  stages,
  trails,
}: {
  techs: TechPoint[];
  stages: string[];
  trails?: Map<string, StageTrail>;
}) {
  const navigate = useNavigate();
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip | null>(null);
  const [hot, setHot] = useState<string | null>(null);

  const placed = useMemo(() => techs.filter((t) => t.x != null && (t.on_curve || t.ghost)), [techs]);
  const domains = useMemo(() => Array.from(new Set(placed.map((t) => t.domain))), [placed]);

  const height = 350;
  const m = { top: 26, right: 16, bottom: 28, left: 16 };
  const plotW = Math.max(0, width - m.left - m.right);
  const plotH = height - m.top - m.bottom;
  const logistic = (x: number) => 1 / (1 + Math.exp(-12 * (x - 0.5)));
  const xOf = (x: number) => m.left + x * plotW;
  const yOf = (y: number) => m.top + (1 - y) * plotH;

  if (!placed.length)
    return <p className="py-10 text-center text-[12.5px] text-faint">No technologies with enough classified coverage yet.</p>;

  const maxCov = Math.max(1, ...placed.map((t) => t.coverage));
  const rOf = (t: TechPoint) => 4 + Math.sqrt(t.coverage / maxCov) * 9;
  const drawn = [...placed].sort((a, b) => b.coverage - a.coverage); // big dots first, small stay hittable on top

  // ── Collision resolution ────────────────────────────────────────────────
  // Dots sit ON the curve, so near-identical stage positions physically stack.
  // Keep the along-the-curve position (that IS the data) and nudge colliding
  // dots perpendicular to the curve in alternating, growing steps until each
  // is visible. Big dots place first (drawn order), small ones move around them.
  const dotPos = new Map<string, { x: number; y: number }>();
  {
    const taken: { x: number; y: number; r: number }[] = [];
    for (const t of drawn) {
      const bx = xOf(t.x as number);
      const by = yOf(logistic(t.x as number));
      const r = rOf(t);
      // unit normal to the curve at this x (finite difference on the tangent)
      const eps = 0.015;
      const tx = xOf((t.x as number) + eps) - xOf((t.x as number) - eps);
      const ty = yOf(logistic((t.x as number) + eps)) - yOf(logistic((t.x as number) - eps));
      const tl = Math.hypot(tx, ty) || 1;
      const nx = -ty / tl;
      const ny = tx / tl;
      let x = bx;
      let y = by;
      // Nudge toward the open side of the plot first (up on the lower half,
      // down on the upper), and never let a displaced dot leave the plot —
      // it would land on the stage labels.
      const pref = by > m.top + plotH / 2 ? -1 : 1;
      outer: for (let k = 0; k <= 8; k++) {
        for (const sign of k === 0 ? [1] : [pref, -pref]) {
          const cx = bx + nx * sign * k * 7;
          const cy = by + ny * sign * k * 7;
          if (k > 0 && (cy < m.top + 3 || cy > m.top + plotH - 3 || cx < m.left + 3 || cx > m.left + plotW - 3))
            continue;
          if (!taken.some((q) => Math.hypot(q.x - cx, q.y - cy) < q.r + r + 2.5)) {
            x = cx;
            y = cy;
            break outer;
          }
        }
      }
      dotPos.set(t.label, { x, y });
      taken.push({ x, y, r });
    }
  }
  const posOf = (t: TechPoint) => dotPos.get(t.label) ?? { x: xOf(t.x as number), y: yOf(logistic(t.x as number)) };

  // Direct labels on every dot, placed greedily in coverage order: try close
  // slots (above/below/beside) first, then farther ones with a hairline leader.
  // A label that can't find a clean slot is dropped — so on narrow screens the
  // high-coverage techs keep their names and the rest stay hover-only.
  type PlacedLabel = { t: TechPoint; lx: number; ly: number; anchor: "start" | "middle" | "end"; leader: boolean };
  const labels: PlacedLabel[] = [];
  if (width > 0) {
    const estW = (s: string) => s.length * 5.8 + 4;
    const boxes: { x1: number; y1: number; x2: number; y2: number }[] = [];
    const dotRects = drawn.map((t) => {
      const { x, y } = posOf(t);
      const r = rOf(t) + 2;
      return { x1: x - r, y1: y - r, x2: x + r, y2: y + r };
    });
    const maxLabels = width < 560 ? 5 : drawn.length;
    for (const t of drawn) {
      if (labels.length >= maxLabels) break;
      const { x: px, y: py } = posOf(t);
      const r = rOf(t);
      const w = estW(t.label);
      const slots: { dx: number; dy: number; anchor: PlacedLabel["anchor"]; leader: boolean }[] = [
        { dx: 0, dy: -(r + 7), anchor: "middle", leader: false },
        { dx: 0, dy: r + 14, anchor: "middle", leader: false },
        { dx: r + 6, dy: 3.5, anchor: "start", leader: false },
        { dx: -(r + 6), dy: 3.5, anchor: "end", leader: false },
        { dx: 0, dy: -(r + 21), anchor: "middle", leader: true },
        { dx: 0, dy: r + 28, anchor: "middle", leader: true },
        { dx: r + 20, dy: 3.5, anchor: "start", leader: true },
        { dx: -(r + 20), dy: 3.5, anchor: "end", leader: true },
        { dx: 22, dy: -(r + 18), anchor: "start", leader: true },
        { dx: -22, dy: -(r + 18), anchor: "end", leader: true },
        { dx: 22, dy: r + 24, anchor: "start", leader: true },
        { dx: -22, dy: r + 24, anchor: "end", leader: true },
        { dx: 0, dy: -(r + 35), anchor: "middle", leader: true },
        { dx: 0, dy: r + 42, anchor: "middle", leader: true },
        { dx: 32, dy: -(r + 34), anchor: "start", leader: true },
        { dx: -32, dy: -(r + 34), anchor: "end", leader: true },
        { dx: 0, dy: -(r + 49), anchor: "middle", leader: true },
        { dx: 0, dy: r + 56, anchor: "middle", leader: true },
        { dx: r + 38, dy: 3.5, anchor: "start", leader: true },
        { dx: -(r + 38), dy: 3.5, anchor: "end", leader: true },
        { dx: 40, dy: -(r + 48), anchor: "start", leader: true },
        { dx: -40, dy: -(r + 48), anchor: "end", leader: true },
        { dx: 0, dy: -(r + 63), anchor: "middle", leader: true },
        { dx: 0, dy: -(r + 77), anchor: "middle", leader: true },
      ];
      // narrow screens: adjacent labels only — long leaders tangle in clusters
      const usable = width < 560 ? slots.filter((s) => !s.leader) : slots;
      for (const s of usable) {
        const lx = px + s.dx;
        const ly = py + s.dy;
        const x1 = s.anchor === "start" ? lx : s.anchor === "end" ? lx - w : lx - w / 2;
        const box = { x1, y1: ly - 9, x2: x1 + w, y2: ly + 3 };
        // labels may kiss the baseline (+6) — the stage names sit lower still
        if (box.x1 < 2 || box.x2 > width - 2 || box.y1 < 2 || box.y2 > m.top + plotH + 6) continue;
        const hits = (q: { x1: number; y1: number; x2: number; y2: number }) =>
          box.x1 < q.x2 && box.x2 > q.x1 && box.y1 < q.y2 && box.y2 > q.y1;
        if (boxes.some(hits) || dotRects.some(hits)) continue;
        labels.push({ t, lx, ly, anchor: s.anchor, leader: s.leader });
        boxes.push(box);
        break;
      }
    }
  }
  // Coverage top-4 read as the flagships: darker, heavier label ink.
  const flagship = new Set(drawn.slice(0, 4).map((t) => t.label));

  const curvePath = Array.from({ length: 41 }, (_, i) => {
    const x = i / 40;
    return `${i ? "L" : "M"}${xOf(x)},${yOf(logistic(x))}`;
  }).join(" ");

  const show = (t: TechPoint, px: number, py: number) =>
    setTip({
      x: Math.min(Math.max(px, m.left), m.left + plotW),
      y: py,
      body: (
        <div>
          <div className="mb-0.5 font-semibold" style={{ color: INK }}>
            {t.label}
          </div>
          <div className="flex items-center gap-1.5" style={{ color: INK2 }}>
            <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: entityColor(t.domain, "domain") }} />
            {t.domain}
          </div>
          <div className="mt-1 capitalize" style={{ color: INK2 }}>
            <span className="font-semibold" style={{ color: INK }}>
              {cap(t.maturity) || "—"}
            </span>
            {t.ghost ? ` · last recorded${t.ghost_as_of ? ` (${t.ghost_as_of})` : ""}` : ""}
            {t.mixed ? " · contested" : ""}
            {t.thin_signal ? " · (thin signal)" : ""}
          </div>
          {t.curve_anchored && (
            <div style={{ color: INK2 }}>
              curated anchor{t.anchor_as_of ? ` (${t.anchor_as_of})` : ""} · news alone reads{" "}
              <span className="capitalize">{cap(t.news_stage || "") || "—"}</span>
            </div>
          )}
          {t.tech && trails?.get(t.tech) && (
            <div style={{ color: INK2 }}>
              was <span className="capitalize">{cap(trails.get(t.tech)!.stage)}</span> until{" "}
              {trails.get(t.tech)!.since}
            </div>
          )}
          <div className="num" style={{ color: INK2 }}>
            {t.ghost
              ? "below the evidence floor this window — dot shows remembered state"
              : `${t.coverage} stage articles · ${t.entrants} players${t.thin_signal ? " · <10 articles" : ""}`}
          </div>
        </div>
      ),
    });

  const ticks = stages.map((_, i) => i / (stages.length - 1));

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <svg width={width} height={height} role="img" className="block">
          <defs>
            {/* the curve reads as a progression: ink deepens toward maturity */}
            <linearGradient id="scurve-stroke" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor="var(--color-seq-300)" />
              <stop offset="1" stopColor="var(--color-seq-600)" />
            </linearGradient>
            <linearGradient id="scurve-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="var(--color-brand)" stopOpacity="0.07" />
              <stop offset="1" stopColor="var(--color-brand)" stopOpacity="0" />
            </linearGradient>
          </defs>
          {/* recessive grid: solid hairlines at the stage boundaries */}
          {ticks.map((tx, i) => (
            <g key={i}>
              <line x1={xOf(tx)} x2={xOf(tx)} y1={m.top} y2={m.top + plotH} stroke={GRID} strokeWidth={1} />
              <text
                x={xOf(tx)}
                y={height - 8}
                textAnchor={i === 0 ? "start" : i === ticks.length - 1 ? "end" : "middle"}
                fontSize={10.5}
                fill={LABEL}
              >
                {stages[i]}
              </text>
            </g>
          ))}
          <line x1={m.left} x2={m.left + plotW} y1={m.top + plotH} y2={m.top + plotH} stroke={AXIS} strokeWidth={1} />
          <path
            d={`${curvePath} L${m.left + plotW},${m.top + plotH} L${m.left},${m.top + plotH} Z`}
            fill="url(#scurve-fill)"
            stroke="none"
          />
          <path d={curvePath} fill="none" stroke="url(#scurve-stroke)" strokeWidth={2.25} strokeLinecap="round" />
          {/* recorded stage moves: dotted trail along the curve from the previous
              stage (ring) to the dot — provenance, drawn under the dots */}
          {trails &&
            drawn.map((t) => {
              // Live dots only: a dozen ghost trails overlapping repaint the
              // curve itself — ghosts keep their history in the tooltip.
              if (t.ghost) return null;
              const tr = t.tech ? trails.get(t.tech) : undefined;
              if (!tr || t.x == null || Math.abs((t.x as number) - tr.x) < 0.02) return null;
              const steps = 14;
              const path = Array.from({ length: steps + 1 }, (_, i) => {
                const xx = tr.x + (((t.x as number) - tr.x) * i) / steps;
                return `${i ? "L" : "M"}${xOf(xx)},${yOf(logistic(xx))}`;
              }).join(" ");
              const dim = hot !== null && hot !== t.label;
              return (
                <g
                  key={`trail-${t.label}`}
                  pointerEvents="none"
                  opacity={dim ? 0.12 : 0.55}
                  style={{ transition: "opacity 150ms" }}
                >
                  <path
                    d={path}
                    fill="none"
                    stroke={entityColor(t.domain, "domain")}
                    strokeWidth={2}
                    strokeDasharray="1 4.5"
                    strokeLinecap="round"
                  />
                  <circle
                    cx={xOf(tr.x)}
                    cy={yOf(logistic(tr.x))}
                    r={3}
                    fill={SURFACE}
                    stroke={entityColor(t.domain, "domain")}
                    strokeWidth={1.5}
                  />
                </g>
              );
            })}
          {drawn.map((t) => {
            const { x: px, y: py } = posOf(t);
            const dim = hot !== null && hot !== t.label;
            const active = hot === t.label;
            const fade = { transition: "fill-opacity 150ms, stroke-opacity 150ms, opacity 150ms" };
            // Ghost (below the evidence floor this window): dashed hollow dot at
            // the last RECORDED stage — remembered state, not a live 30-day claim.
            if (t.ghost)
              return (
                <circle
                  key={t.label}
                  cx={px}
                  cy={py}
                  r={4}
                  fill={SURFACE}
                  stroke={entityColor(t.domain, "domain")}
                  strokeWidth={active ? 2 : 1.5}
                  strokeDasharray="2.5 2"
                  strokeOpacity={dim ? 0.2 : active ? 1 : 0.65}
                  style={fade}
                />
              );
            // Thin signal (<10 stage-classified articles): hollow/outlined dot —
            // visibly LESS confident, never absent (analysts still want to see it).
            if (t.thin_signal)
              return (
                <circle
                  key={t.label}
                  cx={px}
                  cy={py}
                  r={Math.max(rOf(t) - 1, 3.5)}
                  fill={SURFACE}
                  stroke={entityColor(t.domain, "domain")}
                  strokeWidth={active ? 2.25 : 1.75}
                  strokeOpacity={dim ? 0.25 : t.mixed ? 0.5 : 0.9}
                  style={fade}
                />
              );
            return (
              <circle
                key={t.label}
                cx={px}
                cy={py}
                r={rOf(t)}
                fill={entityColor(t.domain, "domain")}
                fillOpacity={dim ? 0.2 : t.mixed ? 0.4 : active ? 1 : 0.85}
                stroke={active ? "var(--color-brand)" : SURFACE}
                strokeWidth={2}
                style={fade}
              />
            );
          })}
          {/* direct labels — ink tokens, never series colour; leaders when displaced */}
          {labels.map(({ t, lx, ly, anchor, leader }) => {
            const { x: px, y: py } = posOf(t);
            const dim = hot !== null && hot !== t.label;
            const active = hot === t.label;
            const big = flagship.has(t.label);
            // leader: dot edge → just short of the label's anchor point
            const ax = lx;
            const ay = ly - 3.5;
            const dl = Math.hypot(ax - px, ay - py) || 1;
            const ux = (ax - px) / dl;
            const uy = (ay - py) / dl;
            return (
              <g key={t.label} pointerEvents="none" opacity={dim ? 0.3 : 1} style={{ transition: "opacity 150ms" }}>
                {leader && (
                  <line
                    x1={px + ux * (rOf(t) + 1.5)}
                    y1={py + uy * (rOf(t) + 1.5)}
                    x2={ax - ux * 5}
                    y2={ay - uy * 5}
                    stroke={LABEL}
                    strokeWidth={1}
                    strokeOpacity={0.55}
                  />
                )}
                <text
                  x={lx}
                  y={ly}
                  textAnchor={anchor}
                  fontSize={10.5}
                  fontWeight={active || big ? 600 : 500}
                  fill={active ? INK : INK2}
                  stroke={SURFACE}
                  strokeWidth={3}
                  paintOrder="stroke"
                >
                  {t.label}
                </text>
              </g>
            );
          })}
          {/* hit layer: ≥ 24px targets over every dot, keyboard reachable */}
          {drawn.map((t) => {
            const { x: px, y: py } = posOf(t);
            return (
              <circle
                key={t.label}
                cx={px}
                cy={py}
                r={Math.max(rOf(t) + 6, 12)}
                fill="transparent"
                tabIndex={0}
                aria-label={`${t.label} (${t.domain}): ${cap(t.maturity) || "unplaced"}, ${t.coverage} articles${t.thin_signal ? ", thin signal" : ""}`}
                className={
                  t.tech
                    ? "cursor-pointer outline-none focus-visible:stroke-[color:var(--color-brand)]"
                    : "cursor-default outline-none focus-visible:stroke-[color:var(--color-brand)]"
                }
                strokeWidth={1.5}
                role={t.tech ? "link" : undefined}
                onPointerMove={() => {
                  show(t, px, py);
                  setHot(t.label);
                }}
                onPointerLeave={() => {
                  setTip(null);
                  setHot(null);
                }}
                onFocus={() => {
                  show(t, px, py);
                  setHot(t.label);
                }}
                onBlur={() => {
                  setTip(null);
                  setHot(null);
                }}
                /* dot → this technology's dossier page */
                onClick={() => t.tech && navigate(`/tech/${t.tech}`)}
                onKeyDown={(e) => {
                  if (t.tech && (e.key === "Enter" || e.key === " ")) navigate(`/tech/${t.tech}`);
                }}
              />
            );
          })}
        </svg>
      )}
      <Overlay tip={tip} width={width} />
      <Legend className="mt-2" items={domains.map((d) => ({ label: d, color: entityColor(d, "domain"), shape: "dot" as const }))} />
    </div>
  );
}

/* ── Diffusion strip — adopter groups as one-hue ordinal columns ─────────────
   Pre-chasm vs mainstream is an ordered split of ordered stages → two steps
   of the sequential ramp (never two identity hues); the chasm itself is a
   labeled threshold marker. Counts stay as direct labels; adopter-group
   tooltips carry the top players. */
function DiffusionStrip({ points, order }: { points: DiffusionPoint[]; order: string[] }) {
  const byStage = new Map(points.map((p) => [p.stage, p]));
  const max = Math.max(1, ...points.map((p) => p.count));
  if (!points.length)
    return <p className="py-6 text-center text-[12.5px] text-faint">No adoption-classified items in scope.</p>;
  // Chasm flag comes from the payload (single source of truth); fall back to
  // the conventional index cut only for stages with no classified items.
  const crossedOf = (stage: string, i: number) => {
    const p = byStage.get(stage);
    return p ? p.crossed : i >= 2;
  };
  const chasmIdx = order.findIndex((s, i) => crossedOf(s, i));
  const PRE = "var(--color-seq-400)";
  const MAIN = "var(--color-seq-700)";

  return (
    <div>
      <div className="relative">
        {chasmIdx > 0 && (
          <div
            className="pointer-events-none absolute top-0 z-[1] h-[160px]"
            style={{ left: `${(chasmIdx / order.length) * 100}%` }}
          >
            <div
              className="h-full w-0 border-l border-dashed opacity-80"
              style={{ borderColor: "var(--color-status-serious)" }}
            />
            <span className="absolute left-1.5 top-0 whitespace-nowrap text-[10px] font-semibold text-muted">
              the chasm
            </span>
          </div>
        )}
        <div className="flex items-start gap-1">
          {order.map((stage, i) => {
            const p = byStage.get(stage);
            const count = p?.count ?? 0;
            const crossed = crossedOf(stage, i);
            // Proportional height (no floor — a 40px pedestal lies about magnitude);
            // nonzero counts keep a 2px sliver so they never vanish, zero stays zero.
            const h = count > 0 ? Math.max(2, (count / max) * 150) : 0;
            return (
              <div
                key={stage}
                tabIndex={0}
                aria-label={`${cap(stage)}: ${count} items${p?.top ? `; top players ${p.top}` : ""}`}
                className="group relative flex flex-1 flex-col items-center gap-2 outline-none"
              >
                <div className="flex w-full items-end justify-center" style={{ height: 160 }}>
                  {/* ≤ 24px column, 4px rounded data end, square baseline */}
                  <div
                    className="w-6 rounded-t-[4px]"
                    style={{ height: h, background: crossed ? MAIN : PRE, opacity: count ? 1 : 0.3 }}
                  />
                </div>
                {/* direct value label — the tooltip never gates the count */}
                <div className="num text-[13px] font-semibold text-ink">{count}</div>
                <div className="text-center text-[10.5px] capitalize leading-tight text-faint">{cap(stage)}</div>
                {p?.top && (
                  <div className="line-clamp-2 max-w-[110px] text-center text-[10px] leading-tight text-faint/80">
                    {p.top}
                  </div>
                )}
                {/* adopter-group tooltip (hover + keyboard focus) */}
                <div
                  className="pointer-events-none absolute left-1/2 z-10 hidden w-max max-w-[240px] group-focus-visible:block group-hover:block"
                  style={{ top: 160 - h - 6, transform: "translate(-50%, -100%)" }}
                >
                  <VizTooltip>
                    <div className="mb-0.5 font-semibold" style={{ color: INK }}>
                      <span className="capitalize">{cap(stage)}</span>
                      <span className="ml-1.5 text-[11px] font-normal" style={{ color: INK2 }}>
                        {crossed ? "mainstream" : "early market"}
                      </span>
                    </div>
                    <div className="num font-semibold" style={{ color: INK }}>
                      {count} <span className="font-normal" style={{ color: INK2 }}>items</span>
                    </div>
                    {p?.top && (
                      <div className="mt-0.5" style={{ color: INK2 }}>
                        Top players: {p.top}
                      </div>
                    )}
                  </VizTooltip>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <Legend
        className="mt-3"
        items={[
          { label: "Early market (pre-chasm)", color: PRE, shape: "rect" as const },
          { label: "Mainstream (crossed)", color: MAIN, shape: "rect" as const },
        ]}
      />
    </div>
  );
}

function TransitionsList({ transitions }: { transitions: Transition[] }) {
  // Forward moves are the real signal; backward moves are near-impossible on these
  // monotonic axes, so they're downranked into a collapsed audit trail — never dropped
  // (mirrors the Streamlit expander from commit da155e5).
  const forward = transitions.filter((t) => !t.backward);
  const backward = transitions.filter((t) => t.backward);
  const [expanded, setExpanded] = useState(false);
  if (!forward.length && !backward.length)
    return <p className="py-4 text-[12.5px] italic text-faint">No transitions yet — they appear once the snapshot has ≥2 days of history.</p>;
  const visible = expanded ? forward : forward.slice(0, 5);
  return (
    <>
      {forward.length ? (
        <>
          <ul className="space-y-2.5">
            {visible.map((t, i) => (
              <li key={i} className="text-[13px] leading-snug">
                <Link
                  to={`/tech/${t.technology}`}
                  className="font-semibold text-ink no-underline hover:underline"
                >
                  {t.label}
                </Link>{" "}
                <span className="text-faint">· {t.dimension}</span>{" "}
                <span className="capitalize text-ink-soft">{cap(t.from)} → {cap(t.to)}</span>{" "}
                {/* literal space before the badge so copied text reads
                    "early adopters pending", not "early adopterspending" */}
                {t.contested ? (
                  <Badge variant="warn" className="ml-1">contested</Badge>
                ) : t.confirmed === false ? (
                  <Badge variant="neutral" className="ml-1">pending</Badge>
                ) : t.modal_share != null ? (
                  <span className="ml-1 text-[11px] text-faint">{Math.round(t.modal_share * 100)}% agree</span>
                ) : null}
              </li>
            ))}
          </ul>
          {forward.length > 5 && (
            <ShowAll expanded={expanded} onToggle={() => setExpanded((e) => !e)} total={forward.length} />
          )}
        </>
      ) : (
        <p className="py-2 text-[12.5px] italic text-faint">No trustworthy (forward) moves this snapshot.</p>
      )}
      {backward.length > 0 && (
        <details className="mt-3 rounded-lg border border-line bg-canvas px-3 py-2">
          <summary className="cursor-pointer select-none text-[12px] font-medium text-muted">
            Backward moves (re-estimation noise) — {backward.length}
          </summary>
          <p className="mt-2 text-[11.5px] leading-relaxed text-faint">
            Maturity and adoption don't run backward in reality (adoption is cumulative — you don't
            un-cross the chasm), so these are almost certainly re-estimation between snapshots —
            surfaced for audit, not action.
          </p>
          <ul className="mt-2 space-y-2">
            {backward.map((t, i) => (
              <li key={i} className="text-[12.5px] leading-snug text-muted">
                <span className="font-medium text-ink-soft">{t.label}</span> <span className="text-faint">· {t.dimension}</span>{" "}
                <span className="capitalize">{cap(t.from)} → {cap(t.to)}</span>
                {t.suspect && <Badge variant="neutral" className="ml-1.5">suspect</Badge>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

function ConvergenceList({ seams, note }: { seams: Seam[]; note: string }) {
  const [expanded, setExpanded] = useState(false);
  if (!seams.length)
    return <p className="py-6 text-[12.5px] italic text-faint">No entity bridges two sector domains in the window yet.</p>;
  const { lead, rest } = splitRead(note);
  const visible = expanded ? seams : seams.slice(0, 4);
  return (
    <>
      {lead && <p className="mb-3 text-[12.5px] leading-relaxed text-muted">{lead}</p>}
      <ul className="space-y-3">
        {visible.map((s, i) => (
          <li key={i}>
            <p className="text-[13px] font-semibold text-ink">
              <span className="mr-1 inline-block h-2 w-2 rounded-full align-middle" style={{ background: entityColor(s.domains[0], "domain") }} />
              {s.domains[0]} <span className="text-faint">✕</span>{" "}
              <span className="mr-1 inline-block h-2 w-2 rounded-full align-middle" style={{ background: entityColor(s.domains[1], "domain") }} />
              {s.domains[1]}
              <span className="ml-1.5 text-[11px] font-normal text-faint">· {s.n_bridges} bridging player{s.n_bridges !== 1 ? "s" : ""}</span>
            </p>
            <p className="mt-0.5 text-[12px] text-muted">
              {s.bridges.slice(0, 6).map((b) => `${b.entity} (${b.mentions})`).join(" · ")}
            </p>
          </li>
        ))}
      </ul>
      {seams.length > 4 && <ShowAll expanded={expanded} onToggle={() => setExpanded((e) => !e)} total={seams.length} />}
      <FullRead rest={rest} />
    </>
  );
}

function Scorecard({ cards }: { cards: MotScorecard[] }) {
  const { isAuthed } = useAuth();
  const [sel, setSel] = useState(cards[0]?.entity ?? "");
  const { run, jobForSlot, tick } = useActions();
  const [read, setRead] = useState<StrategistRead | null>(null);
  const [asOf, setAsOf] = useState<string | undefined>();

  useEffect(() => {
    let alive = true;
    setRead(null);
    if (!sel) return;
    api
      .motScorecardRead(sel)
      .then((r) => alive && (setRead(r.read), setAsOf(r.as_of)))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [sel, tick]);

  if (!cards.length) return <p className="py-6 text-[12.5px] italic text-faint">No named entities in the classified set yet.</p>;
  const card = cards.find((c) => c.entity === sel) ?? cards[0];
  const slot = `scorecard-${sel}`;
  const job = jobForSlot(slot);
  const running = job?.status === "running";

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select value={card.entity} onChange={setSel} options={cards.map((c) => [c.entity, c.entity] as [string, string])} className="min-w-[200px]" />
        {/* Generation spends LLM budget and writes a re-served row — admin-only,
            matching the require_admin gate on POST /api/actions/scorecard. */}
        {isAuthed && (
          <button
            onClick={() => run({ slot, path: `/api/actions/scorecard/${encodeURIComponent(sel)}`, label: `Analyst's read · ${sel}` })}
            disabled={running}
            className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-[13px] font-medium text-ink-soft transition-colors hover:border-line-strong hover:text-ink disabled:opacity-60"
          >
            <Sparkles className="h-3.5 w-3.5" />
            {running ? "Generating…" : "Generate analyst's read"}
          </button>
        )}
      </div>
      {job && job.steps.length > 0 && <ProgressPanel job={job} />}
      <p className="mb-3 mt-1 text-[12.5px] text-muted">
        <span className="font-semibold text-ink">{card.entity}</span> · {card.mentions} classified mention{card.mentions !== 1 ? "s" : ""} across {card.feeds.length} feed{card.feeds.length !== 1 ? "s" : ""}
        {card.feeds.length ? `: ${card.feeds.join(", ")}` : ""}
      </p>
      <ul className="grid gap-x-8 gap-y-2 md:grid-cols-2">
        {card.questions.map((qa, i) => (
          <li key={i} className="text-[12.5px] leading-snug">
            <span className="font-semibold text-ink">{qa.q}</span> — <span className="text-ink-soft">{strip(qa.a)}</span>
          </li>
        ))}
      </ul>
      {read && <FocusedRead read={read} asOf={asOf} entity={card.entity} />}
    </>
  );
}

function FocusedRead({ read, asOf, entity }: { read: StrategistRead; asOf?: string; entity: string }) {
  return (
    <div className="mt-5 rounded-xl border border-brand/20 bg-brand-soft/40 p-4">
      <p className="text-[10.5px] font-medium uppercase tracking-[0.08em] text-brand">
        Strategist's read on {entity}
        {asOf ? ` · ${asOf}` : ""}
      </p>
      {read.bottom_line && <p className="mt-1.5 text-[13.5px] font-medium leading-relaxed text-ink">{read.bottom_line}</p>}
      {(read.signals ?? []).slice(0, 4).map((s, i) => (
        <div key={i} className="mt-3">
          <p className="text-[12.5px] font-semibold text-ink">{s.title}</p>
          <p className="line-clamp-2 text-[12px] leading-relaxed text-muted">{s.implication}</p>
          {s.action && (
            <p className="mt-0.5 text-[11.5px]">
              <span className="font-semibold capitalize text-brand">{s.action}</span>
              {s.action_rationale ? <span className="text-faint"> — {s.action_rationale}</span> : null}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

/* ── Standards battles — factor scores over time per contested standard ──────
   Evidence lists, not magnitude encodings: each battle is a named timeline of
   dated Strategist reads with the four classic standards-battle factors
   (installed base / complementary goods / openness / timing) tallied as chips. */

const STANDARDS_FACTORS = ["installed base", "complementary goods", "openness", "timing"];

function StandardsBattles({ battles }: { battles: StandardsBattle[] }) {
  if (!battles.length)
    return (
      <p className="py-6 text-[12.5px] italic text-faint">
        No contested standards in the tracked window yet.
      </p>
    );
  return (
    <ul className="space-y-5">
      {battles.map((b) => (
        <StandardsBattleRow key={b.battle} battle={b} />
      ))}
    </ul>
  );
}

function StandardsBattleRow({ battle }: { battle: StandardsBattle }) {
  const [expanded, setExpanded] = useState(false);
  const obs = expanded ? battle.observations : battle.observations.slice(0, 3);
  const span =
    battle.first_seen && battle.last_seen && battle.first_seen !== battle.last_seen
      ? `${battle.first_seen} → ${battle.last_seen}`
      : battle.last_seen;
  return (
    <li>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-semibold text-ink">{battle.battle}</span>
        {battle.current_leader && <Badge variant="brand">leads · {battle.current_leader}</Badge>}
        {battle.leader_changes > 0 && (
          <Badge variant="warn">
            {battle.leader_changes} lead change{battle.leader_changes !== 1 ? "s" : ""}
          </Badge>
        )}
        {span && <span className="num text-[11px] text-faint">{span}</span>}
      </div>
      {/* factor scorecard — always all four, zeros faded */}
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {STANDARDS_FACTORS.map((f) => {
          const n = battle.factor_counts?.[f] ?? 0;
          return (
            <span
              key={f}
              title={`${f}: cited ${n} time${n !== 1 ? "s" : ""} as the basis of the lead`}
              className={`inline-flex items-center gap-1 rounded-md border border-line px-1.5 py-0.5 text-[11px] ${
                n ? "text-ink-soft" : "text-faint opacity-60"
              }`}
            >
              {f}
              <span className="num font-semibold">{n}</span>
            </span>
          );
        })}
      </div>
      {/* dated observation timeline, newest first */}
      <ul className="mt-2 space-y-1.5">
        {obs.map((o, i) => (
          <li key={i} className="text-[12px] leading-snug text-muted">
            <span className="num text-faint">{o.as_of ?? "—"}</span>
            {o.leader && (
              <>
                {" · "}
                <span className="font-medium text-ink-soft">{o.leader}</span>
              </>
            )}
            {o.read && <> · {o.read}</>}
          </li>
        ))}
      </ul>
      {battle.observations.length > 3 && (
        <ShowAll
          expanded={expanded}
          onToggle={() => setExpanded((e) => !e)}
          total={battle.observations.length}
        />
      )}
      {battle.single_observation && (
        <p className="mt-1 text-[11px] italic text-faint">
          Single observation — one brief's read, not yet a tracked battle.
        </p>
      )}
    </li>
  );
}

const LENS_DIMS: [string, string][] = [
  ["maturity_stage", "Maturity"],
  ["adoption_stage", "Adoption"],
  ["strategic_move", "Strategic move"],
];

function BrowseLens({ rows }: { rows: MotPayload["browse"] }) {
  const [dim, setDim] = useState("maturity_stage");
  const [expanded, setExpanded] = useState(false);
  const values = Array.from(new Set(rows.map((r) => (r[dim] as string) || "n/a"))).sort();
  const [value, setValue] = useState(values[0] ?? "");
  const active = values.includes(value) ? value : values[0];
  const matches = rows.filter((r) => ((r[dim] as string) || "n/a") === active);
  const capN = Math.min(matches.length, 60);
  const visible = expanded ? matches.slice(0, 60) : matches.slice(0, 6);
  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Segmented value={dim} onChange={(d) => setDim(d)} options={LENS_DIMS} />
        <Select value={active ?? ""} onChange={setValue} options={values.map((v) => [v, `${v} (${rows.filter((r) => ((r[dim] as string) || "n/a") === v).length})`] as [string, string])} />
      </div>
      <ul className="divide-y divide-line">
        {visible.map((s, i) => (
          <StoryRow key={i} story={s} />
        ))}
      </ul>
      {matches.length > 6 && <ShowAll expanded={expanded} onToggle={() => setExpanded((e) => !e)} total={capN} />}
      {expanded && matches.length > 60 && (
        <p className="mt-1.5 text-[11.5px] text-faint">Showing the 60 most recent of {matches.length} matches.</p>
      )}
    </>
  );
}

/** Export dossier — one compact row: pick a technology, download the citable
 *  one-pager (MD/PDF) from /api/mot/dossier. Plain <a> links via apiUrl()
 *  (the DownloadButton pattern in TrackRecord.tsx — in prod the SPA and API
 *  are on different origins, so a relative href would 404). */
function DossierExport({ techs }: { techs: MotPayload["technologies"] }) {
  const options = useMemo(
    () =>
      techs
        .filter((t): t is typeof t & { tech: string } => Boolean(t.tech))
        .map((t) => [t.tech, t.label] as [string, string])
        .sort((a, b) => a[1].localeCompare(b[1])),
    [techs],
  );
  const [sel, setSel] = useState(options[0]?.[0] ?? "");
  if (options.length === 0) return null;
  const tech = options.some(([v]) => v === sel) ? sel : options[0][0];
  const date = new Date().toISOString().slice(0, 10);
  const link = (fmt: "md" | "pdf") => (
    <a
      href={apiUrl(`/api/mot/dossier?tech=${encodeURIComponent(tech)}&fmt=${fmt}`)}
      download={`pharos-dossier-${tech}-${date}.${fmt}`}
      className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12px] font-medium text-ink-soft transition-colors hover:border-line-strong hover:text-ink"
      title={`Download the ${tech} dossier (${fmt.toUpperCase()})`}
    >
      <Download className="h-3 w-3" />
      {fmt.toUpperCase()}
    </a>
  );
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="hidden text-[11.5px] font-medium text-muted sm:inline">Export dossier</span>
      <Select value={tech} onChange={setSel} options={options} className="max-w-[180px]" />
      <Link
        to={`/tech/${tech}`}
        className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12px] font-medium text-ink-soft no-underline transition-colors hover:border-line-strong hover:text-ink"
        title={`Open the ${tech} dossier page`}
      >
        Open page
      </Link>
      {link("md")}
      {link("pdf")}
    </div>
  );
}

/** Self-serve technology tracking — "adding a technology is one entry", as an
 *  admin form instead of a code edit (POST /api/mot/technologies). */
function TrackTechnologyForm({ domains, onChanged }: { domains: string[]; onChanged: () => void }) {
  const [label, setLabel] = useState("");
  const [domain, setDomain] = useState(domains[0] ?? "");
  const [keywords, setKeywords] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!domains.length) return null;
  const activeDomain = domains.includes(domain) ? domain : domains[0];
  const kws = keywords
    .split(",")
    .map((k) => k.trim())
    .filter(Boolean);
  const inputCls =
    "rounded-lg border border-line bg-canvas px-3 py-1.5 text-[12.5px] text-ink outline-none transition-colors placeholder:text-faint focus:border-brand";

  async function add() {
    setBusy(true);
    setError(null);
    const r = await api.trackTechnology(label.trim(), activeDomain, kws);
    setBusy(false);
    if (!r.ok) {
      setError(r.error ?? "Could not add the technology");
      return;
    }
    setLabel("");
    setKeywords("");
    onChanged();
  }

  return (
    <div className="mt-4 rounded-xl border border-dashed border-line bg-canvas p-4">
      <p className="mb-2 text-[12px] font-semibold text-ink">Track a technology</p>
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={label}
          maxLength={60}
          placeholder="Label — e.g. Edge AI chips"
          aria-label="Technology label"
          onChange={(e) => setLabel(e.target.value)}
          className={`${inputCls} w-full sm:w-[200px]`}
        />
        <Select
          value={activeDomain}
          onChange={setDomain}
          options={domains.map((d) => [d, d] as [string, string])}
        />
        <input
          type="text"
          value={keywords}
          placeholder="Keywords, comma-separated — e.g. edge ai, npu, on-device"
          aria-label="Match keywords (comma-separated)"
          onChange={(e) => setKeywords(e.target.value)}
          className={`${inputCls} min-w-[220px] flex-1`}
        />
        <button
          type="button"
          disabled={busy || label.trim().length < 2 || kws.length === 0 || kws.length > 10}
          onClick={() => void add()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-[12.5px] font-medium text-white transition-opacity disabled:opacity-50"
        >
          <Plus className="h-3.5 w-3.5" />
          {busy ? "Adding…" : "Track"}
        </button>
      </div>
      <p className="mt-2 text-[11.5px] leading-relaxed text-faint">
        Keywords are lowercased substrings matched against headline + summary + tags + companies
        (1-10, comma-separated). A new technology appears as{" "}
        <span className="font-medium text-muted">watching — insufficient evidence</span> until it
        accumulates classified coverage; it joins the curves automatically once past the evidence
        floor.
      </p>
      {error && <p className="mt-1.5 text-[12px] text-down">{error}</p>}
    </div>
  );
}

function PlacementTable({
  techs,
  floor,
  onChanged,
}: {
  techs: MotPayload["technologies"];
  floor: number;
  onChanged: () => void;
}) {
  const { isAuthed } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  async function archive(t: TechPoint) {
    if (!t.tech) return;
    setError(null);
    const r = await api.archiveTechnology(t.tech);
    if (!r.ok) setError(r.error ?? `Could not archive ${t.label}`);
    else onChanged();
  }
  // Taxonomy misfits (lifecycle_fit=false) get a footnote, not a row — a single
  // lifecycle label is a forced fit for them, so a stage would mislead.
  // Watching techs (< evidence floor stage articles) are the opposite: they KEEP
  // their row — visibly tracked — but show a "watching" badge instead of a stage.
  const misfits = techs.filter((t) => t.lifecycle_fit === false);
  const sorted = [...techs].filter((t) => t.lifecycle_fit !== false).sort((a, b) => b.coverage - a.coverage);
  const visible = expanded ? sorted : sorted.slice(0, 8);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-faint">
            <th className="py-2 pr-3 font-medium">Technology</th>
            <th className="px-2 py-2 font-medium">Domain</th>
            <th className="px-2 py-2 font-medium">Maturity</th>
            <th className="px-2 py-2 font-medium">Adoption</th>
            <th className="px-2 py-2 font-medium">Regime</th>
            <th className="px-2 py-2 text-right font-medium" title="Articles matching the displayed maturity stage (not the raw article total — Explore-Compare shows that as 'Articles')">Stage coverage</th>
            <th className="py-2 pl-2 text-right font-medium">Players</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((t) => (
            <tr key={t.label} className="border-b border-line/60 last:border-0">
              <td className="py-2 pr-3 font-medium text-ink">
                <span className="mr-1.5 inline-block h-2 w-2 rounded-full align-middle" style={{ background: entityColor(t.domain, "domain") }} />
                {t.label}
                {t.thin_signal && !t.watching && (
                  <span title="Fewer than 10 stage-classified articles in the window — placement is low-confidence">
                    <Badge variant="warn" className="ml-1.5">thin</Badge>
                  </span>
                )}
                {/* archive affordance — only on self-serve (DB-sourced) techs */}
                {t.is_custom && isAuthed && (
                  <button
                    type="button"
                    title={`Stop tracking ${t.label} (archived; stage history is kept)`}
                    aria-label={`Archive ${t.label}`}
                    onClick={() => void archive(t)}
                    className="ml-1.5 inline-flex rounded p-0.5 align-middle text-faint transition-colors hover:text-down"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </td>
              <td className="px-2 py-2 text-faint">{t.domain}</td>
              {t.watching ? (
                <td className="px-2 py-2" colSpan={2}>
                  <span title={`Rolling-window evidence: ${t.coverage} stage-classified articles is below the ${floor}-article floor — tracked, but not placed on the curves until coverage accrues`}>
                    <Badge variant="warn">{`watching — insufficient evidence (n=${t.coverage}, floor ${floor})`}</Badge>
                  </span>
                </td>
              ) : (
                <>
                  <td className="px-2 py-2 capitalize text-muted">{t.maturity || "—"}{t.mixed ? " *" : ""}</td>
                  <td className="px-2 py-2 capitalize text-muted">{t.adoption || "—"}</td>
                </>
              )}
              <td className="px-2 py-2 capitalize text-muted">{t.regime || "—"}</td>
              <td className="num px-2 py-2 text-right text-muted">{t.coverage}</td>
              <td className="num py-2 pl-2 text-right text-muted">{t.entrants}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {sorted.length > 8 && <ShowAll expanded={expanded} onToggle={() => setExpanded((e) => !e)} total={sorted.length} />}
      {error && <p className="mt-2 text-[12px] text-down">{error}</p>}
      {misfits.length > 0 && (
        <p className="mt-3 text-[11.5px] leading-relaxed text-faint">
          <span className="font-medium text-muted">Not lifecycle-tracked:</span>{" "}
          {misfits.map((m) => `${m.label} — ${m.lifecycle_note || "a single lifecycle label is a forced fit"}`).join(" · ")}
        </p>
      )}
    </div>
  );
}

/* ── Tracked-technology index — the dossier front door ─────────────────────────
   Compact card per technology: stage badge (or watching), domain, coverage.
   Sorted best-covered first so the strongest dossiers lead. */
function TechIndex({ techs }: { techs: TechPoint[] }) {
  const [expanded, setExpanded] = useState(false);
  const sorted = [...techs]
    .filter((t) => t.tech)
    .sort((a, b) => Number(a.watching) - Number(b.watching) || b.coverage - a.coverage);
  const visible = expanded ? sorted : sorted.slice(0, 9);
  return (
    <>
      <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {visible.map((t) => (
          <Link
            key={t.tech}
            to={`/tech/${t.tech}`}
            className="group flex items-center gap-2.5 rounded-xl border border-line bg-surface px-3.5 py-2.5 no-underline transition-colors hover:border-line-strong"
          >
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-semibold text-ink">{t.label}</span>
              <span className="num block text-[11px] text-faint">
                {t.domain} · {t.coverage} article{t.coverage === 1 ? "" : "s"}/30d
              </span>
            </span>
            {t.watching ? (
              <Badge variant="warn">watching</Badge>
            ) : (
              <Badge variant="brand" className="capitalize">{cap(t.maturity) || "—"}</Badge>
            )}
            <ArrowRight className="h-3.5 w-3.5 shrink-0 text-faint transition-transform group-hover:translate-x-0.5" />
          </Link>
        ))}
      </div>
      {sorted.length > 9 && (
        <ShowAll expanded={expanded} onToggle={() => setExpanded((e) => !e)} total={sorted.length} />
      )}
    </>
  );
}
