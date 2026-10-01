/**
 * viz.tsx — Phase A chart primitives (plain SVG, no chart library).
 *
 * The design contract these implement is written in frontend/DESIGN.md.
 * Non-negotiables baked in here:
 *   - categorical hues in FIXED order (CATEGORICAL), never cycled, never
 *     repainted on refilter (entityColor / registerEntities);
 *   - one y-axis only (the API has no second-axis prop on purpose);
 *   - thin marks: bars ≤ 24px with 4px rounded data-ends square at the
 *     baseline, 2px lines, 2px surface gaps between stacked fills, 2px
 *     surface rings on markers;
 *   - text wears text tokens (chart-ink / chart-ink-2 / chart-label),
 *     never a series color;
 *   - hover layer by default: crosshair + shared tooltip on time series,
 *     per-mark tooltip on bars and cells, same details on keyboard focus;
 *   - a legend for ≥ 2 series (none for one), selective direct labels;
 *   - every ChartFrame can carry a table-view twin.
 *
 * All components are dumb/presentational: data in via props, no fetching.
 */

import {
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { ArrowDownRight, ArrowUpRight, ChartColumn, ChevronDown, ChevronUp, Minus, Table2 } from "lucide-react";
import { cn } from "../lib/utils";

/* ═══════════════════════════════ color roles ═══════════════════════════════ */

/** Categorical series slots — FIXED order, assign 1..N in sequence, never cycle.
 *  CSS vars so dark mode re-steps automatically (tokens in src/index.css). */
export const CATEGORICAL = [
  "var(--color-cat-1)",
  "var(--color-cat-2)",
  "var(--color-cat-3)",
  "var(--color-cat-4)",
  "var(--color-cat-5)",
  "var(--color-cat-6)",
  "var(--color-cat-7)",
  "var(--color-cat-8)",
] as const;

/** The 9th+ series never gets a new hue — it folds into "Other". */
export const CAT_OTHER = "var(--color-cat-other)";

/** Sequential ramp, light→dark (dark mode flips the anchor via tokens). */
export const SEQUENTIAL = [
  "var(--color-seq-100)",
  "var(--color-seq-200)",
  "var(--color-seq-300)",
  "var(--color-seq-400)",
  "var(--color-seq-500)",
  "var(--color-seq-600)",
  "var(--color-seq-650)",
  "var(--color-seq-700)",
] as const;

/** Map a normalized magnitude t ∈ [0,1] onto the sequential ramp. */
export function seqColor(t: number): string {
  const clamped = Math.max(0, Math.min(1, t));
  const idx = Math.min(SEQUENTIAL.length - 1, Math.floor(clamped * SEQUENTIAL.length));
  return SEQUENTIAL[idx];
}

/** Series color by slot index — slots past the palette fold into "Other". */
export function seriesColor(i: number): string {
  return i < CATEGORICAL.length ? CATEGORICAL[i] : CAT_OTHER;
}

/* Color follows the ENTITY, never its rank: first-seen assignment is sticky
   for the app's lifetime, so refiltering never repaints survivors. Register
   the full (unfiltered) entity list once so the order is data-stable.
   Each entity FAMILY (e.g. "domain", "feed", "sector") gets its own 8-slot
   registry — unrelated families must not drain one shared palette, or
   whichever family registers second renders all-grey "Other". */
const entityFamilies = new Map<string, Map<string, string>>();

function familySlots(family: string): Map<string, string> {
  let slots = entityFamilies.get(family);
  if (!slots) {
    slots = new Map<string, string>();
    entityFamilies.set(family, slots);
  }
  return slots;
}

export function registerEntities(entities: string[], family = "default"): void {
  const slots = familySlots(family);
  for (const e of entities) {
    if (!slots.has(e)) {
      slots.set(e, slots.size < CATEGORICAL.length ? CATEGORICAL[slots.size] : CAT_OTHER);
    }
  }
}

export function entityColor(entity: string, family = "default"): string {
  const slots = familySlots(family);
  if (!slots.has(entity)) registerEntities([entity], family);
  return slots.get(entity)!;
}

/* ═══════════════════════════════ shared bits ═══════════════════════════════ */

const INK = "var(--color-chart-ink)";
const INK2 = "var(--color-chart-ink-2)";
const LABEL = "var(--color-chart-label)";
const GRID = "var(--color-chart-grid)";
const AXIS = "var(--color-chart-axis)";
const SURFACE = "var(--color-surface)";

function defaultFormat(v: number): string {
  if (!isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e4) return `${(v / 1e3).toFixed(1)}K`;
  if (a >= 100 || Number.isInteger(v)) return v.toLocaleString();
  return v.toFixed(1);
}

/** Observe the rendered width of a container (plain SVG needs real pixels). */
function useWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      setWidth(w);
    });
    ro.observe(el);
    setWidth(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

/** Clean axis ticks spanning [min(0,lo), hi] on round numbers. */
function niceTicks(lo: number, hi: number, count = 4): number[] {
  const min = Math.min(0, lo);
  const max = Math.max(hi, min + 1e-9);
  const span = max - min;
  const step0 = span / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(step0));
  const norm = step0 / mag;
  const step = (norm > 5 ? 10 : norm > 2 ? 5 : norm > 1 ? 2 : 1) * mag;
  const start = Math.floor(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step * 0.5; v += step) ticks.push(Math.abs(v) < step * 1e-6 ? 0 : v);
  return ticks;
}

