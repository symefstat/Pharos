import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import type { ReactNode } from "react";
import { api, getToken, clearToken, AUTH_EVENT } from "./api";

interface AuthCtx {
  isAuthed: boolean;
  /** true until the stored token has been validated on first load. */
  ready: boolean;
  login: (username: string, password: string) => Promise<{ ok: boolean; error?: string }>;
  logout: () => void;
}

const Context = createContext<AuthCtx>({
  isAuthed: false,
  ready: false,
  login: async () => ({ ok: false }),
  logout: () => {},
});

export const useAuth = () => useContext(Context);

/** Holds the shared-admin session. The token itself lives in sessionStorage
 *  (see lib/api.ts); this provider mirrors its presence into React state and
 *  validates it once on load. A 401 anywhere fires AUTH_EVENT, which drops us
 *  back to logged-out. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [ready, setReady] = useState(false);

  // Keep state in sync with sessionStorage (login stores it, a 401 clears it).
  useEffect(() => {
    const sync = () => setTokenState(getToken());
    window.addEventListener(AUTH_EVENT, sync);
    return () => window.removeEventListener(AUTH_EVENT, sync);
  }, []);

  // Validate a persisted token once on mount; drop it if the server rejects it.
  useEffect(() => {
    let cancelled = false;
    if (!getToken()) {
      setReady(true);
      return;
    }
    api
      .me()
      .catch(() => clearToken())
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.login(username, password);
    if (res.ok) setTokenState(getToken());
    return res;
  }, []);

  const logout = useCallback(() => clearToken(), []);

  return (
    <Context.Provider value={{ isAuthed: !!token, ready, login, logout }}>
      {children}
    </Context.Provider>
  );
}
