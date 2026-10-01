/**
 * Analyst report — /analyst/:id.
 *
 * A commissioned, stored analysis: the agent's prose (constrained markdown,
 * story-only [S#] citations rendered as checkable chips), the parsed posture
 * block styled like a Briefing signal, and the database-computed exhibits
 * (mention trend, stage table with dossier links, capital split, players,
 * funding) — rendered natively, never drawn by the agent. Admins can lock the
 * central call into the ledger; the badge then links the report to its graded
 * forecast forever.
 */
import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, BookCheck, MessageSquare, Newspaper, Send, Sparkles } from "lucide-react";
import { api } from "../lib/api";
import type { AnalystReport } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useResource } from "../lib/useResource";
import { PageChrome } from "../components/PageChrome";
import { Card, CardBody, SectionHeading, Badge, StoryLink, Rich } from "../components/ui";
import { shortDate } from "../lib/format";

export default function AnalystReportPage() {
  const { id = "" } = useParams();
  const loader = useCallback(() => api.analystReport(Number(id)), [id]);
  const resource = useResource<AnalystReport>(loader, { key: `analyst:${id}` });
  return (
    <PageChrome
      title="Analyst report"
      subtitle="Commissioned analysis — on the record, gradable"
      resource={resource}
    >
      {(r) => <Report r={r} onLogged={resource.refresh} />}
    </PageChrome>
  );
}

