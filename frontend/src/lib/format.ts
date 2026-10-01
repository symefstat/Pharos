/** Display formatters — mirror the units the Streamlit Capital tab used
 *  (trillions/billions market cap, % intensities, ×-multiples, signed moves). */

export function usd(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return "—";
  const a = Math.abs(n);
  if (a >= 1e12) return `$${(n / 1e12).toFixed(1)}T`;
  if (a >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  if (a >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

export function pct(n: number | null | undefined, digits = 0): string {
  if (n == null || !isFinite(n)) return "—";
  return `${n.toFixed(digits)}%`;
}

/** A ratio in 0..1 rendered as a percentage (e.g. 0.23 → "23%"). */
export function ratioPct(n: number | null | undefined, digits = 0): string {
  if (n == null || !isFinite(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

export function signedPct(n: number | null | undefined, digits = 1): string {
  if (n == null || !isFinite(n)) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(digits)}%`;
}

export function multiple(n: number | null | undefined, digits = 1): string {
  if (n == null || !isFinite(n)) return "—";
  return `${n.toFixed(digits)}×`;
}

/** "2026-06-09" → "Jun 9". */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Story date for display. Some publishers put a rule's EFFECTIVE date in the
 *  published_at field, which renders as a future-dated article — a temporal
 *  impossibility that damages trust. A future date is relabeled for what it
 *  almost certainly is. */
export function pubDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = shortDate(iso);
  const today = new Date().toISOString().slice(0, 10);
  return String(iso).slice(0, 10) > today ? `takes effect ${d}` : d;
}

export function truncate(s: string | null | undefined, n: number): string {
  if (!s) return "";
  return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s;
}
