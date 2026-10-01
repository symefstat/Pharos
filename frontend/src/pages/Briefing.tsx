import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Sparkles, Bell, Activity, RefreshCw, Check, ChevronDown, ChevronUp, Compass, FlaskConical, History, SlidersHorizontal, X } from "lucide-react";
import { api } from "../lib/api";
import type {
  BriefingRadarItem,
  BriefingPayload,
  Convergence,
  Signal,
  SinceCounts,
  Story,
  Strategist,
  StrategistRead,
  FeedHealth,
  WatchlistAlert,
  WatchlistItem,
  WatchlistMove,
} from "../lib/api";
import { sourceTier, TIER_TOOLTIP } from "../lib/sources";
import { glossFor } from "../lib/glossary";
import { useResource } from "../lib/useResource";
import { PageChrome, DefaultSkeleton } from "../components/PageChrome";
import { Card, CardBody, SectionHeading, Badge, Segmented, StoryLink, Rich, Dot } from "../components/ui";
import { ActionButton } from "../components/actions";
import { useAuth } from "../lib/auth";
import { StoryRow } from "../components/Story";
import { cn } from "../lib/utils";
import { pct, pubDate, shortDate } from "../lib/format";
import {
  DOMAIN_OPTIONS,
  MANDATE_HINT_KEY,
  clearMandate,
  isEmptyMandate,
  loadMandate,
  matchReason,
  matchSignal,
  saveMandate,
  type Mandate,
  type MandateMatch,
} from "../lib/mandate";

/* Confidence wears STATUS tokens (state, not identity) — always beside a label. */
const CONF_ACCENT: Record<string, string> = {
  high: "var(--color-status-good)",
  medium: "var(--color-status-warning)",
  low: "var(--color-flat)",
};
const CONF_CHIP: Record<string, string> = {
  high: "bg-status-good-soft text-status-good",
  medium: "bg-status-warning-soft text-status-warning",
  low: "bg-[color:var(--color-chart-grid)] text-muted",
};

export default function BriefingPage() {
  const resource = useResource(api.briefing, { key: "briefing" });
  return (
    <PageChrome
      title="Briefing"
      subtitle="What changed today: decisive signals with actions, addressees, and what would prove them wrong."
      resource={resource}
      skeleton={<DefaultSkeleton />}
    >
      {(data) => <Briefing data={data} />}
    </PageChrome>
  );
}

function Briefing({ data }: { data: BriefingPayload }) {
  const { isAuthed } = useAuth();
  return (
    <div className="space-y-7">
      {isAuthed && (
        <div className="flex flex-wrap items-start gap-2">
          <ActionButton slot="briefing-refresh" path="/api/actions/refresh-all" label="Refresh all data" icon={<RefreshCw className="h-3.5 w-3.5" />} primary />
          <ActionButton slot="briefing-strategist" path="/api/actions/strategist" label="Regenerate strategist" icon={<Sparkles className="h-3.5 w-3.5" />} />
        </div>
      )}
      {data.strategist ? (
        <StrategistView read={data.strategist.read} asOf={data.strategist.as_of} stories={data.strategist.stories} />
      ) : (
        <Card><CardBody><p className="text-[13px] text-muted">No strategic read generated yet.</p></CardBody></Card>
      )}
      <SinceLastVisit strategist={data.strategist} />
      <FalsifierStrip />
      <TrustStrip data={data} />
      <RadarStrip items={data.radar ?? []} />
      <WatchlistPanel watchlist={data.watchlist} />
      <PulseOverview pulse={data.pulse} />
    </div>
  );
}

/* ── Page-local helpers ──────────────────────────────────────────────────────── */

/** New on the radar — the horizon scan's freshest evidence-gated candidates.
 *  Compact by design: the Briefing points at Radar, it doesn't replace it. */
