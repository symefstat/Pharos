import type { ReactNode } from "react";
import { ArrowUpRight } from "lucide-react";
import { cn } from "../lib/utils";

// A small, harmonious accent palette — section icons rotate through it (hashed by
// title) so the UI carries colour without per-call wiring.
const ACCENTS = ["#3a5cd0", "#18895a", "#c2410c", "#7c3aed", "#0e7490", "#be185d", "#a16207"];
function accentFor(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return ACCENTS[h % ACCENTS.length];
}
function hexToRgba(hex: string, a: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

/* ── Card — border-first, near-flat (minimal register) ──────────────────────── */
export function Card({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-line bg-surface shadow-[0_1px_2px_rgba(20,24,29,0.03)]",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function CardBody({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return <div className={cn("p-6", className)}>{children}</div>;
}

/* ── Section heading — monochrome icon, tight type, one short subline ────────── */
export function SectionHeading({
  icon,
  title,
  description,
  right,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  right?: ReactNode;
}) {
  const accent = accentFor(title);
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
      <div className="flex items-center gap-3">
        {icon && (
          <span
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
            style={{ background: hexToRgba(accent, 0.12), color: accent }}
          >
            {icon}
          </span>
        )}
        <div>
          <h2 className="text-[14.5px] font-semibold tracking-tight text-ink">{title}</h2>
          {description && (
            <p className="mt-0.5 text-[12.5px] leading-snug text-muted">{description}</p>
          )}
        </div>
      </div>
      {right && <div className="min-w-0">{right}</div>}
    </div>
  );
}

/* ── KPI tile ──────────────────────────────────────────────────────────────── */
export function Kpi({
  label,
  value,
  sub,
  tone = "ink",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "ink" | "up" | "down" | "brand";
}) {
  const toneClass = {
    ink: "text-ink",
    up: "text-up",
    down: "text-down",
    brand: "text-brand",
  }[tone];
  const accent = { ink: "#3a5cd0", up: "#18895a", down: "#d23f3f", brand: "#3a5cd0" }[tone];
  return (
    <div
      className="rounded-xl border border-line border-t-[2.5px] bg-surface px-4 py-3.5"
      style={{ borderTopColor: accent }}
    >
      <div className="text-[10.5px] font-medium uppercase tracking-[0.07em] text-faint">
        {label}
      </div>
      <div className={cn("num mt-2 text-[26px] font-semibold leading-none tracking-tight", toneClass)}>
        {value}
      </div>
      {sub != null && (
        <div
          className="mt-2 truncate text-[12px] text-muted"
          title={typeof sub === "string" ? sub : undefined}
        >
          {sub}
        </div>
      )}
    </div>
  );
}

/* ── Badge ─────────────────────────────────────────────────────────────────── */
type BadgeVariant = "neutral" | "up" | "down" | "option" | "commit" | "warn" | "brand";
export function Badge({
  children,
  variant = "neutral",
  className,
}: {
  children: ReactNode;
  variant?: BadgeVariant;
  className?: string;
}) {
  const v: Record<BadgeVariant, string> = {
    neutral: "bg-[#f3f4f6] text-muted",
    up: "bg-up-soft text-up",
    down: "bg-down-soft text-down",
    option: "bg-brand-soft text-option",
    commit: "bg-down-soft text-commit",
    warn: "bg-warn-soft text-warn",
    brand: "bg-brand-soft text-brand",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide",
        v[variant],
        className,
      )}
    >
      {children}
    </span>
  );
}

/* ── Dot — a small semantic marker that replaces the old emoji ──────────────── */
export function Dot({ color, className }: { color: string; className?: string }) {
  return (
    <span
      className={cn("inline-block h-2 w-2 shrink-0 rounded-full", className)}
      style={{ background: color }}
    />
  );
}

/* ── A linked story title with a trailing ↗ ───────────────────────────────── */
export function StoryLink({
  href,
  children,
}: {
  href?: string | null;
  children: ReactNode;
}) {
  if (!href) return <span className="text-ink-soft">{children}</span>;
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-ink-soft decoration-line underline-offset-2 transition-colors hover:text-brand hover:underline"
    >
      {children}
      <ArrowUpRight className="ml-0.5 inline h-3 w-3 align-baseline text-faint" />
    </a>
  );
}

/* ── A callout strip (warnings / notes) ────────────────────────────────────── */
export function Callout({
  tone = "warn",
  children,
}: {
  tone?: "warn" | "info";
  children: ReactNode;
}) {
  const cls =
    tone === "warn"
      ? "border-warn/25 bg-warn-soft text-[#7a5713]"
      : "border-brand/15 bg-brand-soft text-brand-ink";
  return (
    <div className={cn("rounded-lg border px-3.5 py-2.5 text-[12.5px] leading-relaxed", cls)}>
      {children}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-[#eff0f3]", className)} />;
}

/* ── Segmented control ─────────────────────────────────────────────────────── */
export function Segmented({
  options,
  value,
  onChange,
}: {
  options: [string, string][];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-canvas p-0.5">
      {options.map(([v, label]) => (
        <button
          key={v}
          onClick={() => onChange(v)}
          className={cn(
            "rounded-md px-3 py-1 text-[12.5px] font-medium transition-colors",
            v === value
              ? "bg-surface text-ink shadow-[0_1px_2px_rgba(20,24,29,0.06)]"
              : "text-muted hover:text-ink",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/* ── Styled native select ──────────────────────────────────────────────────── */
export function Select({
  value,
  onChange,
  options,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
  className?: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        "rounded-lg border border-line bg-surface px-3 py-1.5 text-[13px] text-ink outline-none transition-colors focus:border-brand focus:ring-2 focus:ring-brand/15",
        className,
      )}
    >
      {options.map(([v, l]) => (
        <option key={v} value={v}>
          {l}
        </option>
      ))}
    </select>
  );
}

/** A constrained, lightly-accented line for the analytics' generated "read"
 *  text — keeps long interpretations readable instead of full-width walls. */
export function Insight({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p
      className={cn(
        "mt-4 max-w-3xl border-l-2 border-line pl-3 text-[12.5px] leading-relaxed text-muted",
        className,
      )}
    >
      {children}
    </p>
  );
}

export function Spinner() {
  return (
    <div className="flex items-center justify-center py-16 text-[12.5px] text-faint">
      <span className="mr-2 h-3.5 w-3.5 animate-spin rounded-full border-2 border-line border-t-brand" />
      Loading…
    </div>
  );
}

/** Renders the analytics' lightweight **bold** markdown as real <b> spans. */
export function Rich({ text }: { text: string | null | undefined }) {
  const parts = (text ?? "").split(/\*\*(.+?)\*\*/g);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <b key={i} className="font-semibold text-ink">
            {p}
          </b>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}
