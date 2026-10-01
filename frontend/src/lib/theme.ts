/** Shared numeric helpers for charts. Colour now lives in the CSS tokens
 *  (--color-cat-* / --color-seq-* in index.css) consumed via components/viz —
 *  the old SECTOR_RANGE / sectorColor / reactionColor hex palette was removed
 *  with the recharts-based components/charts.tsx. */

export function median(xs: number[]): number | null {
  const v = xs.filter((x) => isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}
