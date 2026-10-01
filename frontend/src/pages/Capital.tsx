/**
 * Capital & Economics — Phase B redesign on the Phase A primitives (viz.tsx).
 *
 * Every exhibit follows the DESIGN.md contract: ChartFrame card anatomy
 * (title / read line / viz / caption), token-driven colors (sector identity
 * via entityColor, diverging tokens for the event study, status tokens for
 * posture), density folds (collapsedAfter / FoldList), StatTile KPI rows
 * with units in the labels, and a source caption on financial exhibits.
 */
import {
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
  type RefObject,
} from "react";
import {
  Map as MapIcon,
  Compass,
  Waves,
  TrendingUp,
  Landmark,
  Microscope,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  CircleCheck,
  CircleHelp,
  TriangleAlert,
} from "lucide-react";
import { api } from "../lib/api";
import type {
  CapitalPayload,
  DealFlowRow,
  LandscapePoint,
  Move,
  MSItem,
  Reaction,
  Scorecard,
  ShareRow,
} from "../lib/api";
import { useResource } from "../lib/useResource";
import { PageChrome } from "../components/PageChrome";
import { usd, pct, ratioPct, signedPct, multiple, truncate, shortDate } from "../lib/format";
import { glossFor } from "../lib/glossary";
import { median } from "../lib/theme";
import { cn } from "../lib/utils";
import {
  Card,
  CardBody,
  SectionHeading,
  Badge,
  StoryLink,
  Callout,
  Skeleton,
  Insight,
} from "../components/ui";
import {
  ChartFrame,
  HBarList,
  StatTile,
  Legend,
  Tooltip,
  entityColor,
  registerEntities,
  type HBarDatum,
} from "../components/viz";

/* ── chart-chrome tokens (SVG needs literal var() strings) ──────────────────── */

const INK = "var(--color-chart-ink)";
const INK2 = "var(--color-chart-ink-2)";
const LABEL = "var(--color-chart-label)";
const GRID = "var(--color-chart-grid)";
const AXIS = "var(--color-chart-axis)";
const SURFACE = "var(--color-surface)";

/** Provenance caption for every exhibit computed off the financials snapshot.
 *  Undated fallback for snapshots written before the fx_asof migration. */
const FIN_SOURCE = "Source: yfinance fundamentals & prices · FX normalized to USD";

/** Dated source caption once the snapshot carries FX provenance
 *  (migrations/2026-07-03_fx_asof.sql + a financials run); static otherwise. */
function finSource(p: Pick<CapitalPayload, "fx_as_of" | "fx_source">): string {
  return p.fx_as_of
    ? `Source: yfinance · FX as of ${p.fx_as_of} (${p.fx_source ?? "yfinance"})`
    : FIN_SOURCE;
}

/* ── small presentational helpers ───────────────────────────────────────────── */

function Caption({ children }: { children: ReactNode }) {
  return <p className="mt-3 text-[11.5px] leading-snug text-faint">{children}</p>;
}

/** StatTile value with an optional muted sub-line (entity name, split, …). */
function TileValue({ v, sub }: { v: ReactNode; sub?: ReactNode }) {
  return (
    <>
      {v}
      {sub != null && (
        <span className="mt-1.5 block truncate text-[12px] font-normal tracking-normal text-muted">
          {sub}
        </span>
      )}
    </>
  );
}

/* Status chips — reserved state colors, always icon + label, never color alone. */
type Tone = "good" | "warning" | "serious" | "critical" | "neutral";
const TONE_CLASS: Record<Tone, string> = {
  good: "bg-status-good-soft text-status-good",
  warning: "bg-status-warning-soft text-status-warning",
  serious: "bg-status-serious-soft text-status-serious",
  critical: "bg-status-critical-soft text-status-critical",
  neutral: "bg-[color:var(--color-chart-grid)] text-muted",
};
const TONE_ICON: Record<Tone, ComponentType<{ className?: string }>> = {
  good: CircleCheck,
  warning: TriangleAlert,
  serious: TriangleAlert,
  critical: CircleAlert,
  neutral: CircleHelp,
};
function StatusChip({ tone, children }: { tone: Tone; children: ReactNode }) {
  const Icon = TONE_ICON[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold",
        TONE_CLASS[tone],
      )}
    >
      <Icon className="h-3 w-3" />
      {children}
    </span>
  );
}

function ColumnHeader({
  dot,
  title,
  count,
  subtitle,
}: {
  dot: string;
  title: string;
  count: number;
  subtitle: string;
}) {
  return (
    <div className="mb-3">
      <div className="flex items-center gap-2">
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: dot }} />
        <span className="text-[13px] font-semibold tracking-tight text-ink">{title}</span>
        <span className="num text-[12px] text-faint">{count}</span>
      </div>
      <div className="ml-4 mt-0.5 text-[11.5px] leading-snug text-faint">{subtitle}</div>
    </div>
  );
}

/** Density rule for lists: show N items, fold the rest behind "Show all". */
function FoldList({
  items,
  collapsedAfter = 5,
  empty = "none this window",
}: {
  items: ReactNode[];
  collapsedAfter?: number;
  empty?: string;
}) {
  const [open, setOpen] = useState(false);
  if (!items.length) return <p className="py-2 text-[12.5px] italic text-faint">{empty}</p>;
  const shown = open ? items : items.slice(0, collapsedAfter);
  return (
    <>
      <ul className="space-y-2">{shown}</ul>
      {items.length > collapsedAfter && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="mt-2 inline-flex items-center gap-1 text-[11.5px] font-medium text-muted transition-colors hover:text-ink"
        >
          {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          {open ? "Show fewer" : `Show all ${items.length}`}
        </button>
      )}
    </>
  );
}

