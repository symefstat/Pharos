import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Compass,
  Copy,
  Download,
  FlaskConical,
  Gauge,
  ListChecks,
  ShieldCheck,
} from "lucide-react";
import { api, apiUrl } from "../lib/api";
import type {
  FalsifierEvent,
  ForecastsPayload,
  LedgerPayload,
  LedgerRow,
  LedgerTech,
  Thesis,
  ThesisEvent,
} from "../lib/api";
import { useAuth } from "../lib/auth";
import { useResource } from "../lib/useResource";
import type { Resource } from "../lib/useResource";
import { PageChrome, DefaultSkeleton } from "../components/PageChrome";
import { Card, CardBody, SectionHeading, Badge, Rich, StoryLink } from "../components/ui";
import { CalibrationPlot, ChartFrame, StatTile } from "../components/viz";
import { ratioPct } from "../lib/format";
import { glossFor } from "../lib/glossary";

/* Track record — the one page for Pharos's forecast credibility:
   the graded public ledger (calibration, scorecard, receipts) up top,
   the forward view and live open calls beneath it, and the verifiable
   by-technology record + methodology at the end. Merges the former
   Forecasts and Ledger pages. */

const OUTCOME: Record<string, { label: string; variant: "up" | "down" | "warn" }> = {
  hit: { label: "Hit", variant: "up" },
  miss: { label: "Miss", variant: "down" },
  partial: { label: "Partial", variant: "warn" },
};

const VISIBLE_ROWS = 8;

