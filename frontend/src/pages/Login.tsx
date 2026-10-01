import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Lock, Loader2, ShieldCheck } from "lucide-react";
import { useAuth } from "../lib/auth";
import { Card, CardBody } from "../components/ui";

/** Admin sign-in. Gates the Prosus page and the agent-triggering actions. */
export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/prosus";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    const res = await login(username.trim(), password);
    setBusy(false);
    if (res.ok) navigate(from, { replace: true });
    else setError(res.error ?? "Login failed");
  };

  return (
    <main className="flex min-h-screen flex-1 items-center justify-center px-6">
      <div className="w-full max-w-[380px]">
        <div className="mb-5 flex flex-col items-center text-center">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft text-brand">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <h1 className="mt-3 text-[17px] font-semibold tracking-tight text-ink">Admin sign-in</h1>
          <p className="mt-1 text-[12.5px] text-muted">
            Required for the Prosus portfolio and agent actions.
          </p>
        </div>
        <Card>
          <CardBody>
            <form onSubmit={submit} className="space-y-3.5">
              <div>
                <label className="mb-1 block text-[12px] font-medium text-ink-soft">Username</label>
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoFocus
                  autoComplete="username"
                  className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-[14px] text-ink outline-none transition-colors focus:border-brand"
                />
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-medium text-ink-soft">Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-[14px] text-ink outline-none transition-colors focus:border-brand"
                />
              </div>
              {error && (
                <p className="rounded-lg border border-down/30 bg-down-soft px-3 py-2 text-[12.5px] text-down">
                  {error}
                </p>
              )}
              <button
                type="submit"
                disabled={busy || !username.trim() || !password}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-brand px-3.5 py-2 text-[13.5px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Lock className="h-3.5 w-3.5" />}
                {busy ? "Signing in…" : "Sign in"}
              </button>
            </form>
          </CardBody>
        </Card>
      </div>
    </main>
  );
}
