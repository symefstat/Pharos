import { useMemo, useState } from "react";
import { chord as d3chord, ribbon as d3ribbon } from "d3-chord";
import { arc as d3arc } from "d3-shape";
import { Legend, entityColor } from "./viz";

/** Co-mention chord: companies around a ring, ribbons = how often they're named
 *  together, coloured by each company's dominant feed/domain. Colours come from
 *  the fixed-order categorical tokens via entityColor (colour follows the
 *  domain, never rank — the parent registers the unfiltered feed list), so a
 *  refilter never repaints and dark mode re-steps for free. Hover a company to
 *  isolate its links. Input is the square co-occurrence matrix from the API. */
export function ChordDiagram({
  labels,
  domains,
  matrix,
}: {
  labels: string[];
  domains: string[];
  matrix: number[][];
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const size = 480;
  const outer = size / 2 - 104;
  const inner = outer - 12;

  const { groups, ribbons } = useMemo(() => {
    const layout = d3chord().padAngle(0.045).sortSubgroups((a, b) => b - a);
    const c = layout(matrix);
    const arcGen = d3arc<{ startAngle: number; endAngle: number }>()
      .innerRadius(inner)
      .outerRadius(outer);
    const ribbonGen = d3ribbon<unknown, unknown>().radius(inner) as unknown as (d: unknown) => string;
    const groups = c.groups.map((g) => ({
      index: g.index,
      d: arcGen(g) ?? "",
      angle: (g.startAngle + g.endAngle) / 2,
    }));
    const ribbons = c.map((ch) => ({
      source: ch.source.index,
      target: ch.target.index,
      value: matrix[ch.source.index]?.[ch.target.index] ?? 0,
      d: ribbonGen(ch) ?? "",
    }));
    return { groups, ribbons };
  }, [matrix, inner, outer]);

  if (labels.length < 3) return null;
  const color = (i: number) => entityColor(domains[i] ?? "Other", "domain");
  const domainsPresent = Array.from(new Set(domains));

  return (
    <div className="flex flex-col items-center gap-3">
      <svg viewBox={`0 0 ${size} ${size}`} className="block w-full max-w-[460px]">
        <g transform={`translate(${size / 2},${size / 2})`}>
          {ribbons.map((r, i) => {
            const active = hovered == null || hovered === r.source || hovered === r.target;
            return (
              <path
                key={i}
                d={r.d}
                fill={color(r.source)}
                fillOpacity={active ? 0.55 : 0.06}
                tabIndex={0}
                aria-label={`${labels[r.source]} and ${labels[r.target]} co-mentioned ${r.value} time${r.value === 1 ? "" : "s"}`}
                className="outline-none focus-visible:stroke-[color:var(--color-brand)]"
                strokeWidth={1.5}
                onMouseEnter={() => setHovered(r.source)}
                onMouseLeave={() => setHovered(null)}
                onFocus={() => setHovered(r.source)}
                onBlur={() => setHovered(null)}
                style={{ transition: "fill-opacity 0.15s" }}
              >
                {/* per-ribbon readout — labels rendered as text nodes, never HTML */}
                <title>
                  {labels[r.source]} ↔ {labels[r.target]}: {r.value}
                </title>
              </path>
            );
          })}
          {groups.map((g) => {
            const deg = (g.angle * 180) / Math.PI - 90;
            const flip = g.angle > Math.PI;
            const dim = hovered != null && hovered !== g.index;
            return (
              <g
                key={g.index}
                onMouseEnter={() => setHovered(g.index)}
                onMouseLeave={() => setHovered(null)}
              >
                {/* arc separated by a surface-colour gap, never a drawn border;
                    keyboard-focusable (tab through companies, focus isolates links) */}
                <path
                  d={g.d}
                  fill={color(g.index)}
                  fillOpacity={dim ? 0.3 : 1}
                  stroke="var(--color-surface)"
                  strokeWidth={1}
                  tabIndex={0}
                  aria-label={`${labels[g.index]} (${domains[g.index] ?? "Other"})`}
                  className="outline-none focus-visible:stroke-[color:var(--color-brand)]"
                  onFocus={() => setHovered(g.index)}
                  onBlur={() => setHovered(null)}
                />
                <g transform={`rotate(${deg}) translate(${outer + 8},0)${flip ? " rotate(180)" : ""}`}>
                  {/* entity names wear ink tokens — identity rides the coloured arc */}
                  <text
                    dy="0.32em"
                    textAnchor={flip ? "end" : "start"}
                    style={{
                      fontSize: 10.5,
                      fill: dim ? "var(--color-chart-label)" : "var(--color-chart-ink-2)",
                      transition: "fill 0.15s",
                    }}
                  >
                    {labels[g.index]}
                  </text>
                </g>
              </g>
            );
          })}
        </g>
      </svg>
      <Legend
        items={domainsPresent.map((d) => ({ label: d, color: entityColor(d, "domain"), shape: "dot" as const }))}
      />
    </div>
  );
}