function RadarStrip({ items }: { items: BriefingRadarItem[] }) {
  if (!items.length) return null;
  return (
    <Card>
      <CardBody className="py-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <SectionHeading
            title="New on the radar"
            description="Surfaced from unmatched evidence — not tracked yet, awaiting a decision"
          />
          <Link to="/radar" className="text-[12.5px] font-medium text-brand hover:underline">
            Open Radar →
          </Link>
        </div>
        <ul className="mt-1 grid grid-cols-1 gap-3 md:grid-cols-3">
          {items.map((r) => (
            <li key={r.key} className="rounded-xl border border-line bg-canvas p-3">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[13px] font-semibold">{r.label}</span>
                {r.research_stage && <Badge variant="brand">research-stage</Badge>}
              </div>
              <p className="num mt-1 text-[11px] text-faint">
                {r.mentions} stories · {r.sources} publishers
                {r.papers > 0 ? ` · ${r.papers} papers` : ""}
              </p>
              {r.why && (
                <p className="mt-1 text-[12px] leading-snug text-muted">
                  {r.why.replace(/\s*\[S\d+\]/g, "")}
                </p>
              )}
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}

/** Density rule: show `limit` rows, fold the rest behind "Show all N". */
function FoldList<T>({
  items,
  limit = 5,
  ulClass,
  render,
}: {
  items: T[];
  limit?: number;
  ulClass?: string;
  render: (item: T, i: number) => ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? items : items.slice(0, limit);
  return (
    <div>
      <ul className={ulClass}>{shown.map(render)}</ul>
      {items.length > limit && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="mt-1.5 inline-flex items-center gap-1 text-[11.5px] font-medium text-muted transition-colors hover:text-ink"
        >
          {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          {expanded ? "Show fewer" : `Show all ${items.length}`}
        </button>
      )}
    </div>
  );
}

/** Small source/entity chip — identity as a labeled mark, never color alone. */
function MiniChip({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-line bg-canvas px-1.5 py-0.5 text-[10.5px] text-muted">
      {children}
    </span>
  );
}

/* ── Falsifier strip — "what would prove us wrong" may just have happened ──────
   Compact amber banner when any open call's falsifier has RECENT candidate
   evidence (falsifier_events, last 7 days). Fetched lazily and fail-silent:
   a missing table/endpoint just means no strip. Distinct forecasts counted, not
   raw events — three articles against one falsifier is still one falsifier. */

const FALSIFIER_RECENT_DAYS = 7;

function FalsifierStrip() {
  const [count, setCount] = useState(0);
  useEffect(() => {
    let alive = true;
    api
      .falsifierEvents()
      .then((p) => {
        const cutoff = Date.now() - FALSIFIER_RECENT_DAYS * 86_400_000;
        const preds = new Set(
          (p.events ?? [])
            .filter((e) => e.detected_at && new Date(e.detected_at).getTime() >= cutoff)
            .map((e) => e.pred_id),
        );
        if (alive) setCount(preds.size);
      })
      .catch(() => {
        /* fail silent — no strip */
      });
    return () => {
      alive = false;
    };
  }, []);
  if (count === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-status-warning/25 bg-status-warning-soft px-4 py-2.5 text-[12px] leading-snug text-ink-soft">
      <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-status-warning" />
      <span className="font-medium text-ink">
        {count} falsifier{count > 1 ? "s" : ""} may have triggered
      </span>
      <span>— evidence found in fresh news; nothing resolves until a human grades it.</span>
      <Link
        to="/ledger"
        className="ml-auto whitespace-nowrap text-[11.5px] font-medium text-brand no-underline hover:underline"
      >
        Review in Track record →
      </Link>
    </div>
  );
}

/* ── "Since your last visit" — the return loop's welcome-back line ─────────────
   Client-side: the previous visit lives in localStorage and is re-stamped on
   every Briefing mount. The previous value is memoized at module level so
   StrictMode's double effects (and tab-hopping within one SPA session) don't
   overwrite it with "just now". Counts come from a cheap /api/briefing/since
   aggregation; "new signals" is derived from the strategist read's as_of. */

const LAST_VISIT_KEY = "lodestar-last-visit";
const SINCE_MIN_GAP_MS = 6 * 3_600_000;
let prevVisitMemo: string | null | undefined;

/** Read the previous visit (once per SPA load), then stamp now. */
function markVisit(): string | null {
  try {
    if (prevVisitMemo === undefined) prevVisitMemo = localStorage.getItem(LAST_VISIT_KEY);
    localStorage.setItem(LAST_VISIT_KEY, new Date().toISOString());
  } catch {
    prevVisitMemo = null; // storage unavailable (private mode) — no strip
  }
  return prevVisitMemo ?? null;
}

function plural(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

function SinceLastVisit({ strategist }: { strategist: Strategist | null }) {
  const [prev, setPrev] = useState<string | null>(null);
  const [counts, setCounts] = useState<SinceCounts | null>(null);
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    const p = markVisit();
    if (!p) return;
    const gap = Date.now() - new Date(p).getTime();
    if (!isFinite(gap) || gap < SINCE_MIN_GAP_MS) return;
    setPrev(p);
    api
      .briefingSince(p)
      .then(setCounts)
      .catch(() => {
        /* fail silent — no strip */
      });
  }, []);
  if (dismissed || !prev || !counts) return null;

  // Signals are "new" when the strategist read post-dates the last visit day.
  const newSignals =
    strategist?.as_of && strategist.as_of.slice(0, 10) > prev.slice(0, 10)
      ? strategist.read.signals?.length ?? 0
      : 0;
  const parts: string[] = [];
  if (newSignals > 0) parts.push(plural(newSignals, "new signal"));
  if (counts.resolved > 0) parts.push(`${plural(counts.resolved, "forecast")} resolved`);
  if (counts.transitions > 0) parts.push(plural(counts.transitions, "stage transition"));
  if (parts.length === 0) return null; // nothing new — no strip

  const hours = Math.max(1, Math.round((Date.now() - new Date(prev).getTime()) / 3_600_000));
  const ago = hours >= 48 ? `${Math.round(hours / 24)} days ago` : `${hours} hours ago`;
  return (
    <div className="flex items-center gap-2 rounded-lg border border-line bg-canvas px-4 py-2 text-[12px] leading-snug text-ink-soft">
      <History className="h-3.5 w-3.5 shrink-0 text-faint" />
      <span>
        <span className="font-medium text-ink">Since your last visit</span>{" "}
        <span className="text-faint">({ago})</span>: {parts.join(" · ")}
      </span>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label="Dismiss"
        className="ml-auto shrink-0 text-faint transition-colors hover:text-ink"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

/* ── Trust strip — one-line calibration credentials; the ledger has the detail ── */
function TrustStrip({ data }: { data: BriefingPayload }) {
  const h = data.calibration.headline;
  // While no world-graded call has resolved, the pooled accuracy/Brier measure
  // internal consistency, not world-prediction skill — the chips say so.
  const internalOnly = (h.external?.resolved ?? 0) === 0;
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-lg border border-brand/20 bg-brand-soft/40 px-4 py-2.5 text-[12px] leading-snug text-ink-soft">
      <span className="font-medium text-ink">
        <Rich text={data.calibration.tagline} />
      </span>
      <span className="text-faint">·</span>
      <span
        title={internalOnly ? "Grades Pharos's own future labels — a consistency measure, not world-prediction skill. The world-graded record is on the Track record page." : undefined}
        className={internalOnly ? "cursor-help" : undefined}
      >
        {internalOnly ? "Internal accuracy" : "Accuracy"}{" "}
        <span className="num font-semibold text-ink">{h.accuracy != null ? pct(h.accuracy * 100, 0) : "—"}</span>
      </span>
      <span className="text-faint">·</span>
      <span title={glossFor("brier")} className="cursor-help">
        Brier <span className="num font-semibold text-ink">{h.brier != null ? h.brier.toFixed(2) : "—"}</span>
      </span>
      <span className="text-faint">
        (excludes quarantined price calls{h.quarantined_resolved ? `, ${h.quarantined_resolved} resolved held out` : ""})
      </span>
      <Link to="/ledger" className="ml-auto whitespace-nowrap text-[11.5px] font-medium text-brand no-underline hover:underline">
        Full track record →
      </Link>
    </div>
  );
}

/* ── Strategist read ─────────────────────────────────────────────────────────── */
function StrategistView({
  read,
  asOf,
  stories,
}: {
  read: StrategistRead;
  asOf: string | null;
  stories: Story[];
}) {
  const signals = read.signals ?? [];
  const scenarios = read.scenarios ?? {};
  // The strategist labels its developments S1..Sn; a signal's `sources` hold those
  // ids, so this resolves each chip back to the actual story (title + link).
  const storyByLabel = useMemo(
    () => new Map(stories.map((s) => [String(s.label ?? ""), s])),
    [stories],
  );
  const convergence = read.convergence ?? [];
  // Convergence only earns the space when it's genuinely cross-feed: at least
  // one item must cite ≥2 distinct feeds, else it's single-source restated.
  const showConvergence = convergence.some((c) => new Set(c.feeds ?? []).size >= 2);

  // ── Mandate personalization — client-side only (localStorage, no auth) ──────
  const [mandate, setMandate] = useState<Mandate | null>(() => loadMandate());
  const [mandateOpen, setMandateOpen] = useState(false);
  const [persona, setPersona] = useState<string>(() => {
    try {
      return localStorage.getItem(PERSONA_KEY) ?? "all";
    } catch {
      return "all";
    }
  });
  const setPersonaPref = (v: string) => {
    setPersona(v);
    try {
      localStorage.setItem(PERSONA_KEY, v);
    } catch {
      /* private mode — session only */
    }
  };
  const [hintDismissed, setHintDismissed] = useState(() => {
    try {
      return localStorage.getItem(MANDATE_HINT_KEY) === "1";
    } catch {
      return true; // storage unavailable — the hint could never persist anyway
    }
  });

  // Re-rank: matched signals rise (score desc, original order as tie-break);
  // unmatched signals keep their original relative order below. `i` stays the
  // signal's original index — it remains the React key, so cards keep their
  // expand/collapse state across re-ranking. No mandate → exactly the original
  // order with no match info.
  const ranked = useMemo(() => {
    const entries = signals.map((sig, i) => {
      if (!mandate) return { sig, i, match: null as MandateMatch | null };
      // A signal's domains = the feed labels of the stories it cites.
      const feeds = new Set<string>();
      for (const label of sig.sources ?? []) {
        const st = storyByLabel.get(label);
        const feed = st?.feed_label ?? st?._feed_label;
        if (feed) feeds.add(feed);
      }
      return { sig, i, match: matchSignal(sig, mandate, [...feeds]) };
    });
    if (!mandate) return entries;
    return [...entries].sort((a, b) => b.match!.score - a.match!.score || a.i - b.i);
  }, [signals, mandate, storyByLabel]);

  return (
    <Card>
      <CardBody>
        <SectionHeading
          icon={<Sparkles className="h-4 w-4" />}
          title="Strategist read"
          description={`Decisive signals → recommended moves, read through MOT theory.${asOf ? ` As of ${asOf}.` : ""}`}
          right={
            <button
              type="button"
              onClick={() => setMandateOpen((o) => !o)}
              aria-expanded={mandateOpen}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-canvas px-2.5 py-1.5 text-[11.5px] font-medium text-muted transition-colors hover:border-brand/40 hover:text-ink"
            >
              <SlidersHorizontal className="h-3.5 w-3.5" />
              Your mandate
              {mandate && <Dot color="var(--color-status-good)" className="h-1.5 w-1.5" />}
            </button>
          }
        />

        {mandateOpen && (
          <MandatePanel
            mandate={mandate}
            onSave={(m) => {
              saveMandate(m);
              setMandate(isEmptyMandate(m) ? null : m);
              setMandateOpen(false);
            }}
            onClear={() => {
              clearMandate();
              setMandate(null);
              setMandateOpen(false);
            }}
          />
        )}

        {read.bottom_line && (
          <div className="rounded-xl border-l-[3px] border-brand bg-canvas px-4 py-3">
            <p className="text-[10px] font-medium uppercase tracking-[0.08em] text-faint">Bottom line</p>
            <p className="mt-1 text-[15px] font-medium leading-relaxed text-ink">{read.bottom_line}</p>
          </div>
        )}

        {!mandate && !hintDismissed && (
          <div className="mt-2 flex items-center gap-2 text-[11.5px] leading-snug">
            <button
              type="button"
              onClick={() => setMandateOpen(true)}
              className="font-medium text-brand transition-colors hover:underline"
            >
              Tell Pharos your mandate to rank signals for you →
            </button>
            <button
              type="button"
              aria-label="Dismiss mandate hint"
              onClick={() => {
                setHintDismissed(true);
                try {
                  localStorage.setItem(MANDATE_HINT_KEY, "1");
                } catch {
                  /* private mode — dismiss for this session only */
                }
              }}
              className="text-faint transition-colors hover:text-ink"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        )}

        {signals.length > 0 && (
          <>
            <div className="mb-3 mt-6 flex flex-wrap items-center justify-between gap-2">
              <p className="text-[12.5px] font-medium text-muted">Decisive signals</p>
              {/* zero-setup persona lens — coarser than the mandate, instant.
                  'both' signals show under every lens: a filter must never
                  hide what it can't confidently classify. */}
              <Segmented
                options={[
                  ["all", `All (${ranked.length})`],
                  ["strategy", `Operators (${ranked.filter((e) => (e.sig.persona ?? "both") !== "investment").length})`],
                  ["investment", `Investors (${ranked.filter((e) => (e.sig.persona ?? "both") !== "strategy").length})`],
                ]}
                value={persona}
                onChange={setPersonaPref}
              />
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
              {ranked
                .filter(({ sig }) =>
                  persona === "all" ||
                  (sig.persona ?? "both") === "both" ||
                  (sig.persona ?? "both") === persona)
                .map(({ sig, i, match }) => (
                  <SignalCard key={i} sig={sig} storyByLabel={storyByLabel} match={match} />
                ))}
            </div>
          </>
        )}

        {showConvergence && (
          <>
            <p className="mb-2 mt-6 text-[12.5px] font-medium text-muted">Cross-domain convergence</p>
            <ul className="space-y-2.5">
              {convergence.map((c, i) => (
                <ConvergenceItem key={i} c={c} storyByLabel={storyByLabel} />
              ))}
            </ul>
          </>
        )}

        {(scenarios.base || scenarios.bull || scenarios.bear) && (
          <details className="group mt-6">
            <summary className="cursor-pointer select-none text-[12.5px] text-muted transition-colors hover:text-ink">
              <span className="font-medium">Scenarios</span>
              {/* teaser so the fold reads as content, not a footnote; gone once open */}
              <span className="text-faint group-open:hidden">
                {" — base / bull / bear"}
                {scenarios.base ? `: ${scenarios.base.slice(0, 90).trimEnd()}…` : ""}
              </span>
            </summary>
            {/* polarity, not status: bull/bear wear the diverging poles, base the neutral midpoint */}
            <div className="mt-2 grid gap-3 sm:grid-cols-3">
              {([
                ["Base", scenarios.base, "var(--color-flat)"],
                ["Bull", scenarios.bull, "var(--color-div-pos)"],
                ["Bear", scenarios.bear, "var(--color-div-neg)"],
              ] as const).map(([label, text, color]) => (
                <div key={label} className="rounded-lg border border-line bg-surface p-3" style={{ borderTopColor: color, borderTopWidth: 2 }}>
                  {/* the colored mark carries polarity; the text wears ink */}
                  <p className="flex items-center gap-1.5 text-[12px] font-semibold text-ink">
                    <Dot color={color} className="h-1.5 w-1.5" />
                    {label}
                  </p>
                  <ExpandableText text={text || "—"} clampClass="line-clamp-4" className="mt-1 text-[12.5px] leading-relaxed text-muted" />
                </div>
              ))}
            </div>
          </details>
        )}

        {(read.watch ?? []).length > 0 && (
          <>
            <p className="mb-2 mt-6 text-[12.5px] font-medium text-muted">What to watch</p>
            <FoldList
              items={read.watch!}
              limit={5}
              ulClass="space-y-1.5"
              render={(w, i) => (
                <li key={i} className="line-clamp-2 text-[13px] leading-snug text-ink-soft">
                  <span className="font-semibold text-ink">{w.item}</span>
                  {w.horizon ? <span className="ml-1 text-[11px] text-faint">[{w.horizon}]</span> : null} — {w.why}
                </li>
              )}
            />
          </>
        )}
      </CardBody>
    </Card>
  );
}

/* ── "Your mandate" — one-time reader profile, stored in localStorage only ─────
   Visible to everyone (client-side personalization, not auth). Domains are the
   feed labels; interests are free keywords; role is who the reader is, matched
   against the addressee clause of each recommended action. */
function MandatePanel({
  mandate,
  onSave,
  onClear,
}: {
  mandate: Mandate | null;
  onSave: (m: Mandate) => void;
  onClear: () => void;
}) {
  const [domains, setDomains] = useState<string[]>(mandate?.domains ?? []);
  const [interests, setInterests] = useState(mandate?.interests ?? "");
  const [role, setRole] = useState(mandate?.role ?? "");
  const toggle = (d: string) =>
    setDomains((cur) => (cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d]));
  const inputCls =
    "mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12.5px] normal-case tracking-normal text-ink outline-none transition-colors placeholder:text-faint focus:border-brand";
  return (
    <div className="mb-4 rounded-xl border border-line bg-canvas p-4">
      <p className="text-[12.5px] font-medium text-ink">Your mandate</p>
      <p className="mt-0.5 text-[11.5px] leading-snug text-muted">
        Stored only in this browser — signals that match are ranked first and badged. Nothing is
        sent anywhere.
      </p>
      <p className="mt-3 text-[10.5px] font-medium uppercase tracking-[0.07em] text-faint">Domains</p>
      <div className="mt-1.5 flex flex-wrap gap-x-3.5 gap-y-1.5">
        {DOMAIN_OPTIONS.map((d) => (
          <label key={d} className="inline-flex cursor-pointer items-center gap-1.5 text-[12px] text-ink-soft">
            <input
              type="checkbox"
              checked={domains.includes(d)}
              onChange={() => toggle(d)}
              className="h-3.5 w-3.5 accent-[color:var(--color-brand)]"
            />
            {d}
          </label>
        ))}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="block text-[10.5px] font-medium uppercase tracking-[0.07em] text-faint">
          Interests (comma-separated)
          <input
            type="text"
            value={interests}
            onChange={(e) => setInterests(e.target.value)}
            placeholder="solid-state, LFP, grid storage"
            className={inputCls}
          />
        </label>
        <label className="block text-[10.5px] font-medium uppercase tracking-[0.07em] text-faint">
          Your role
          <input
            type="text"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            placeholder="e.g. payments processor, battery-materials investor"
            className={inputCls}
          />
        </label>
      </div>
      <div className="mt-3.5 flex items-center gap-2">
        <button
          type="button"
          onClick={() => onSave({ domains, interests: interests.trim(), role: role.trim() })}
          className="rounded-lg bg-brand px-3 py-1.5 text-[12px] font-medium text-white transition-opacity hover:opacity-90"
        >
          Save
        </button>
        <button
          type="button"
          onClick={onClear}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-[12px] font-medium text-muted transition-colors hover:text-ink"
        >
          Clear
        </button>
      </div>
    </div>
  );
}

/** Development ids the strategist cites in prose, e.g. "[S3]" or "S3". Returns
 *  unique labels ("S3") in first-seen order so they resolve back to stories. */
function extractSourceLabels(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  const re = /\bS(\d+)\b/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const label = `S${m[1]}`;
    if (!seen.has(label)) {
      seen.add(label);
      out.push(label);
    }
  }
  return out;
}

/** Strip inline [S#]/[T#] citation tokens (now shown as chips) and tidy the
 *  leftover spacing/punctuation so the sentence reads cleanly. */
function stripCitations(text: string): string {
  return text
    .replace(/\[\s*(?:[ST]\d+\s*[,;]?\s*)+\]/g, "")
    .replace(/\s+([.,;:!?])/g, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/** One cross-domain convergence row: theme + feeds, the implication (fully
 *  readable — expands rather than truncating), and the developments it cites
 *  resolved into clickable source chips. */
function ConvergenceItem({
  c,
  storyByLabel,
}: {
  c: Convergence;
  storyByLabel: Map<string, Story>;
}) {
  const [open, setOpen] = useState(false);
  // Prefer explicit sources from the read; fall back to ids parsed from prose.
  const labels = useMemo(
    () => (c.sources?.length ? c.sources : extractSourceLabels(c.implication)),
    [c.sources, c.implication],
  );
  const text = useMemo(() => stripCitations(c.implication), [c.implication]);
  const long = text.length > 160;
  return (
    <li className="text-[13px] leading-snug text-ink-soft">
      <p className={cn(!open && long && "line-clamp-2")}>
        <span className="font-semibold text-ink">{c.theme}</span>
        {c.feeds?.length ? <span className="text-faint"> ({c.feeds.join(" + ")})</span> : null}
        {text ? <> — {text}</> : null}
      </p>
      {(labels.length > 0 || long) && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {labels.map((s) => (
            <SourceChip key={s} label={s} story={storyByLabel.get(s)} />
          ))}
          {long && (
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              className="ml-auto inline-flex items-center gap-1 text-[11px] font-medium text-muted transition-colors hover:text-ink"
            >
              {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              {open ? "Less" : "More"}
            </button>
          )}
        </div>
      )}
    </li>
  );
}

/** Clamped paragraph with a "More" expander — no full-width text walls. */
function ExpandableText({
  text,
  clampClass,
  className,
}: {
  text: string;
  clampClass: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const long = text.length > 180;
  return (
    <>
      <p className={cn(className, !open && clampClass)}>{text}</p>
      {long && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="mt-0.5 text-[11px] font-medium text-muted transition-colors hover:text-ink"
        >
          {open ? "Less" : "More"}
        </button>
      )}
    </>
  );
}

/** A signal's source chip — resolves the strategist's S# id back to the story it
 *  cites, so it links to the article (title on hover) instead of being dead text.
 *  The outlet name rides along (muted, truncated) so a claim's provenance is
 *  visible without hovering. */
function SourceChip({ label, story }: { label: string; story?: Story }) {
  const title = story?.title
    ? `${story.title}${story.feed_label ? ` — ${story.feed_label}` : ""}`
    : `${label} — source not in this read`;
  const cls =
    "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10.5px] transition-colors";
  const outlet = story?.source_name ? (
    <span className="max-w-[8rem] truncate font-normal text-muted">{story.source_name}</span>
  ) : null;
  if (story?.url) {
    return (
      <a
        href={story.url}
        target="_blank"
        rel="noopener noreferrer"
        title={title}
        className={`${cls} border-brand/25 bg-brand-soft text-brand-ink no-underline hover:border-brand/50`}
      >
        {label}
        {outlet}
      </a>
    );
  }
  return (
    <span title={title} className={`${cls} border-line bg-canvas text-muted`}>
      {label}
      {outlet}
    </span>
  );
}

const PERSONA_KEY = "lodestar-persona-lens";
/* Decision window, spelled out from the signal's coarse horizon. */
const WINDOW: Record<string, string> = {
  near: "window: this quarter",
  mid: "window: 2–3 quarters",
  long: "window: 12+ months",
};

function SignalCard({
  sig,
  storyByLabel,
  match,
}: {
  sig: Signal;
  storyByLabel: Map<string, Story>;
  match?: MandateMatch | null;
}) {
  const conf = (sig.confidence ?? "").toLowerCase();
  const accent = CONF_ACCENT[conf] ?? "var(--color-flat)";
  const [open, setOpen] = useState(false);
  const hasSources = (sig.sources?.length ?? 0) > 0;
  // Source-authority disclosure: flag (neutrally) when EVERY cited source is
  // tier 3 — unrecognized outlets only, no wire/major or trade/primary among
  // them. Requires at least one source to resolve to a story, so a resolution
  // miss alone never fires the chip. Individual chips are never colored.
  const resolvedStories = (sig.sources ?? []).map((s) => storyByLabel.get(s));
  const singleTierSourcing =
    hasSources &&
    resolvedStories.some(Boolean) &&
    resolvedStories.every((st) => sourceTier(st?.source_name) === 3);
  const longText =
    (sig.implication?.length ?? 0) +
      (sig.action_rationale?.length ?? 0) +
      (sig.value_capture?.length ?? 0) +
      (sig.falsifier?.length ?? 0) >
    260;
  return (
    <div className="flex flex-col rounded-xl border border-line bg-surface p-4" style={{ borderLeftColor: accent, borderLeftWidth: 3 }}>
      {/* header: what it is (chips), then the claim */}
      <div className="flex flex-wrap items-center gap-1.5">
        {sig.lens && (
          <span title={glossFor(sig.lens)} className={glossFor(sig.lens) ? "cursor-help" : undefined}>
            <Badge variant="neutral">{sig.lens}</Badge>
          </span>
        )}
        {sig.impact && <Badge variant={sig.impact === "material" ? "commit" : "neutral"}>{sig.impact}</Badge>}
        {sig.confidence && (
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide",
              CONF_CHIP[conf] ?? CONF_CHIP.low,
            )}
          >
            {sig.confidence} conf
          </span>
        )}
        {sig.owner && (
          /* the decision owner, lifted from the rationale's addressee clause */
          <span title={`Decision owner: ${sig.owner}`}>
            <Badge variant="brand" className="normal-case tracking-normal">
              for {sig.owner.length > 44 ? sig.owner.slice(0, 42) + "…" : sig.owner}
            </Badge>
          </span>
        )}
        {sig.horizon && WINDOW[sig.horizon] && (
          <span title="Decision window, derived from the signal's stated horizon">
            <Badge variant="neutral" className="normal-case tracking-normal">
              {WINDOW[sig.horizon]}
            </Badge>
          </span>
        )}
        {match && match.score > 0 && (
          /* personalization chip — the title spells out exactly why it fired */
          <span title={matchReason(match)}>
            <Badge variant={match.role ? "up" : "brand"}>
              {match.role ? "addressed to you" : "relevant to your mandate"}
            </Badge>
          </span>
        )}
      </div>
      <p className="mt-2 text-[13.5px] font-semibold leading-snug text-ink">{sig.title}</p>
      <p className={cn("mt-1 text-[12.5px] leading-relaxed text-muted", !open && "line-clamp-3")}>{sig.implication}</p>

      {sig.action && (
        <div className={cn("mt-2.5 text-[12px] leading-relaxed", !open && "line-clamp-2")}>
          <span className="font-semibold capitalize text-brand">{sig.action}</span>
          {sig.action_rationale ? <span className="text-muted"> — {sig.action_rationale}</span> : null}
        </div>
      )}

      {sig.value_capture && (
        <div className="mt-2.5 rounded-md bg-warn-soft px-2.5 py-1.5">
          <p className="text-[9.5px] font-semibold uppercase tracking-[0.08em] text-warn">Value capture</p>
          <p className={cn("mt-0.5 text-[11.5px] leading-relaxed text-ink-soft", !open && "line-clamp-2")}>{sig.value_capture}</p>
        </div>
      )}

      {sig.standards && (sig.standards.leader || sig.standards.read) && (
        <p className={cn("mt-2 text-[11.5px] leading-relaxed text-muted", !open && "line-clamp-2")}>
          <span className="font-semibold text-ink-soft">Standards:</span>{" "}
          {sig.standards.leader && <span className="font-medium text-ink">{sig.standards.leader}</span>}
          {sig.standards.leader && sig.standards.read ? " — " : ""}
          {sig.standards.read}
          {sig.standards.basis?.length ? (
            <span className="text-faint"> ({sig.standards.basis.join(", ")})</span>
          ) : null}
        </p>
      )}

      {/* the honesty feature — a labeled, bordered row, visually distinct */}
      {sig.falsifier && (
        <div
          className="mt-2.5 rounded-md border border-line bg-canvas px-2.5 py-1.5"
          style={{ borderLeftColor: "var(--color-status-serious)", borderLeftWidth: 3 }}
        >
          <p className="text-[9.5px] font-semibold uppercase tracking-[0.08em] text-status-serious">Falsifier</p>
          <p className={cn("mt-0.5 text-[11.5px] leading-relaxed text-ink-soft", !open && "line-clamp-2")}>{sig.falsifier}</p>
        </div>
      )}

      <TrackAsThesisButton sig={sig} />

      {(hasSources || sig.horizon || longText) && (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          {/* dossier doors — the signal's tracked technologies */}
          {sig.techs?.map((t) => (
            <Link
              key={t.key}
              to={`/tech/${t.key}`}
              className="inline-flex items-center gap-1 rounded-md border border-brand/25 bg-brand-soft px-1.5 py-0.5 text-[10.5px] font-medium text-brand-ink no-underline transition-colors hover:border-brand/50"
              title={`Open the ${t.label} dossier`}
            >
              <FlaskConical className="h-3 w-3" />
              {t.label}
            </Link>
          ))}
          {sig.sources?.map((s) => (
            <SourceChip key={s} label={s} story={storyByLabel.get(s)} />
          ))}
          {singleTierSourcing && (
            <span
              title={`All of this signal's cited sources are unrecognized outlets. ${TIER_TOOLTIP}`}
              className="inline-flex items-center gap-1 rounded-md border border-dashed border-line bg-canvas px-1.5 py-0.5 text-[10.5px] text-muted"
            >
              single-tier sourcing
            </span>
          )}
          {sig.horizon && <span className="text-[10.5px] text-faint">{sig.horizon}</span>}
          {(longText || hasSources) && (
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              className="ml-auto inline-flex items-center gap-1 text-[11px] font-medium text-muted transition-colors hover:text-ink"
            >
              {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              {open ? "Less" : "More"}
            </button>
          )}
        </div>
      )}

      {/* Expanded: the sources spelled out (title + link), so "More" reveals them. */}
      {open && hasSources && (
        <ul className="mt-2 space-y-1 border-t border-line pt-2">
          {sig.sources!.map((s) => {
            const st = storyByLabel.get(s);
            return (
              <li key={s} className="flex items-baseline gap-1.5 text-[11.5px] leading-snug">
                <span className="shrink-0 font-semibold text-faint">{s}</span>
                {st?.url ? (
                  <StoryLink href={st.url}>{st.title}</StoryLink>
                ) : (
                  <span className="text-muted">{st?.title ?? "source not in this read"}</span>
                )}
                {st?.feed_label ? <span className="text-faint">· {st.feed_label}</span> : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/* ── "Track as thesis" — pre-register a signal in the private thesis book ──────
   Admin-only. One optimistic api.addThesis call: the signal's title becomes the
   thesis claim and its falsifier the thesis falsifier — the thesis-watch engine
   then scans news for it alongside the admin's own theses (Track record page).
   Theses live in their own table; this never touches the public ledger. */
function TrackAsThesisButton({ sig }: { sig: Signal }) {
  const { isAuthed } = useAuth();
  const [state, setState] = useState<"idle" | "tracked" | "error">("idle");
  if (!isAuthed || !sig.title || !sig.falsifier) return null;

  const track = () => {
    setState("tracked"); // optimistic — reverts to an error note only on failure
    void api.addThesis(sig.title, sig.falsifier!).then((r) => {
      if (!r.ok) setState("error");
    });
  };

  if (state === "tracked") {
    return (
      <p className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-status-good">
        <Check className="h-3 w-3 shrink-0" />
        Tracked as thesis — evidence will surface in Track record
      </p>
    );
  }
  return (
    <div className="mt-2 flex items-center gap-2">
      <button
        type="button"
        onClick={track}
        className="inline-flex items-center gap-1 rounded-md border border-line bg-canvas px-2 py-0.5 text-[11px] font-medium text-muted transition-colors hover:border-brand/40 hover:text-ink"
      >
        <Compass className="h-3 w-3 shrink-0" />
        Track as thesis
      </button>
      {state === "error" && (
        <span className="text-[11px] text-status-critical">could not register — try again</span>
      )}
    </div>
  );
}

/* ── Watchlist ───────────────────────────────────────────────────────────────── */

/** Inline "+ Track" input — adds a term on Enter (admin only). */
function TrackInput({ onAdd }: { onAdd: (term: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <input
      type="text"
      value={value}
      maxLength={80}
      placeholder="+ Track…"
      aria-label="Track a technology, entity or feed"
      onChange={(e) => setValue(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter" && value.trim()) {
          onAdd(value.trim());
          setValue("");
        }
      }}
      className="w-24 rounded-md border border-dashed border-line bg-canvas px-1.5 py-0.5 text-[10.5px] text-ink outline-none transition-all placeholder:text-faint focus:w-40 focus:border-brand"
    />
  );
}

function WatchlistPanel({ watchlist }: { watchlist: BriefingPayload["watchlist"] }) {
  const { alerts } = watchlist;
  const { isAuthed } = useAuth();
  // Local copy of the tracked items so add/remove can update optimistically;
  // resynced whenever the briefing payload refreshes.
  const [items, setItems] = useState<WatchlistItem[]>(watchlist.items);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setItems(watchlist.items), [watchlist.items]);

  // Competitor moves (Phase 3 🏢) — GET /api/watchlist carries each watched
  // entity's recent strategic moves (public read, so this renders for viewers
  // too). Fetched lazily and fail-silent: no moves just means no block.
  const [movesByTerm, setMovesByTerm] = useState<Map<string, WatchlistMove[]>>(new Map());
  useEffect(() => {
    let alive = true;
    api
      .watchlist()
      .then((p) => {
        if (!alive) return;
        const m = new Map<string, WatchlistMove[]>();
        for (const e of p.items ?? []) {
          if (e.moves?.length) m.set(e.term.toLowerCase(), e.moves);
        }
        setMovesByTerm(m);
      })
      .catch(() => {
        /* fail silent — chips render without moves */
      });
    return () => {
      alive = false;
    };
  }, [watchlist.items]);

  async function add(term: string) {
    if (items.some((it) => it.value.toLowerCase() === term.toLowerCase())) return;
    setError(null);
    const before = items;
    const temp: WatchlistItem = { id: -Date.now(), kind: "entity", value: term };
    setItems([...before, temp]); // optimistic
    const r = await api.addWatch(term);
    if (!r.ok) {
      setItems(before); // revert
      setError(r.error ?? "Could not add to watchlist");
    } else if (r.item) {
      // Canonicalize (e.g. a technology label resolves to its key).
      const item = r.item;
      setItems((cur) =>
        cur.map((it) => (it.id === temp.id ? { ...it, kind: item.kind, value: item.term } : it)),
      );
    }
  }

  async function remove(target: WatchlistItem) {
    setError(null);
    const before = items;
    setItems(before.filter((it) => !(it.kind === target.kind && it.value === target.value))); // optimistic
    const r = await api.removeWatch(target.value);
    if (!r.ok) {
      setItems(before); // revert
      setError(r.error ?? "Could not remove from watchlist");
    }
  }

  // Chips (with × when admin) + the inline add input — shared by both layouts.
  const chips = (
    <>
      {items.map((it) => (
        <MiniChip key={`${it.kind}:${it.value}`}>
          {it.value}
          {isAuthed && (
            <button
              type="button"
              onClick={() => void remove(it)}
              aria-label={`Stop tracking ${it.value}`}
              className="-mr-0.5 text-faint transition-colors hover:text-status-critical"
            >
              <X className="h-2.5 w-2.5" />
            </button>
          )}
        </MiniChip>
      ))}
      {isAuthed && <TrackInput onAdd={(t) => void add(t)} />}
      {error && <span className="text-[11px] text-status-critical">{error}</span>}
    </>
  );

  // Watched entities with recent strategic moves — rendered under the chips
  // (read-only, so public viewers see them too).
  const moveRows = items
    .filter((it) => it.kind === "entity")
    .map((it) => ({ it, moves: movesByTerm.get(it.value.toLowerCase()) ?? [] }))
    .filter((x) => x.moves.length > 0);
  const movesBlock =
    moveRows.length > 0 ? (
      <div className="mt-2.5 space-y-1.5">
        <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">
          Competitor moves (7d)
        </p>
        {moveRows.map(({ it, moves }) => (
          <div key={`${it.kind}:${it.value}`} className="text-[11.5px] leading-snug">
            <span className="font-semibold text-ink">{it.value}</span>
            <ul className="mt-0.5 space-y-0.5">
              {moves.slice(0, 3).map((m, i) => (
                <li key={m.url ?? i} className="flex flex-wrap items-baseline gap-1.5">
                  <Badge variant="brand">{m.move}</Badge>
                  {m.url ? (
                    <StoryLink href={m.url}>{m.title ?? m.url}</StoryLink>
                  ) : (
                    <span className="text-muted">{m.title}</span>
                  )}
                  {m.published_at && (
                    <span className="num text-faint">{pubDate(m.published_at)}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    ) : null;

  // Quiet watchlist earns one line, not a card — the section only opens up
  // when there is actually something to report. Public viewers can't add
  // items, so an empty watchlist renders nothing for them rather than a
  // "nothing tracked yet" line they can't act on.
  if (alerts.length === 0) {
    if (items.length === 0 && !isAuthed) return null;
    return (
      <div>
        <div className="flex flex-wrap items-center gap-1.5 text-[12px] text-faint">
          <Bell className="h-3.5 w-3.5 shrink-0" />
          <span>Tracking:</span>
          {chips}
          {items.length > 0 && <span>— no alerts in the last 8h</span>}
        </div>
        {movesBlock}
      </div>
    );
  }
  return (
    <Card>
      <CardBody>
        <SectionHeading icon={<Bell className="h-4 w-4" />} title="Watchlist & alerts" description="New story alerts (last 8h) plus current stage transitions." />
        <FoldList
          items={alerts.slice(0, 10)}
          limit={5}
          ulClass="space-y-2"
          render={(a, i) => <AlertRow key={i} alert={a} />}
        />
        {(items.length > 0 || isAuthed) && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-faint">Tracking:</span>
            {chips}
          </div>
        )}
        {movesBlock}
      </CardBody>
    </Card>
  );
}

function AlertRow({ alert }: { alert: WatchlistAlert }) {
  if (alert.type === "transition")
    return (
      <li className="text-[13px] leading-snug">
        <span className="font-semibold text-ink">{alert.subject}</span>{" "}
        <span className="text-muted">— {alert.detail}</span>
      </li>
    );
  return (
    <li className="text-[13px] leading-snug">
      <span className="font-semibold text-ink">{alert.subject}</span>
      {alert.feed ? <span className="text-faint"> [{alert.feed}]</span> : null}:{" "}
      <StoryLink href={alert.url}>{alert.title}</StoryLink>
    </li>
  );
}

/* ── Pulse overview — top stories only; the KPI tiles live on Explore ─────────── */
function PulseOverview({ pulse }: { pulse: BriefingPayload["pulse"] }) {
  const { isAuthed } = useAuth();
  return (
    <Card>
      <CardBody>
        <SectionHeading
          icon={<Activity className="h-4 w-4" />}
          title="Top stories (7d)"
          right={
            <Link to="/explore" className="whitespace-nowrap text-[11.5px] font-medium text-brand no-underline hover:underline">
              Full trends →
            </Link>
          }
        />
        <FoldList
          items={pulse.top_stories.slice(0, 10)}
          limit={5}
          ulClass="divide-y divide-line"
          render={(st, i) => <StoryRow key={i} story={st} />}
        />
        {/* ops telemetry — admin eyes only */}
        {isAuthed && (
          <div className="mt-6">
            <p className="mb-2 text-[12.5px] font-medium text-muted">Feed health</p>
            <FeedHealthTable health={pulse.health} />
          </div>
        )}
      </CardBody>
    </Card>
  );
}

/** Freshness → status token; the date beside the dot carries the value. */
function freshnessColor(iso: string | null): string {
  if (!iso) return "var(--color-status-critical)";
  const days = (Date.now() - new Date(iso).getTime()) / 86400000;
  if (!isFinite(days) || days > 7) return "var(--color-status-serious)";
  if (days > 2) return "var(--color-status-warning)";
  return "var(--color-status-good)";
}

function FeedHealthTable({ health }: { health: FeedHealth[] }) {
  const classifiedPct = (h: FeedHealth) =>
    h.classified == null ? "n/a" : !h.rows ? "0%" : `${Math.floor((100 * h.classified) / h.rows)}%`;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12px]">
        <thead>
          <tr className="border-b border-line text-left text-[10.5px] uppercase tracking-wide text-faint">
            <th className="py-1.5 pr-2 font-medium">Feed</th>
            <th className="px-2 py-1.5 text-right font-medium">Rows</th>
            <th className="px-2 py-1.5 text-right font-medium">Classified</th>
            <th className="px-2 py-1.5 text-right font-medium">Fetched</th>
            <th className="py-1.5 pl-2 text-right font-medium">Rollup</th>
          </tr>
        </thead>
        <tbody>
          {health.map((h) => (
            <tr key={h.key} className="border-b border-line/50 last:border-0">
              <td className="py-1 pr-2 text-ink">
                {h.icon} {h.label}
                {!h.has_key && (
                  <span className="ml-1.5 text-[10px] font-medium text-status-critical">no key</span>
                )}
              </td>
              <td className="num px-2 py-1 text-right text-muted">{h.rows}</td>
              <td className="num px-2 py-1 text-right text-muted">{classifiedPct(h)}</td>
              <td className="px-2 py-1 text-right">
                <span className="inline-flex items-center gap-1.5">
                  <Dot color={freshnessColor(h.last_fetched)} className="h-1.5 w-1.5" />
                  <span className="num text-faint">{h.last_fetched ? shortDate(h.last_fetched) : "never"}</span>
                </span>
              </td>
              <td className="num py-1 pl-2 text-right text-faint">{h.last_rollup ? shortDate(h.last_rollup) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
