/**
 * Home — the landing page and navigation hub.
 *
 * Orientation, not analysis — and deliberately SIMPLE: one promise, today's
 * headline, one proof strip, and the three-step workflow where each step IS
 * the door to its surface (Briefing → Technologies → Track record). The
 * supporting tools (Capital, Explore, Ask) sit in a quiet row below. The page
 * is the front door, so every stat degrades to a static description when the
 * API is cold or unreachable — never an error card.
 */
import { Link } from "react-router-dom";
import {
  ArrowRight,
  BookCheck,
  BookOpen,
  Compass,
  FlaskConical,
  MessageSquare,
  Radar,
  Search,
  Wallet,
} from "lucide-react";
import { api } from "../lib/api";
import type { HomePayload } from "../lib/api";
import { useResource } from "../lib/useResource";
import { ratioPct } from "../lib/format";
import { Card, CardBody, Badge } from "../components/ui";

export default function HomePage() {
  const { data } = useResource<HomePayload>(api.home, { key: "home" });
  const ext = data?.record.external;
  const hasRecord = !!ext && ext.resolved > 0;

  return (
    <main className="mx-auto w-full max-w-[1080px] flex-1 px-4 pb-10 sm:px-8">
      {/* ── Hero — one promise, one support line, two actions ────────────── */}
      <section className="-mx-4 mb-5 bg-gradient-to-b from-brand-soft/70 via-brand-soft/25 to-transparent px-4 pb-6 pt-8 sm:-mx-8 sm:px-8 sm:pt-10">
        <h1 className="max-w-[820px] text-[30px] font-semibold sm:text-[38px] leading-[1.15] tracking-tight text-ink">
          Market signals, turned into accountable strategy.
        </h1>
        <p className="mt-4 max-w-[740px] text-[15.5px] leading-relaxed text-muted">
          Pharos helps corporate strategy and technology-intelligence teams track emerging
          technologies through their lifecycle.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <span className="rounded-full bg-brand-soft px-3 py-1 text-[12px] font-medium text-brand">
            Built for corporate strategy &amp; technology-intelligence teams
          </span>
          <span className="rounded-full border border-line bg-surface/80 px-3 py-1 text-[12px] text-muted">
            Also useful to investors and technology leaders evaluating emerging markets
          </span>
        </div>
      </section>

      {/* ── Today — the front-page headline ──────────────────────────────── */}
      {data?.today && data.today.bottom_line && (
        <Link to="/briefing" className="group mb-4 block">
          <Card className="border-brand/25 bg-brand-soft/25 transition-colors group-hover:border-brand/45">
            <CardBody>
              <div className="mb-1.5 flex flex-wrap items-center gap-2">
                <span className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-brand">
                  Today — {data.today.as_of}
                </span>
                {data.today.confidence && (
                  <Badge variant="brand">{data.today.confidence} confidence</Badge>
                )}
              </div>
              <p className="text-[16px] font-medium leading-snug text-ink">
                {data.today.bottom_line}
              </p>
              <p className="mt-1.5 text-[12.5px] text-muted">
                <span className="num">{data.today.signal_count}</span> decisive signal
                {data.today.signal_count === 1 ? "" : "s"}
                {data.today.top_signal ? <> · leading: {data.today.top_signal}</> : null} —{" "}
                <span className="font-medium text-ink-soft group-hover:underline">
                  open the briefing →
                </span>
              </p>
            </CardBody>
          </Card>
        </Link>
      )}

      {/* ── Chapter: why Pharos — claims, receipts, the live example ────── */}
      <p className="mb-3 mt-10 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
        Why Pharos
      </p>
      <section className="mb-4 grid gap-3 sm:grid-cols-3">
        <WhyCard
          icon={<Search className="h-4 w-4" />}
          title="Receipts, not opinions"
          body="Every lifecycle placement links to the classified stories behind it. No analyst hunch survives here without evidence you can open."
        />
        <WhyCard
          icon={<BookCheck className="h-4 w-4" />}
          title="Locked now. Graded in public."
          body="Every forecast is timestamped with a deadline and a falsifier. The first independently graded calls resolve from September 2026 — misses included."
        />
        <WhyCard
          icon={<Radar className="h-4 w-4" />}
          title="Detected before the watchlist"
          body="Radar scans unmatched news and research papers to surface emerging technologies before they enter the tracked universe — and puts its own detections on the record."
        />
      </section>

      {/* the numbers behind the claims — a slim stat band, not a footnote */}
      {data && (
        <div className="num mb-4 flex flex-wrap items-center gap-x-6 gap-y-1 border-y border-line px-1 py-2.5 text-[12.5px] text-muted">
          <span>
            <span className="font-semibold text-ink-soft">
              {data.pulse.articles_7d.toLocaleString()}
            </span>{" "}
            articles reviewed this week
          </span>
          <span>
            <span className="font-semibold text-ink-soft">{data.tech.on_curve}</span> technologies
            placed on their lifecycle
          </span>
          {hasRecord ? (
            <span>
              <span className="font-semibold text-ink-soft">
                {ext.accuracy != null ? ratioPct(ext.accuracy) : "—"}
              </span>{" "}
              independently graded over {ext.resolved} resolved
            </span>
          ) : (
            <span>
              <span className="font-semibold text-ink-soft">{ext?.open ?? 0}</span> independent
              calls locked — first grading September 2026
            </span>
          )}
          <span className="text-ink-soft">every miss published</span>
        </div>
      )}

      {/* ── The worked example — the whole idea in one true story ─────────── */}
      {data?.radar_example && (
        <Link to="/radar" className="group mb-12 block">
          <Card className="border-brand/25 bg-brand-soft/25 transition-colors group-hover:border-brand/45">
            <CardBody className="py-4">
              <p className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-brand">
                Watch it work
              </p>
              <p className="mt-1.5 max-w-[760px] text-[14px] leading-relaxed text-ink-soft">
                Radar surfaced <span className="font-semibold text-ink">{data.radar_example.label}</span>{" "}
                before it entered Pharos's tracked universe. On{" "}
                {data.radar_example.first_detected}, the evidence gate identified{" "}
                <span className="num">{data.radar_example.mentions}</span> news stories from{" "}
                <span className="num">{data.radar_example.sources}</span> publishers
                {data.radar_example.papers > 0 && (
                  <>
                    {" "}and <span className="num">{data.radar_example.papers}</span> research
                    papers
                  </>
                )}
                .{" "}
                {data.radar_example.status === "promoted" ? (
                  <>It was promoted into tracking; the detection is now a public 90-day call.</>
                ) : (
                  <>It now awaits human review; promotion would create a public 90-day call.</>
                )}{" "}
                <span className="font-medium text-brand group-hover:underline">
                  See it on the Radar →
                </span>
              </p>
            </CardBody>
          </Card>
        </Link>
      )}

      {/* ── Chapter: start here — each card is the door to its surface ────── */}
      <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
        Start here
      </p>
      <section className="grid gap-4 sm:grid-cols-3">
        <StepCard
          to="/briefing"
          icon={<Compass className="h-4 w-4" />}
          title="Briefing"
          stat={
            data?.today
              ? `${data.today.signal_count} signal${data.today.signal_count === 1 ? "" : "s"} today`
              : undefined
          }
        />
        <StepCard
          to="/mot"
          icon={<FlaskConical className="h-4 w-4" />}
          title="Technologies"
          stat={
            data
              ? `${data.tech.on_curve} on curve · ${data.tech.watching} watching`
              : undefined
          }
        />
        <StepCard
          to="/ledger"
          icon={<BookCheck className="h-4 w-4" />}
          title="Track record"
          stat={
            hasRecord
              ? `${ext.accuracy != null ? ratioPct(ext.accuracy) : "—"} independently graded · ${data.record.resolved} resolved`
              : data
                ? `${ext?.open ?? 0} independent calls on the clock`
                : undefined
          }
        />
      </section>

      {/* live examples — the friendliest doorway into the dossiers */}
      {data && data.tech.examples.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="text-[12px] text-muted">See it live:</span>
          {data.tech.examples.map((t) => (
            <Link
              key={t.tech}
              to={`/tech/${t.tech}`}
              className="group/chip inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-[12.5px] no-underline transition-colors hover:border-line-strong"
            >
              <span className="font-medium text-ink">{t.label}</span>
              {t.maturity && (
                <Badge variant="brand" className="capitalize">{t.maturity.replace(/-/g, " ")}</Badge>
              )}
              <ArrowRight className="h-3 w-3 text-faint transition-transform group-hover/chip:translate-x-0.5" />
            </Link>
          ))}
        </div>
      )}

      {/* ── Supporting tools — present, not competing ────────────────────── */}
      <section className="mt-10 border-t border-line pt-6">
        <div className="grid gap-x-8 gap-y-4 sm:grid-cols-3">
          <QuietLink
            to="/capital"
            icon={<Wallet className="h-4 w-4" />}
            title="Capital"
            blurb="Who funds the next curve, and whether the market re-priced."
          />
          <QuietLink
            to="/explore"
            icon={<Search className="h-4 w-4" />}
            title="Explore"
            blurb="The evidence base — every classified story behind every claim."
          />
          <QuietLink
            to="/ask"
            icon={<MessageSquare className="h-4 w-4" />}
            title="Ask"
            blurb="A conversational analyst with checkable citations."
          />
        </div>
      </section>

      {/* ── Trust footer ─────────────────────────────────────────────────── */}
      <section className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-line pt-5 text-[12.5px] text-muted">
        {data != null && data.falsifier_events > 0 && (
          <span className="inline-flex items-center gap-1.5">
            <Radar className="h-3.5 w-3.5 text-status-warning" />
            Falsifier watch: <span className="num">{data.falsifier_events}</span> candidate
            event{data.falsifier_events === 1 ? "" : "s"} under review
          </span>
        )}
        <span className="inline-flex items-center gap-1.5">
          <BookOpen className="h-3.5 w-3.5" />
          <Link to="/methodology" className="underline decoration-line hover:text-ink">
            Methodology
          </Link>{" "}
          — how every number is made, including the misses
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Link to="/legal#terms" className="underline decoration-line hover:text-ink">
            Terms
          </Link>
          ·
          <Link to="/legal#privacy" className="underline decoration-line hover:text-ink">
            Privacy
          </Link>
          ·
          <Link to="/legal#about" className="underline decoration-line hover:text-ink">
            About
          </Link>
        </span>
      </section>
    </main>
  );
}

