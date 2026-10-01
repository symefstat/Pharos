/**
 * Source-authority tiers for the Briefing's source chips — transparent disclosure,
 * not shaming. Material claims sometimes rest on outlets like "Crypto Briefing" or
 * "WebProNews" with no visible authority signal; this module makes the signal
 * visible without editorializing on individual chips.
 *
 * Rubric (curated, deliberately small — mirrors the backend map in
 * analytics/weights.py SOURCE_TIERS and the alias-map philosophy of
 * analytics/entities.py; extend as you see source_name drift):
 *
 *   Tier 1 — wire services & major business press. Newsrooms with institutional
 *            fact-checking and corrections: Reuters, Bloomberg, FT, WSJ, AP,
 *            Nikkei, CNBC, The Economist, NYT, Washington Post, BBC, AFP…
 *   Tier 2 — established trade/tech press and primary sources. Specialist desks
 *            with domain expertise (TechCrunch, The Verge, Ars Technica, IEEE
 *            Spectrum, Electrek, InsideEVs, CnEVPost, DigiTimes, Utility Dive,
 *            Energy-Storage.News, The Information…), peer-reviewed journals
 *            (Nature, Science), and company / agency / government announcements
 *            (press-release wires, SEC, FDA, .gov) — primary but self-interested.
 *   Tier 3 — everything unrecognized. Not "wrong", just unverified: no claim is
 *            made about the outlet either way.
 *
 * Matching is case-insensitive and substring-tolerant on whole words, so
 * "Reuters via Yahoo" → tier 1 while "Microsoft" does NOT match the "ft" token.
 * Domain forms ("www.coindesk.com/markets") are normalized before matching.
 */

export type SourceTier = 1 | 2 | 3;

export const TIER_LABELS: Record<SourceTier, string> = {
  1: "wire/major",
  2: "trade/primary",
  3: "unverified outlet",
};

/* Tier 1 — wire services & major business press. */
const TIER_1: string[] = [
  "reuters",
  "bloomberg",
  "financial times",
  "ft",
  "wall street journal",
  "wsj",
  "associated press",
  "ap",
  "afp",
  "agence france-presse",
  "nikkei",
  "cnbc",
  "economist",
  "new york times",
  "nyt",
  "washington post",
  "bbc",
  "dow jones",
];

/* Tier 2 — established trade/tech press, journals, and primary sources. */
const TIER_2: string[] = [
  // tech & business trade press
  "techcrunch",
  "verge",
  "ars technica",
  "wired",
  "ieee spectrum",
  "mit technology review",
  "technology review",
  "information", // The Information ("the " is stripped by normalization)
  "axios",
  "politico",
  "semafor",
  // sector desks
  "electrek",
  "insideevs",
  "cnevpost",
  "digitimes",
  "utility dive",
  "energy-storage.news",
  "energy storage news",
  "canary media",
  "coindesk",
  "defense news",
  "spacenews",
  "space news",
  "stat",
  "endpoints",
  "endpoints news",
  "fierce biotech",
  // journals & preprints
  "nature",
  "science",
  "arxiv",
  // company / agency / government announcements (primary sources)
  "press release",
  "business wire",
  "businesswire",
  "pr newswire",
  "globenewswire",
  ".gov",
  "sec",
  "fda",
  "doe",
  "epa",
  "nasa",
  "iea",
  "european commission",
  "white house",
  "department of",
  "ministry of",
];

/** Lowercase and strip URL decoration ("https://www.coindesk.com/x" → "coindesk.com")
 *  and a leading "the " — same normalization analytics/weights.py applies. */
function normalizeSource(name: string): string {
  let s = name.trim().toLowerCase();
  if (!s) return "";
  const scheme = s.split("//");
  s = scheme[scheme.length - 1]; // drop scheme
  if (s.startsWith("www.")) s = s.slice(4);
  s = s.split("/")[0]; // drop any path
  if (s.startsWith("the ")) s = s.slice(4);
  return s.replace(/^[\s.,'"]+|[\s.,'"]+$/g, "");
}

function escapeRegExp(term: string): string {
  return term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Whole-word substring matcher: "reuters" hits "reuters via yahoo", but the
 *  short token "ft" cannot fire inside "microsoft". */
function wordMatcher(terms: string[]): RegExp {
  const alts = terms.map(escapeRegExp).join("|");
  return new RegExp(`(^|[^a-z0-9])(${alts})([^a-z0-9]|$)`);
}

const TIER_1_RE = wordMatcher(TIER_1);
const TIER_2_RE = wordMatcher(TIER_2);

/** Tier for a free-text source name. Missing/empty names are tier 3 — an outlet
 *  we cannot identify is by definition unverified. */
export function sourceTier(name?: string | null): SourceTier {
  const n = normalizeSource(name ?? "");
  if (!n) return 3;
  if (TIER_1_RE.test(n)) return 1;
  if (TIER_2_RE.test(n)) return 2;
  return 3;
}

/** One-line explanation of the rubric — used by the caution chip's tooltip. */
export const TIER_TOOLTIP =
  `Source tiers — 1: ${TIER_LABELS[1]} (Reuters, Bloomberg, FT, WSJ, AP…); ` +
  `2: ${TIER_LABELS[2]} (established trade/tech press, journals, company/agency announcements); ` +
  `3: ${TIER_LABELS[3]} (not in the curated map — unverified, not necessarily wrong).`;
