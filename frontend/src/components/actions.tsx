import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { Check, X, Loader2 } from "lucide-react";
import { api, type Job } from "../lib/api";
import { cn } from "../lib/utils";

interface TrackedJob extends Job {
  slot: string;
  label: string;
}
interface Toast {
  id: string;
  label: string;
  ok: boolean;
}
interface Ctx {
  run: (opts: { slot: string; label: string; path: string; body?: unknown }) => void;
  jobForSlot: (slot: string) => TrackedJob | undefined;
  tick: number; // bumped whenever any action completes → pages auto-refresh
}

const ActionsContext = createContext<Ctx>({
  run: () => {},
  jobForSlot: () => undefined,
  tick: 0,
});
export const useActions = () => useContext(ActionsContext);

/** App-global runner: tracks background jobs, polls them regardless of which page
 *  is mounted, toasts on completion, and bumps `tick` so live pages refetch. */
export function ActionsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Record<string, TrackedJob>>({});
  const [slots, setSlots] = useState<Record<string, string>>({});
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [tick, setTick] = useState(0);
  const jobsRef = useRef(jobs);
  jobsRef.current = jobs;

  const pushToast = useCallback((label: string, ok: boolean) => {
    const id = `${label}-${Math.random().toString(36).slice(2)}`;
    setToasts((t) => [...t, { id, label, ok }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  }, []);

  const run = useCallback(
    async ({ slot, label, path, body }: { slot: string; label: string; path: string; body?: unknown }) => {
      const tempId = `tmp-${slot}-${Math.random().toString(36).slice(2)}`;
      const placeholder: TrackedJob = {
        id: tempId, kind: slot, slot, label, status: "running",
        steps: [{ msg: "Starting…", ok: true }], error: null, started: 0, finished: null,
      };
      setJobs((j) => ({ ...j, [tempId]: placeholder }));
      setSlots((s) => ({ ...s, [slot]: tempId }));

      const res = await api.runActionByPath(path, body);
      setJobs((j) => {
        const n = { ...j };
        delete n[tempId];
        return n;
      });
      if (!res.job_id) {
        const id = `err-${tempId}`;
        setJobs((j) => ({
          ...j,
          [id]: { ...placeholder, id, status: "error", steps: [{ msg: res.error ?? "Failed to start", ok: false }], error: res.error ?? null },
        }));
        setSlots((s) => ({ ...s, [slot]: id }));
        pushToast(label, false);
        return;
      }
      setJobs((j) => ({ ...j, [res.job_id!]: { ...placeholder, id: res.job_id!, steps: [] } }));
      setSlots((s) => ({ ...s, [slot]: res.job_id! }));
    },
    [pushToast],
  );

  // Single poller that reads the live job set from a ref.
  useEffect(() => {
    const poll = async () => {
      const running = Object.values(jobsRef.current).filter(
        (j) => j.status === "running" && !j.id.startsWith("tmp"),
      );
      for (const job of running) {
        try {
          const s = await api.actionStatus(job.id);
          const prev = jobsRef.current[job.id];
          if (!prev) continue;
          setJobs((p) => (p[job.id] ? { ...p, [job.id]: { ...p[job.id], ...s } } : p));
          if (prev.status === "running" && (s.status === "done" || s.status === "error")) {
            pushToast(prev.label, s.status === "done");
            setTick((x) => x + 1);
          }
        } catch {
          /* transient — retry next tick */
        }
      }
    };
    const t = window.setInterval(poll, 1500);
    return () => window.clearInterval(t);
  }, [pushToast]);

  const jobForSlot = useCallback(
    (slot: string) => {
      const id = slots[slot];
      return id ? jobs[id] : undefined;
    },
    [slots, jobs],
  );

  return (
    <ActionsContext.Provider value={{ run, jobForSlot, tick }}>
      {children}
      <ToastContainer toasts={toasts} />
    </ActionsContext.Provider>
  );
}

function ToastContainer({ toasts }: { toasts: Toast[] }) {
  if (!toasts.length) return null;
  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="flex items-center gap-2.5 rounded-xl border border-line bg-surface px-4 py-3 text-[13px] shadow-[0_8px_28px_rgba(20,24,29,0.16)]"
        >
          <span
            className={cn(
              "flex h-5 w-5 items-center justify-center rounded-full",
              t.ok ? "bg-up-soft text-up" : "bg-down-soft text-down",
            )}
          >
            {t.ok ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
          </span>
          <span className="text-ink">
            <span className="font-semibold">{t.label}</span> — {t.ok ? "complete" : "failed"}
          </span>
        </div>
      ))}
    </div>
  );
}

/** A button bound to a background action, with its live progress below it. */
export function ActionButton({
  slot,
  path,
  label,
  icon,
  primary,
}: {
  slot: string;
  path: string;
  label: string;
  icon?: ReactNode;
  primary?: boolean;
}) {
  const { run, jobForSlot } = useActions();
  const job = jobForSlot(slot);
  const running = job?.status === "running";
  return (
    <div>
      <button
        onClick={() => run({ slot, label, path })}
        disabled={running}
        className={cn(
          "inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors disabled:opacity-60",
          primary
            ? "bg-brand text-white hover:opacity-90"
            : "border border-line bg-surface text-ink-soft hover:border-line-strong hover:text-ink",
        )}
      >
        {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : icon}
        {running ? "Running…" : label}
      </button>
      {job && job.steps.length > 0 && <ProgressPanel job={job} />}
    </div>
  );
}

export function ProgressPanel({ job }: { job: Job }) {
  return (
    <div className="mt-2.5 w-full max-w-xl rounded-lg border border-line bg-canvas p-3">
      <ul className="space-y-1">
        {job.steps.map((s, i) => {
          const last = i === job.steps.length - 1;
          const pending = job.status === "running" && last;
          return (
            <li key={i} className="flex items-start gap-2 text-[12px] leading-snug">
              <span className="mt-0.5 shrink-0">
                {pending ? (
                  <Loader2 className="h-3 w-3 animate-spin text-brand" />
                ) : s.ok ? (
                  <Check className="h-3 w-3 text-up" />
                ) : (
                  <X className="h-3 w-3 text-down" />
                )}
              </span>
              <span className={s.ok ? "text-muted" : "text-down"}>{s.msg}</span>
            </li>
          );
        })}
      </ul>
      {job.status === "done" && <p className="mt-2 text-[11.5px] font-medium text-up">Complete — data refreshed.</p>}
      {job.status === "error" && <p className="mt-2 text-[11.5px] font-medium text-down">Failed — see above.</p>}
    </div>
  );
}