/** Density rule for secondary exhibits: fold a whole block behind a toggle. */
function Disclosure({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 text-[11.5px] font-medium text-muted transition-colors hover:text-ink"
      >
        {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        {label}
      </button>
      {open && <div className="mt-3">{children}</div>}
    </div>
  );
}

function moveItems(moves: Move[]): ReactNode[] {
  return moves.map((m, i) => (
    <li key={i} className="text-[13px] leading-snug">
      {m.companies?.[0] && <span className="font-semibold text-ink">{m.companies[0]} · </span>}
      <StoryLink href={m.url}>{truncate(m.title, 80)}</StoryLink>
      {m.feed && <span className="ml-1.5 text-[11px] text-faint">{m.feed}</span>}
    </li>
  ));
}

function msItems(items: MSItem[]): ReactNode[] {
  return items.map((m, i) => (
    <li key={i} className="text-[13px] leading-snug">
      {m.companies?.[0] && <span className="font-semibold text-ink">{m.companies[0]} · </span>}
      <StoryLink href={m.url}>{truncate(m.title, 80)}</StoryLink>
      {m.feed && <span className="ml-1.5 text-[11px] text-faint">{m.feed}</span>}
      {m.impact === "material" && (
        <Badge variant="commit" className="ml-1.5">
          material
        </Badge>
      )}
    </li>
  ));
}

/* ── shared bits for the custom (bubble) chart ─────────────────────────────── */

function useBoxWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
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

function TipLayer({ tip, width }: { tip: Tip | null; width: number }) {
  if (!tip) return null;
  const flip = width > 0 && tip.x > width - 200;
  return (
    <div
      className="pointer-events-none absolute z-10"
      style={{
        left: tip.x,
        top: tip.y,
        transform: flip ? "translate(calc(-100% - 12px), -50%)" : "translate(12px, -50%)",
      }}
    >
      <Tooltip>{tip.body}</Tooltip>
    </div>
  );
}

function roundTicks(max: number, want = 5): number[] {
  const raw = max / Math.max(1, want);
  const mag = 10 ** Math.floor(Math.log10(raw || 1));
  const n = raw / mag;
  const step = (n > 5 ? 10 : n > 2 ? 5 : n > 1 ? 2 : 1) * mag;
  const out: number[] = [];
  for (let v = 0; v <= max + step * 1e-6; v += step) out.push(v);
  return out;
}

function logTicks(lo: number, hi: number): number[] {
  const out: number[] = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) {
    for (const m of [1, 2, 5]) {
      const v = m * 10 ** e;
      if (v >= lo && v <= hi) out.push(v);
    }
  }
  return out.length > 7 ? out.filter((_, i) => i % 2 === 0) : out;
}

/* ── §2 flagship — investment landscape 2×2 bubble chart ────────────────────── */

function LandscapeBubbles({
  points,
  sectors,
  medX,
  medY,
  xCap,
}: {
  points: LandscapePoint[];
  sectors: string[];
  medX: number;
  medY: number;
  /** p95-driven x-domain cap (%): points beyond it pin at the right edge. */
  xCap: number;
}) {
  const [ref, width] = useBoxWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip | null>(null);
  const [hot, setHot] = useState<number | null>(null);

  const height = 420;
  const M = { top: 24, right: 16, bottom: 52, left: 56 };
  const plotW = Math.max(0, width - M.left - M.right);
  const plotH = height - M.top - M.bottom;

  /* x-domain: capped at xCap so 2 biotech-style outliers can't squash the
     cluster; outliers pin at the edge with a "→ true%" label. */
  const rawXMax = Math.max(1, ...points.map((p) => p.intensity));
  const xMax = rawXMax > xCap ? xCap : Math.min(xCap, rawXMax * 1.08);
  const pinned = (p: LandscapePoint) => p.intensity > xMax;
  const nPinned = points.filter(pinned).length;
  const mults = points.map((p) => p.multiple);
  const yLo = Math.max(0.1, Math.min(...mults) * 0.7);
  const yHi = Math.max(...mults) * 1.35;
  const lg = Math.log10;
  const xOf = (v: number) => M.left + (Math.min(v, xMax) / xMax) * plotW;
  const yOf = (v: number) =>
    M.top + plotH - ((lg(v) - lg(yLo)) / (lg(yHi) - lg(yLo) || 1)) * plotH;

  const capMax = Math.max(1, ...points.map((p) => p.market_cap));
  const rOf = (cap: number) => 4 + Math.sqrt(Math.max(cap, 0) / capMax) * 18;

  // big bubbles first so small ones stay hoverable on top
  const ordered = useMemo(
    () => [...points].sort((a, b) => b.market_cap - a.market_cap),
    [points],
  );

  /* Legend hygiene: `sectors` is the app-wide registration list (union across
     exhibits, kept for color stability) — the legend only names sectors that
     actually appear among the plotted points. */
  const legendSectors = useMemo(
    () => sectors.filter((s) => points.some((p) => p.sector === s)),
    [sectors, points],
  );

  const show = (p: LandscapePoint) =>
    setTip({
      x: xOf(p.intensity),
      y: yOf(p.multiple),
      body: (
        <div>
          <div className="font-semibold" style={{ color: INK }}>
            {p.entity}
          </div>
          <div className="mb-1 text-faint">{p.sector}</div>
          <div className="num" style={{ color: INK2 }}>
            Intensity {pct(p.intensity, 1)} (R&D {pct(p.rd_pct, 0)} + capex {pct(p.capex_pct, 0)})
          </div>
          <div className="num" style={{ color: INK2 }}>
            Valuation {multiple(p.multiple)} P/S
          </div>
          <div className="num" style={{ color: INK2 }}>
            Market cap {usd(p.market_cap)}
          </div>
        </div>
      ),
    });

  /* Honest axis: with pinned outliers the last tick reads ">{cap}%" at the
     edge; drop regular ticks that would collide with it. */
  const xTicks = roundTicks(xMax).filter(
    (t) => !nPinned || xOf(xMax) - xOf(t) > 34,
  );
  const yTicks = logTicks(yLo, yHi);
  const mx = xOf(Math.min(medX, xMax));
  const my = yOf(Math.min(Math.max(medY, yLo), yHi));

  const quad = (x: number, y: number, anchor: "start" | "end", text: string) => (
    <text
      x={x}
      y={y}
      textAnchor={anchor}
      fontSize={10}
      fontWeight={500}
      letterSpacing="0.06em"
      fill={LABEL}
      style={{ textTransform: "uppercase" }}
    >
      {text}
    </text>
  );

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <svg width={width} height={height} role="img" className="block">
          {/* recessive grid on the y ticks only (log scale carries the reading) */}
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={M.left} x2={M.left + plotW} y1={yOf(t)} y2={yOf(t)} stroke={GRID} strokeWidth={1} />
              <text
                x={M.left - 8}
                y={yOf(t)}
                textAnchor="end"
                dominantBaseline="central"
                fontSize={11}
                className="num"
                fill={LABEL}
              >
                {multiple(t, t < 1 ? 1 : 0)}
              </text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text
              key={t}
              x={xOf(t)}
              y={M.top + plotH + 16}
              textAnchor="middle"
              fontSize={11}
              className="num"
              fill={LABEL}
            >
              {pct(t, 0)}
            </text>
          ))}
          {nPinned > 0 && (
            <text
              x={M.left + plotW}
              y={M.top + plotH + 16}
              textAnchor="end"
              fontSize={11}
              className="num"
              fill={LABEL}
            >
              {">"}
              {pct(xMax, 0)}
            </text>
          )}
          {/* single axis per dimension */}
          <line x1={M.left} x2={M.left + plotW} y1={M.top + plotH} y2={M.top + plotH} stroke={AXIS} strokeWidth={1} />
          <line x1={M.left} x2={M.left} y1={M.top} y2={M.top + plotH} stroke={AXIS} strokeWidth={1} />

          {/* quadrant dividers at the sample medians (solid hairlines) */}
          <line x1={mx} x2={mx} y1={M.top} y2={M.top + plotH} stroke={AXIS} strokeWidth={1} />
          <line x1={M.left} x2={M.left + plotW} y1={my} y2={my} stroke={AXIS} strokeWidth={1} />

          {/* quadrant labels in muted ink */}
          {quad(M.left + 8, M.top + 14, "start", "Premium without the spend")}
          {quad(M.left + plotW - 8, M.top + 14, "end", "Betting big — market believes")}
          {quad(M.left + 8, M.top + plotH - 8, "start", "Harvesting")}
          {quad(M.left + plotW - 8, M.top + plotH - 8, "end", "Betting big — not yet rewarded")}

          {/* bubbles: color = sector identity, area = market cap, 2px surface ring */}
          {ordered.map((p, i) => {
            const cx = xOf(p.intensity);
            const cy = yOf(p.multiple);
            const r = rOf(p.market_cap);
            const pin = pinned(p);
            return (
              <g key={p.entity ?? i}>
                {pin ? (
                  <>
                    {/* off-scale outlier: pinned at the edge as an open
                        dashed ring + "→ true%" so the value is never hidden */}
                    <circle
                      cx={cx}
                      cy={cy}
                      r={r}
                      fill="none"
                      stroke={entityColor(p.sector, "sector")}
                      strokeWidth={2}
                      strokeDasharray="4 3"
                      strokeOpacity={hot === i ? 1 : 0.85}
                    />
                    <text
                      x={cx - r - 6}
                      y={cy}
                      textAnchor="end"
                      dominantBaseline="central"
                      fontSize={10}
                      className="num"
                      fill={INK2}
                    >
                      {"→ "}
                      {pct(p.intensity, 0)}
                    </text>
                  </>
                ) : (
                  <circle
                    cx={cx}
                    cy={cy}
                    r={r}
                    fill={entityColor(p.sector, "sector")}
                    fillOpacity={hot === i ? 1 : 0.85}
                    stroke={SURFACE}
                    strokeWidth={2}
                  />
                )}
                {/* hit target ≥ 24px diameter, keyboard-focusable */}
                <circle
                  cx={cx}
                  cy={cy}
                  r={Math.max(r + 4, 13)}
                  fill="transparent"
                  tabIndex={0}
                  aria-label={`${p.entity}: intensity ${pct(p.intensity, 1)}, valuation ${multiple(p.multiple)}, market cap ${usd(p.market_cap)}`}
                  className="cursor-default outline-none focus-visible:stroke-brand"
                  onPointerMove={() => {
                    setHot(i);
                    show(p);
                  }}
                  onPointerLeave={() => {
                    setHot(null);
                    setTip(null);
                  }}
                  onFocus={() => {
                    setHot(i);
                    show(p);
                  }}
                  onBlur={() => {
                    setHot(null);
                    setTip(null);
                  }}
                />
              </g>
            );
          })}

          {/* axis titles — ink tokens, never a series color */}
          <text x={M.left + plotW / 2} y={height - 8} textAnchor="middle" fontSize={11} fill={INK2}>
            Investment intensity — (R&D + capex) / revenue (%)
          </text>
          <text
            transform={`translate(14, ${M.top + plotH / 2}) rotate(-90)`}
            textAnchor="middle"
            fontSize={11}
            fill={INK2}
          >
            Valuation — P/S (×, log)
          </text>
        </svg>
      )}
      <TipLayer tip={tip} width={width} />
      <Legend
        className="mt-2"
        items={legendSectors.map((s) => ({ label: s, color: entityColor(s, "sector"), shape: "dot" as const }))}
      />
    </div>
  );
}