function Report({ r, onLogged }: { r: AnalystReport; onLogged: () => void }) {
  const { isAuthed } = useAuth();
  const [logging, setLogging] = useState(false);
  const [logError, setLogError] = useState<string | null>(null);
  const byLabel = new Map(r.citations.map((c) => [c.label, c]));

  const logCall = async () => {
    setLogging(true);
    setLogError(null);
    const res = await api.analystLogCall(r.id);
    setLogging(false);
    if (!res.ok) setLogError(res.error ?? "Could not log the call");
    else onLogged();
  };

  return (
    <div className="space-y-7">
      {/* header */}
      <Card>
        <CardBody>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to="/ask"
              className="inline-flex items-center gap-1 text-[12px] font-medium text-muted no-underline hover:text-ink"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> Analyst library
            </Link>
            <span className="text-faint">·</span>
            {r.coverage === "thin" && <Badge variant="warn">thin coverage</Badge>}
            <span className="num ml-auto text-[11.5px] text-faint">
              {r.as_of} · commissioned by {r.created_by}
            </span>
          </div>
          <h2 className="mt-3 text-[22px] font-semibold tracking-tight text-ink">{r.topic}</h2>
        </CardBody>
      </Card>

      {/* the note itself */}
      <Card>
        <CardBody>
          <ReportProse text={r.report} byLabel={byLabel} />
        </CardBody>
      </Card>

      {/* the posture — the gradable call */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<BookCheck className="h-4 w-4" />}
            title="The call"
            description="The report's central, falsifiable recommendation."
          />
          <div
            className="rounded-xl border border-line bg-surface p-4"
            style={{ borderLeftColor: "var(--color-brand)", borderLeftWidth: 3 }}
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant={r.posture.posture === "invest" ? "up" : r.posture.posture === "avoid" ? "down" : "brand"}
              >
                {r.posture.posture.toUpperCase()}
              </Badge>
              <span className="num text-[12px] text-muted">
                {Math.round(r.posture.confidence * 100)}% confidence · resolves by{" "}
                {shortDate(r.posture.resolve_by)}
              </span>
            </div>
            <p className="mt-2 text-[13px] text-ink-soft">For: {r.posture.addressee}</p>
            <div
              className="mt-2.5 rounded-md border border-line bg-canvas px-2.5 py-1.5"
              style={{ borderLeftColor: "var(--color-status-serious)", borderLeftWidth: 3 }}
            >
              <p className="text-[9.5px] font-semibold uppercase tracking-[0.08em] text-status-serious">
                Wrong if
              </p>
              <p className="mt-0.5 text-[12px] leading-relaxed text-ink-soft">{r.posture.falsifier}</p>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
              {r.ledger_pred_id ? (
                <Badge variant="up">On the ledger — graded when due</Badge>
              ) : isAuthed ? (
                <button
                  onClick={() => void logCall()}
                  disabled={logging}
                  className="inline-flex items-center gap-2 rounded-lg bg-brand px-3.5 py-1.5 text-[12.5px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  <BookCheck className="h-3.5 w-3.5" />
                  {logging ? "Locking…" : "Log this call to the ledger"}
                </button>
              ) : (
                <span className="text-[12px] text-faint">
                  Not yet on the ledger — an admin can lock this call for grading.
                </span>
              )}
              {logError && <span className="text-[12px] text-status-critical">{logError}</span>}
            </div>
          </div>
        </CardBody>
      </Card>

      {/* exhibits — computed from the database, never by the agent */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<Sparkles className="h-4 w-4" />}
            title="Exhibits"
            description="Computed from Pharos's database at commission time — the agent analyzes, the data illustrates."
          />
          <Exhibits r={r} />
        </CardBody>
      </Card>

      {/* interrogate the author — the note is immutable; the Q&A is conversation */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<MessageSquare className="h-4 w-4" />}
            title="Ask the Analyst about this report"
            description="The author defends and explains the published call. The note never changes here — a material gap earns a fresh commission, not a silent edit."
          />
          <Interrogation reportId={r.id} byLabel={byLabel} />
        </CardBody>
      </Card>

      {/* checkable sources — stories only, by design */}
      <Card>
        <CardBody>
          <SectionHeading
            icon={<Newspaper className="h-4 w-4" />}
            title={`Sources (${r.citations.length})`}
            description="Every [S#] in the note resolves here — theory is applied by name in prose, not cited as chunks."
          />
          <ul className="space-y-1.5">
            {r.citations.map((c) => (
              <li key={c.label} className="text-[12.5px] leading-snug">
                <span className="mr-1.5 font-semibold text-faint">{c.label}</span>
                {c.url ? <StoryLink href={c.url}>{c.title}</StoryLink> : <span>{c.title}</span>}
                <span className="ml-1.5 text-faint">
                  {c.feed ?? "?"}{c.published_at ? ` · ${shortDate(c.published_at)}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>
    </div>
  );
}

/* ── Constrained-markdown renderer for the report prose ─────────────────────────
   The contract allows only: ## headings, paragraphs, "- " bullets, **bold**,
   and [S#] citations (rendered as chips resolving to the sources panel). The
   structured posture block is rendered separately, so it's stripped here. */
function ReportProse({ text, byLabel }: { text: string; byLabel: Map<string, { url: string | null; title: string | null }> }) {
  const body = text
    .replace(/^(POSTURE|ADDRESSEE|CONFIDENCE|WRONG IF|RESOLVE BY):.*$/gim, "")
    .trim();
  const blocks = body.split(/\n{2,}/);
  return (
    <div className="max-w-3xl space-y-3">
      {blocks.map((b, i) => {
        const t = b.trim();
        if (!t) return null;
        if (t.startsWith("## ")) {
          return (
            <h3 key={i} className="pt-1 text-[14px] font-semibold tracking-tight text-ink">
              {t.slice(3)}
            </h3>
          );
        }
        if (/^- /m.test(t)) {
          return (
            <ul key={i} className="list-disc space-y-1 pl-5">
              {t.split("\n").filter((l) => l.trim().startsWith("- ")).map((l, j) => (
                <li key={j} className="text-[13.5px] leading-relaxed text-ink-soft">
                  <Cited text={l.replace(/^- /, "")} byLabel={byLabel} />
                </li>
              ))}
            </ul>
          );
        }
        return (
          <p key={i} className="text-[13.5px] leading-relaxed text-ink-soft">
            <Cited text={t} byLabel={byLabel} />
          </p>
        );
      })}
    </div>
  );
}

/** Bold via Rich, plus [S#] rendered as checkable chips. */
function Cited({ text, byLabel }: { text: string; byLabel: Map<string, { url: string | null; title: string | null }> }) {
  const parts = text.split(/(\[S\d+\])/g);
  return (
    <>
      {parts.map((p, i) => {
        const m = p.match(/^\[(S\d+)\]$/);
        if (!m) return <Rich key={i} text={p} />;
        const src = byLabel.get(m[1]);
        const chip =
          "mx-0.5 inline-flex items-center rounded border border-brand/25 bg-brand-soft px-1 text-[10.5px] font-medium text-brand-ink no-underline align-baseline";
        return src?.url ? (
          <a key={i} href={src.url} target="_blank" rel="noopener noreferrer" title={src.title ?? m[1]} className={chip}>
            {m[1]}
          </a>
        ) : (
          <span key={i} title={src?.title ?? undefined} className={chip}>{m[1]}</span>
        );
      })}
    </>
  );
}

/* ── Native exhibits ───────────────────────────────────────────────────────────── */
function Exhibits({ r }: { r: AnalystReport }) {
  const ex = r.exhibits;
  const maxTrend = Math.max(1, ...ex.mention_trend.map((m) => m.count));
  return (
    <div className="space-y-5">
      {ex.stage_table.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">
            Related technologies — lifecycle stage at commission time
          </p>
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full text-[12.5px]">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-faint">
                  <th className="px-3 py-2 font-medium">Technology</th>
                  <th className="px-2 py-2 font-medium">Maturity</th>
                  <th className="px-2 py-2 font-medium">Adoption</th>
                  <th className="px-3 py-2 text-right font-medium">Articles/30d</th>
                </tr>
              </thead>
              <tbody>
                {ex.stage_table.map((t) => (
                  <tr key={t.tech} className="border-b border-line/50 last:border-0">
                    <td className="px-3 py-2">
                      <Link to={`/tech/${t.tech}`} className="font-medium text-ink no-underline hover:underline">
                        {t.label}
                      </Link>
                    </td>
                    {t.watching ? (
                      <td colSpan={2} className="px-2 py-2">
                        <Badge variant="warn">watching — no stage claim</Badge>
                      </td>
                    ) : (
                      <>
                        <td className="px-2 py-2 capitalize text-ink-soft">{(t.maturity ?? "—").replace(/-/g, " ")}</td>
                        <td className="px-2 py-2 capitalize text-ink-soft">{(t.adoption ?? "—").replace(/-/g, " ")}</td>
                      </>
                    )}
                    <td className="num px-3 py-2 text-right text-faint">{t.articles ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {ex.mention_trend.length > 1 && (
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">
            Coverage trend (matched stories / month)
          </p>
          <div className="flex items-end gap-1.5">
            {ex.mention_trend.map((m) => (
              <div key={m.month} className="flex flex-col items-center gap-1">
                <span className="num text-[10px] text-faint">{m.count}</span>
                <div
                  className="w-8 rounded-t bg-[color:var(--color-seq-500,#6b8fd6)]"
                  style={{ height: `${Math.max(6, (m.count / maxTrend) * 64)}px` }}
                  title={`${m.month}: ${m.count}`}
                />
                <span className="num text-[10px] text-faint">{m.month.slice(2)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-x-8 gap-y-3">
        {(ex.capital_split.commitment + ex.capital_split.option > 0) && (
          <div>
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">Capital (30d)</p>
            <p className="num text-[13px] text-ink-soft">
              <span className="font-semibold text-ink">{ex.capital_split.commitment}</span> commitments ·{" "}
              <span className="font-semibold text-ink">{ex.capital_split.option}</span> options
            </p>
          </div>
        )}
        {ex.funding && (
          <div>
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">Funding signal</p>
            <p className="num text-[13px] text-ink-soft">
              {ex.funding.rounds} rounds/12mo · {ex.funding.early} early / {ex.funding.late} late
            </p>
          </div>
        )}
        {ex.players.length > 0 && (
          <div className="min-w-0">
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">Most-named players</p>
            <div className="flex flex-wrap gap-1.5">
              {ex.players.map((p) => (
                <span key={p.name} className="inline-flex items-center gap-1 rounded-md border border-line bg-canvas px-1.5 py-0.5 text-[11.5px] text-ink">
                  {p.name} <span className="num text-faint">{p.mentions}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Interrogation thread — ephemeral by design (the record is the report) ──── */
function Interrogation({ reportId, byLabel }: { reportId: number; byLabel: Map<string, { url: string | null; title: string | null }> }) {
  const [thread, setThread] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ask = async () => {
    const question = q.trim();
    if (!question || busy) return;
    setError(null);
    setThread((t) => [...t, { role: "user", content: question }]);
    setQ("");
    setBusy(true);
    const res = await api.analystAsk(reportId, question, thread);
    setBusy(false);
    if (!res.ok || !res.answer) {
      setError(res.error ?? "The Analyst could not answer");
      return;
    }
    setThread((t) => [...t, { role: "assistant", content: res.answer! }]);
  };

  return (
    <div className="max-w-3xl">
      {thread.length > 0 && (
        <div className="mb-3 space-y-2.5">
          {thread.map((m, i) =>
            m.role === "user" ? (
              <p key={i} className="ml-auto w-fit max-w-[85%] rounded-lg bg-brand px-3 py-1.5 text-[12.5px] text-white">
                {m.content}
              </p>
            ) : (
              <div key={i} className="w-fit max-w-[92%] rounded-lg border border-line bg-canvas px-3 py-2 text-[13px] leading-relaxed text-ink-soft">
                <Cited text={m.content} byLabel={byLabel} />
              </div>
            ),
          )}
        </div>
      )}
      {busy && <p className="mb-2 text-[12px] italic text-faint">The Analyst is answering…</p>}
      {error && <p className="mb-2 text-[12px] text-status-critical">{error}</p>}
      <div className="flex gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void ask()}
          placeholder="e.g. why watch and not invest? what would move your confidence?"
          disabled={busy}
          className="flex-1 rounded-lg border border-line bg-canvas px-3.5 py-2 text-[13px] text-ink outline-none transition-colors placeholder:text-faint focus:border-brand disabled:opacity-60"
        />
        <button
          onClick={() => void ask()}
          disabled={busy || !q.trim()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3.5 py-2 text-[12.5px] font-medium text-ink-soft transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
        >
          <Send className="h-3.5 w-3.5" /> Ask
        </button>
      </div>
    </div>
  );
}
