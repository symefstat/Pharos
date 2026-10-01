import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp, RefreshCw } from "lucide-react";
import { api } from "../lib/api";
import type { ProsusCompany, ProsusForecast, ProsusPayload, ProsusStory } from "../lib/api";
import { useResource } from "../lib/useResource";
import { useActions, ProgressPanel } from "../components/actions";
import { PageChrome, DefaultSkeleton } from "../components/PageChrome";
import { StoryCard } from "../components/Story";
import { shortDate } from "../lib/format";

/* The region lens persists across visits: a strategist focused on India lands
 * on India every time without re-configuring (DESIGN.md §3 — the filter row
 * scopes everything below it). */
const REGION_STORAGE_KEY = "lodestar-prosus-region";

/* Prosus's declared strategic geographies — always shown, even at zero. */
const PINNED_REGIONS = ["latam", "india", "europe"];

export default function ProsusPage() {
  const resource = useResource(api.prosus, { key: "prosus" });
  return (
    <PageChrome
      title="Prosus"
      subtitle="The group portfolio — signals, segments, and strategic geographies"
      resource={resource}
      skeleton={<DefaultSkeleton />}
    >
      {(data) => <Prosus data={data} />}
    </PageChrome>
  );
}

function Prosus({ data }: { data: ProsusPayload }) {
  const [region, setRegion] = useState<string>(
    () => localStorage.getItem(REGION_STORAGE_KEY) ?? "",
  );
  const [segment, setSegment] = useState<string>("");
  const [company, setCompany] = useState<string>("");
  const { run, jobForSlot } = useActions();

  const segmentBySlug = useMemo(
    () => new Map(data.companies.map((c) => [c.slug, c.segment])),
    [data.companies],
  );

  const pickRegion = (key: string) => {
    setRegion(key);
    if (key) localStorage.setItem(REGION_STORAGE_KEY, key);
    else localStorage.removeItem(REGION_STORAGE_KEY);
  };
  const pickSegment = (key: string) => {
    setSegment(key);
    setCompany(""); // a company belongs to one segment; switching resets it
  };

  const storySegments = (s: ProsusStory): Set<string> => {
    const segs = new Set<string>();
    for (const t of s.prosus_tags ?? []) {
      const seg = segmentBySlug.get(t);
      if (seg) segs.add(seg);
    }
    return segs;
  };

  const stories = useMemo(
    () =>
      data.stories.filter((s) => {
        if (region && s.region !== region) return false;
        if (segment && !storySegments(s).has(segment)) return false;
        if (company && !(s.prosus_tags ?? []).includes(company)) return false;
        return true;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data.stories, region, segment, company, segmentBySlug],
  );

  const segmentCompanies = useMemo(() => {
    if (!segment) return [];
    return data.companies
      .filter((c) => c.segment === segment && c.status === "active")
      .sort((a, b) => (a.tier === b.tier ? a.name.localeCompare(b.name) : a.tier === "core" ? -1 : 1));
  }, [data.companies, segment]);

  const slot = "feed-prosus";
  const job = jobForSlot(slot);
  const running = job?.status === "running";

  return (
    <div className="space-y-5">
      {!data.configured && <SetupNotice />}

      {/* Filter row — region lens + refresh (DESIGN.md §3). */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <Chips
          options={regionOptions(data)}
          active={region}
          allLabel="All regions"
          onPick={pickRegion}
        />
        <button
          onClick={() => run({ slot, path: "/api/actions/feed/prosus", label: "Refresh Prosus feed" })}
          disabled={running}
          className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-[13px] font-medium text-ink-soft transition-colors hover:border-line-strong hover:text-ink disabled:opacity-60"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${running ? "animate-spin" : ""}`} />
          {running ? "Refreshing…" : "Refresh feed"}
        </button>
      </div>
      {job && job.steps.length > 0 && <ProgressPanel job={job} />}

      {/* Segment tabs — the four assessment segments plus ecommerce & travel,
          mobility, and the Ventures frontier-tech layer. */}
      <Chips options={data.segments} active={segment} allLabel="All segments" onPick={pickSegment} />

      {segment && segmentCompanies.length > 0 && (
        <CompanyRow companies={segmentCompanies} active={company} onPick={setCompany} />
      )}

      <section className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 className="text-[14.5px] font-semibold tracking-tight text-ink">Portfolio signals</h2>
          <p className="num text-[11.5px] text-faint">
            {stories.length} of {data.total_stories} stories in 30d
          </p>
        </div>
        <StoryList stories={stories} />
      </section>

      {data.forecasts.length > 0 && <ForecastStrip forecasts={data.forecasts} />}
    </div>
  );
}

function regionOptions(data: ProsusPayload) {
  // The three strategic lenses always render; other regions appear once they
  // have stories, so nothing is hidden but the row stays calm.
  return data.regions.filter((r) => PINNED_REGIONS.includes(r.key) || r.count > 0);
}

/* ── Shared chip row (mirrors the Feeds tab switcher) ───────────────────────── */

function Chips({
  options,
  active,
  allLabel,
  onPick,
}: {
  options: { key: string; label: string; count: number }[];
  active: string;
  allLabel: string;
  onPick: (key: string) => void;
}) {
  const total = options.reduce((n, o) => n + o.count, 0);
  return (
    <div className="inline-flex flex-wrap gap-1 rounded-xl border border-line bg-canvas p-1">
      <Chip label={allLabel} count={total} active={active === ""} onClick={() => onPick("")} />
      {options.map((o) => (
        <Chip
          key={o.key}
          label={o.label}
          count={o.count}
          active={active === o.key}
          onClick={() => onPick(o.key)}
        />
      ))}
    </div>
  );
}

function Chip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[12.5px] font-medium transition-colors ${
        active
          ? "bg-surface text-ink shadow-[0_1px_2px_rgba(20,24,29,0.06)]"
          : "text-muted hover:text-ink"
      }`}
    >
      {label}
      {typeof count === "number" && <span className="num text-[11px] text-faint">{count}</span>}
    </button>
  );
}

/* ── Companies in the active segment ────────────────────────────────────────── */

function CompanyRow({
  companies,
  active,
  onPick,
}: {
  companies: ProsusCompany[];
  active: string;
  onPick: (slug: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {companies.map((c) => {
        const isActive = c.slug === active;
        return (
          <button
            key={c.slug}
            onClick={() => onPick(isActive ? "" : c.slug)}
            aria-pressed={isActive}
            title={[c.ownership, c.notes].filter(Boolean).join(" — ") || undefined}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] transition-colors ${
              isActive
                ? "border-line-strong bg-surface font-semibold text-ink"
                : "border-line bg-canvas text-ink-soft hover:border-line-strong hover:text-ink"
            }`}
          >
            <span className={c.tier === "core" ? "font-semibold" : ""}>{c.name}</span>
            {c.tier === "core" && c.ownership && (
              <span className="num text-[10.5px] text-faint">{c.ownership}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/* ── Story grid (Feeds tab pagination pattern) ──────────────────────────────── */

const PAGE = 12;

function StoryList({ stories }: { stories: ProsusStory[] }) {
  const [shown, setShown] = useState(PAGE);
  if (!stories.length)
    return (
      <p className="py-6 text-center text-[12.5px] text-faint">
        No portfolio stories match this lens yet. Stories appear as feeds tag
        portfolio companies and the Prosus feed runs.
      </p>
    );
  const visible = stories.slice(0, shown);
  const folded = stories.length > PAGE;
  return (
    <div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
        {visible.map((s, i) => (
          <StoryCard key={s.url ?? `${i}`} story={s} />
        ))}
      </div>
      {folded && (
        <div className="mt-3 flex items-center gap-4 px-1 py-1.5">
          {shown < stories.length ? (
            <>
              <button
                type="button"
                onClick={() => setShown((n) => Math.min(n + PAGE, stories.length))}
                className="inline-flex items-center gap-1 text-[11.5px] font-medium text-muted transition-colors hover:text-ink"
              >
                <ChevronDown className="h-3 w-3" />
                Show {Math.min(PAGE, stories.length - shown)} more
              </button>
              <button
                type="button"
                onClick={() => setShown(stories.length)}
                className="text-[11.5px] font-medium text-muted transition-colors hover:text-ink"
              >
                Show all {stories.length}
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setShown(PAGE)}
              className="inline-flex items-center gap-1 text-[11.5px] font-medium text-muted transition-colors hover:text-ink"
            >
              <ChevronUp className="h-3 w-3" />
              Show fewer
            </button>
          )}
          <span className="num ml-auto text-[11.5px] text-faint">
            {visible.length} of {stories.length}
          </span>
        </div>
      )}
    </div>
  );
}

/* ── Portfolio-anchored ledger calls ────────────────────────────────────────── */

function ForecastStrip({ forecasts }: { forecasts: ProsusForecast[] }) {
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-[14.5px] font-semibold tracking-tight text-ink">
          Ledger — portfolio-anchored calls
        </h2>
        <p className="num text-[11.5px] text-faint">{forecasts.length} shown</p>
      </div>
      <div className="divide-y divide-line rounded-xl border border-line bg-surface">
        {forecasts.map((f, i) => (
          <div key={i} className="flex items-start gap-3 px-4 py-2.5">
            <OutcomeBadge status={f.status} outcome={f.outcome} />
            <div className="min-w-0 flex-1">
              <p className="text-[13px] leading-snug text-ink">{f.claim}</p>
              <p className="num mt-0.5 text-[11px] text-faint">
                {typeof f.confidence === "number" && `${Math.round(f.confidence * 100)}% · `}
                made {shortDate(f.made_on)}
                {f.resolve_by && ` · resolve by ${shortDate(f.resolve_by)}`}
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function OutcomeBadge({ status, outcome }: { status: string; outcome: string | null }) {
  const label = status === "resolved" ? (outcome ?? "resolved") : "open";
  const tone =
    label === "hit"
      ? "bg-status-good-soft text-status-good border-status-good/25"
      : label === "miss"
        ? "bg-status-critical-soft text-status-critical border-status-critical/25"
        : label === "partial"
          ? "bg-status-warning-soft text-status-warning border-status-warning/25"
          : "bg-canvas text-muted border-line";
  return (
    <span
      className={`mt-0.5 inline-flex shrink-0 rounded-full border px-2 py-0.5 text-[10.5px] font-medium uppercase tracking-wide ${tone}`}
    >
      {label}
    </span>
  );
}

/* ── Not-configured banner ──────────────────────────────────────────────────── */

function SetupNotice() {
  return (
    <div className="rounded-xl border border-status-warning/25 bg-status-warning-soft px-4 py-3 text-[13px] leading-relaxed text-status-warning">
      The portfolio lens isn't set up yet. Apply{" "}
      <code className="rounded bg-surface/60 px-1">SQL Tables/prosus_companies.sql</code> and{" "}
      <code className="rounded bg-surface/60 px-1">migrations/2026-07-03_prosus_tags.sql</code> in
      Supabase, then run <code className="rounded bg-surface/60 px-1">prosus_seed.py</code> and{" "}
      <code className="rounded bg-surface/60 px-1">prosus_backfill.py</code>. Stories from the
      dedicated Prosus feed still appear below once{" "}
      <code className="rounded bg-surface/60 px-1">TOQAN_PROSUS_NEWS</code> is configured.
    </div>
  );
}