/* ── §4 deal-flow timeline (stacked weekly columns on the option/commitment
      tokens) — discrete counts get discrete marks, not a smoothed area ─────── */

type WeekBar = { week: string; commitment: number; option: number };

const DEAL_SERIES = [
  { key: "commitment", label: "Commitments", color: "var(--color-commit)" },
  { key: "option", label: "Options", color: "var(--color-option)" },
] as const;

/** Vertical column with an optionally 4px-rounded DATA end (top) and a square
 *  baseline end — the vertical twin of viz.tsx's barPath. */
function colPath(x: number, yTop: number, w: number, h: number, roundedTop: boolean): string {
  if (h <= 0 || w <= 0) return "";
  const r = roundedTop ? Math.min(4, w / 2, h) : 0;
  return `M${x},${yTop + h} v${-(h - r)} a${r},${r} 0 0 1 ${r},${-r} h${w - 2 * r} a${r},${r} 0 0 1 ${r},${r} v${h - r} Z`;
}

/** Stacked weekly columns: commitments at the baseline, options on top with a
 *  2px surface gap between the fills; integer y-ticks (they're counts). */
function StackedColumns({ data, height = 220 }: { data: WeekBar[]; height?: number }) {
  const [ref, width] = useBoxWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip | null>(null);

  const M = { top: 8, right: 10, bottom: 24, left: 36 };
  const plotW = Math.max(0, width - M.left - M.right);
  const plotH = height - M.top - M.bottom;
  const n = data.length;

  /* Integer tick scale — counts never get fractional gridlines. */
  const maxTotal = Math.max(1, ...data.map((d) => d.commitment + d.option));
  const step = Math.max(1, Math.ceil(maxTotal / 4));
  const yMax = Math.ceil(maxTotal / step) * step;
  const ticks: number[] = [];
  for (let v = 0; v <= yMax; v += step) ticks.push(v);
  const yOf = (v: number) => M.top + plotH - (v / yMax) * plotH;

  const band = n ? plotW / n : plotW;
  const colW = Math.max(6, Math.min(24, band * 0.6)); // thin marks: ≤ 24px, band keeps air
  const cxOf = (i: number) => M.left + i * band + band / 2;

  /* thin x labels when bands get narrow */
  const labelEvery = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(plotW / 56))));

  const show = (i: number) => {
    const d = data[i];
    setTip({
      x: cxOf(i),
      y: yOf(d.commitment + d.option),
      body: (
        <div>
          <div className="mb-1 font-semibold" style={{ color: INK }}>
            Week of {shortDate(d.week)}
          </div>
          {DEAL_SERIES.map((s) => (
            <div key={s.key} className="flex items-center gap-2 leading-relaxed">
              <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: s.color }} />
              <span className="num font-semibold" style={{ color: INK }}>
                {d[s.key]}
              </span>
              <span style={{ color: INK2 }}>{s.label}</span>
            </div>
          ))}
        </div>
      ),
    });
  };

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <svg width={width} height={height} role="img" className="block">
          {/* recessive grid + integer tick labels */}
          {ticks.map((t) => (
            <g key={t}>
              <line x1={M.left} x2={M.left + plotW} y1={yOf(t)} y2={yOf(t)} stroke={GRID} strokeWidth={1} />
              <text
                x={M.left - 6}
                y={yOf(t)}
                textAnchor="end"
                dominantBaseline="central"
                fontSize={11}
                className="num"
                fill={LABEL}
              >
                {t.toLocaleString()}
              </text>
            </g>
          ))}
          <line x1={M.left} x2={M.left + plotW} y1={yOf(0)} y2={yOf(0)} stroke={AXIS} strokeWidth={1} />
          {data.map((d, i) =>
            i % labelEvery === 0 ? (
              <text key={d.week} x={cxOf(i)} y={height - 6} textAnchor="middle" fontSize={11} fill={LABEL}>
                {shortDate(d.week)}
              </text>
            ) : null,
          )}

          {/* columns: commitments from the baseline, options stacked above with
              a 2px surface gap; only the topmost segment wears the rounded end */}
          {data.map((d, i) => {
            const x = cxOf(i) - colW / 2;
            const yC = yOf(d.commitment);
            const hC = yOf(0) - yC;
            const gap = d.commitment > 0 && d.option > 0 ? 2 : 0;
            const hO = Math.max(0, yC - yOf(d.commitment + d.option) - gap);
            return (
              <g key={d.week}>
                {d.commitment > 0 && (
                  <path d={colPath(x, yC, colW, hC, d.option === 0)} fill={DEAL_SERIES[0].color} />
                )}
                {d.option > 0 && (
                  <path
                    d={colPath(x, yC - gap - hO, colW, hO, true)}
                    fill={DEAL_SERIES[1].color}
                  />
                )}
                {/* full-band hit target (wider than the mark), keyboard-focusable */}
                <rect
                  x={M.left + i * band}
                  y={M.top}
                  width={band}
                  height={plotH}
                  fill="transparent"
                  tabIndex={0}
                  aria-label={`Week of ${shortDate(d.week)}: ${d.commitment} commitments, ${d.option} options`}
                  className="cursor-default outline-none focus-visible:stroke-brand"
                  onPointerMove={() => show(i)}
                  onPointerLeave={() => setTip(null)}
                  onFocus={() => show(i)}
                  onBlur={() => setTip(null)}
                />
              </g>
            );
          })}
        </svg>
      )}
      <TipLayer tip={tip} width={width} />
      <Legend
        className="mt-2"
        items={DEAL_SERIES.map((s) => ({ label: s.label, color: s.color, shape: "rect" as const }))}
      />
    </div>
  );
}