/** A bar with a 4px rounded DATA end and a square baseline end. */
function barPath(x: number, y: number, w: number, h: number, dataEnd: "right" | "left"): string {
  const r = Math.min(4, Math.max(0, w), h / 2);
  const body = Math.max(0, w - r);
  if (w <= 0) return "";
  if (dataEnd === "right") {
    return `M${x},${y} h${body} a${r},${r} 0 0 1 ${r},${r} v${h - 2 * r} a${r},${r} 0 0 1 ${-r},${r} h${-body} Z`;
  }
  return `M${x + w},${y} h${-body} a${r},${r} 0 0 0 ${-r},${r} v${h - 2 * r} a${r},${r} 0 0 0 ${r},${r} h${body} Z`;
}

/* ── Tooltip ────────────────────────────────────────────────────────────────
   The shared readout box + an overlay positioner. HTML overlay (not SVG) so
   it can escape the plot, wrap text, and stay crisp. Content arrives as
   ReactNode — labels are rendered as text nodes, never injected as HTML. */

export function Tooltip({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "pointer-events-none rounded-lg border border-line bg-surface px-3 py-2 text-[12px] shadow-[0_8px_24px_rgba(15,23,41,0.12)]",
        className,
      )}
    >
      {children}
    </div>
  );
}

type TipState = { x: number; y: number; body: ReactNode };

function TipOverlay({ tip, width }: { tip: TipState | null; width: number }) {
  if (!tip) return null;
  const flip = width > 0 && tip.x > width - 180;
  return (
    <div
      className="absolute z-10"
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

/** Tooltip row: value leads (strong ink), label follows; a short line-key
 *  in the series color carries identity — text never wears series color. */
function TipRow({ color, value, label }: { color?: string; value: ReactNode; label?: ReactNode }) {
  return (
    <div className="flex items-center gap-2 leading-relaxed">
      {color && <span className="h-[2px] w-3 shrink-0 rounded-full" style={{ background: color }} />}
      <span className="num font-semibold" style={{ color: INK }}>
        {value}
      </span>
      {label != null && <span style={{ color: INK2 }}>{label}</span>}
    </div>
  );
}

/* ── Legend ─────────────────────────────────────────────────────────────── */

export type LegendItem = {
  label: string;
  color: string;
  /** Mirror the mark: rect for bars/areas, line for lines, dot for points. */
  shape?: "rect" | "line" | "dot";
};

export function Legend({ items, className }: { items: LegendItem[]; className?: string }) {
  if (items.length < 2) return null; // one series needs no legend box — the title names it
  return (
    <div className={cn("flex flex-wrap items-center gap-x-4 gap-y-1.5", className)}>
      {items.map((it) => (
        <span key={it.label} className="inline-flex items-center gap-1.5 text-[11px]" style={{ color: INK2 }}>
          {it.shape === "line" ? (
            <span className="h-[2px] w-3.5 shrink-0 rounded-full" style={{ background: it.color }} />
          ) : it.shape === "dot" ? (
            <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: it.color }} />
          ) : (
            <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: it.color }} />
          )}
          {it.label}
        </span>
      ))}
    </div>
  );
}

/* ═══════════════════════════════ ChartFrame ═══════════════════════════════ */

export type ChartTable = { columns: string[]; rows: ReactNode[][] };

/**
 * The card anatomy every Phase B chart follows: title / read line / viz /
 * caption — plus the accessible table-view twin behind a toggle.
 */