/** A workflow step that IS the door to its surface — number, name, one line,
 *  and the live stat that proves it's running. */
function StepCard({
  to,
  icon,
  title,
  blurb,
  stat,
}: {
  to: string;
  icon: React.ReactNode;
  title: string;
  blurb?: string;
  stat?: string;
}) {
  return (
    <Link to={to} className="group block h-full">
      <Card className="h-full transition-all group-hover:-translate-y-0.5 group-hover:border-line-strong group-hover:shadow-sm">
        <CardBody>
          <div className="mb-2.5 flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-soft text-brand">
              {icon}
            </span>
            <span className="text-[15px] font-semibold tracking-tight text-ink">{title}</span>
            <ArrowRight className="ml-auto h-3.5 w-3.5 text-faint transition-transform group-hover:translate-x-0.5 group-hover:text-ink-soft" />
          </div>
          {blurb && <p className="text-[12.5px] leading-relaxed text-muted">{blurb}</p>}
          {stat && (
            <p className={"num text-[12px] font-medium text-ink-soft" + (blurb ? " mt-3" : "")}>
              {stat}
            </p>
          )}
        </CardBody>
      </Card>
    </Link>
  );
}

/** One differentiator — icon, claim, one honest sentence. */
function WhyCard({ icon, title, body }: { icon: React.ReactNode; title: string; body: string }) {
  return (
    <Card className="h-full">
      <CardBody className="py-4">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-soft text-brand">
            {icon}
          </span>
          <span className="text-[13.5px] font-semibold text-ink">{title}</span>
        </div>
        <p className="mt-2 text-[12.5px] leading-relaxed text-muted">{body}</p>
      </CardBody>
    </Card>
  );
}

/** A supporting tool — findable, deliberately quiet. */
function QuietLink({
  to,
  icon,
  title,
  blurb,
}: {
  to: string;
  icon: React.ReactNode;
  title: string;
  blurb: string;
}) {
  return (
    <Link to={to} className="group flex items-start gap-3 no-underline">
      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-canvas text-muted transition-colors group-hover:bg-brand-soft group-hover:text-brand">
        {icon}
      </span>
      <span>
        <span className="flex items-center gap-1 text-[13.5px] font-medium text-ink">
          {title}
          <ArrowRight className="h-3 w-3 text-faint transition-transform group-hover:translate-x-0.5" />
        </span>
        <span className="text-[12px] leading-snug text-muted">{blurb}</span>
      </span>
    </Link>
  );
}