function DealFlowCard({ rows, read }: { rows: DealFlowRow[]; read: string }) {
  const data = useMemo(() => {
    const byWeek = new Map<string, WeekBar>();
    for (const r of rows) {
      const w = byWeek.get(r.week) ?? { week: r.week, commitment: 0, option: 0 };
      w[r.kind] += r.count;
      byWeek.set(r.week, w);
    }
    return [...byWeek.values()].sort((a, b) => a.week.localeCompare(b.week));
  }, [rows]);

  return (
    <ChartFrame
      title="Weekly capital moves"
      read={read}
      caption="News-derived, LLM-classified capital moves · last 8 weeks"
      table={{
        columns: ["Week of", "Commitments", "Options"],
        rows: data.map((d) => [shortDate(d.week), d.commitment, d.option]),
      }}
    >
      {data.length ? (
        <StackedColumns data={data} height={220} />
      ) : (
        <p className="py-6 text-center text-[12.5px] text-faint">no dated capital moves yet</p>
      )}
    </ChartFrame>
  );
}

/* ── §1 posture chips + preserved posture callout ───────────────────────────── */

const FLAG_META: Record<string, { tone: Tone; label: string }> = {
  "over-extension": { tone: "serious", label: "Over-extension risk" },
  timid: { tone: "warning", label: "Timid / late" },
  aligned: { tone: "good", label: "Posture fits field maturity" },
  "low-confidence": { tone: "neutral", label: "Low confidence — thin sample" },
};

function PostureRow({ payload }: { payload: CapitalPayload }) {
  const p = payload.posture;
  const meta = FLAG_META[p.flag];
  if (p.flag === "none") return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {meta && <StatusChip tone={meta.tone}>{meta.label}</StatusChip>}
      <Badge variant="commit">{p.commitment} commitments</Badge>
      <Badge variant="option">{p.option} options</Badge>
      <span className="text-[12px] text-muted">
        stance: <b className="font-semibold text-ink-soft">{p.stance}</b>
        {p.maturity && (
          <>
            {" "}
            · field maturity: <b className="font-semibold text-ink-soft">{p.maturity}</b>
          </>
        )}{" "}
        · n={p.n}
      </span>
    </div>
  );
}

function PostureCallout({ payload }: { payload: CapitalPayload }) {
  const f = payload.posture.flag;
  if (f === "over-extension")
    return (
      <Callout tone="warn">
        <b>Over-extension risk</b> — large, irreversible commitments into an{" "}
        <i>early / uncertain</i> field. Staged options would buy information before betting big.
      </Callout>
    );
  if (f === "timid")
    return (
      <Callout tone="warn">
        <b>Timid / late</b> — small options in a <i>mature</i> field; the option-value window may
        have closed and conviction bets look overdue.
      </Callout>
    );
  if (f === "low-confidence")
    return (
      <p className="text-[12px] italic text-faint">
        Posture read withheld — only {payload.posture.n} clearly-typed capital move(s) in the
        window; too few to call over-extension or timidity. The deals below stand on their own.
      </p>
    );
  return null;
}

/* ── §7 company deep-dive (select preserved; tiles carry units) ─────────────── */

