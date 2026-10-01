import { useEffect, useRef, useState } from "react";
import type { ReactElement } from "react";
import { AlertTriangle, BookOpen, Brain, ChevronRight, Send, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { api, apiUrl } from "../lib/api";
import type { AnalystReportMeta, AskSource } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Topbar } from "../components/layout";
import { Card, CardBody, Badge, Segmented, StoryLink } from "../components/ui";

interface Msg {
  role: "user" | "assistant";
  content: string;
  stories?: AskSource[];
  theory?: AskSource[];
  /** The agent's reasoning trace (<think> block) — shown in a collapsible panel. */
  thinking?: string;
  /** false = backend answered in degraded mode (TOQAN_ASK not set). */
  configured?: boolean;
  /** true = the request itself failed (network / server error). */
  error?: boolean;
  /** true = typewriter-reveal this message (set on the freshly-streamed answer). */
  animate?: boolean;
}

/** A mix that exercises both retrieval paths: three news-grounded questions
 *  (phrased evergreen against the rolling corpus) and two theory questions
 *  (grounded in what the theory pack covers — see eval/judges/ask_questions.jsonl). */
const SUGGESTED = [
  "Who wins from hyperscalers buying nuclear power?",
  "Which technologies moved lifecycle stage recently, and why?",
  "Where is capital concentrating across the tracked domains right now?",
  "What does it take to cross the chasm in technology adoption?",
  "Why did Kodak fail despite inventing the digital camera?",
];

/* ── The page: two contracts, one place ────────────────────────────────────────
   Ask = grounded chat in seconds. Analyst = a commissioned, stored report that
   ends in a posture with a falsifier and can be locked into the ledger. */
export default function AskPage() {
  const [tab, setTab] = useState("ask");
  const tabs = (
    <div className="mb-5">
      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          ["ask", "Ask"],
          ["analyst", "Analyst"],
        ]}
      />
    </div>
  );
  return tab === "ask" ? <ChatTab tabs={tabs} /> : <AnalystTab tabs={tabs} />;
}