export function ChartFrame({
  title,
  read,
  caption,
  table,
  right,
  children,
  className,
}: {
  title: string;
  /** One-sentence hero read line — what the chart says, not what it shows. */
  read?: ReactNode;
  caption?: ReactNode;
  /** The chart's accessible twin; providing it renders the toggle. */
  table?: ChartTable;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const [showTable, setShowTable] = useState(false);
  return (
    <figure className={cn("m-0", className)}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <figcaption className="text-[13.5px] font-semibold tracking-tight text-ink">{title}</figcaption>
          {read && <p className="mt-0.5 text-[12.5px] leading-snug text-ink-soft">{read}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {right}
          {table && (
            <button
              type="button"
              onClick={() => setShowTable((s) => !s)}
              aria-pressed={showTable}
              title={showTable ? "Show chart" : "Show as table"}
              className="rounded-md border border-line bg-surface p-1.5 text-muted transition-colors hover:text-ink"
            >
              {showTable ? <ChartColumn className="h-3.5 w-3.5" /> : <Table2 className="h-3.5 w-3.5" />}
              <span className="sr-only">{showTable ? "Show chart" : "Show as table"}</span>
            </button>
          )}
        </div>
      </div>
      {showTable && table ? (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[12px]">
            <thead>
              <tr>
                {table.columns.map((c, i) => (
                  <th
                    key={i}
                    scope="col"
                    className={cn(
                      "border-b border-line pb-1.5 text-[10.5px] font-medium uppercase tracking-[0.07em] text-faint",
                      i === 0 ? "text-left" : "text-right",
                    )}
                  >
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, ri) => (
                <tr key={ri} className="border-b border-line last:border-0">
                  {row.map((cell, ci) => (
                    <td key={ci} className={cn("py-1.5", ci === 0 ? "pr-3 text-ink" : "num pl-3 text-right text-muted")}>
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        children
      )}
      {caption && <p className="mt-2 text-[11.5px] leading-snug text-faint">{caption}</p>}
    </figure>
  );
}

/* ═══════════════════════════════ HBarList ═══════════════════════════════ */

export type HBarDatum = {
  label: string;
  value: number;
  /** Explicit per-datum color (e.g. diverging/status semantics). */
  color?: string;
  /** Extra tooltip lines (already-formatted ReactNode). */
  tip?: ReactNode;
  /** Small chip/annotation rendered after the value label (e.g. drift). */
  chip?: ReactNode;
};

/**
 * Horizontal bar list. Bars grow from a shared zero baseline (negatives go
 * left), 4px rounded data-ends, 2px row gaps, direct value labels in ink.
 * Single-series default is slot 1 for every bar (never a value-ramp on
 * nominal categories). `colorOf` maps label → entity color and must be a
 * stable mapping (use entityColor) so refiltering never repaints.
 */
export function HBarList({
  data,
  format = defaultFormat,
  color = CATEGORICAL[0],
  colorOf,
  labelWidth = 116,
  barHeight = 14,
  domainMax,
  collapsedAfter,
  className,
}: {
  data: HBarDatum[];
  format?: (v: number) => string;
  color?: string;
  colorOf?: (label: string) => string;
  labelWidth?: number;
  barHeight?: number;
  /** Pin the value domain (e.g. 100 for shares) instead of data max. */
  domainMax?: number;
  /** Density rule: show N rows, fold the rest behind "Show all". */
  collapsedAfter?: number;
  className?: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState | null>(null);
  const [expanded, setExpanded] = useState(false);

  const rows = collapsedAfter && !expanded ? data.slice(0, collapsedAfter) : data;
  const pitch = barHeight + 12; // ≥ 2px visual gap + a comfortable ≥ 8px hit band
  const valueW = 64;
  const plotX = labelWidth + 8;
  const plotW = Math.max(0, width - plotX - valueW);

  const lo = Math.min(0, ...data.map((d) => d.value));
  const hi = Math.max(0, ...data.map((d) => d.value), domainMax ?? 0);
  const span = hi - lo || 1;
  const xOf = (v: number) => plotX + ((v - lo) / span) * plotW;
  const zeroX = xOf(0);

  if (!data.length) return <p className="py-6 text-center text-[12.5px] text-faint">no data</p>;

  const height = rows.length * pitch;
  const fillOf = (d: HBarDatum) => d.color ?? (colorOf ? colorOf(d.label) : color);

  const show = (i: number, y: number) => {
    const d = rows[i];
    setTip({
      x: Math.min(Math.max(xOf(d.value), plotX), plotX + plotW),
      y,
      body: (
        <div>
          <div className="mb-0.5 font-semibold" style={{ color: INK }}>
            {d.label}
          </div>
          <TipRow color={fillOf(d)} value={format(d.value)} />
          {d.tip}
        </div>
      ),
    });
  };

  return (
    <div ref={ref} className={cn("relative w-full", className)}>
      {width > 0 && (
        <svg width={width} height={height} role="img" className="block">
          {lo < 0 && <line x1={zeroX} x2={zeroX} y1={0} y2={height} stroke={AXIS} strokeWidth={1} />}
          {rows.map((d, i) => {
            const y = i * pitch + (pitch - barHeight) / 2;
            const w = Math.abs(xOf(d.value) - zeroX);
            const neg = d.value < 0;
            const labelX = neg ? zeroX - w - 6 : zeroX + w + 6;
            return (
              <g key={d.label}>
                <text
                  x={labelWidth}
                  y={y + barHeight / 2}
                  textAnchor="end"
                  dominantBaseline="central"
                  fontSize={11.5}
                  fill={INK}
                >
                  {d.label}
                </text>
                <path d={barPath(neg ? zeroX - w : zeroX, y, w, barHeight, neg ? "left" : "right")} fill={fillOf(d)} />
                {/* direct value label at the tip, in ink — never series color */}
                <text
                  x={Math.min(Math.max(labelX, plotX), width - 2)}
                  y={y + barHeight / 2}
                  textAnchor={neg ? "end" : "start"}
                  dominantBaseline="central"
                  fontSize={11}
                  className="num"
                  fill={INK2}
                >
                  {format(d.value)}
                </text>
                {/* full-row hit target (≥ 8px, includes the gaps), focusable */}
                <rect
                  x={0}
                  y={i * pitch}
                  width={width}
                  height={pitch}
                  fill="transparent"
                  tabIndex={0}
                  aria-label={`${d.label}: ${format(d.value)}`}
                  onPointerMove={() => show(i, i * pitch + pitch / 2)}
                  onPointerLeave={() => setTip(null)}
                  onFocus={() => show(i, i * pitch + pitch / 2)}
                  onBlur={() => setTip(null)}
                  className="cursor-default outline-none focus-visible:stroke-brand"
                />
              </g>
            );
          })}
        </svg>
      )}
      {/* chips (drift, flags) live in HTML so they can reuse Badge etc. */}
      {rows.some((d) => d.chip) && (
        <div className="pointer-events-none absolute inset-0">
          {rows.map((d, i) =>
            d.chip ? (
              <div
                key={d.label}
                className="absolute right-0 flex items-center"
                style={{ top: i * pitch, height: pitch }}
              >
                {d.chip}
              </div>
            ) : null,
          )}
        </div>
      )}
      <TipOverlay tip={tip} width={width} />
      {collapsedAfter != null && data.length > collapsedAfter && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="mt-1.5 inline-flex items-center gap-1 text-[11.5px] font-medium text-muted transition-colors hover:text-ink"
        >
          {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          {expanded ? "Show fewer" : `Show all ${data.length}`}
        </button>
      )}
    </div>
  );
}

/* ═══════════════════════════════ TimeSeries ═══════════════════════════════ */

export type TimeSeriesSeries = {
  /** Key into each data row. */
  key: string;
  label?: string;
  /** Fixed-order categorical slot by default; override to follow an entity. */
  color?: string;
};

/**
 * Line or stacked-area time series. 2px lines, crosshair + one shared
 * tooltip listing every series at the hovered X, legend for ≥ 2 series,
 * direct end-labels when ≤ 4 series separate cleanly, single y-axis only.
 * Stacked bands are separated by 2px surface gaps; each band edge is a
 * 2px line in its series color.
 */
export function TimeSeries({
  data,
  xKey,
  series,
  variant = "line",
  height = 240,
  formatX = String,
  formatY = defaultFormat,
  formatXTip,
  className,
}: {
  data: Array<Record<string, unknown>>;
  xKey: string;
  series: TimeSeriesSeries[];
  variant?: "line" | "area";
  height?: number;
  formatX?: (x: string) => string;
  formatY?: (y: number) => string;
  /** Tooltip title format (defaults to formatX). */
  formatXTip?: (x: string) => string;
  className?: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const n = data.length;
  const cols = series.map((s, i) => s.color ?? seriesColor(i));
  const names = series.map((s) => s.label ?? s.key);
  const num = (row: Record<string, unknown>, key: string) => {
    const v = row[key];
    return typeof v === "number" && isFinite(v) ? v : 0;
  };

  const { ticks, lo, hi, stacks } = useMemo(() => {
    let lo = 0;
    let hi = 1;
    let stacks: number[][] | null = null;
    if (variant === "area") {
      // cumulative sums per row, series order = stack order (bottom-up)
      stacks = data.map((row) => {
        let acc = 0;
        return series.map((s) => (acc += num(row, s.key)));
      });
      hi = Math.max(1e-9, ...stacks.map((r) => r[r.length - 1] ?? 0));
    } else {
      const vals = data.flatMap((row) => series.map((s) => num(row, s.key)));
      lo = Math.min(0, ...vals);
      hi = Math.max(1e-9, ...vals);
    }
    const ticks = niceTicks(lo, hi);
    return { ticks, lo: ticks[0], hi: Math.max(hi, ticks[ticks.length - 1]), stacks };
  }, [data, series, variant]);

  // direct end-labels: ≤ 4 series AND labels don't collide at the right edge
  const margin = useMemo(() => {
    const wantLabels = series.length <= 4 && series.length >= 2 && n > 0;
    const labelW = wantLabels ? Math.min(96, Math.max(...names.map((s) => s.length)) * 6 + 12) : 0;
    return { top: 8, right: 10 + labelW, bottom: 22, left: 40, labelW };
  }, [series.length, names, n]);

  const plotW = Math.max(0, width - margin.left - margin.right);
  const plotH = height - margin.top - margin.bottom;
  const xOf = (i: number) => margin.left + (n > 1 ? (i / (n - 1)) * plotW : plotW / 2);
  const yOf = (v: number) => margin.top + plotH - ((v - lo) / (hi - lo || 1)) * plotH;

  const endYs = useMemo(() => {
    if (!n) return [];
    const last = data[n - 1];
    return series.map((s, si) =>
      variant === "area" && stacks
        ? yOf((stacks[n - 1][si] + (si > 0 ? stacks[n - 1][si - 1] : 0)) / 2)
        : yOf(num(last, s.key)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, series, variant, stacks, lo, hi, plotH, n]);

  const labelsCollide = useMemo(() => {
    const ys = [...endYs].sort((a, b) => a - b);
    return ys.some((y, i) => i > 0 && y - ys[i - 1] < 12);
  }, [endYs]);
  const directLabels = series.length >= 2 && series.length <= 4 && !labelsCollide;

  if (!n) return <p className="py-6 text-center text-[12.5px] text-faint">no data</p>;

  const xTickIdx = (() => {
    const want = Math.min(6, n);
    if (n <= want) return data.map((_, i) => i);
    const step = (n - 1) / (want - 1);
    return Array.from({ length: want }, (_, i) => Math.round(i * step));
  })();

  const moveTo = (i: number | null) => setHover(i == null ? null : Math.max(0, Math.min(n - 1, i)));
  const onPointer = (e: PointerEvent<SVGSVGElement>) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const px = e.clientX - rect.left;
    const i = n > 1 ? Math.round(((px - margin.left) / (plotW || 1)) * (n - 1)) : 0;
    moveTo(i);
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key === "ArrowRight") moveTo((hover ?? -1) + 1);
    else if (e.key === "ArrowLeft") moveTo((hover ?? n) - 1);
    else if (e.key === "Escape") moveTo(null);
    else return;
    e.preventDefault();
  };

  const linePoints = (si: number) =>
    data.map((row, i) => `${xOf(i)},${yOf(num(row, series[si].key))}`).join(" ");

  const bandTopPath = (si: number) =>
    stacks!.map((r, i) => `${i ? "L" : "M"}${xOf(i)},${yOf(r[si])}`).join(" ");

  const bandFillPath = (si: number) => {
    const top = stacks!.map((r, i) => `${i ? "L" : "M"}${xOf(i)},${yOf(r[si])}`).join(" ");
    const bottom = [...stacks!]
      .map((r, i) => ({ x: xOf(i), y: yOf(si > 0 ? r[si - 1] : 0) }))
      .reverse()
      .map((p) => `L${p.x},${p.y}`)
      .join(" ");
    return `${top} ${bottom} Z`;
  };

  const hoverBody =
    hover != null ? (
      <div>
        <div className="mb-1 font-semibold" style={{ color: INK }}>
          {(formatXTip ?? formatX)(String(data[hover][xKey]))}
        </div>
        {series.map((s, si) => (
          <TipRow key={s.key} color={cols[si]} value={formatY(num(data[hover], s.key))} label={names[si]} />
        ))}
      </div>
    ) : null;

  return (
    <div ref={ref} className={cn("relative w-full", className)}>
      {width > 0 && (
        <svg
          ref={svgRef}
          width={width}
          height={height}
          role="img"
          tabIndex={0}
          className="block outline-none"
          onPointerMove={onPointer}
          onPointerLeave={() => moveTo(null)}
          onKeyDown={onKey}
          onBlur={() => moveTo(null)}
        >
          {/* recessive grid: solid hairlines, one step off the surface */}
          {ticks.map((t) => (
            <g key={t}>
              <line x1={margin.left} x2={margin.left + plotW} y1={yOf(t)} y2={yOf(t)} stroke={GRID} strokeWidth={1} />
              <text x={margin.left - 6} y={yOf(t)} textAnchor="end" dominantBaseline="central" fontSize={11} className="num" fill={LABEL}>
                {formatY(t)}
              </text>
            </g>
          ))}
          <line x1={margin.left} x2={margin.left + plotW} y1={yOf(lo)} y2={yOf(lo)} stroke={AXIS} strokeWidth={1} />
          {xTickIdx.map((i) => (
            <text key={i} x={xOf(i)} y={height - 6} textAnchor="middle" fontSize={11} fill={LABEL}>
              {formatX(String(data[i][xKey]))}
            </text>
          ))}

          {variant === "area" && stacks ? (
            <>
              {series.map((s, si) => (
                <path key={s.key} d={bandFillPath(si)} fill={cols[si]} fillOpacity={0.45} />
              ))}
              {/* 2px surface gap under each band edge, then the 2px colored edge */}
              {series.map((s, si) => (
                <g key={`${s.key}-edge`}>
                  <path d={bandTopPath(si)} fill="none" stroke={SURFACE} strokeWidth={4} strokeLinejoin="round" />
                  <path d={bandTopPath(si)} fill="none" stroke={cols[si]} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
                </g>
              ))}
            </>
          ) : (
            series.map((s, si) => (
              <polyline
                key={s.key}
                points={linePoints(si)}
                fill="none"
                stroke={cols[si]}
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ))
          )}

          {/* selective direct labels at line ends — ink, keyed by proximity */}
          {directLabels &&
            series.map((s, si) => (
              <text
                key={`${s.key}-label`}
                x={margin.left + plotW + 8}
                y={endYs[si]}
                dominantBaseline="central"
                fontSize={11}
                fill={INK2}
              >
                {names[si]}
              </text>
            ))}

          {/* crosshair + ringed markers on hover/focus */}
          {hover != null && (
            <g>
              <line x1={xOf(hover)} x2={xOf(hover)} y1={margin.top} y2={margin.top + plotH} stroke={AXIS} strokeWidth={1} />
              {series.map((s, si) => {
                const y =
                  variant === "area" && stacks ? yOf(stacks[hover][si]) : yOf(num(data[hover], s.key));
                return (
                  <circle key={s.key} cx={xOf(hover)} cy={y} r={4} fill={cols[si]} stroke={SURFACE} strokeWidth={2} />
                );
              })}
            </g>
          )}
        </svg>
      )}
      <TipOverlay tip={hover != null ? { x: xOf(hover), y: margin.top + plotH / 2, body: hoverBody } : null} width={width} />
      <Legend
        className="mt-2"
        items={series.map((_s, si) => ({
          label: names[si],
          color: cols[si],
          shape: variant === "area" ? "rect" : "line",
        }))}
      />
    </div>
  );
}

/* ═══════════════════════════════ CalibrationPlot ═══════════════════════════
   Stated-confidence (x) vs realized hit-rate (y) per confidence band, with the
   identity diagonal as the reference — the shared credibility scatter used by
   the Forecasts tab and the public Ledger page. Structural bin type so the
   component stays presentational (lib/api's CalBin is compatible). */

export type CalibrationBin = { band: string; predicted: number; actual: number; n: number };

const pctOf = (t: number) => `${Math.round(t * 100)}%`;

export function CalibrationPlot({ bins, height = 280 }: { bins: CalibrationBin[]; height?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<{ x: number; y: number; bin: CalibrationBin } | null>(null);

  // height includes the x-axis band — no nested scroll
  const m = { top: 18, right: 16, bottom: 40, left: 46 };
  const plotW = Math.max(0, width - m.left - m.right);
  const plotH = height - m.top - m.bottom;
  const xOf = (t: number) => m.left + t * plotW;
  const yOf = (t: number) => m.top + (1 - t) * plotH;
  const ticks = [0, 0.25, 0.5, 0.75, 1];

  const maxN = Math.max(1, ...bins.map((b) => b.n));
  const rOf = (n: number) => 4 + 5 * Math.sqrt(n / maxN);

  const show = (b: CalibrationBin) => setTip({ x: xOf(b.predicted), y: yOf(b.actual), bin: b });
  const flip = tip != null && width > 0 && tip.x > width - 190;

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <svg width={width} height={height} role="img" className="block">
          {/* recessive grid: solid hairlines */}
          {ticks.map((t) => (
            <g key={t}>
              <line x1={m.left} x2={m.left + plotW} y1={yOf(t)} y2={yOf(t)} stroke={t === 0 ? AXIS : GRID} strokeWidth={1} />
              <line x1={xOf(t)} x2={xOf(t)} y1={m.top} y2={m.top + plotH} stroke={t === 0 ? AXIS : GRID} strokeWidth={1} />
              <text x={m.left - 8} y={yOf(t)} textAnchor="end" dominantBaseline="central" fontSize={11} className="num" fill={LABEL}>
                {pctOf(t)}
              </text>
              <text x={xOf(t)} y={m.top + plotH + 16} textAnchor="middle" fontSize={11} className="num" fill={LABEL}>
                {pctOf(t)}
              </text>
            </g>
          ))}

          {/* identity reference: on this line, stated = realized */}
          <line x1={xOf(0)} y1={yOf(0)} x2={xOf(1)} y2={yOf(1)} stroke={AXIS} strokeWidth={1} />
          <text x={xOf(1) - 6} y={yOf(1) + 12} textAnchor="end" fontSize={10} fill={LABEL}>
            perfectly calibrated
          </text>

          {/* axis titles — ink tokens, never a series color */}
          <text x={m.left} y={10} fontSize={10} fill={LABEL}>
            realized hit-rate
          </text>
          <text x={m.left + plotW / 2} y={height - 6} textAnchor="middle" fontSize={10} fill={LABEL}>
            stated confidence
          </text>

          {/* one series → one hue; r4+ markers with the 2px surface ring */}
          {bins.map((b) => (
            <g key={b.band}>
              <circle cx={xOf(b.predicted)} cy={yOf(b.actual)} r={rOf(b.n)} fill={CATEGORICAL[0]} stroke={SURFACE} strokeWidth={2} />
              {/* generous hit target (≥ 24px), keyboard reachable */}
              <circle
                cx={xOf(b.predicted)}
                cy={yOf(b.actual)}
                r={Math.max(14, rOf(b.n) + 8)}
                fill="transparent"
                tabIndex={0}
                aria-label={`${b.band} band: stated ${pctOf(b.predicted)}, realized ${pctOf(b.actual)}, n=${b.n}`}
                onPointerMove={() => show(b)}
                onPointerLeave={() => setTip(null)}
                onFocus={() => show(b)}
                onBlur={() => setTip(null)}
                className="cursor-default outline-none focus-visible:stroke-brand"
              />
            </g>
          ))}
        </svg>
      )}
      {tip && (
        <div
          className="absolute z-10"
          style={{
            left: tip.x,
            top: tip.y,
            transform: flip ? "translate(calc(-100% - 12px), -50%)" : "translate(12px, -50%)",
          }}
        >
          <Tooltip>
            <div className="mb-0.5 font-semibold" style={{ color: INK }}>
              {tip.bin.band} band
            </div>
            <div className="num" style={{ color: INK2 }}>
              stated {pctOf(tip.bin.predicted)} → realized {pctOf(tip.bin.actual)}
            </div>
            <div className="num" style={{ color: INK2 }}>
              n={tip.bin.n} resolved
            </div>
          </Tooltip>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════ StatTile ═══════════════════════════════ */

/**
 * The "is it even a chart?" answer for single values. Proportional figures
 * on the value (never tabular at display size). Delta chip wears STATUS
 * tokens — color = direction × whether up is good — with an icon so the
 * state never rides on color alone.
 */
export function StatTile({
  label,
  value,
  delta,
  spark,
  help,
  className,
}: {
  label: string;
  value: ReactNode;
  delta?: { text: string; direction: "up" | "down" | "flat"; upIsGood?: boolean };
  /** ~12-point trend; drawn in the de-emphasis hue, current period in accent. */
  spark?: number[];
  /** One-line gloss for a term-of-art label, shown as a native tooltip. */
  help?: string;
  className?: string;
}) {
  const good =
    delta &&
    (delta.direction === "flat" ? null : (delta.direction === "up") === (delta.upIsGood ?? true));
  const chip =
    good == null
      ? "bg-[color:var(--color-chart-grid)] text-muted"
      : good
        ? "bg-status-good-soft text-status-good"
        : "bg-status-critical-soft text-status-critical";
  const Icon = delta?.direction === "up" ? ArrowUpRight : delta?.direction === "down" ? ArrowDownRight : Minus;

  return (
    <div className={cn("rounded-xl border border-line bg-surface px-4 py-3.5", className)}>
      <div
        title={help}
        className={cn(
          "text-[10.5px] font-medium uppercase tracking-[0.07em] text-faint",
          help && "cursor-help",
        )}
      >
        {label}
      </div>
      <div className="mt-2 flex items-end justify-between gap-3">
        {/* proportional figures — .num (tabular) is for columns, not heroes */}
        <div className="text-[26px] font-semibold leading-none tracking-tight text-ink">{value}</div>
        {spark && spark.length > 1 && <Sparkline points={spark} />}
      </div>
      {delta && (
        <span className={cn("mt-2 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold", chip)}>
          <Icon className="h-3 w-3" />
          {delta.text}
        </span>
      )}
    </div>
  );
}

function Sparkline({ points }: { points: number[] }) {
  const w = 72;
  const h = 24;
  const lo = Math.min(...points);
  const hi = Math.max(...points);
  const span = hi - lo || 1;
  const xy = points.map((v, i) => ({
    x: (i / (points.length - 1)) * (w - 4) + 2,
    y: h - 3 - ((v - lo) / span) * (h - 6),
  }));
  const path = xy.map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join(" ");
  const last = xy[xy.length - 1];
  const prev = xy[xy.length - 2];
  return (
    <svg width={w} height={h} aria-hidden="true" className="shrink-0">
      <path d={path} fill="none" stroke={LABEL} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
      <line x1={prev.x} y1={prev.y} x2={last.x} y2={last.y} stroke="var(--color-brand)" strokeWidth={2} strokeLinecap="round" />
      <circle cx={last.x} cy={last.y} r={2.5} fill="var(--color-brand)" stroke={SURFACE} strokeWidth={2} />
    </svg>
  );
}

/* ═══════════════════════════════ MatrixHeat ═══════════════════════════════ */

/**
 * Small heat/matrix cells on the sequential ramp (magnitude = one hue,
 * light→dark; the token ramp re-anchors itself in dark mode). Null cells
 * (e.g. the diagonal) stay blank. Per-cell hover/focus tooltip; a scale
 * legend names the extremes.
 */
export function MatrixHeat({
  rowLabels,
  colLabels,
  values,
  format = defaultFormat,
  cellSize = 22,
  labelWidth = 96,
  relation = "×",
  className,
}: {
  rowLabels: string[];
  colLabels: string[];
  /** rows × cols; null = no cell (renders blank). */
  values: Array<Array<number | null>>;
  format?: (v: number) => string;
  cellSize?: number;
  labelWidth?: number;
  /** Word/symbol joining row and column in the tooltip. */
  relation?: string;
  className?: string;
}) {
  const [tip, setTip] = useState<TipState | null>(null);
  const gap = 2;
  const colLabelH = 64;
  const pitch = cellSize + gap;
  const width = labelWidth + colLabels.length * pitch + 8;
  const legendH = 26;
  const height = colLabelH + rowLabels.length * pitch + legendH;

  const max = Math.max(1e-9, ...values.flat().map((v) => v ?? 0));
  const gradId = `mh-${useMemo(() => Math.random().toString(36).slice(2, 8), [])}`;

  const show = (r: number, c: number, v: number) =>
    setTip({
      x: labelWidth + c * pitch + cellSize / 2,
      y: colLabelH + r * pitch,
      body: (
        <div>
          <div className="mb-0.5 font-semibold" style={{ color: INK }}>
            {rowLabels[r]} {relation} {colLabels[c]}
          </div>
          <TipRow value={format(v)} />
        </div>
      ),
    });

  return (
    <div className={cn("relative w-fit max-w-full overflow-x-auto", className)}>
      <svg width={width} height={height} role="img" className="block">
        {colLabels.map((c, j) => (
          <text
            key={j}
            transform={`translate(${labelWidth + j * pitch + cellSize / 2 + 4}, ${colLabelH - 6}) rotate(-45)`}
            fontSize={10.5}
            fill={INK2}
          >
            {c}
          </text>
        ))}
        {rowLabels.map((r, i) => (
          <text
            key={i}
            x={labelWidth - 6}
            y={colLabelH + i * pitch + cellSize / 2}
            textAnchor="end"
            dominantBaseline="central"
            fontSize={10.5}
            fill={INK2}
          >
            {r}
          </text>
        ))}
        {values.map((row, i) =>
          row.map((v, j) => {
            if (v == null) return null;
            const x = labelWidth + j * pitch;
            const y = colLabelH + i * pitch;
            return (
              <rect
                key={`${i}-${j}`}
                x={x}
                y={y}
                width={cellSize}
                height={cellSize}
                rx={3}
                fill={v > 0 ? seqColor(v / max) : GRID}
                tabIndex={0}
                aria-label={`${rowLabels[i]} ${relation} ${colLabels[j]}: ${format(v)}`}
                className="cursor-default outline-none hover:stroke-[color:var(--color-chart-ink-2)] focus-visible:stroke-[color:var(--color-chart-ink-2)]"
                strokeWidth={1.5}
                onPointerMove={() => show(i, j, v)}
                onPointerLeave={() => setTip(null)}
                onFocus={() => show(i, j, v)}
                onBlur={() => setTip(null)}
              />
            );
          }),
        )}
        {/* scale legend: the sequential ramp with named extremes */}
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="1" y2="0">
            {SEQUENTIAL.map((c, i) => (
              <stop key={i} offset={`${(i / (SEQUENTIAL.length - 1)) * 100}%`} style={{ stopColor: c }} />
            ))}
          </linearGradient>
        </defs>
        <g transform={`translate(${labelWidth}, ${height - 12})`}>
          <text x={-6} y={4} textAnchor="end" fontSize={10} className="num" fill={LABEL}>
            0
          </text>
          <rect x={0} y={0} width={72} height={6} rx={3} fill={`url(#${gradId})`} />
          <text x={78} y={4} fontSize={10} className="num" fill={LABEL}>
            {format(max)}
          </text>
        </g>
      </svg>
      <TipOverlay tip={tip} width={width} />
    </div>
  );
}