function CompanyDeepDive({ companies, src }: { companies: Scorecard[]; src: string }) {
  const [sel, setSel] = useState(companies[0]?.entity ?? "");
  const card = companies.find((c) => c.entity === sel) ?? companies[0];
  if (!card) return null;
  return (
    <>
      <div className="mb-4 max-w-xs">
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-faint">
          Company
        </label>
        <select
          value={sel}
          onChange={(e) => setSel(e.target.value)}
          className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-[13.5px] text-ink outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
        >
          {companies.map((c) => (
            <option key={c.entity} value={c.entity}>
              {c.entity}
              {c.symbol ? ` (${c.symbol})` : ""}
            </option>
          ))}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="Market cap (USD)" value={card.market_cap ? usd(card.market_cap) : "—"} />
        <StatTile
          label="Valuation (P/S, ×)"
          value={card.multiple != null ? multiple(card.multiple) : "—"}
        />
        <StatTile label="R&D intensity (% of revenue)" value={ratioPct(card.rd_intensity)} />
        <StatTile
          label="Investment intensity (% of revenue)"
          value={ratioPct(card.investment_intensity)}
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {card.sector && <Badge variant="neutral">{card.sector}</Badge>}
        <Badge variant="brand">R&D posture: {card.signal}</Badge>
        {card.reaction && (
          <span className="text-[12px] text-muted">
            latest deal reaction:{" "}
            <b
              className={`num font-semibold ${
                card.reaction.pct < 0 ? "text-down" : "text-up"
              }`}
            >
              {signedPct(card.reaction.pct, 1)}
            </b>{" "}
            (±3 trading days)
          </span>
        )}
        {card.cash != null && (
          <span className="text-[12px] text-muted">
            cash: <b className="num font-semibold text-ink-soft">{usd(card.cash)}</b>
          </span>
        )}
      </div>
      {/* curated-override basis (e.g. Toyota's 20-F R&D) rides the source caption */}
      <Caption>
        {card.rd_basis ? `R&D: ${card.rd_basis} · ` : ""}
        {src}
      </Caption>
    </>
  );
}

/* ── the page ────────────────────────────────────────────────────────────────── */

export function CapitalSkeleton() {
  return (
    <div className="space-y-6">
      <Card>
        <CardBody>
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="mt-2 h-4 w-1/2" />
          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
        </CardBody>
      </Card>
      {Array.from({ length: 3 }).map((_, i) => (
        <Card key={i}>
          <CardBody>
            <Skeleton className="h-4 w-48" />
            <Skeleton className="mt-4 h-64 w-full" />
          </CardBody>
        </Card>
      ))}
    </div>
  );
}

export default function CapitalPage() {
  const resource = useResource(api.capital, { key: "capital" });
  return (
    <PageChrome
      title="Capital & Economics"
      subtitle="How capital and the market are betting on the next S-curve"
      resource={resource}
      skeleton={<CapitalSkeleton />}
    >
      {(data) => <Capital data={data} />}
    </PageChrome>
  );
}

