import { useCallback, useEffect, useState } from "react";
import type { DependencyList, ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ArrowDownRight,
  ArrowUpRight,
  ChevronDown,
  ChevronUp,
  GitCompareArrows,
  RefreshCw,
} from "lucide-react";
import { api } from "../lib/api";
import type {
  TrendsPayload,
  EntityProfile,
  FeedGroup,
  FeedsPayload,
  NameCount,
  MomentumItem,
  VoiceSlice,
  VolumePoint,
  Story,
} from "../lib/api";
import { Topbar } from "../components/layout";
import { Card, CardBody, SectionHeading, Segmented, Select, Spinner, Rich, Badge } from "../components/ui";
import { StoryCard, StoryRow } from "../components/Story";
import { useActions, ProgressPanel } from "../components/actions";
import { useAuth } from "../lib/auth";
import {
  ChartFrame,
  HBarList,
  StatTile,
  TimeSeries,
  CAT_OTHER,
  entityColor,
  registerEntities,
} from "../components/viz";
import type { HBarDatum, TimeSeriesSeries, ChartTable } from "../components/viz";
import { signedPct, pct, shortDate } from "../lib/format";
import { cn } from "../lib/utils";

/* small async helper for param-driven fetches — tracks error state separately
   from "loaded but empty", plus the wall-clock time of the last good fetch */
function useAsync<T>(
  fn: () => Promise<T>,
  deps: DependencyList,
): { data: T | null; loading: boolean; error: string | null; updatedAt: Date | null } {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fn()
      .then((d) => {
        if (!alive) return;
        setData(d);
        setUpdatedAt(new Date());
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : String(e));
        setLoading(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, loading, error, updatedAt };
}

/** What the active tab tells the topbar about itself. */
type TabStatus = { live: boolean; updatedAt: Date | null };
type StatusFn = (s: TabStatus) => void;

/** Distinct error state — a failed fetch is not an empty range. Tone matches
 *  PageChrome's error card. */
function ErrorCard() {
  return (
    <Card>
      <CardBody>
        <p className="text-[13px] text-muted">The data service didn&rsquo;t respond — try refreshing.</p>
      </CardBody>
    </Card>
  );
}

const RANGES: [string, string][] = [
  ["30", "30D"],
  ["90", "90D"],
  ["180", "180D"],
  ["365", "1Y"],
];
const ENTITY_RANGES: [string, string][] = [
  ["30", "30D"],
  ["90", "90D"],
  ["180", "180D"],
];

/* ── page-local viz helpers ─────────────────────────────────────────────────── */

/** Drift chip for share-of-voice rows — status tokens (it means gaining/losing
 *  share), signed text + icon so the state never rides on color alone. */
function DriftChip({ delta }: { delta: number | null }) {
  const base = "inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold";
  if (delta == null) {
    return <span className={cn(base, "bg-[color:var(--color-chart-grid)] text-muted")}>new</span>;
  }
  if (Math.abs(delta) < 0.05) {
    return <span className={cn(base, "num bg-[color:var(--color-chart-grid)] text-muted")}>±0.0 pp</span>;
  }
  const up = delta > 0;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={cn(base, "num", up ? "bg-status-good-soft text-status-good" : "bg-status-critical-soft text-status-critical")}>
      <Icon className="h-3 w-3" />
      {signedPct(delta, 1).replace("%", "")} pp
    </span>
  );
}

/** Pivot [{date, feed, count}] long rows into wide rows + entity-stable series.
 *  Feeds past the 8 categorical slots fold into a single gray "Other" band
 *  (only when ≥ 2 of them would share the Other hue). */