/** Signed decimal ("+0.42" / "−0.21") for skill scores and edges. */
function signed(v: number | null | undefined, digits = 2): string {
  if (v == null || !isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
}

/* Every date on this page carries a year — the record spans years, so the
   year-less shortDate in lib/format.ts is ambiguous here. Local on purpose:
   other pages still want the compact form. */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-06-12" → "12 Jun 2026". Falls through for non-dates ("—", ""). */
function fmtDate(iso: string | null | undefined): string {
  if (!iso || iso === "—") return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

interface Combined {
  fc: ForecastsPayload;
  lg: LedgerPayload;
}

export default function TrackRecordPage() {
  const forecasts = useResource(api.forecasts, { key: "forecasts" });
  const ledger = useResource(api.ledger, { key: "ledger" });

  // Combined resource: ready only when both payloads are in; surfaces the
  // first error; "updated" shows the staler of the two timestamps.
  const refresh = () => {
    forecasts.refresh();
    ledger.refresh();
  };
  const resource: Resource<Combined> = {
    data:
      forecasts.data && ledger.data ? { fc: forecasts.data, lg: ledger.data } : null,
    loading: forecasts.loading || ledger.loading,
    error: forecasts.error ?? ledger.error,
    updatedAt:
      forecasts.updatedAt && ledger.updatedAt
        ? forecasts.updatedAt < ledger.updatedAt
          ? forecasts.updatedAt
          : ledger.updatedAt
        : (forecasts.updatedAt ?? ledger.updatedAt),
    refresh,
  };

  return (
    <PageChrome
      title="Track record"
      subtitle="The public record and the forward view — every call locked when made and graded in the open"
      resource={resource}
      skeleton={<DefaultSkeleton />}
    >
      {(data) => <TrackRecord fc={data.fc} lg={data.lg} onRefresh={refresh} />}
    </PageChrome>
  );
}

function TrackRecord({ fc, lg, onRefresh }: Combined & { onRefresh: () => void }) {
  const { isAuthed } = useAuth();
  const resolved = lg.forecasts.filter((r) => r.status === "resolved");
  const open = lg.forecasts.filter((r) => r.status === "open");
  const s = lg.stats;
  const ext = lg.records_by_basis?.external;
  const internal = lg.records_by_basis?.internal;
  const floor = lg.policy.headline_accuracy_floor;

  return (
    <div className="space-y-7">
      {/* 0 — The one sentence a skeptic must read first. Until a world-graded
          call resolves, the internal figures below measure the system's
          consistency, not proven forecasting skill — say so, prominently,
          before any 100% can be misread. */}
      {(!ext || ext.resolved === 0) && (
        <Card className="border-brand/30 bg-brand-soft/25">
          <CardBody className="py-4">
            <p className="text-[14px] font-semibold text-ink">
              Independent track record: building.
            </p>
            <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-muted">
              <span className="num font-medium text-ink-soft">{s.open}</span> calls are locked
              and on the clock
              {(() => {
                const due = lg.forecasts
                  .filter((r) => r.status === "open" && r.kind === "manual" && r.resolve_by)
                  .map((r) => r.resolve_by as string)
                  .sort()[0];
                return due ? (
                  <>
                    ; the first world-graded resolution is due{" "}
                    <span className="font-medium text-ink-soft">{fmtDate(due)}</span>
                  </>
                ) : null;
              })()}
              . Every accuracy figure below this line is an{" "}
              <span className="font-medium text-ink-soft">internal-consistency measure</span> —
              evidence the system behaves coherently, not yet proof it predicts the world.
              Price-direction calls are quarantined and never headline.
            </p>
          </CardBody>
        </Card>
      )}

      {/* 1 — Hero: the calibration curve IS the record */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<Gauge className="h-4 w-4" />}
            title="Calibration — the whole record, graded"
            description="When we say 60%, does it happen about 60% of the time? This curve is the answer."
            right={<DownloadButton />}
          />
          {/* World-graded record headlines (2.2): only calls resolved against
              public events are independently verifiable, so only they may lead.
              Until the FIRST one resolves, a scoreboard of dashes reads as
              broken — so the building state shows what IS true instead: how
              many calls are on the clock and when the record starts. */}
          {ext && ext.resolved > 0 ? (
            <>
              <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.08em] text-muted">
                World-graded record — Strategist calls resolved against public events
              </p>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <StatTile
                  label="Accuracy"
                  value={ext.accuracy != null ? ratioPct(ext.accuracy) : "—"}
                />
                <StatTile
                  label="Brier score"
                  value={ext.brier != null ? ext.brier.toFixed(2) : "—"}
                  help={glossFor("brier")}
                />
                <StatTile label="Resolved" value={ext.resolved} />
                <StatTile
                  label="Skill vs baseline"
                  value={ext.brier_skill != null ? signed(ext.brier_skill) : "no test"}
                />
              </div>
            </>
          ) : (
            <>
              <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.08em] text-muted">
                World-graded record — building. Calls are locked; none has reached
                its resolution date yet.
              </p>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <StatTile label="World-graded calls on the clock" value={ext?.open ?? 0} />
                <StatTile
                  label="First resolution due"
                  value={(() => {
                    const due = lg.forecasts
                      .filter((r) => r.status === "open" && r.kind === "manual" && r.resolve_by)
                      .map((r) => r.resolve_by as string)
                      .sort()[0];
                    return due ? fmtDate(due) : "—";
                  })()}
                />
                <StatTile label="Graded so far (all kinds)" value={s.resolved} />
              </div>
              <p className="mt-2 text-[12px] text-muted">
                Accuracy for the world-graded record appears with its first graded call —
                until then we show no number rather than a promise. Every open call below is
                already locked and cannot be edited.
              </p>
            </>
          )}
          {internal && internal.total > 0 && (
            <p className="mt-2.5 text-[12px] text-muted">
              Internal-consistency record (grades our <em>own</em> future labels — stage
              transitions, posture, deal flow — a consistency measure, not world-prediction):{" "}
              <span className="num">
                {internal.accuracy != null ? ratioPct(internal.accuracy) : "—"}
              </span>{" "}
              accuracy over <span className="num">{internal.resolved}</span> resolved,{" "}
              <span className="num">{internal.open}</span> open. Scored per category below.
            </p>
          )}
          <p className="mt-2.5 text-[12px] text-muted">
            Full ledger: <span className="num">{s.hits}</span> hits ·{" "}
            <span className="num">{s.misses}</span> misses
            {s.partials ? (
              <>
                {" "}
                · <span className="num">{s.partials}</span> partial
              </>
            ) : null}{" "}
            across <span className="num">{s.resolved}</span> graded calls (
            <span className="num">{s.total}</span> logged all-time, <span className="num">{s.open}</span>{" "}
            still open). Lower Brier is better; 0.25 is a coin flip at 50%. The calibration curve
            below spans the full non-quarantined record.
          </p>
          {/* One compact caveat box — the facts that qualify the headline. */}
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-line bg-canvas px-3 py-2.5">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
            <div className="space-y-1 text-[12.5px] leading-snug text-ink-soft">
              <p>
                Headline numbers{" "}
                <b className="font-semibold text-ink">exclude quarantined price-direction calls</b>{" "}
                — deliberate 50/50 momentum bets. They stay in the ledger below, flagged "held
                out", and are scored in their own category row
                {s.quarantined_resolved ? (
                  <>
                    {" "}
                    (<span className="num">{s.quarantined_resolved}</span> resolved held out)
                  </>
                ) : null}
                .
              </p>
              {s.resolved > 0 && s.resolved < floor && (
                <p>
                  <b className="font-semibold text-ink">Small record:</b> below{" "}
                  <span className="num">{floor}</span> resolved, one result can move the accuracy
                  figure by several points — read the tally, not the percentage.
                </p>
              )}
              {s.brier_skill == null && s.base_rate != null && (
                <p>
                  <b className="font-semibold text-ink">No skill score yet:</b> the graded
                  outcomes haven't varied (base rate{" "}
                  <span className="num">{ratioPct(s.base_rate)}</span>), so no discrimination has
                  been tested.
                </p>
              )}
            </div>
          </div>

          <div className="mt-7">
            <ChartFrame
              title="Stated confidence vs realized hit-rate"
              read={s.verdict}
              caption="Each dot is a confidence band over graded forecasts; dot size = number of calls. On the diagonal = perfectly calibrated; above it = underconfident, below = overconfident. Quarantined price calls are held out here, matching the headline stats."
              table={
                lg.calibration_bins.length
                  ? {
                      columns: ["Band", "Stated", "Realized", "n"],
                      rows: lg.calibration_bins.map((b) => [
                        b.band,
                        ratioPct(b.predicted),
                        ratioPct(b.actual),
                        b.n,
                      ]),
                    }
                  : undefined
              }
            >
              {lg.calibration_bins.length > 0 ? (
                <CalibrationPlot bins={lg.calibration_bins} height={320} />
              ) : (
                <p className="py-10 text-center text-[12.5px] text-faint">
                  Nothing graded yet — the curve appears with the first resolved forecasts.
                </p>
              )}
            </ChartFrame>
          </div>

          {/* Per-category scorecard — the quarantined calls scored in the open */}
          <div className="mt-7 overflow-x-auto">
            <p className="mb-2 text-[13.5px] font-semibold tracking-tight text-ink">
              Scorecard by category
            </p>
            <table className="w-full border-collapse text-[12px]">
              <thead>
                <tr className="text-[10.5px] font-medium uppercase tracking-[0.07em] text-faint">
                  <th className="border-b border-line pb-1.5 text-left font-medium">Category</th>
                  <th className="border-b border-line pb-1.5 text-right font-medium">Resolved</th>
                  <th className="border-b border-line pb-1.5 text-right font-medium">Record</th>
                  <th className="border-b border-line pb-1.5 text-right font-medium">Accuracy</th>
                  <th className="border-b border-line pb-1.5 text-right font-medium">Base rate</th>
                  <th className="border-b border-line pb-1.5 text-right font-medium">Naive baseline</th>
                  <th className="border-b border-line pb-1.5 text-right font-medium">Skill</th>
                </tr>
              </thead>
              <tbody>
                {lg.categories.map((c) => (
                  <tr key={c.category} className="border-b border-line last:border-0">
                    <td className="py-1.5 pr-3 text-ink">
                      {c.category}
                      {c.basis === "external" && (
                        <span className="ml-1.5 text-[10px] font-medium uppercase tracking-wide text-status-good">
                          world-graded
                        </span>
                      )}
                      {c.basis === "internal" && (
                        <span
                          className="ml-1.5 text-[10px] font-medium uppercase tracking-wide text-faint"
                          title="Graded against Pharos's own future labels — a consistency measure, not world-prediction"
                        >
                          internal
                        </span>
                      )}
                    </td>
                    <td className="num py-1.5 pl-3 text-right text-muted">{c.resolved}</td>
                    <td className="num py-1.5 pl-3 text-right text-muted">
                      {c.hits}✓ / {c.misses}✗{c.partials ? ` / ${c.partials}~` : ""}
                    </td>
                    <td className="num py-1.5 pl-3 text-right text-muted">
                      {c.accuracy != null ? ratioPct(c.accuracy) : "—"}
                    </td>
                    <td className="num py-1.5 pl-3 text-right text-muted">
                      {c.base_rate != null ? ratioPct(c.base_rate) : "—"}
                    </td>
                    <td className="num py-1.5 pl-3 text-right text-muted">
                      {c.baseline_accuracy != null ? ratioPct(c.baseline_accuracy) : "—"}
                    </td>
                    <td className="num py-1.5 pl-3 text-right text-muted">
                      {c.brier_skill != null
                        ? signed(c.brier_skill)
                        : c.base_rate != null
                          ? "no test"
                          : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[11.5px] leading-snug text-faint">
              Naive baseline = always predicting the majority outcome. Skill = 1 − Brier / the
              always-forecast-the-base-rate Brier; positive beats the dumb rule, "no test" means the
              outcome never varied so no discrimination has been tested yet.
            </p>
          </div>
        </CardBody>
      </Card>

      {/* 2 — Forward view: the only forward-looking exhibit */}
      <Card>
        <CardBody>
          <p className="text-[10.5px] font-medium uppercase tracking-[0.08em] text-faint">
            Forward view
          </p>
          <ReadMore text={fc.summary} />
          {fc.hero.length > 0 && (
            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              {fc.hero.map((h, i) => (
                <div key={i} className="rounded-xl border border-line bg-surface p-4">
                  <div className="flex items-center justify-between">
                    <Badge variant="brand">{h.category}</Badge>
                    <span className="num text-[13px] font-semibold text-brand">
                      {ratioPct(h.confidence)}
                    </span>
                  </div>
                  <p className="mt-2 text-[13px] leading-snug text-ink">{h.claim}</p>
                  {h.resolve_by && (
                    <p className="mt-2 text-[11.5px] text-faint">resolves {fmtDate(h.resolve_by)}</p>
                  )}
                </div>
              ))}
            </div>
          )}
          <p className="mt-3 text-[11.5px] text-faint">The 3 highest-conviction open calls.</p>
        </CardBody>
      </Card>

      {/* 2.5 — Falsifier watch: candidate evidence that an open call may be wrong.
          Self-fetching and fail-silent — renders nothing until events exist. */}
      <FalsifierWatchCard isAuthed={isAuthed} />

      {/* 2.6 — Theses: the investor's PRIVATE thesis book (admin-only, its own
          table — never part of the public ledger or the calibration stats). */}
      <ThesesCard isAuthed={isAuthed} />

      {/* 3 — Open forecasts: the ONE list of live calls (locked terms +
          fingerprints included — this table absorbed the old "Open
          commitments" duplicate) + admin-only grading of overdue calls */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<ListChecks className="h-4 w-4" />}
            title="Open forecasts"
            description={`${open.length} live calls — each locked with a deadline, its terms, and a verifiable fingerprint. Judgment calls are graded by hand when due; auto calls resolve from data.`}
          />
          {/* Grading writes an immutable outcome — admin-only, matching the
              require_admin gate on POST /api/forecasts/resolve. */}
          {isAuthed && fc.overdue.length > 0 && (
            <div className="mb-5 rounded-xl border border-status-warning/25 bg-status-warning-soft p-4">
              <p className="mb-2 flex items-center gap-1.5 text-[12.5px] font-semibold text-status-warning">
                <Clock className="h-3.5 w-3.5 shrink-0" />
                {fc.overdue.length} overdue judgment call{fc.overdue.length > 1 ? "s" : ""} — grade them
              </p>
              <ul className="space-y-2.5">
                {fc.overdue.map((o) => (
                  <Resolver key={o.id} id={o.id} claim={o.claim} onRefresh={onRefresh} />
                ))}
              </ul>
            </div>
          )}
          <CommitmentsTable rows={open} />
        </CardBody>
      </Card>

      {/* 4 — The receipts: every graded forecast, once */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<CheckCircle2 className="h-4 w-4" />}
            title="The receipts"
            description="Every graded forecast: when it was made, what was locked, and how it resolved. Outcomes are immutable once written."
          />
          <ResolvedTable rows={resolved} />
        </CardBody>
      </Card>

      {/* 5 — Per-technology transition record */}
      {lg.technologies.length > 0 && (
        <Card>
          <CardBody>
            <SectionHeading
              icon={<FlaskConical className="h-4 w-4" />}
              title="By technology — stage-transition calls"
              description="For each technology we track: where it stands today, what we're predicting next, and how past calls resolved."
            />
            <div className="grid gap-3 lg:grid-cols-2">
              {lg.technologies.map((t) => (
                <TechBlock key={t.tech} tech={t} />
              ))}
            </div>
            <p className="mt-3 text-[11.5px] leading-snug text-faint">
              "Today" is the anchored display stage — a curated world-truth floor advanced by news
              evidence, the same stage shown across the product. A transition call only grades as a
              hit once the advance is confirmed by two consecutive clean readings.
            </p>
          </CardBody>
        </Card>
      )}

      <Methodology data={lg} />

      {/* Verifiability footer */}
      <p className="px-1 text-[11.5px] leading-relaxed text-faint">
        Generated <span className="num">{fmtDate(lg.generated_at)}</span> · ledger digest{" "}
        <Fingerprint fp={lg.ledger_digest} chars={16} /> — recompute it from the downloaded JSON
        to verify this exact history (see Methodology).
      </p>
    </div>
  );
}

/* ── Download ───────────────────────────────────────────────────────────────── */

function DownloadButton() {
  return (
    <a
      // In prod the SPA and API are on different origins — a relative href 404s.
      href={apiUrl("/api/ledger?download=1")}
      download="pharos-ledger.json"
      className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-[13px] font-medium text-ink-soft transition-colors hover:border-line-strong hover:text-ink"
    >
      <Download className="h-3.5 w-3.5" />
      Download ledger (JSON)
    </a>
  );
}

/* ── Fingerprint chip — truncated, full value on hover, copies on click ─────── */

function Fingerprint({ fp, chars = 8 }: { fp: string | null; chars?: number }) {
  const [copied, setCopied] = useState(false);
  if (!fp) return <span className="text-faint">—</span>;
  return (
    <button
      type="button"
      title={`${fp} — click to copy`}
      onClick={() => {
        void navigator.clipboard?.writeText(fp);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      }}
      className="num inline-flex items-center gap-1 rounded-md border border-line bg-canvas px-1.5 py-0.5 text-[10.5px] text-muted transition-colors hover:text-ink"
    >
      {copied ? <Check className="h-3 w-3 text-status-good" /> : <Copy className="h-3 w-3" />}
      {fp.slice(0, chars)}
    </button>
  );
}

/* ── Shared table bits — chips filter + progressive disclosure ──────────────── */

function CategoryChips({
  cats,
  value,
  onChange,
}: {
  cats: string[];
  value: string;
  onChange: (c: string) => void;
}) {
  return (
    <div className="mb-3 flex flex-wrap gap-1.5">
      {["All", ...cats].map((c) => (
        <button
          key={c}
          onClick={() => onChange(c)}
          aria-pressed={c === value}
          className={`rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors ${
            c === value ? "bg-brand text-white" : "bg-canvas text-muted hover:text-ink"
          }`}
        >
          {c}
        </button>
      ))}
    </div>
  );
}

function ShowAllButton({
  expanded,
  total,
  onToggle,
}: {
  expanded: boolean;
  total: number;
  onToggle: () => void;
}) {
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

function useCategoryFold(rows: LedgerRow[]) {
  const cats = Array.from(new Set(rows.map((r) => r.category)));
  const [cat, setCat] = useState("All");
  const [expanded, setExpanded] = useState(false);
  const filtered = cat === "All" ? rows : rows.filter((r) => r.category === cat);
  const visible = expanded ? filtered : filtered.slice(0, VISIBLE_ROWS);
  return { cats, cat, setCat, expanded, setExpanded, filtered, visible };
}

/** The locked terms of a call — stage window or calibrated threshold. */
function LockedTerms({ row }: { row: LedgerRow }) {
  if (row.from_stage && row.to_stage) {
    return (
      <span className="whitespace-nowrap text-ink-soft">
        {row.from_stage} → {row.to_stage}
      </span>
    );
  }
  if (row.from_stage) {
    return <span className="whitespace-nowrap text-ink-soft">beyond {row.from_stage}</span>;
  }
  if (row.threshold != null) {
    return (
      <span
        className="num whitespace-nowrap text-ink-soft"
        title={row.threshold_basis ? `threshold ${row.threshold_basis}` : undefined}
      >
        ≥{row.threshold}
        {row.kind === "reactivity" ? "%" : ""}
        {row.threshold_basis?.startsWith("calibrated") ? "*" : ""}
      </span>
    );
  }
  return <span className="text-faint">—</span>;
}

function anyCalibrated(rows: LedgerRow[]): boolean {
  return rows.some((r) => r.threshold_basis?.startsWith("calibrated"));
}

/* ── Open forecasts table (live calls, ranked by conviction) ────────────────── */

function isPastDue(iso: string): boolean {
  if (!iso || iso === "—") return false;
  const today = new Date().toISOString().slice(0, 10);
  return iso < today;
}

/* ── Falsifier watch — "we told you what would prove us wrong; this may be it" ──
   Candidate evidence only: a text match between an open call's falsifier and a
   fresh article. Nothing here resolves anything — a human grades the forecast
   (admin, via the overdue block above / POST /api/forecasts/resolve). Fetched
   lazily and fail-silent so a missing table or endpoint never breaks the page. */

function FalsifierWatchCard({ isAuthed }: { isAuthed: boolean }) {
  const [events, setEvents] = useState<FalsifierEvent[]>([]);
  useEffect(() => {
    let alive = true;
    api
      .falsifierEvents()
      .then((p) => {
        if (alive) setEvents(p.events ?? []);
      })
      .catch(() => {
        /* fail silent — the card simply doesn't render */
      });
    return () => {
      alive = false;
    };
  }, []);
  if (events.length === 0) return null;
  return (
    <Card>
      <CardBody>
        <SectionHeading
          icon={<AlertTriangle className="h-4 w-4" />}
          title="Falsifier watch"
          description="We published what would prove each call wrong — these recent stories may be exactly that. Candidate evidence, not a verdict: each forecast stays open until a human grades it."
        />
        <ul className="space-y-3">
          {events.slice(0, VISIBLE_ROWS).map((e) => (
            <li
              key={e.id}
              className="rounded-xl border border-status-warning/25 bg-status-warning-soft p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <p className="text-[13px] leading-snug text-ink">{e.claim ?? e.falsifier}</p>
                <Badge variant="warn" className="shrink-0">
                  may have triggered
                </Badge>
              </div>
              {e.falsifier && (
                <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-soft">
                  <span className="font-semibold">Wrong if:</span> {e.falsifier}
                </p>
              )}
              <p className="mt-1.5 text-[12px] leading-snug">
                <StoryLink href={e.article_url ?? undefined}>{e.article_title}</StoryLink>
              </p>
              <p className="num mt-1 text-[11px] text-faint">
                match score {e.score != null ? e.score.toFixed(2) : "—"} · detected{" "}
                {fmtDate(e.detected_at?.slice(0, 10))}
                {e.published_at ? <> · published {fmtDate(e.published_at)}</> : null}
              </p>
              {isAuthed && (
                <p className="mt-1.5 text-[11.5px] font-medium text-status-warning">
                  If this evidence holds up, grade the forecast (hit / partial / miss) in Open
                  forecasts below — it won't resolve itself.
                </p>
              )}
            </li>
          ))}
        </ul>
        {events.length > VISIBLE_ROWS && (
          <p className="mt-2 text-[11.5px] text-faint">
            Showing the {VISIBLE_ROWS} most recent of {events.length} events.
          </p>
        )}
      </CardBody>
    </Card>
  );
}

/* ── Theses — the investor's private thesis book ("thesis maintenance") ───────
   Admin-only: theses live in their own table (never `predictions`), so they can
   never contaminate the public ledger or the calibration stats. The falsifier-
   watch engine scans news against each thesis's falsifier AND confirmer; events
   land here labeled "confirms" (good) or "falsifies" (warning). Fetched lazily
   and fail-silent so unapplied tables never break the page. */

const THESIS_EVENTS_SHOWN = 3;

const THESIS_LABEL_CHIP: Record<string, string> = {
  confirms: "bg-status-good-soft text-status-good",
  falsifies: "bg-status-warning-soft text-status-warning",
};

function ThesesCard({ isAuthed }: { isAuthed: boolean }) {
  const [theses, setTheses] = useState<Thesis[]>([]);
  const [events, setEvents] = useState<ThesisEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [claim, setClaim] = useState("");
  const [falsifier, setFalsifier] = useState("");
  const [confirmer, setConfirmer] = useState("");

  useEffect(() => {
    if (!isAuthed) return;
    let alive = true;
    Promise.all([api.theses(), api.thesisEvents()])
      .then(([t, e]) => {
        if (alive) {
          setTheses(t.theses ?? []);
          setEvents(e.events ?? []);
        }
      })
      .catch(() => {
        /* fail silent — tables not applied yet, or transport error */
      });
    return () => {
      alive = false;
    };
  }, [isAuthed]);

  if (!isAuthed) return null;

  const eventsFor = (id: number) => events.filter((e) => e.thesis_id === id);

  async function add() {
    const c = claim.trim();
    const f = falsifier.trim();
    if (!c || !f) {
      setError("A thesis needs both a claim and a falsifier.");
      return;
    }
    setBusy(true);
    setError(null);
    const r = await api.addThesis(c, f, confirmer.trim() || undefined);
    setBusy(false);
    if (!r.ok || !r.thesis) {
      setError(r.error ?? "Could not register the thesis");
      return;
    }
    setTheses((cur) => [r.thesis!, ...cur]);
    setClaim("");
    setFalsifier("");
    setConfirmer("");
  }

  async function archive(t: Thesis) {
    setError(null);
    const before = theses;
    setTheses(before.filter((x) => x.id !== t.id)); // optimistic
    const r = await api.archiveThesis(t.id);
    if (!r.ok) {
      setTheses(before); // revert
      setError(r.error ?? "Could not archive the thesis");
    }
  }

  const inputCls =
    "w-full rounded-lg border border-line bg-canvas px-3 py-1.5 text-[12.5px] text-ink outline-none transition-colors placeholder:text-faint focus:border-brand";

  return (
    <Card>
      <CardBody>
        <SectionHeading
          icon={<Compass className="h-4 w-4" />}
          title="Theses — private book"
          description="Your investment theses, each registered with what would prove it wrong (and, optionally, what would confirm it). The falsifier-watch engine scans fresh news for both — evidence lands here, labeled. Admin-only: nothing on this card touches the public ledger or the calibration stats."
        />

        {theses.length === 0 ? (
          <p className="text-[12.5px] italic text-faint">
            No theses registered yet — add the first one below.
          </p>
        ) : (
          <ul className="space-y-3">
            {theses.map((t) => {
              const evs = eventsFor(t.id);
              return (
                <li key={t.id} className="rounded-xl border border-line bg-surface p-4">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-[13.5px] font-semibold leading-snug text-ink">{t.claim}</p>
                    <button
                      type="button"
                      onClick={() => void archive(t)}
                      className="shrink-0 rounded-md border border-line bg-canvas px-2 py-0.5 text-[11px] font-medium text-muted transition-colors hover:border-line-strong hover:text-status-critical"
                    >
                      Archive
                    </button>
                  </div>
                  <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-soft">
                    <span className="font-semibold text-status-warning">Wrong if:</span>{" "}
                    {t.falsifier}
                  </p>
                  {t.confirmer && (
                    <p className="mt-1 text-[11.5px] leading-relaxed text-ink-soft">
                      <span className="font-semibold text-status-good">Confirmed by:</span>{" "}
                      {t.confirmer}
                    </p>
                  )}
                  <p className="num mt-1 text-[11px] text-faint">
                    registered {fmtDate(t.created_at?.slice(0, 10))}
                  </p>
                  {evs.length > 0 && (
                    <ul className="mt-2.5 space-y-1.5 border-t border-line pt-2.5">
                      {evs.slice(0, THESIS_EVENTS_SHOWN).map((e) => (
                        <li key={e.id} className="flex items-start gap-2 text-[12px] leading-snug">
                          <span
                            className={`mt-px inline-flex shrink-0 items-center rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                              THESIS_LABEL_CHIP[e.label] ?? "bg-canvas text-muted"
                            }`}
                          >
                            {e.label}
                          </span>
                          <span className="min-w-0">
                            <StoryLink href={e.article_url ?? undefined}>
                              {e.article_title}
                            </StoryLink>
                            <span className="num text-faint">
                              {" "}
                              · match {e.score != null ? e.score.toFixed(2) : "—"} · detected{" "}
                              {fmtDate(e.detected_at?.slice(0, 10))}
                            </span>
                          </span>
                        </li>
                      ))}
                      {evs.length > THESIS_EVENTS_SHOWN && (
                        <li className="text-[11px] text-faint">
                          + {evs.length - THESIS_EVENTS_SHOWN} earlier event
                          {evs.length - THESIS_EVENTS_SHOWN > 1 ? "s" : ""}
                        </li>
                      )}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {/* add form — claim + falsifier required, confirmer optional */}
        <div className="mt-4 rounded-xl border border-dashed border-line bg-canvas p-4">
          <p className="mb-2 text-[12px] font-semibold text-ink">Register a thesis</p>
          <div className="space-y-2">
            <input
              type="text"
              value={claim}
              maxLength={300}
              placeholder="Thesis — the claim you're invested in"
              aria-label="Thesis claim"
              onChange={(e) => setClaim(e.target.value)}
              className={inputCls}
            />
            <input
              type="text"
              value={falsifier}
              maxLength={300}
              placeholder="Falsifier — evidence that would prove it wrong"
              aria-label="Thesis falsifier"
              onChange={(e) => setFalsifier(e.target.value)}
              className={inputCls}
            />
            <input
              type="text"
              value={confirmer}
              maxLength={300}
              placeholder="Confirmer (optional) — evidence that would confirm it"
              aria-label="Thesis confirmer"
              onChange={(e) => setConfirmer(e.target.value)}
              className={inputCls}
            />
          </div>
          <div className="mt-2.5 flex items-center gap-3">
            <button
              type="button"
              disabled={busy || !claim.trim() || !falsifier.trim()}
              onClick={() => void add()}
              className="rounded-lg bg-brand px-3 py-1.5 text-[12.5px] font-medium text-white transition-opacity disabled:opacity-50"
            >
              {busy ? "Registering…" : "Register thesis"}
            </button>
            {error && <p className="text-[11.5px] text-status-critical">{error}</p>}
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

/* ── Resolver — inline grading with guard errors shown in place ────────────── */

function Resolver({
  id,
  claim,
  onRefresh,
}: {
  id: number;
  claim: string | null;
  onRefresh: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const grade = async (outcome: string) => {
    setBusy(true);
    setError(null);
    const res = await api.resolveForecast(id, outcome);
    if (!res.ok) {
      // Guard rejection (auto-graded kind / already resolved) or transport error.
      setError(res.error ?? "could not grade this forecast");
      setBusy(false);
      return;
    }
    onRefresh();
  };
  return (
    <li className="text-[12.5px]">
      <div className="flex items-start justify-between gap-3">
        <span className="text-ink">{claim}</span>
        <span className="flex shrink-0 gap-1">
          {(["hit", "partial", "miss"] as const).map((o) => (
            <button
              key={o}
              disabled={busy}
              onClick={() => grade(o)}
              className="rounded-md border border-line bg-surface px-2 py-0.5 text-[11px] font-medium capitalize text-ink-soft hover:border-line-strong disabled:opacity-50"
            >
              {o}
            </button>
          ))}
        </span>
      </div>
      {error && <p className="mt-1 text-[11.5px] text-status-critical">{error}</p>}
    </li>
  );
}

/* ── Resolved receipts table ───────────────────────────────────────────────── */

function ResolvedTable({ rows }: { rows: LedgerRow[] }) {
  const f = useCategoryFold(rows);
  if (rows.length === 0) {
    return (
      <p className="text-[12.5px] italic text-faint">
        Nothing graded yet — the record starts with the first resolution.
      </p>
    );
  }
  return (
    <>
      <CategoryChips cats={f.cats} value={f.cat} onChange={f.setCat} />
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-[12.5px]">
          <thead>
            <tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-faint">
              <th className="px-3 py-2 font-medium">Forecast</th>
              <th className="px-2 py-2 font-medium">Outcome</th>
              <th className="px-2 py-2 text-right font-medium">Conf</th>
              <th className="px-2 py-2 text-right font-medium">Made → resolved</th>
              <th className="px-2 py-2 font-medium">Locked terms</th>
              <th className="px-3 py-2 font-medium">Fingerprint</th>
            </tr>
          </thead>
          <tbody>
            {f.visible.map((r, i) => {
              const o = OUTCOME[r.outcome ?? ""] ?? { label: r.outcome ?? "—", variant: "warn" as const };
              return (
                <tr key={r.fingerprint ?? i} className="border-b border-line/50 align-top last:border-0">
                  <td className="px-3 py-2">
                    <p className="leading-snug text-ink">{r.claim}</p>
                    <p className="mt-0.5 text-[11.5px] text-faint">
                      {r.category}
                      {r.quarantined && (
                        <>
                          {" "}
                          · <Badge variant="warn">held out</Badge>
                        </>
                      )}
                      {r.evidence ? <> · {r.evidence}</> : null}
                    </p>
                  </td>
                  <td className="px-2 py-2">
                    <Badge variant={o.variant}>{o.label}</Badge>
                  </td>
                  <td className="num px-2 py-2 text-right font-medium text-ink">
                    {ratioPct(r.confidence)}
                  </td>
                  <td className="num whitespace-nowrap px-2 py-2 text-right text-faint">
                    {fmtDate(r.made_on)} → {r.resolved_on ? fmtDate(r.resolved_on) : "—"}
                  </td>
                  <td className="px-2 py-2">
                    <LockedTerms row={r} />
                  </td>
                  <td className="px-3 py-2">
                    <Fingerprint fp={r.fingerprint} />
                  </td>
                </tr>
              );
            })}
            {f.visible.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-faint">
                  No graded calls in this category yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {f.filtered.length > VISIBLE_ROWS && (
        <ShowAllButton
          expanded={f.expanded}
          total={f.filtered.length}
          onToggle={() => f.setExpanded((e) => !e)}
        />
      )}
      <p className="mt-2 text-[11.5px] text-faint">
        Confidence and terms are exactly as locked on the day the call was made — the "evidence"
        line is what the automatic grader saw.
        {anyCalibrated(rows) && " * = threshold calibrated from that sector's own trailing history at creation, then frozen."}
      </p>
    </>
  );
}

/* ── Open commitments table (the locked public record of live calls) ────────── */

function CommitmentsTable({ rows }: { rows: LedgerRow[] }) {
  const f = useCategoryFold(rows);
  if (rows.length === 0) {
    return <p className="text-[12.5px] italic text-faint">No open calls right now.</p>;
  }
  return (
    <>
      <CategoryChips cats={f.cats} value={f.cat} onChange={f.setCat} />
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-[12.5px]">
          <thead>
            <tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-faint">
              <th className="px-3 py-2 font-medium">Forecast</th>
              <th className="px-2 py-2 font-medium">Type</th>
              <th className="px-2 py-2 text-right font-medium">Conf</th>
              <th className="px-2 py-2 text-right font-medium">Made</th>
              <th className="px-2 py-2 text-right font-medium">Resolves by</th>
              <th className="px-2 py-2 font-medium">Locked terms</th>
              <th className="px-3 py-2 font-medium">Fingerprint</th>
            </tr>
          </thead>
          <tbody>
            {f.visible.map((r, i) => (
              <tr key={r.fingerprint ?? i} className="border-b border-line/50 align-top last:border-0">
                <td className="px-3 py-2">
                  <p className="leading-snug text-ink">{r.claim}</p>
                  <p className="mt-0.5 text-[11.5px] text-faint">
                    {r.category}
                    {r.quarantined && (
                      <>
                        {" "}
                        · <Badge variant="warn">held out</Badge>
                      </>
                    )}
                  </p>
                </td>
                <td className="px-2 py-2 whitespace-nowrap">
                  {/* judgment = a human will eventually grade this; auto = objective resolver */}
                  <Badge variant={r.kind === "manual" ? "warn" : "neutral"}>
                    {r.kind === "manual" ? "judgment" : "auto"}
                  </Badge>
                </td>
                <td className="num px-2 py-2 text-right font-medium text-ink">
                  {ratioPct(r.confidence)}
                </td>
                <td className="num whitespace-nowrap px-2 py-2 text-right text-faint">
                  {fmtDate(r.made_on)}
                </td>
                <td className="num whitespace-nowrap px-2 py-2 text-right text-faint">
                  {r.resolve_by && isPastDue(r.resolve_by) ? (
                    // status token + icon — the state never rides on color alone
                    <span className="inline-flex items-center gap-1 font-medium text-status-serious">
                      <Clock className="h-3 w-3 shrink-0" />
                      {fmtDate(r.resolve_by)}
                      <span className="rounded bg-status-serious-soft px-1 py-px text-[10px] font-semibold uppercase">
                        overdue
                      </span>
                    </span>
                  ) : (
                    fmtDate(r.resolve_by)
                  )}
                </td>
                <td className="px-2 py-2">
                  <LockedTerms row={r} />
                </td>
                <td className="px-3 py-2">
                  <Fingerprint fp={r.fingerprint} />
                </td>
              </tr>
            ))}
            {f.visible.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-faint">
                  No open calls in this category.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {f.filtered.length > VISIBLE_ROWS && (
        <ShowAllButton
          expanded={f.expanded}
          total={f.filtered.length}
          onToggle={() => f.setExpanded((e) => !e)}
        />
      )}
      <p className="mt-2 text-[11.5px] text-faint">
        Every open call is already locked — when it comes due it will be graded against the data and
        move to the receipts above, hit or miss.
      </p>
    </>
  );
}

/* ── Per-technology block ──────────────────────────────────────────────────── */

function TechBlock({ tech }: { tech: LedgerTech }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            to={`/tech/${tech.tech}`}
            className="text-[13.5px] font-semibold tracking-tight text-ink no-underline hover:underline"
          >
            {tech.label}
          </Link>
          {tech.domain && <p className="text-[11.5px] text-faint">{tech.domain}</p>}
        </div>
        <Badge variant="brand" className="shrink-0">
          {tech.current_stage ? `today: ${tech.current_stage}` : "out of window"}
        </Badge>
      </div>
      {tech.open.length > 0 && (
        <ul className="mt-3 space-y-2">
          {tech.open.map((r, i) => (
            <li key={r.fingerprint ?? i} className="rounded-lg border border-line bg-canvas px-3 py-2">
              <p className="text-[12.5px] leading-snug text-ink">{r.claim}</p>
              <p className="num mt-1 text-[11px] text-faint">
                on record since {fmtDate(r.made_on)} · resolves by {fmtDate(r.resolve_by)} · called at{" "}
                {ratioPct(r.confidence)} · <Fingerprint fp={r.fingerprint} />
              </p>
            </li>
          ))}
        </ul>
      )}
      {tech.resolved.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {tech.resolved.map((r, i) => {
            const o = OUTCOME[r.outcome ?? ""] ?? { label: r.outcome ?? "—", variant: "warn" as const };
            return (
              <li key={r.fingerprint ?? i} className="flex items-start gap-2 text-[12px]">
                <Badge variant={o.variant} className="mt-0.5 shrink-0">
                  {o.label}
                </Badge>
                <span className="min-w-0 leading-snug text-ink-soft">
                  {r.from_stage} → {r.to_stage}
                  <span className="num text-faint">
                    {" "}
                    · {fmtDate(r.made_on)} → {fmtDate(r.resolved_on)}
                  </span>
                  {r.evidence ? <span className="text-faint"> · {r.evidence}</span> : null}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {tech.open.length === 0 && tech.resolved.length === 0 && (
        <p className="mt-3 text-[12px] italic text-faint">No transition calls yet.</p>
      )}
    </div>
  );
}

/* ── Text-wall guards ──────────────────────────────────────────────────────── */

/** Split a summary at the first sentence boundary that doesn't break a **bold** pair. */
function splitLead(text: string): [string, string] {
  const re = /[.!?](?=\s)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    const lead = text.slice(0, m.index + 1);
    if (((lead.match(/\*\*/g) ?? []).length & 1) === 0) {
      return [lead, text.slice(m.index + 1).trimStart()];
    }
  }
  return [text, ""];
}

/** One visible sentence (the read line) + an expander for the rest. */
function ReadMore({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const [lead, rest] = useMemo(() => splitLead(text ?? ""), [text]);
  const collapsible = rest.length > 60;
  return (
    <div className="mt-2.5 max-w-3xl">
      <p className="text-[15.5px] leading-relaxed text-ink-soft">
        <Rich text={collapsible && !open ? lead : text} />
      </p>
      {collapsible && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="mt-1.5 inline-flex items-center gap-1 text-[11.5px] font-medium text-muted transition-colors hover:text-ink"
        >
          {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          {open ? "Show less" : "Read the full view"}
        </button>
      )}
    </div>
  );
}

/* ── Methodology — the rules of the game, in plain language ─────────────────── */

function Methodology({ data }: { data: LedgerPayload }) {
  const [open, setOpen] = useState(false);
  const p = data.policy;
  return (
    <Card>
      <CardBody>
        <SectionHeading
          icon={<BookOpen className="h-4 w-4" />}
          title="Methodology"
          description="How the record is kept honest — locking, grading, quarantine, baselines, and how to verify the file yourself."
        />
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="inline-flex items-center gap-1 text-[11.5px] font-medium text-muted transition-colors hover:text-ink"
        >
          {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          {open ? "Hide the rules" : "Read the rules"}
        </button>
        {open && (
          <div className="mt-4 max-w-3xl space-y-4 text-[13px] leading-relaxed text-muted">
            <div>
              <p className="font-semibold text-ink">Locked when made</p>
              <p>
                Every forecast carries its claim, confidence, deadline, and terms (thresholds, stage
                windows) exactly as written on the day it was made. Each gets a fingerprint — a hash
                of what-about-whom-and-when — so the same call can never be silently re-logged, and
                nothing is edited after the fact. A graded outcome is immutable: no regrading, no
                deletions, no cherry-picking.
              </p>
            </div>
            <div>
              <p className="font-semibold text-ink">Objective grading</p>
              <p>
                Machine-checkable calls are graded automatically against our own stored data, not by
                anyone's judgment: deal counts are recounted, market reactions re-measured, stage
                changes re-read from the dated stage history. A technology stage advance only counts
                as a hit once <b className="font-medium text-ink">two consecutive clean snapshots</b>{" "}
                (no contested reading) sit at or above the predicted stage — one noisy flip never
                banks a win. Event-window calls cannot score a hit in their first{" "}
                <span className="num">{p.min_resolve_days}</span> days, so a forecast can't "predict"
                the situation it was born in. A call still unconfirmed at its deadline is graded a{" "}
                <b className="font-medium text-ink">miss</b>, not quietly extended. Judgment calls
                (from our strategist) are the one hand-graded kind, and are labeled as such.
              </p>
            </div>
            <div>
              <p className="font-semibold text-ink">Quarantine</p>
              <p>
                Short-horizon price-direction calls ({p.quarantined_kinds.join(", ")}) are deliberate
                coin flips logged at 50% to test our own limits. Pooling them would drag the headline
                toward 50% without saying anything about skill — so they are excluded from the
                headline numbers, kept visible in the ledger with a "held out" flag, and scored in
                their own category row.
              </p>
            </div>
            <div>
              <p className="font-semibold text-ink">Baselines — does this beat a dumb rule?</p>
              <p>
                Accuracy alone flatters an easy environment, so every accuracy figure ships with its
                base rate and two naive baselines: always predicting the majority outcome, and always
                forecasting the base-rate probability. Skill = 1 − Brier / baseline-Brier; positive
                means we discriminate better than the dumb rule. When the outcome never varies we
                print <b className="font-medium text-ink">"no test"</b> instead of a score, because an
                all-hit record on an always-happens event proves nothing. Headline accuracy is also
                held back until <span className="num">{p.headline_accuracy_floor}</span> resolved
                calls — below that a single result swings it too far to mean anything.
              </p>
            </div>
            <div>
              <p className="font-semibold text-ink">Verify this exact history</p>
              <p>
                The <b className="font-medium text-ink">ledger digest</b> is the sha256 checksum of
                the forecast rows exactly as delivered ({data.digest_recipe}). Download the JSON,
                recompute the checksum over its <code className="rounded bg-canvas px-1 py-0.5 text-[12px]">forecasts</code>{" "}
                array, and compare: a match proves you are looking at this exact record; any edit —
                one outcome, one date, one word of one claim — produces a different digest. Diff two
                downloads over time and the record can only have grown. Each day&apos;s digest is
                also anchored to an append-only history (the payload&apos;s{" "}
                <code className="rounded bg-canvas px-1 py-0.5 text-[12px]">digest_history</code>),
                so a rewrite of past rows would show up as a mismatch against an already-anchored
                digest.
              </p>
              <p className="num mt-1.5 break-all text-[11.5px] text-faint">
                current digest: {data.ledger_digest}
              </p>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