export function Capital({ data }: { data: CapitalPayload }) {
  const k = data.kpis;
  const div = data.divergence;
  /* Source caption for every financial exhibit — dated once FX provenance lands. */
  const src = finSource(data);

  /* Sector identity colors: register the FULL sector list once, in a fixed
     (alphabetical) order, so every exhibit paints a sector the same hue and
     refiltering never repaints. */
  const sectors = useMemo(() => {
    const s = new Set<string>();
    data.landscape.forEach((p) => s.add(p.sector));
    data.sector_rollup.forEach((r) => s.add(r.sector));
    data.market_cap_share.forEach((r) => s.add(r.sector));
    const list = [...s].sort();
    registerEntities(list, "sector");
    return list;
  }, [data]);

  /* Flagship medians + read line. */
  const medX = useMemo(() => median(data.landscape.map((p) => p.intensity)) ?? 0, [data]);
  const medY = useMemo(() => median(data.landscape.map((p) => p.multiple)) ?? 1, [data]);
  /* x-domain cap for the 2×2: p95-driven so a couple of biotech outliers
     (~163% / ~550% intensity) can't squash the cluster into the left edge. */
  const xCap = useMemo(() => {
    const v = data.landscape.map((p) => p.intensity).sort((a, b) => a - b);
    if (!v.length) return 120;
    const p95 = v[Math.max(0, Math.ceil(v.length * 0.95) - 1)];
    return Math.max(120, Math.ceil(p95 / 10) * 10);
  }, [data]);
  const nPinnedX = useMemo(
    () => data.landscape.filter((p) => p.intensity > xCap).length,
    [data, xCap],
  );
  const landscapeRead = useMemo(() => {
    const pts = data.landscape;
    if (!pts.length) return undefined;
    const hot = pts.filter((p) => p.intensity >= medX && p.multiple >= medY);
    const anchor = (hot.length ? hot : pts).reduce((a, b) =>
      b.market_cap > a.market_cap ? b : a,
    );
    return `${hot.length} of ${pts.length} companies out-invest the median (${pct(medX, 0)} of revenue) and still command an above-median multiple — ${anchor.entity} is the biggest such bet.`;
  }, [data, medX, medY]);

  return (
    <div className="space-y-7">
      {/* §1 — executive read */}
      <Card>
        <CardBody>
          <p className="text-[10.5px] font-medium uppercase tracking-[0.08em] text-faint">
            Executive read
          </p>
          <p className="mt-2.5 max-w-3xl text-[15.5px] leading-relaxed text-ink-soft [&_b]:font-semibold [&_b]:text-ink">
            <Synthesis text={data.synthesis} />
          </p>

          {k && (
            <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <StatTile
                label="Deals (count, 30d)"
                value={
                  <TileValue v={k.deals} sub={`${k.commitment} commit · ${k.option} option`} />
                }
              />
              <StatTile
                label="Commit : option (ratio)"
                value={k.ratio}
                help={glossFor("commit:option")}
              />
              <StatTile
                label="Top R&D intensity (% of revenue)"
                value={
                  <TileValue v={k.top_rd ? pct(k.top_rd.pct, 0) : "—"} sub={k.top_rd?.entity} />
                }
              />
              <StatTile
                label="Biggest deal reaction (%, ±3d)"
                value={k.biggest_reaction ? signedPct(k.biggest_reaction.pct, 1) : "—"}
                delta={
                  k.biggest_reaction
                    ? {
                        text: k.biggest_reaction.company,
                        direction: k.biggest_reaction.pct < 0 ? "down" : "up",
                        upIsGood: true,
                      }
                    : undefined
                }
              />
              <StatTile label="Tracked market cap (USD)" value={usd(k.total_market_cap)} />
            </div>
          )}

          <div className="mt-5 space-y-3">
            <PostureRow payload={data} />
            <PostureCallout payload={data} />
          </div>
          <p className="mt-4 border-t border-line pt-3 text-[11.5px] text-faint">
            News-derived · LLM-classified via the MOT lens · {data.row_count.toLocaleString()}{" "}
            stories / 30d · directional signal, not an audited dataset
            {k ? ` · financials: yfinance, FX normalized to USD` : ""}.
          </p>
        </CardBody>
      </Card>

      {/* Degraded states — say WHY the financial sections are missing instead of
          silently dropping them (Streamlit parity: the run-financials hint). */}
      {!data.have_fin ? (
        <Callout tone="info">
          <b>Financial data isn't available yet</b> — the investment landscape, sector rollup and
          company deep-dive will appear once the next financials refresh completes.
          {import.meta.env.DEV && (
            <>
              {" "}
              (Dev: run <code>python financials_run.py</code> after applying{" "}
              <code>company_financials.sql</code> &amp; <code>stock_prices.sql</code>.)
            </>
          )}
        </Callout>
      ) : data.landscape.length === 0 ? (
        <Callout tone="info">
          Financial snapshots exist but yielded no plottable companies yet — the landscape, rollup
          and intensity sections are hidden until the next full financials refresh.
          {import.meta.env.DEV && (
            <>
              {" "}
              (Dev: re-run <code>financials_run.py</code> — rows are missing revenue/market-cap
              fields.)
            </>
          )}
        </Callout>
      ) : null}

      {/* §2 — investment landscape (flagship 2×2) */}
      {data.landscape.length > 0 && (
        <Card>
          <CardBody>
            <SectionHeading
              icon={<MapIcon className="h-4 w-4" />}
              title="Investment landscape"
              description="Who's funding the next curve, and how richly the market values it."
            />
            <ChartFrame
              title="Investment intensity × valuation"
              read={landscapeRead}
              caption={
                <>
                  Bubble area = market cap · quadrant dividers = sample medians ({pct(medX, 0)},{" "}
                  {multiple(medY)}) · y-axis log
                  {nPinnedX > 0 && (
                    <>
                      {" "}
                      · x-axis capped at {pct(xCap, 0)} (p95); {nPinnedX}{" "}
                      {nPinnedX === 1 ? "outlier" : "outliers"} pinned at the edge with true values
                    </>
                  )}{" "}
                  · table view ranks companies by intensity (median {pct(medX, 0)}) · {src}
                </>
              }
              table={{
                columns: [
                  "Company",
                  "Sector",
                  "Intensity rank",
                  "Intensity (%)",
                  "R&D (%)",
                  "Capex (%)",
                  "P/S (×)",
                  "Market cap",
                ],
                rows: [...data.landscape]
                  .sort((a, b) => b.intensity - a.intensity)
                  .map((p, i) => [
                    p.entity,
                    p.sector,
                    `#${i + 1}`,
                    pct(p.intensity, 1),
                    pct(p.rd_pct, 1),
                    pct(p.capex_pct, 1),
                    multiple(p.multiple),
                    usd(p.market_cap),
                  ]),
              }}
            >
              <LandscapeBubbles
                points={data.landscape}
                sectors={sectors}
                medX={medX}
                medY={medY}
                xCap={xCap}
              />
            </ChartFrame>
          </CardBody>
        </Card>
      )}

      {/* §5 — consensus vs reality (event study) */}
      {!data.have_prices && (
        <Callout tone="info">
          <b>Price history isn't available yet</b> — the consensus-vs-reality event study (deal
          reactions ±3 trading days) will appear once the next financials refresh completes.
          {import.meta.env.DEV && (
            <>
              {" "}
              (Dev: run <code>python financials_run.py</code>.)
            </>
          )}
        </Callout>
      )}
      {div && (
        <Card>
          <CardBody>
            <SectionHeading
              icon={<TrendingUp className="h-4 w-4" />}
              title="Consensus vs. reality — material deals the market shrugged at"
            />
            <EventStudyDistribution reactions={data.reactions} div={div}
                                    read={data.divergence_read} src={src} />
          </CardBody>
        </Card>
      )}

      {/* §3 — sector rollup (market cap, share of tracked value & 30d drift) */}
      {data.sector_rollup.length > 0 && (
        <Card>
          <CardBody>
            <SectionHeading
              icon={<Compass className="h-4 w-4" />}
              title="Sector rollup"
              description="Tracked market cap, share of tracked value & ~30d drift by sector — medians in the table view."
            />
            <p className="mb-3 max-w-3xl text-[12.5px] leading-relaxed text-muted">
              <span className="font-medium text-ink-soft">For strategy teams:</span> a sector
              gaining share of tracked value while tilting toward commitments is consolidating —
              expect partnership windows there to narrow, and price entry accordingly.
            </p>
            <SectorRollup rows={data.sector_rollup} share={data.market_cap_share} src={src} />
          </CardBody>
        </Card>
      )}

      {/* §4 — deal flow & posture */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<Waves className="h-4 w-4" />}
            title="Deal flow & posture — real options vs commitments"
            description="Weekly capital moves — conviction bets vs hedged options."
          />
          <DealFlowCard
            rows={data.deal_flow}
            read={`${data.board.counts.commitment} commitments vs ${data.board.counts.option} options in the window — a ${data.posture.stance} stance.`}
          />
          {data.board_read && <Insight>{data.board_read.replace(/\*\*/g, "")}</Insight>}

          <div className="mt-5 grid gap-6 md:grid-cols-2">
            <div>
              <ColumnHeader
                dot="var(--color-commit)"
                title="Full commitments"
                count={data.board.counts.commitment}
                subtitle="large, irreversible — acquisitions, big capex"
              />
              <FoldList items={moveItems(data.board.commitment)} collapsedAfter={5} />
            </div>
            <div>
              <ColumnHeader
                dot="var(--color-option)"
                title="Real options"
                count={data.board.counts.option}
                subtitle="staged, reversible — funding rounds, pilots, partnerships"
              />
              <FoldList items={moveItems(data.board.option)} collapsedAfter={5} />
            </div>
          </div>

          {/* secondary exhibits fold away so the section leads with deal flow
              plus the commitments/options lists */}
          <div className="mt-6">
            <Disclosure label="Show concentration — by domain & by player">
              <div className="grid gap-6 md:grid-cols-2">
                <ChartFrame
                  title="Concentration by domain"
                  caption="weighted capital-move count per feed"
                >
                  <HBarList
                    data={data.concentration.by_feed.map((c) => ({
                      label: c.feed ?? "—",
                      value: c.count,
                    }))}
                    format={(v) => v.toLocaleString(undefined, { maximumFractionDigits: 1 })}
                    collapsedAfter={5}
                  />
                </ChartFrame>
                <ChartFrame
                  title="Concentration by player"
                  caption="weighted capital-move count per named company"
                >
                  <HBarList
                    data={data.concentration.by_entity.map((c) => ({
                      label: c.entity ?? "—",
                      value: c.count,
                    }))}
                    format={(v) => v.toLocaleString(undefined, { maximumFractionDigits: 1 })}
                    collapsedAfter={5}
                  />
                </ChartFrame>
              </div>
            </Disclosure>
          </div>
        </CardBody>
      </Card>

      {/* §6 — structural shifts */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<Landmark className="h-4 w-4" />}
            title="Structural shifts — market structure & regulation"
            description="M&A / consolidation vs regulatory shifts."
          />
          {data.market_structure_read && (
            <Insight className="mb-4 mt-0">{data.market_structure_read.replace(/\*\*/g, "")}</Insight>
          )}
          <div className="grid gap-6 md:grid-cols-2">
            <div>
              <ColumnHeader
                dot="var(--color-commit)"
                title="Concentrating moves"
                count={data.market_structure.counts.concentrating}
                subtitle="M&A / consolidation — fewer, larger players"
              />
              <FoldList items={msItems(data.market_structure.concentrating)} collapsedAfter={4} />
            </div>
            <div>
              <ColumnHeader
                dot="var(--color-warn)"
                title="Regulation / market failure"
                count={data.market_structure.counts.regulatory}
                subtitle="rules of the game shifting"
              />
              <FoldList items={msItems(data.market_structure.regulatory)} collapsedAfter={4} />
            </div>
          </div>
        </CardBody>
      </Card>

      {/* §7 — company deep-dive */}
      {data.companies.length > 0 && (
        <Card>
          <CardBody>
            <SectionHeading
              icon={<Microscope className="h-4 w-4" />}
              title="Company deep-dive"
              description="Valuation, investment intensity, cash & latest market reaction."
            />
            <p className="mb-3 max-w-3xl text-[12.5px] leading-relaxed text-muted">
              <span className="font-medium text-ink-soft">For strategy teams:</span> read cash and
              investment intensity together — a rival strong on both is funding a land-grab; one
              with neither is a partnership or acquisition conversation waiting to happen.
            </p>
            <CompanyDeepDive companies={data.companies} src={src} />
          </CardBody>
        </Card>
      )}

      {/* universe coverage — a single footer line, not a card */}
      <p className="border-t border-line pt-3 text-[11.5px] leading-snug text-faint">
        {data.coverage.mentions
          ? `Pricing ${data.coverage.tracked_entities} of ${
              data.coverage.tracked_entities + data.coverage.untracked_entities
            } companies mentioned this window (${data.tracked_tickers} tracked tickers) · coverage grows with each financials run.`
          : `Tracking ${data.tracked_tickers} tickers · coverage grows with each financials run.`}
      </p>
    </div>
  );
}