function feedAreaSeries(points: VolumePoint[]): {
  rows: Array<Record<string, unknown>>;
  series: TimeSeriesSeries[];
} {
  const totals = new Map<string, number>();
  for (const p of points) totals.set(p.feed, (totals.get(p.feed) ?? 0) + p.count);
  const labels = [...totals.keys()];
  const overflow = labels.filter((l) => entityColor(l, "feed") === CAT_OTHER);
  const fold = overflow.length >= 2;
  const main = labels
    .filter((l) => !fold || entityColor(l, "feed") !== CAT_OTHER)
    .sort((a, b) => (totals.get(b) ?? 0) - (totals.get(a) ?? 0));
  const byDate = new Map<string, Record<string, unknown>>();
  for (const p of points) {
    const key = fold && entityColor(p.feed, "feed") === CAT_OTHER ? "Other" : p.feed;
    const row = byDate.get(p.date) ?? { date: p.date };
    row[key] = ((row[key] as number | undefined) ?? 0) + p.count;
    byDate.set(p.date, row);
  }
  const rows = [...byDate.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const series: TimeSeriesSeries[] = [
    ...main.map((l) => ({ key: l, color: entityColor(l, "feed") })),
    ...(fold ? [{ key: "Other", color: CAT_OTHER }] : []),
  ];
  return { rows, series };
}

/** Table-view twin for a pivoted time series (accessibility relief). */
function seriesTable(rows: Array<Record<string, unknown>>, series: TimeSeriesSeries[]): ChartTable {
  return {
    columns: ["Date", ...series.map((s) => s.label ?? s.key)],
    rows: rows.map((r) => [
      shortDate(String(r.date)),
      ...series.map((s) => ((r[s.key] as number | undefined) ?? 0).toLocaleString()),
    ]),
  };
}

/** ~12-bucket downsample for StatTile sparklines. */
function sparkOf(values: number[], buckets = 12): number[] | undefined {
  if (values.length < 2) return undefined;
  if (values.length <= buckets) return values;
  const size = values.length / buckets;
  return Array.from({ length: buckets }, (_, i) =>
    values.slice(Math.floor(i * size), Math.floor((i + 1) * size)).reduce((a, b) => a + b, 0),
  );
}

const count = (v: number) => (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(1));

/** One-line read for a magnitude leaderboard. */
function leadRead(data: NameCount[], noun: string): string | undefined {
  if (!data.length) return undefined;
  const total = data.reduce((a, d) => a + d.count, 0);
  const share = total ? Math.round((100 * data[0].count) / total) : 0;
  return `${data[0].name} leads ${noun} with ${data[0].count.toLocaleString()} of the top ${total.toLocaleString()} (${share}%).`;
}

/** A named-category HBarList card (single hue — nominal categories never get
 *  a value-ramp), folded after `visible` rows per the density rules. */
function BreakdownCard({
  title,
  read,
  data,
  visible = 8,
  labelWidth = 130,
  caption,
}: {
  title: string;
  read?: string;
  data: NameCount[];
  visible?: number;
  labelWidth?: number;
  caption?: ReactNode;
}) {
  return (
    <Card>
      <CardBody>
        <ChartFrame title={title} read={read} caption={caption}>
          <HBarList
            data={data.map((d) => ({ label: d.name, value: d.count }))}
            format={count}
            labelWidth={labelWidth}
            collapsedAfter={data.length > visible ? visible : undefined}
          />
        </ChartFrame>
      </CardBody>
    </Card>
  );
}

const TABS = ["trends", "entities", "stories"] as const;

export default function ExplorePage() {
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab") ?? "trends";
  // unknown/retired params (e.g. old ?tab=compare links) fall back to Trends
  const tab = (TABS as readonly string[]).includes(raw) ? raw : "trends";
  const setTab = (t: string) => setParams(t === "trends" ? {} : { tab: t }, { replace: true });
  const [tick, setTick] = useState(0);
  const [status, setStatus] = useState<TabStatus>({ live: false, updatedAt: null });
  const onStatus = useCallback((s: TabStatus) => setStatus(s), []);
  const refresh = async () => {
    await api.refresh();
    setTick((t) => t + 1);
  };
  return (
    <>
      <Topbar
        title="Explore"
        subtitle="The evidence base — the classified stories, trends & entity dossiers behind every claim"
        live={status.live}
        updatedAt={status.updatedAt}
        loading={false}
        onRefresh={refresh}
      />
      <main className="mx-auto w-full max-w-[1240px] flex-1 px-8 py-7">
        <div className="mb-6">
          <Segmented
            value={tab}
            onChange={setTab}
            options={[
              ["trends", "Trends"],
              ["entities", "Entities"],
              ["stories", "Stories"],
            ]}
          />
        </div>
        {tab === "trends" && <TrendsView key={`t${tick}`} onStatus={onStatus} />}
        {tab === "entities" && <EntitiesView key={`e${tick}`} onStatus={onStatus} />}
        {tab === "stories" && <StoriesView key={`s${tick}`} onStatus={onStatus} />}
      </main>
    </>
  );
}

/* ── Trends ──────────────────────────────────────────────────────────────────── */
function TrendsView({ onStatus }: { onStatus: StatusFn }) {
  const [days, setDays] = useState("90");
  const [feed, setFeed] = useState("all");
  const [weighted, setWeighted] = useState("true");
  const { data, loading, error, updatedAt } = useAsync<TrendsPayload>(
    () => api.exploreTrends(Number(days), feed, weighted === "true"),
    [days, feed, weighted],
  );
  useEffect(() => {
    onStatus({ live: !!data && !error, updatedAt });
  }, [data, error, updatedAt, onStatus]);

  const feedOpts: [string, string][] = [
    ["all", "All feeds"],
    ...(data?.feeds ?? []).map((f) => [f.key, f.label] as [string, string]),
  ];
  // Register the FULL feed universe once — color follows the feed, never its
  // rank, so refiltering never repaints survivors.
  if (data?.feeds?.length) registerEntities(data.feeds.map((f) => f.label), "feed");

  return (
    <div className="space-y-6">
      {/* one filter row above everything it scopes — never inside a card */}
      <div className="flex flex-wrap items-center gap-3">
        <Segmented value={days} onChange={setDays} options={RANGES} />
        <Select value={feed} onChange={setFeed} options={feedOpts} />
        <Segmented
          value={weighted}
          onChange={setWeighted}
          options={[
            ["true", "Weighted"],
            ["false", "Raw"],
          ]}
        />
      </div>

      {loading && !data ? (
        <Spinner />
      ) : error ? (
        <ErrorCard />
      ) : !data || data.empty ? (
        <Card><CardBody><p className="text-[13px] text-muted">No rollup data in this range yet.</p></CardBody></Card>
      ) : (
        /* on refetch, hold the previous render at reduced opacity — no skeleton flash */
        <div className={cn("space-y-6 transition-opacity", loading && "opacity-60")}>
          <Card>
            <CardBody>
              <p className="max-w-3xl text-[14.5px] leading-relaxed text-ink-soft">
                <Rich text={data.headline} />
              </p>
              <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3">
                <StatTile
                  label="Articles"
                  value={data.kpis.articles.toLocaleString()}
                  spark={sparkOf(dailyTotals(data.volume))}
                  /* aggregate small-base guard: don't imply a solid trend when the
                     prior half is a sliver of the window (headline says the same) */
                  delta={
                    data.kpis.volume_trend?.thin
                      ? { text: "low prior-half base", direction: "flat" }
                      : undefined
                  }
                />
                {/* one sentiment tile, not three renderings of the same number —
                    the net leads, the raw split rides the delta chip */}
                <StatTile
                  label="Net sentiment"
                  value={`${data.kpis.net > 0 ? "+" : ""}${data.kpis.net.toLocaleString()}`}
                  delta={{
                    text: `${data.kpis.pos.toLocaleString()} pos / ${data.kpis.neg.toLocaleString()} neg`,
                    direction: data.kpis.net > 0 ? "up" : data.kpis.net < 0 ? "down" : "flat",
                  }}
                />
                <StatTile
                  label="Top momentum"
                  value={
                    data.kpis.leader ? (
                      <span className="text-[18px] leading-tight">{data.kpis.leader.feed}</span>
                    ) : (
                      "—"
                    )
                  }
                  delta={
                    data.kpis.leader
                      ? data.kpis.leader.thin
                        ? {
                            /* thin prior base — a % would be an artifact, so the
                               chip carries raw counts instead */
                            text: `${data.kpis.leader.prior.toLocaleString()} → ${data.kpis.leader.recent.toLocaleString()} articles`,
                            direction: "up",
                          }
                        : {
                            text: `${signedPct(data.kpis.leader.pct, 0)} vs prior half`,
                            direction: data.kpis.leader.pct >= 0 ? "up" : "down",
                          }
                      : undefined
                  }
                />
              </div>
            </CardBody>
          </Card>

          {data.multi && data.momentum.length > 1 && (
            <Card>
              <CardBody>
                <MomentumCard items={data.momentum} days={Number(days)} />
              </CardBody>
            </Card>
          )}

          {data.voice.slices.length > 0 && (
            <Card>
              <CardBody>
                <VoiceCard voice={data.voice} weighted={weighted === "true"} days={Number(days)} />
              </CardBody>
            </Card>
          )}

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardBody>
                <VolumeCard volume={data.volume} days={Number(days)} />
              </CardBody>
            </Card>
            <Card>
              <CardBody>
                <SentimentCard sentiment={data.sentiment} days={Number(days)} />
              </CardBody>
            </Card>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <BreakdownCard
              title="Top companies"
              read={leadRead(data.breakdowns.by_company ?? [], "company mentions")}
              data={data.breakdowns.by_company ?? []}
              caption={`${days}d window · mention counts from the daily rollup.`}
            />
            <BreakdownCard
              title="Top countries"
              read={leadRead(data.breakdowns.by_country ?? [], "country mentions")}
              data={data.breakdowns.by_country ?? []}
              caption={`${days}d window · mention counts from the daily rollup.`}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function dailyTotals(volume: VolumePoint[]): number[] {
  const byDate = new Map<string, number>();
  for (const p of volume) byDate.set(p.date, (byDate.get(p.date) ?? 0) + p.count);
  return [...byDate.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([, v]) => v);
}

/* Momentum — diverging bars (± means rising/cooling, so diverging tokens, not
   categorical). Thin-base feeds are kept OUT of the bar scale — one 2→40 swing
   would blow the axis — and listed below with an explicit caveat instead. */
function MomentumCard({ items, days }: { items: MomentumItem[]; days: number }) {
  const solid = items.filter((m) => !m.thin).sort((a, b) => b.pct - a.pct);
  const thin = items.filter((m) => m.thin);

  const riser = solid.length && solid[0].pct > 0 ? solid[0] : null;
  const faller = solid.length && solid[solid.length - 1].pct < 0 ? solid[solid.length - 1] : null;
  const read = riser && faller
    ? `${riser.feed} is heating up (${signedPct(riser.pct, 0)}) while ${faller.feed} cools (${signedPct(faller.pct, 0)}).`
    : riser
      ? `${riser.feed} is rising fastest at ${signedPct(riser.pct, 0)}.`
      : faller
        ? `${faller.feed} is cooling fastest at ${signedPct(faller.pct, 0)}.`
        : thin.length > 0
          ? "Every feed is on a thin prior-half base — volume is ramping, but a % swing would be an artifact."
          : "Volume is roughly flat across feeds — no feed has a reliable swing.";

  const bars: HBarDatum[] = solid.map((m) => ({
    label: m.feed,
    value: m.pct,
    color: m.pct >= 0 ? "var(--color-div-pos)" : "var(--color-div-neg)",
    tip: (
      <div className="num text-muted">
        {m.prior.toLocaleString()} → {m.recent.toLocaleString()} articles
      </div>
    ),
  }));

  const table: ChartTable = {
    columns: ["Feed", "Change", "Recent", "Prior"],
    rows: items.map((m) => [
      <span key="f">
        {m.feed} {m.thin && <Badge variant="warn" className="ml-1">thin base</Badge>}
      </span>,
      m.thin ? "—" : signedPct(m.pct, 0),
      m.recent.toLocaleString(),
      m.prior.toLocaleString(),
    ]),
  };

  return (
    <ChartFrame
      title="Momentum — which feeds are rising"
      read={read}
      table={table}
      caption={`Recent half vs prior half of the ${days}-day window. Feeds with under 5 prior-half articles are flagged “thin base” and kept off the % scale.`}
    >
      {bars.length > 0 ? (
        <HBarList data={bars} format={(v) => signedPct(v, 0)} labelWidth={130} />
      ) : (
        <p className="py-4 text-center text-[12.5px] text-faint">
          Every feed is on a thin prior-half base — % change is not meaningful yet.
        </p>
      )}
      {thin.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {thin.map((m) => (
            <div key={m.feed} className="flex flex-wrap items-center gap-2 text-[11.5px]">
              <Badge variant="warn">thin base</Badge>
              <span className="text-ink">{m.feed}</span>
              <span className="num text-faint">
                {m.prior.toLocaleString()} → {m.recent.toLocaleString()} articles · % suppressed
              </span>
            </div>
          ))}
        </div>
      )}
    </ChartFrame>
  );
}

/* Share of voice — magnitude across nominal names, so ONE hue for every bar
   (slot 1); the 30d drift rides a labeled status chip per row, and the read
   line + caption spell the encoding out on screen. */
function VoiceCard({
  voice,
  weighted,
  days,
}: {
  voice: { slices: VoiceSlice[]; total: number; n_entities: number };
  weighted: boolean;
  days: number;
}) {
  const named = voice.slices.filter((s) => s.name !== "Others").sort((a, b) => b.share - a.share);
  const others = voice.slices.find((s) => s.name === "Others") ?? null;
  if (!named.length) return null;

  const gainer = [...named]
    .filter((s) => (s.delta ?? 0) > 0)
    .sort((a, b) => (b.delta ?? 0) - (a.delta ?? 0))[0];
  const read =
    `${named[0].name} leads the conversation at ${pct(named[0].share, 1)}` +
    (gainer && gainer.name !== named[0].name
      ? `; ${gainer.name} is gaining share fastest (+${(gainer.delta ?? 0).toFixed(1)} pp).`
      : gainer
        ? ` and is still gaining (+${(gainer.delta ?? 0).toFixed(1)} pp).`
        : ".");

  const maxShare = Math.max(...named.map((s) => s.share));
  const bars: HBarDatum[] = named.map((s) => ({
    label: s.name,
    value: s.share,
    chip: <DriftChip delta={s.delta} />,
    tip: (
      <div className="num text-muted">
        {count(s.count)} {weighted ? "weighted mentions" : "mentions"}
        {s.delta != null && ` · ${signedPct(s.delta, 1).replace("%", "")} pp vs prior half`}
      </div>
    ),
  }));

  const table: ChartTable = {
    columns: ["Entity", "Share", weighted ? "Weighted mentions" : "Mentions", "Drift (pp)"],
    rows: voice.slices.map((s) => [
      s.name,
      pct(s.share, 1),
      count(s.count),
      s.delta == null ? "—" : signedPct(s.delta, 1).replace("%", ""),
    ]),
  };

  return (
    <ChartFrame
      title="Share of voice — who's dominating"
      read={read}
      table={table}
      caption={
        <>
          Bar = share of {weighted ? "weighted" : "raw"} mentions in the recent half of the {days}-day
          window. Chip = drift vs the prior half in percentage points (pp) — green gaining, red losing,
          gray flat. Top {named.length} of {voice.n_entities.toLocaleString()} entities
          {others ? `; the long tail ("Others") holds ${pct(others.share, 1)}` : ""}.
        </>
      }
    >
      {/* domainMax pads the axis so the longest bar's value label clears the drift chips */}
      <HBarList data={bars} format={(v) => pct(v, 1)} labelWidth={130} domainMax={maxShare * 1.45} />
    </ChartFrame>
  );
}

function VolumeCard({ volume, days }: { volume: VolumePoint[]; days: number }) {
  const { rows, series } = feedAreaSeries(volume);
  if (!rows.length) return <p className="py-6 text-center text-[12.5px] text-faint">no data</p>;
  // read the true busiest feed from the raw points (a folded feed can still lead)
  const totals = new Map<string, number>();
  for (const p of volume) totals.set(p.feed, (totals.get(p.feed) ?? 0) + p.count);
  const top = [...totals.entries()].sort((x, y) => y[1] - x[1])[0];
  const read =
    series.length > 1 && top
      ? `${top[0]} carries the largest share of article volume in this window.`
      : undefined;
  return (
    <ChartFrame
      title="Volume over time"
      read={read}
      table={seriesTable(rows, series)}
      caption={`Articles per day by feed, stacked · ${days}d window.`}
    >
      <TimeSeries data={rows} xKey="date" series={series} variant="area" formatX={shortDate} />
    </ChartFrame>
  );
}

function SentimentCard({
  sentiment,
  days,
}: {
  sentiment: Array<Record<string, unknown>>;
  days: number;
}) {
  // positive/negative MEAN good/bad → status tokens (+ neutral gray), never categorical
  const series: TimeSeriesSeries[] = [
    { key: "positive", label: "Positive", color: "var(--color-status-good)" },
    { key: "negative", label: "Negative", color: "var(--color-status-critical)" },
    { key: "neutral", label: "Neutral", color: "var(--color-flat)" },
  ];
  if (!sentiment.length) return <p className="py-6 text-center text-[12.5px] text-faint">no data</p>;
  return (
    <ChartFrame
      title="Sentiment over time"
      /* the net read lives on the KPI tile above — no duplicate line here */
      table={seriesTable(sentiment, series)}
      caption={`Classified articles per day by sentiment · ${days}d window.`}
    >
      <TimeSeries data={sentiment} xKey="date" series={series} variant="line" formatX={shortDate} />
    </ChartFrame>
  );
}

/* ── Entities ────────────────────────────────────────────────────────────────── */
function EntitiesView({ onStatus }: { onStatus: StatusFn }) {
  const [days, setDays] = useState("90");
  const [selected, setSelected] = useState<string | null>(null);
  // optional second entity — when set, the dossier becomes a side-by-side compare
  const [compareWith, setCompareWith] = useState("");
  const uni = useAsync(() => api.exploreEntities(Number(days)), [days]);
  useEffect(() => {
    const list = uni.data?.universe;
    if (list?.length && (!selected || !list.find((u) => u.name === selected))) {
      setSelected(list[0].name);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uni.data]);
  useEffect(() => {
    const list = uni.data?.universe;
    if (compareWith && (compareWith === selected || (list && !list.find((u) => u.name === compareWith)))) {
      setCompareWith("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uni.data, selected]);
  const prof = useAsync<EntityProfile | null>(
    () => (selected ? api.exploreEntity(selected, Number(days)) : Promise.resolve(null)),
    [selected, days],
  );
  const comp = useAsync<EntityProfile | null>(
    () => (compareWith ? api.exploreEntity(compareWith, Number(days)) : Promise.resolve(null)),
    [compareWith, days],
  );
  useEffect(() => {
    onStatus({
      live: !!prof.data && !uni.error && !prof.error,
      updatedAt: prof.updatedAt ?? uni.updatedAt,
    });
  }, [prof.data, prof.error, prof.updatedAt, uni.error, uni.updatedAt, onStatus]);

  const entityOpts: [string, string][] = (uni.data?.universe ?? []).map(
    (u) => [u.name, `${u.name} (${u.count})`] as [string, string],
  );
  const compareOpts: [string, string][] = [
    ["", "Compare with…"],
    ...entityOpts.filter(([name]) => name !== selected),
  ];
  const byFeed: NameCount[] = prof.data
    ? Object.entries(prof.data.by_feed)
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => b.count - a.count)
    : [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Segmented value={days} onChange={setDays} options={ENTITY_RANGES} />
        {entityOpts.length > 0 && selected && (
          <Select value={selected} onChange={setSelected} options={entityOpts} className="min-w-[220px]" />
        )}
        {entityOpts.length > 1 && selected && (
          <Select value={compareWith} onChange={setCompareWith} options={compareOpts} className="min-w-[200px]" />
        )}
      </div>

      {uni.error || prof.error ? (
        <ErrorCard />
      ) : !prof.data ? (
        uni.loading || prof.loading ? <Spinner /> : (
          <Card><CardBody><p className="text-[13px] text-muted">No entity data in this range yet.</p></CardBody></Card>
        )
      ) : compareWith ? (
        <EntityCompare
          a={prof.data}
          b={comp.data}
          loadingA={prof.loading}
          loadingB={comp.loading}
          errorB={comp.error}
        />
      ) : (
        <div className={cn("space-y-6 transition-opacity", prof.loading && "opacity-60")}>
          <Card>
            <CardBody>
              <h2 className="text-[17px] font-semibold tracking-tight text-ink">{prof.data.entity}</h2>
              <p className="mt-1.5 max-w-3xl text-[13.5px] leading-relaxed text-ink-soft">
                <Rich text={prof.data.read} />
              </p>
              <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <StatTile
                  label="Prominence (wtd)"
                  value={
                    <>
                      {prof.data.weighted.toFixed(1)}{" "}
                      <span className="text-[13px] font-normal text-faint">· {prof.data.total} raw</span>
                    </>
                  }
                />
                <StatTile label="Feeds" value={prof.data.feeds_count} />
                <StatTile
                  label="Positive / negative"
                  value={`${prof.data.sentiment.positive ?? 0} / ${prof.data.sentiment.negative ?? 0}`}
                />
                <StatTile
                  label="Reach"
                  value={
                    <span className="text-[18px] leading-tight">
                      {prof.data.feeds_count >= 2 ? "Cross-domain" : "Single feed"}
                    </span>
                  }
                />
              </div>
            </CardBody>
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <BreakdownCard
              title="Where it shows up"
              read={byFeed.length ? `Most mentions come from ${byFeed[0].name}.` : undefined}
              data={byFeed}
              visible={6}
              caption={`Mentions by feed · ${days}d window.`}
            />
            <Card>
              <CardBody>
                {prof.data.series.length ? (
                  <EntityMentionsCard series={prof.data.series} days={Number(days)} />
                ) : (
                  <ChartFrame title="Mentions over time">
                    <p className="py-10 text-center text-[12.5px] text-faint">No rollup history yet.</p>
                  </ChartFrame>
                )}
              </CardBody>
            </Card>
          </div>

          <BreakdownCard
            title="Co-mentioned players"
            read={
              prof.data.co_mentions.length
                ? `Most often named alongside ${prof.data.co_mentions[0].name}.`
                : undefined
            }
            data={prof.data.co_mentions}
            caption={`The ecosystem named alongside ${prof.data.entity} · ${days}d window.`}
          />

          <Card>
            <CardBody>
              <SectionHeading title="Recent stories" />
              {prof.data.stories.length === 0 ? (
                <p className="text-[12.5px] italic text-faint">No recent stories in the live window.</p>
              ) : (
                <StoriesList stories={prof.data.stories} />
              )}
            </CardBody>
          </Card>
        </div>
      )}
    </div>
  );
}

function EntityMentionsCard({ series, days }: { series: VolumePoint[]; days: number }) {
  const pivot = feedAreaSeries(series);
  return (
    <ChartFrame
      title="Mentions over time"
      table={seriesTable(pivot.rows, pivot.series)}
      caption={`Mentions per day by feed, stacked · ${days}d window.`}
    >
      <TimeSeries data={pivot.rows} xKey="date" series={pivot.series} variant="area" formatX={shortDate} />
    </ChartFrame>
  );
}

/** Density rule for text walls: show a handful of stories, fold the rest. */
function StoriesList({ stories }: { stories: Story[] }) {
  const [expanded, setExpanded] = useState(false);
  const all = stories.slice(0, 16);
  const shown = expanded ? all : all.slice(0, 6);
  return (
    <>
      <ul className="divide-y divide-line">
        {shown.map((s, i) => (
          <StoryRow key={i} story={s} />
        ))}
      </ul>
      {all.length > 6 && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="mt-2 text-[11.5px] font-medium text-muted transition-colors hover:text-ink"
        >
          {expanded ? "Show fewer" : `Show all ${all.length}`}
        </button>
      )}
    </>
  );
}

/* ── Entity compare — folded into the Entities tab ───────────────────────────── */
function EntityCompare({
  a,
  b,
  loadingA,
  loadingB,
  errorB,
}: {
  a: EntityProfile;
  b: EntityProfile | null;
  loadingA: boolean;
  loadingB: boolean;
  errorB: string | null;
}) {
  if (errorB) return <ErrorCard />;
  const sharedFeeds = b ? Object.keys(a.by_feed).filter((f) => f in b.by_feed) : [];
  const sharedCo = b
    ? a.co_mentions.map((c) => c.name).filter((n) => b.co_mentions.some((c) => c.name === n))
    : [];

  return (
    <div className={cn("space-y-6 transition-opacity", (loadingA || loadingB) && "opacity-60")}>
      <div className="grid gap-6 sm:grid-cols-2">
        <EntityPanel prof={a} loading={loadingA} />
        <EntityPanel prof={b} loading={loadingB} />
      </div>
      {b && (
        <Card>
          <CardBody>
            <SectionHeading icon={<GitCompareArrows className="h-4 w-4" />} title="Overlap" />
            <p className="text-[13px] text-ink-soft">
              <span className="text-faint">Shared feeds:</span>{" "}
              {sharedFeeds.length ? sharedFeeds.join(", ") : "—"}
            </p>
            <p className="mt-1.5 text-[13px] text-ink-soft">
              <span className="text-faint">Co-mentioned with both:</span>{" "}
              {sharedCo.length ? sharedCo.join(", ") : "—"}
            </p>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

/* Card anatomy: title / one-sentence read / viz / caption. */
function EntityPanel({ prof, loading }: { prof: EntityProfile | null; loading: boolean }) {
  if (!prof) return <Card><CardBody>{loading ? <Spinner /> : <p className="text-[13px] text-faint">—</p>}</CardBody></Card>;
  const byFeed: HBarDatum[] = Object.entries(prof.by_feed)
    .map(([label, value]) => ({ label, value }))
    .sort((x, y) => y.value - x.value);
  return (
    <Card>
      <CardBody>
        <h3 className="text-[15px] font-semibold tracking-tight text-ink">{prof.entity}</h3>
        <p className="mt-1 text-[12.5px] leading-snug text-muted"><Rich text={prof.read} /></p>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <StatTile label="Prominence (wtd)" value={prof.weighted.toFixed(1)} />
          <StatTile label="Feeds" value={prof.feeds_count} />
        </div>
        <div className="mt-5">
          <ChartFrame title="Mentions by feed">
            <HBarList data={byFeed} format={count} collapsedAfter={byFeed.length > 5 ? 5 : undefined} />
          </ChartFrame>
        </div>
        {prof.co_mentions.length > 0 && (
          <p className="mt-3 text-[11.5px] text-faint">
            Top co-mentions: {prof.co_mentions.slice(0, 6).map((c) => c.name).join(", ")}
          </p>
        )}
      </CardBody>
    </Card>
  );
}

/* ── Stories — absorbed from the Feeds page ──────────────────────────────────── */
function StoriesView({ onStatus }: { onStatus: StatusFn }) {
  const { data, loading, error, updatedAt } = useAsync<FeedsPayload>(() => api.feeds(), []);
  useEffect(() => {
    onStatus({ live: !!data && !error, updatedAt });
  }, [data, error, updatedAt, onStatus]);
  if (loading && !data) return <Spinner />;
  if (error) return <ErrorCard />;
  if (!data) {
    return (
      <Card><CardBody><p className="text-[13px] text-muted">No stories yet.</p></CardBody></Card>
    );
  }
  return <StoriesContent data={data} />;
}

function StoriesContent({ data }: { data: FeedsPayload }) {
  const feeds = data.feeds.filter((f) => f.count > 0);
  const [active, setActive] = useState(feeds[0]?.key ?? "");
  const feed = feeds.find((f) => f.key === active) ?? feeds[0];
  const { run, jobForSlot } = useActions();
  const { isAuthed } = useAuth();
  if (!feed) return <p className="text-[13px] text-muted">No stories yet.</p>;
  const slot = `feed-${feed.key}`;
  const job = jobForSlot(slot);
  const running = job?.status === "running";

  return (
    <div className="space-y-5">
      {/* Filter row — the switcher scopes everything below it (DESIGN.md §3). */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="inline-flex flex-wrap gap-1 rounded-xl border border-line bg-canvas p-1">
          {feeds.map((f) => {
            const isActive = f.key === feed.key;
            return (
              <button
                key={f.key}
                onClick={() => setActive(f.key)}
                aria-pressed={isActive}
                className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[12.5px] font-medium transition-colors ${
                  isActive
                    ? "bg-surface text-ink shadow-[0_1px_2px_rgba(20,24,29,0.06)]"
                    : "text-muted hover:text-ink"
                }`}
              >
                <span aria-hidden="true">{f.icon}</span>
                {f.label}
                <span className="num text-[11px] text-faint">{f.count}</span>
              </button>
            );
          })}
        </div>
        {isAuthed && (
          <button
            onClick={() => run({ slot, path: `/api/actions/feed/${feed.key}`, label: `Refresh ${feed.label}` })}
            disabled={running}
            className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-[13px] font-medium text-ink-soft transition-colors hover:border-line-strong hover:text-ink disabled:opacity-60"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${running ? "animate-spin" : ""}`} />
            {running ? "Refreshing…" : `Refresh ${feed.label}`}
          </button>
        )}
      </div>
      {isAuthed && job && job.steps.length > 0 && <ProgressPanel job={job} />}

      <FeedSection key={feed.key} feed={feed} />
    </div>
  );
}

/* Per-feed section: one-line read + paginated story grid */

function feedRead(feed: FeedGroup): string {
  const loaded = feed.stories.length;
  const classified = feed.stories.filter(
    (s) => Boolean(s.sentiment) || typeof s["maturity_stage"] === "string",
  ).length;
  const classifiedPct = loaded ? Math.round((classified / loaded) * 100) : 0;
  let lastFetch: string | undefined;
  for (const s of feed.stories) {
    const f = s["fetched_at"];
    const when = (typeof f === "string" && f) || s.published_at;
    if (when && (!lastFetch || when > lastFetch)) lastFetch = when;
  }
  const parts = [
    `${feed.count} ${feed.count === 1 ? "story" : "stories"} in 30d`,
    `${classifiedPct}% of latest ${loaded} classified`,
  ];
  if (lastFetch) parts.push(`last fetch ${shortDate(lastFetch)}`);
  return parts.join(" · ");
}

function FeedSection({ feed }: { feed: FeedGroup }) {
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-[14.5px] font-semibold tracking-tight text-ink">{feed.label}</h2>
        <p className="num text-[11.5px] text-faint">{feedRead(feed)}</p>
      </div>
      <StoryList stories={feed.stories} />
    </section>
  );
}

const PAGE = 12;

function StoryList({ stories }: { stories: Story[] }) {
  const [shown, setShown] = useState(PAGE);
  if (!stories.length)
    return <p className="py-6 text-center text-[12.5px] text-faint">No stories loaded for this feed.</p>;
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