function ChatTab({ tabs }: { tabs: ReactElement }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy, stage, elapsed]);

  const send = async (q: string) => {
    const question = q.trim();
    if (!question || busy) return;
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((m) => [...m, { role: "user", content: question }]);
    setInput("");
    setBusy(true);
    setStage("Starting…");
    setElapsed(0);
    try {
      await api.askStream(question, history, (ev) => {
        if (ev.type === "stage") setStage(ev.label);
        else if (ev.type === "tick") setElapsed(ev.elapsed);
        else if (ev.type === "done")
          setMessages((m) => [
            ...m,
            {
              role: "assistant",
              content: ev.answer,
              thinking: ev.thinking,
              stories: ev.stories,
              theory: ev.theory,
              configured: ev.configured,
              animate: true,
            },
          ]);
        else if (ev.type === "error")
          setMessages((m) => [
            ...m,
            { role: "assistant", content: `Couldn't answer: ${ev.message}`, error: true },
          ]);
      });
    } catch (e) {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: `Couldn't answer: ${e instanceof Error ? e.message : e}`, error: true },
      ]);
    } finally {
      setBusy(false);
      setStage(null);
    }
  };

  return (
    <>
      <Topbar
        title="Ask Pharos"
        subtitle="A conversational analyst over the feeds + MOT theory"
        live={false}
        updatedAt={null}
        loading={busy}
        refreshLabel="New chat"
        /* Clearing the conversation is destructive — guard when messages exist. */
        onRefresh={() => {
          if (
            messages.length === 0 ||
            window.confirm("Start a new chat? The current conversation will be cleared.")
          ) {
            setMessages([]);
          }
        }}
      />
      <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col px-8 py-7">
        {tabs}
        <div className="flex-1 space-y-5">
          {messages.length === 0 && (
            <Card>
              <CardBody>
                <div className="flex items-center gap-2 text-ink">
                  <Sparkles className="h-4 w-4 text-brand" />
                  <span className="text-[14px] font-semibold">Ask anything about the tracked domains</span>
                </div>
                <p className="mt-1.5 max-w-[62ch] text-[13px] leading-relaxed text-muted">
                  Answered over a retrieved slice of the feeds + MOT theory (the most relevant recent
                  stories &amp; passages). Claims carry <DemoChip label="S1" /> and{" "}
                  <DemoChip label="T1" /> citations you can check against the sources panel under
                  each answer. No web search.
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {SUGGESTED.map((q) => (
                    <button
                      key={q}
                      onClick={() => send(q)}
                      className="rounded-full border border-line bg-canvas px-3.5 py-1.5 text-left text-[12.5px] text-ink-soft transition-colors hover:border-brand/40 hover:bg-brand-soft hover:text-brand-ink"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </CardBody>
            </Card>
          )}

          {messages.map((m, i) => (
            <MessageBubble key={i} msg={m} />
          ))}
          {busy && <LiveThinking stage={stage} elapsed={elapsed} />}
          <div ref={endRef} />
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
          className="sticky bottom-4 mt-4 flex items-center gap-2 rounded-xl border border-line bg-surface p-2 shadow-[0_2px_12px_rgba(20,24,29,0.06)]"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about a technology, company, or trend…"
            className="flex-1 bg-transparent px-3 py-2 text-[14px] text-ink outline-none placeholder:text-faint"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3.5 py-2 text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            <Send className="h-3.5 w-3.5" />
            Send
          </button>
        </form>
      </main>
    </>
  );
}

/* ── Message rendering ─────────────────────────────────────────────────────── */

/** The live status panel shown while the agent works: the real retrieval stage
 *  the backend is on, plus an elapsed-seconds timer streamed from the poll. */
function LiveThinking({ stage, elapsed }: { stage: string | null; elapsed: number }) {
  return (
    <div className="flex items-center gap-2.5 rounded-lg border border-line bg-canvas px-3.5 py-2.5 text-[12.5px]">
      <span className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-line border-t-brand" />
      <span className="text-ink-soft">{stage ?? "Thinking…"}</span>
      {elapsed > 0 && <span className="num text-faint">· {elapsed}s</span>}
    </div>
  );
}

/** Reveal `full` progressively when `active` (typewriter); otherwise whole. */
function useTypewriter(full: string, active: boolean): string {
  const [n, setN] = useState(active ? 0 : full.length);
  useEffect(() => {
    if (!active) {
      setN(full.length);
      return;
    }
    setN(0);
    const step = Math.max(2, Math.floor(full.length / 300)); // ~3.6s regardless of length
    const id = window.setInterval(() => {
      setN((c) => {
        if (c >= full.length) {
          window.clearInterval(id);
          return c;
        }
        return Math.min(full.length, c + step);
      });
    }, 12);
    return () => window.clearInterval(id);
  }, [full, active]);
  return full.slice(0, n);
}

/** Collapsible reasoning trace (the agent's <think> block). Collapsed by default. */
function ThinkingBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mb-1.5">
      <button
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-faint transition-colors hover:text-muted"
      >
        <Brain className="h-3 w-3" />
        Thinking
        <ChevronRight className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`} />
      </button>
      {open && (
        <div className="mt-1.5 whitespace-pre-wrap border-l-2 border-line pl-3 text-[12px] leading-relaxed text-muted">
          {text}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ msg }: { msg: Msg }) {
  const isUser = msg.role === "user";
  const degraded = !isUser && msg.configured === false;
  const failed = !isUser && msg.error === true;
  const shown = useTypewriter(msg.content ?? "", !isUser && !!msg.animate);
  const revealing = !isUser && !!msg.animate && shown.length < (msg.content?.length ?? 0);

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-brand px-4 py-2.5 text-[13.5px] leading-relaxed text-white">
          {msg.content}
        </div>
      </div>
    );
  }

  const sources = buildSourceMap(msg.stories, msg.theory);
  const bubbleCls = failed
    ? "rounded-2xl rounded-bl-sm border border-status-critical/30 bg-status-critical-soft px-4 py-3"
    : degraded
      ? "rounded-2xl rounded-bl-sm border border-status-warning/30 bg-status-warning-soft px-4 py-3"
      : "rounded-2xl rounded-bl-sm border border-line bg-surface px-4 py-3";

  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[700px]">
        {msg.thinking ? <ThinkingBlock text={msg.thinking} /> : null}
        <div className={bubbleCls}>
          {failed && (
            <p className="mb-1.5 flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-status-critical">
              <AlertTriangle className="h-3 w-3" />
              Request failed
            </p>
          )}
          {degraded && (
            <p className="mb-1.5 flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-status-warning">
              <AlertTriangle className="h-3 w-3" />
              Ask not configured
            </p>
          )}
          <AnswerText text={shown} sources={sources} />
        </div>
        {!revealing && (msg.stories?.length || msg.theory?.length) ? (
          <SourcesPanel stories={msg.stories ?? []} theory={msg.theory ?? []} />
        ) : null}
      </div>
    </div>
  );
}

/* ── Answer text: analyst prose with inline citation chips ─────────────────── */

type SourceMap = Map<string, AskSource>;

function buildSourceMap(stories?: AskSource[], theory?: AskSource[]): SourceMap {
  const map: SourceMap = new Map();
  for (const s of stories ?? []) if (s.label) map.set(s.label, s);
  for (const t of theory ?? []) if (t.label) map.set(t.label, t);
  return map;
}

/** Bold (**…**), italic (*…*), [S#]/[T#] citations, and the [unverified] marker.
 *  Bold is listed before italic so `**x**` matches as bold, not two italics. */
const INLINE_RE = /(\*\*[^*]+?\*\*|\*[^*]+?\*|\[[ST]\d+\]|\[unverified\])/g;

type Block =
  | { kind: "h"; level: number; text: string }
  | { kind: "hr" }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "table"; header: string[]; rows: string[][] }
  | { kind: "note"; text: string }
  | { kind: "p"; text: string };

/** A GFM table separator row, e.g. `|---|:--:|`. */
const TABLE_DELIM_RE = /^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$/;

function splitRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

/** Parse the answer's lightweight markdown into blocks. Handles headings (#..),
 *  ordered/unordered lists, GFM tables, horizontal rules, and the italic note
 *  line; inline formatting (bold, italic, [S#]/[T#] chips) is left to <Inline>
 *  per block. Tolerant of partial input, so it renders cleanly mid-typewriter. */
function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  const lines = text.split("\n");
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (list) {
      blocks.push({ kind: "list", ...list });
      list = null;
    }
  };
  let i = 0;
  while (i < lines.length) {
    const raw = lines[i];
    const t = raw.trim();
    let m: RegExpExecArray | null;

    // Table: a `| … |` header row immediately followed by a `|---|` separator.
    if (
      t.includes("|") &&
      i + 1 < lines.length &&
      lines[i + 1].includes("-") &&
      TABLE_DELIM_RE.test(lines[i + 1])
    ) {
      flush();
      const header = splitRow(t);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim() !== "" && lines[i].includes("|")) {
        rows.push(splitRow(lines[i]));
        i += 1;
      }
      blocks.push({ kind: "table", header, rows });
      continue;
    }

    if (t === "") {
      flush();
    } else if ((m = /^(#{1,6})\s+(.*)$/.exec(t))) {
      flush();
      blocks.push({ kind: "h", level: m[1].length, text: m[2] });
    } else if (/^(-{3,}|\*{3,}|_{3,})$/.test(t)) {
      flush();
      blocks.push({ kind: "hr" });
    } else if ((m = /^[-*]\s+(.*)$/.exec(t))) {
      if (!list || list.ordered) {
        flush();
        list = { ordered: false, items: [] };
      }
      list.items.push(m[1]);
    } else if ((m = /^(\d+)\.\s+(.*)$/.exec(t))) {
      if (!list || !list.ordered) {
        flush();
        list = { ordered: true, items: [] };
      }
      list.items.push(m[2]);
    } else if ((m = /^_(.+)_$/.exec(t))) {
      flush();
      blocks.push({ kind: "note", text: m[1] });
    } else {
      flush();
      blocks.push({ kind: "p", text: raw });
    }
    i += 1;
  }
  flush();
  return blocks;
}

function AnswerText({ text, sources }: { text: string; sources: SourceMap }) {
  return (
    <div className="max-w-[64ch] text-[13.5px] leading-[1.7] text-ink-soft">
      {parseBlocks(text).map((b, i) => {
        if (b.kind === "hr") return <hr key={i} className="my-3.5 border-line" />;
        if (b.kind === "h") {
          const cls =
            b.level <= 2
              ? "mt-4 mb-1.5 text-[15px] font-semibold tracking-tight text-ink first:mt-0"
              : "mt-3 mb-1 text-[13.5px] font-semibold text-ink first:mt-0";
          return (
            <p key={i} className={cls}>
              <Inline text={b.text} sources={sources} />
            </p>
          );
        }
        if (b.kind === "note")
          return (
            <p key={i} className="mt-2 text-[12.5px] text-muted">
              <em>
                <Inline text={b.text} sources={sources} />
              </em>
            </p>
          );
        if (b.kind === "table") {
          return (
            <div key={i} className="my-3 overflow-x-auto">
              <table className="w-full border-collapse text-[12.5px]">
                <thead>
                  <tr>
                    {b.header.map((h, j) => (
                      <th
                        key={j}
                        className="border-b border-line-strong px-2.5 py-1.5 text-left font-semibold text-ink"
                      >
                        <Inline text={h} sources={sources} />
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {b.rows.map((r, ri) => (
                    <tr key={ri}>
                      {r.map((c, ci) => (
                        <td
                          key={ci}
                          className="border-b border-line px-2.5 py-1.5 align-top text-ink-soft"
                        >
                          <Inline text={c} sources={sources} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (b.kind === "list") {
          const items = b.items.map((it, j) => (
            <li key={j} className="pl-0.5">
              <Inline text={it} sources={sources} />
            </li>
          ));
          return b.ordered ? (
            <ol key={i} className="my-2 list-decimal space-y-1 pl-5 marker:text-faint">
              {items}
            </ol>
          ) : (
            <ul key={i} className="my-2 list-disc space-y-1 pl-5 marker:text-faint">
              {items}
            </ul>
          );
        }
        return (
          <p key={i} className="mb-2 last:mb-0">
            <Inline text={b.text} sources={sources} />
          </p>
        );
      })}
    </div>
  );
}

function Inline({ text, sources }: { text: string; sources: SourceMap }) {
  const parts = text.split(INLINE_RE);
  return (
    <>
      {parts.map((p, i) => {
        if (!p) return null;
        if (p.startsWith("**") && p.endsWith("**") && p.length > 4) {
          return (
            <b key={i} className="font-semibold text-ink">
              <Inline text={p.slice(2, -2)} sources={sources} />
            </b>
          );
        }
        if (p.startsWith("*") && p.endsWith("*") && p.length > 2) {
          return (
            <em key={i} className="italic">
              <Inline text={p.slice(1, -1)} sources={sources} />
            </em>
          );
        }
        if (p === "[unverified]") {
          return (
            <span
              key={i}
              className="mx-0.5 inline-flex translate-y-[1px] items-center gap-1 rounded border border-status-warning/40 bg-status-warning-soft px-1.5 text-[10.5px] font-semibold leading-[1.6] text-status-warning"
            >
              <AlertTriangle className="h-2.5 w-2.5" />
              unverified
            </span>
          );
        }
        if (/^\[[ST]\d+\]$/.test(p)) {
          return <CiteChip key={i} label={p.slice(1, -1)} sources={sources} />;
        }
        return <span key={i}>{p}</span>;
      })}
    </>
  );
}

/** Clean a theory source path to a readable title: just the filename, minus a
 *  leading catalog code like "703503-PDF-ENG " → "Kodak case (2024).PDF". */
function theoryTitle(path?: string): string {
  if (!path) return "";
  const base = path.split("/").pop() ?? path;
  return base.replace(/^\d+[-_][A-Z0-9-]+\s+/, "").trim() || base;
}

/** Decorative chip for the intro copy — shows what an [S#]/[T#] citation looks
 *  like before any answer exists. Plain text: no link, no tooltip (there are no
 *  sources to point at yet, so a hover would mislead). */
function DemoChip({ label }: { label: string }) {
  const tone = label.startsWith("S")
    ? "border-brand/25 bg-brand-soft text-brand-ink"
    : "border-line-strong bg-canvas text-muted";
  return (
    <span
      aria-hidden="true"
      className={`mx-0.5 inline-flex -translate-y-[1px] items-center rounded border px-1 text-[10.5px] font-semibold leading-[1.6] ${tone}`}
    >
      {label}
    </span>
  );
}

/** Inline citation chip — [S#] links to the story, [T#] names the theory file. */
function CiteChip({ label, sources }: { label: string; sources: SourceMap }) {
  const src = sources.get(label);
  const isStory = label.startsWith("S");
  const title = src
    ? isStory
      ? `${src.title ?? label}${src.feed ? ` — ${src.feed}` : ""}`
      : (theoryTitle(src.source_file) || label)
    : `${label} — see sources below`;
  const base =
    "mx-0.5 inline-flex -translate-y-[1px] items-center rounded border px-1 text-[10.5px] font-semibold leading-[1.6]";
  const tone = isStory
    ? "border-brand/25 bg-brand-soft text-brand-ink"
    : "border-line-strong bg-canvas text-muted";
  if (isStory && src?.url) {
    return (
      <a
        href={src.url}
        target="_blank"
        rel="noopener noreferrer"
        title={title}
        className={`${base} ${tone} no-underline transition-colors hover:border-brand/50`}
      >
        {label}
      </a>
    );
  }
  return (
    <span title={title} className={`${base} ${tone}`}>
      {label}
    </span>
  );
}

/* ── Sources panel: numbered to match the inline citations ─────────────────── */

const COLLAPSED_ROWS = 5;

function SourcesPanel({ stories, theory }: { stories: AskSource[]; theory: AskSource[] }) {
  const [showAll, setShowAll] = useState(false);
  const sources = buildSourceMap(stories, theory);
  const rows: { key: string; label: string; node: ReactElement }[] = [
    ...stories.map((s, i) => ({
      key: `s${i}`,
      label: s.label ?? `S${i + 1}`,
      node: (
        <>
          <StoryLink href={s.url}>{s.title}</StoryLink>
          {s.feed ? <span className="text-faint"> · {s.feed}</span> : null}
        </>
      ),
    })),
    ...theory.map((t, i) => ({
      key: `t${i}`,
      label: t.label ?? `T${i + 1}`,
      node: (
        <>
          <span className="text-muted" title={t.source_file}>
            {theoryTitle(t.source_file)}
          </span>
          {t.similarity != null ? (
            <span className="text-faint">
              {" "}
              · relevance <span className="num">{t.similarity.toFixed(2)}</span>
            </span>
          ) : null}
        </>
      ),
    })),
  ];
  const visible = showAll ? rows : rows.slice(0, COLLAPSED_ROWS);
  const hidden = rows.length - visible.length;

  return (
    <div className="mt-2 rounded-lg border border-line bg-canvas px-3.5 py-2.5">
      <p className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-faint">
        <BookOpen className="h-3 w-3" />
        Sources
        <span className="num font-normal">({rows.length})</span>
      </p>
      <ul className="space-y-1.5">
        {visible.map((r) => (
          <li key={r.key} className="flex items-baseline gap-2 text-[12.5px] leading-snug">
            <CiteChip label={r.label} sources={sources} />
            <span className="min-w-0">{r.node}</span>
          </li>
        ))}
      </ul>
      {hidden > 0 && (
        <button
          onClick={() => setShowAll(true)}
          className="mt-2 text-[12px] font-medium text-brand transition-opacity hover:opacity-80"
        >
          Show all {rows.length}
        </button>
      )}
    </div>
  );
}

/* ── The Analyst tab — commission box, live job, and the report library ───────
   Commissioning is admin-gated (each run is real agent spend); the library is
   public like every other read. Job progress polls the same actions registry
   the Refresh-all panel uses. */
function AnalystTab({ tabs }: { tabs: ReactElement }) {
  const { isAuthed } = useAuth();
  const [topic, setTopic] = useState("");
  const [job, setJob] = useState<{ id: string; steps: { msg: string; ok: boolean }[]; status: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reports, setReports] = useState<AnalystReportMeta[] | null>(null);

  const loadReports = () =>
    api.analystReports().then((r) => setReports(r.reports)).catch(() => setReports([]));
  useEffect(() => {
    void loadReports();
  }, []);

  // Poll the running job every 2s; on completion refresh the library.
  useEffect(() => {
    if (!job || job.status !== "running") return;
    const id = window.setInterval(async () => {
      try {
        const res = await fetch(apiUrl(`/api/actions/status/${job.id}`));
        const j = (await res.json()) as { steps?: { msg: string; ok: boolean }[]; status?: string };
        setJob({ id: job.id, steps: j.steps ?? [], status: j.status ?? "running" });
        if (j.status && j.status !== "running") void loadReports();
      } catch {
        /* transient poll failure — keep trying */
      }
    }, 2000);
    return () => window.clearInterval(id);
  }, [job?.id, job?.status]);

  const commission = async () => {
    const t = topic.trim();
    if (!t) return;
    setError(null);
    const r = await api.analystCommission(t);
    if (!r.ok || !r.job) {
      setError(r.error ?? "Could not commission the report");
      return;
    }
    setTopic("");
    setJob({ id: r.job, steps: [], status: "running" });
  };

  const running = job?.status === "running";
  return (
    <>
      <Topbar
        title="The Analyst"
        subtitle="Commission an analysis that will be graded — posture, falsifier, and all"
        live={false}
        updatedAt={null}
        loading={running ?? false}
        onRefresh={() => void loadReports()}
      />
      <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col px-8 py-7">
        {tabs}
        <div className="flex-1 space-y-5">
          <Card>
            <CardBody>
              <div className="flex items-center gap-2 text-ink">
                <Sparkles className="h-4 w-4 text-brand" />
                <span className="text-[14px] font-semibold">Commission a report</span>
              </div>
              <p className="mt-1.5 max-w-[68ch] text-[13px] leading-relaxed text-muted">
                The Analyst sweeps everything Pharos tracks about a topic — stories across all
                feeds, lifecycle stages, nearby forecasts and their outcomes, capital moves, the
                funding signal — and returns a stored, straight-to-the-point note that ends in a{" "}
                <span className="text-ink-soft">posture with a falsifier</span>. Its central call
                can be locked into the ledger and graded later.
              </p>
              {isAuthed ? (
                <div className="mt-4 flex gap-2">
                  <input
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && !running && void commission()}
                    placeholder="e.g. sodium-ion batteries for grid storage"
                    disabled={running}
                    className="flex-1 rounded-lg border border-line bg-canvas px-3.5 py-2 text-[13.5px] text-ink outline-none transition-colors placeholder:text-faint focus:border-brand disabled:opacity-60"
                  />
                  <button
                    onClick={() => void commission()}
                    disabled={running || !topic.trim()}
                    className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                  >
                    <Send className="h-3.5 w-3.5" />
                    {running ? "Working…" : "Commission"}
                  </button>
                </div>
              ) : (
                <p className="mt-3 text-[12.5px] text-muted">
                  Commissioning requires an admin login (each run spends real analyst budget) —
                  the report library below is open to everyone.
                </p>
              )}
              {error && <p className="mt-2 text-[12.5px] text-status-critical">{error}</p>}
              {job && (
                <div className="mt-4 rounded-lg border border-line bg-canvas px-3.5 py-2.5">
                  {job.steps.map((s, i) => (
                    <p key={i} className={`text-[12px] leading-relaxed ${s.ok ? "text-ink-soft" : "text-status-critical"}`}>
                      {s.msg}
                    </p>
                  ))}
                  {running && <p className="text-[12px] italic text-faint">The Analyst is working — a few minutes is normal…</p>}
                </div>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardBody>
              <div className="mb-3 flex items-center gap-2 text-ink">
                <BookOpen className="h-4 w-4 text-brand" />
                <span className="text-[14px] font-semibold">Report library</span>
              </div>
              {reports == null ? (
                <p className="text-[12.5px] text-faint">Loading…</p>
              ) : reports.length === 0 ? (
                <p className="text-[12.5px] text-muted">
                  No reports yet — the library fills as analyses are commissioned.
                </p>
              ) : (
                <ul className="divide-y divide-line">
                  {reports.map((r) => (
                    <li key={r.id}>
                      <Link
                        to={`/analyst/${r.id}`}
                        className="group flex flex-wrap items-baseline gap-x-2.5 gap-y-1 py-2.5 no-underline"
                      >
                        <span className="text-[13.5px] font-medium text-ink group-hover:underline">
                          {r.topic}
                        </span>
                        <Badge variant={r.posture?.posture === "invest" ? "up" : r.posture?.posture === "avoid" ? "down" : "brand"}>
                          {r.posture?.posture}
                        </Badge>
                        {r.coverage === "thin" && <Badge variant="warn">thin coverage</Badge>}
                        {r.ledger_pred_id && <Badge variant="neutral">on the ledger</Badge>}
                        <span className="num ml-auto text-[11.5px] text-faint">
                          {r.as_of} · {r.created_by}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        </div>
      </main>
    </>
  );
}