/* ── inline sub-views that need the payload ──────────────────────────────────── */

/** §3 — sector rollup, one exhibit: bars encode tracked market cap (USD) in
 *  sector-identity colors, the direct value label reads the sector's share of
 *  tracked value (%), and the ~30d drift rides each row as a chip. The full
 *  medians table stays as the ChartFrame table twin (now with share & drift). */
function SectorRollup({
  rows,
  share,
  src,
}: {
  rows: CapitalPayload["sector_rollup"];
  share: ShareRow[];
  src: string;
}) {
  const shareBySector = useMemo(
    () => new Map(share.map((s) => [s.sector, s])),
    [share],
  );
  const totalCap = rows.reduce((a, r) => a + r.market_cap, 0) || 1;
  /* share-% label off the bar's own value so bars and labels can't disagree */
  const shareOfCap = (cap: number) => pct((cap / totalCap) * 100, 1);
  const top = rows[0];
  const mover = share.reduce<ShareRow | null>(
    (a, r) => (r.delta != null && Math.abs(r.delta) > Math.abs(a?.delta ?? 0) ? r : a),
    null,
  );
  const data: HBarDatum[] = rows.map((r) => {
    const s = shareBySector.get(r.sector);
    return {
      label: r.sector,
      value: r.market_cap,
      tip: (
        <div className="mt-0.5 space-y-0.5" style={{ color: INK2 }}>
          <div className="num">
            {usd(r.market_cap)} tracked cap
            {s?.delta != null && <> · {signedPct(s.delta, 1)} pp / 30d</>}
          </div>
          <div className="num">
            {r.companies} companies · median intensity{" "}
            {r.intensity != null ? pct(r.intensity, 0) : "—"}
          </div>
          <div className="num">
            median P/S {r.multiple != null ? multiple(r.multiple) : "—"} · R&D{" "}
            {r.rd != null ? pct(r.rd, 0) : "—"}
          </div>
          <div className="num">
            deals {r.commitment}:{r.option} (commit:option)
          </div>
        </div>
      ),
      chip:
        s?.delta != null && Math.abs(s.delta) >= 0.05 ? (
          <Badge variant={s.delta > 0 ? "up" : "down"}>{signedPct(s.delta, 1)} pp</Badge>
        ) : undefined,
    };
  });
  return (
    <ChartFrame
      title="Tracked market cap by sector (USD; labels = share of tracked value)"
      read={
        top
          ? `${top.sector} carries ${usd(top.market_cap)} — ${shareOfCap(top.market_cap)} of tracked value${
              mover?.delta != null
                ? `; ${mover.sector} moved the most, ${signedPct(mover.delta, 1)} pp in ~30 days`
                : ""
            }.`
          : undefined
      }
      caption={
        <>
          Bar length = tracked market cap; value label = share of <i>tracked</i> market value, not
          product market share · chips = ~30d drift (pp) · {src}
        </>
      }
      table={{
        columns: [
          "Sector",
          "Cos",
          "Market cap",
          "Share (%)",
          "Drift (pp, 30d)",
          "Invest %",
          "P/S ×",
          "R&D %",
          "C : O",
        ],
        rows: rows.map((r) => {
          const s = shareBySector.get(r.sector);
          return [
            r.sector,
            r.companies,
            usd(r.market_cap),
            shareOfCap(r.market_cap),
            s?.delta != null ? signedPct(s.delta, 1) : "—",
            r.intensity != null ? pct(r.intensity, 0) : "—",
            r.multiple != null ? multiple(r.multiple) : "—",
            r.rd != null ? pct(r.rd, 0) : "—",
            `${r.commitment}:${r.option}`,
          ];
        }),
      }}
    >
      <HBarList
        data={data}
        colorOf={(l) => entityColor(l, "sector")}
        format={shareOfCap}
        collapsedAfter={6}
      />
    </ChartFrame>
  );
}

