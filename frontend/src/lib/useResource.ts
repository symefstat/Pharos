import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { useActions } from "../components/actions";

export interface Resource<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  updatedAt: Date | null;
  refresh: () => void;
}

export interface ResourceOptions {
  /** Cache key. When set, results are cached across mounts (stale-while-
   *  revalidate). Omit to opt out of caching (legacy behaviour). Include any
   *  parameters the loader depends on, e.g. `mot:${scope}`. */
  key?: string;
  /** How long a cached entry is considered fresh (ms). While fresh, a revisit
   *  serves the cache and skips the network entirely. Once stale, the cache is
   *  shown immediately and a background refetch runs. Default 30s. */
  staleTime?: number;
}

interface CacheEntry {
  data: unknown;
  updatedAt: number;
}

// Module-level cache: survives component unmounts, cleared on hard refresh or
// when a background action busts the server cache (see the `tick` effect).
const cache = new Map<string, CacheEntry>();

/** Drop cached client-side data so the next read of any page hits the network. */
export function clearResourceCache(): void {
  cache.clear();
}

/** Generic data hook: runs `loader`, exposes {data, loading, error}, and a
 *  `refresh()` that busts the server cache then reloads. One per page.
 *
 *  With an `opts.key`, results are cached: a revisit paints instantly from the
 *  cache while (if stale) a background refetch keeps it current — no skeleton
 *  flash, no redundant round-trips. */
export function useResource<T>(
  loader: () => Promise<T>,
  opts: ResourceOptions = {},
): Resource<T> {
  const { key, staleTime = 30_000 } = opts;

  const cached = key ? (cache.get(key) as CacheEntry | undefined) : undefined;
  const [data, setData] = useState<T | null>(
    cached ? (cached.data as T) : null,
  );
  const [loading, setLoading] = useState(!cached);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(
    cached ? new Date(cached.updatedAt) : null,
  );

  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  /**
   * @param bust        hard refresh — clears the server cache first, always
   *                    shows a loading state.
   * @param background  revalidate without flipping to a loading state (keeps
   *                    stale data visible under a stale-while-revalidate read).
   */
  const load = useCallback(
    async (bust: boolean, background = false) => {
      if (!background) setLoading(true);
      setError(null);
      try {
        if (bust) {
          await api.refresh();
          clearResourceCache(); // server cache is global — every page is now stale
        }
        const next = await loader();
        if (!alive.current) return;
        setData(next);
        const now = Date.now();
        setUpdatedAt(new Date(now));
        if (key) cache.set(key, { data: next, updatedAt: now });
      } catch (e) {
        if (!alive.current) return;
        // Keep any stale data visible on a background failure; surface the error.
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (alive.current && !background) setLoading(false);
      }
    },
    [loader, key],
  );

  // Initial load / key change. Serve the cache when present; only hit the
  // network if the entry is missing or stale.
  useEffect(() => {
    const entry = key ? (cache.get(key) as CacheEntry | undefined) : undefined;
    if (!entry) {
      void load(false);
      return;
    }
    // Paint cached value (covers a key change to an already-cached resource).
    setData(entry.data as T);
    setUpdatedAt(new Date(entry.updatedAt));
    setLoading(false);
    if (Date.now() - entry.updatedAt > staleTime) {
      void load(false, /* background */ true);
    }
  }, [load, key, staleTime]);

  // When any background action completes, the server cache is already cleared —
  // drop the client cache and revalidate this page in the background
  // (skip the initial mount value).
  const { tick } = useActions();
  const lastTick = useRef(tick);
  useEffect(() => {
    if (tick === lastTick.current) return;
    lastTick.current = tick;
    if (key) cache.delete(key);
    void load(false, /* background */ true);
  }, [tick, load, key]);

  return { data, loading, error, updatedAt, refresh: () => void load(true) };
}