/* Render the analytics' lightweight **bold** markdown into real <b> spans. */
function Synthesis({ text }: { text: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return (
    <>
      {parts.map((p, i) => (i % 2 === 1 ? <b key={i}>{p}</b> : <span key={i}>{p}</span>))}
    </>
  );
}

/* ── §5 — the event study as a DISTRIBUTION, not an enumeration ────────────────
   The section's question is "how often does the market ignore what we call
   material?" — a histogram answers it at any n. Signed buckets around the ±2%
   shrug threshold wear the diverging poles; the shrug bucket wears the neutral
   flat token. Two five-row lists name the extremes; the ⊞ table enumerates all
   measured reactions. (Replaced the magnitude-ranked bar list, which hid the
   headline fact that most re-pricings were negative.) */
function EventStudyDistribution({
  reactions,
  div,
  read,
  src,
}: {
  reactions: Reaction[];
  div: NonNullable<CapitalPayload["divergence"]>;
  read: string | null;
  src: string;
}) {
  const BUCKETS: { label: string; test: (p: number) => boolean; color: string }[] = [
    { label: "≤ −10%", test: (p) => p <= -10, color: "var(--color-div-neg)" },
    { label: "−10…−5%", test: (p) => p > -10 && p <= -5, color: "var(--color-div-neg)" },
    { label: "−5…−2%", test: (p) => p > -5 && p < -2, color: "var(--color-div-neg)" },
    { label: "±2% shrug", test: (p) => Math.abs(p) <= 2, color: "var(--color-flat)" },
    { label: "+2…5%", test: (p) => p > 2 && p < 5, color: "var(--color-div-pos)" },
    { label: "+5…10%", test: (p) => p >= 5 && p < 10, color: "var(--color-div-pos)" },
    { label: "≥ +10%", test: (p) => p >= 10, color: "var(--color-div-pos)" },
  ];
  // Per-bucket membership — the hover card shows WHO is behind each count
  // (identity only; the ⊞ table remains the full record).
  const members = BUCKETS.map((b) =>
    [...reactions].filter((r) => b.test(r.pct)).sort((x, y) => Math.abs(y.pct) - Math.abs(x.pct)),
  );
  const counts = members.map((m) => m.length);
  const max = Math.max(1, ...counts);
  const shrugPct = div.divergence_rate != null ? Math.round(div.divergence_rate * 100) : null;

  // The extremes, named: flattest shrugs (material, unpaid-for) and sharpest moves.
  const flattest = [...div.shrugged].sort((a, b) => Math.abs(a.pct) - Math.abs(b.pct)).slice(0, 5);
  const sharpest = [...reactions].sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct)).slice(0, 5);

  const fallbackRead =
    `${div.n_shrugged} of ${div.n} material deals drew a market shrug` +
    (shrugPct != null ? ` — a ${shrugPct}% divergence.` : ".");

  return (
    <ChartFrame
      title="Event study — the distribution of every measured reaction"
      read={read ? read.replace(/\*\*/g, "") : fallbackRead}
      caption={<>Move over ±3 trading days around the story · {src}</>}
      table={{
        columns: ["Deal", "Move (%)", "Verdict"],
        rows: [...reactions]
          .sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct))
          .map((r) => [
            `${r.company} · ${shortDate(r.event_date)}`,
            signedPct(r.pct, 1),
            Math.abs(r.pct) <= 2 ? "shrugged" : "re-priced",
          ]),
      }}
    >
      <div className="flex items-end gap-2.5">
        {BUCKETS.map((b, i) => (
          <div key={b.label} className="group relative flex flex-1 flex-col items-center gap-1">
            <span className="num text-[11px] text-muted">{counts[i]}</span>
            <div
              className="w-full rounded-t transition-opacity group-hover:opacity-100"
              style={{
                height: `${Math.max(4, (counts[i] / max) * 110)}px`,
                background: b.color,
                opacity: b.label.includes("shrug") ? 0.85 : 0.75,
              }}
            />
            <span className={`text-[10.5px] ${b.label.includes("shrug") ? "font-semibold text-ink" : "text-faint"}`}>
              {b.label}
            </span>
            {/* hover card: the names behind the count (top 5 by |move|) */}
            {counts[i] > 0 && (
              <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 hidden w-56 -translate-x-1/2 rounded-lg border border-line bg-surface p-2.5 shadow-lg group-hover:block">
                <p className="mb-1 text-[11px] font-semibold text-ink">
                  {b.label} · {counts[i]} deal{counts[i] === 1 ? "" : "s"}
                </p>
                <ul className="space-y-0.5">
                  {members[i].slice(0, 5).map((r, j) => (
                    <li key={j} className="flex items-baseline gap-1.5 text-[11px] leading-snug">
                      <span className="num shrink-0 text-faint">{signedPct(r.pct, 1)}</span>
                      <span className="truncate text-ink-soft">{r.company} · {shortDate(r.event_date)}</span>
                    </li>
                  ))}
                </ul>
                {counts[i] > 5 && (
                  <p className="mt-1 text-[10.5px] text-faint">+ {counts[i] - 5} more — see the table (⊞)</p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="mt-6 grid gap-6 md:grid-cols-2">
        <div>
          <p className="mb-1.5 text-[12.5px] font-semibold text-ink">
            Flattest shrugs <span className="font-normal text-faint">— material, unpaid-for: the contrarian watch</span>
          </p>
          <ul className="space-y-1.5">
            {flattest.map((r, i) => (
              <li key={i} className="text-[12px] leading-snug">
                <span className="num text-faint">{signedPct(r.pct, 1)}</span>{" "}
                <span className="font-semibold text-ink">{r.company}</span>{" "}
                {r.url ? <StoryLink href={r.url}>{truncate(r.title ?? "", 70)}</StoryLink> : <span className="text-muted">{truncate(r.title ?? "", 70)}</span>}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p className="mb-1.5 text-[12.5px] font-semibold text-ink">
            Sharpest re-pricings <span className="font-normal text-faint">— the market spoke, loudly</span>
          </p>
          <ul className="space-y-1.5">
            {sharpest.map((r, i) => (
              <li key={i} className="text-[12px] leading-snug">
                <span
                  className="num font-medium"
                  style={{ color: r.pct >= 0 ? "var(--color-div-pos)" : "var(--color-div-neg)" }}
                >
                  {signedPct(r.pct, 1)}
                </span>{" "}
                <span className="font-semibold text-ink">{r.company}</span>{" "}
                {r.url ? <StoryLink href={r.url}>{truncate(r.title ?? "", 70)}</StoryLink> : <span className="text-muted">{truncate(r.title ?? "", 70)}</span>}
              </li>
            ))}
          </ul>
        </div>
      </div>
      <p className="mt-3 text-[11.5px] text-faint">
        Full per-deal detail is in the table view (⊞ above) — the chart summarizes, the table enumerates.
      </p>
    </ChartFrame>
  );
}
