/* ── Mandate — client-side reader personalization ──────────────────────────────
   The Briefing's recommended actions address classes of reader ("if you are a
   payments processor…"), but the reader never told the system who they are.
   A Mandate is that one-time answer. It lives ONLY in localStorage — this is
   single-visitor personalization, not auth, and nothing is sent to a server.

   Matching is transparent keyword/domain overlap (no ML), so every badge can
   say exactly why it fired:
     +2 per domain match   — signal's source feeds ∩ mandate.domains
     +1 per interest match — comma-separated keyword found in title+implication
                             (case-insensitive; keywords under 3 chars ignored)
     +2 role match         — mandate.role tokens all appear in the action
                             rationale's addressee clause ("if you are a …")
   relevanceLabel: score ≥ 4 → "high", ≥ 1 → "some", else null.               */

export interface Mandate {
  /** Feed labels the reader cares about (e.g. "EV", "Fintech"). */
  domains: string[];
  /** Free-text keywords, comma-separated (e.g. "solid-state, LFP, sodium-ion"). */
  interests: string;
  /** Who the reader is, free text (e.g. "payments processor"). */
  role: string;
}

export const MANDATE_KEY = "lodestar-mandate";
export const MANDATE_HINT_KEY = "lodestar-mandate-hint-dismissed";

/** The feed labels defined in feeds.py — the domain vocabulary. */
export const DOMAIN_OPTIONS: string[] = [
  "EV",
  "AI & Energy",
  "Disruptive Tech",
  "Chips",
  "Geopolitics & Trade",
  "Climate & Energy",
  "Biotech & Health",
  "Software & Cyber",
  "Fintech",
  "Prosus",
  "Defense & Space",
];

export function isEmptyMandate(m: Mandate): boolean {
  return m.domains.length === 0 && !m.interests.trim() && !m.role.trim();
}

export function loadMandate(): Mandate | null {
  try {
    const raw = localStorage.getItem(MANDATE_KEY);
    if (!raw) return null;
    const p = JSON.parse(raw) as Partial<Mandate>;
    const m: Mandate = {
      domains: Array.isArray(p.domains) ? p.domains.filter((d) => typeof d === "string") : [],
      interests: typeof p.interests === "string" ? p.interests : "",
      role: typeof p.role === "string" ? p.role : "",
    };
    return isEmptyMandate(m) ? null : m;
  } catch {
    return null; // storage unavailable or corrupt — behave as "no mandate"
  }
}

export function saveMandate(m: Mandate): void {
  try {
    if (isEmptyMandate(m)) localStorage.removeItem(MANDATE_KEY);
    else localStorage.setItem(MANDATE_KEY, JSON.stringify(m));
  } catch {
    /* private mode — personalization simply won't persist */
  }
}

export function clearMandate(): void {
  try {
    localStorage.removeItem(MANDATE_KEY);
  } catch {
    /* ignore */
  }
}

/* ── Matching primitives ─────────────────────────────────────────────────────── */

/** Lowercased word tokens ≥3 chars. Hyphens split ("battery-materials" ~
 *  "battery materials") and trailing "s" is stripped so plurals compare equal
 *  ("payments" ~ "payment"). Purely mechanical — no stemming beyond that. */
export function tokenize(text: string): string[] {
  return (text.toLowerCase().replace(/[-–]/g, " ").match(/[a-z0-9]+/g) ?? [])
    .map((t) => (t.length > 3 && t.endsWith("s") ? t.slice(0, -1) : t))
    .filter((t) => t.length >= 3);
}

/** Comma-separated interests → cleaned lowercase keywords (≥3 chars each). */
export function interestKeywords(interests: string): string[] {
  return interests
    .split(",")
    .map((k) => k.trim().toLowerCase())
    .filter((k) => k.length >= 3);
}

/** The clause naming who an action is for, e.g. the "a payments processor"
 *  in "if you are a payments processor, lock in…". Empty when none found. */
export function extractAddressee(rationale: string): string {
  const m =
    rationale.match(/\bif you(?:'re| are)\s+([^.;:—]+)/i) ??
    rationale.match(/^\s*for\s+([^,.;:—]+)/i);
  return (m?.[1] ?? "").trim();
}

/** The minimal shape of a strategist signal that matching needs. */
export interface MatchableSignal {
  title?: string;
  implication?: string;
  action_rationale?: string;
}

export interface MandateMatch {
  score: number;
  /** Mandate domains that intersect the signal's source feeds. */
  domains: string[];
  /** Interest keywords found in the title + implication. */
  keywords: string[];
  /** True when the role matches the action rationale's addressee clause. */
  role: boolean;
}

/** Transparent overlap scoring — see the rules at the top of this file. */
export function matchSignal(
  signal: MatchableSignal,
  mandate: Mandate,
  feedsOfSignal: string[],
): MandateMatch {
  const feedSet = new Set(feedsOfSignal.map((f) => f.toLowerCase()));
  const domains = mandate.domains.filter((d) => feedSet.has(d.toLowerCase()));

  const haystack = `${signal.title ?? ""} ${signal.implication ?? ""}`.toLowerCase();
  const keywords = interestKeywords(mandate.interests).filter((k) => haystack.includes(k));

  const roleTokens = tokenize(mandate.role);
  const addresseeTokens = new Set(tokenize(extractAddressee(signal.action_rationale ?? "")));
  const role = roleTokens.length > 0 && roleTokens.every((t) => addresseeTokens.has(t));

  return {
    score: domains.length * 2 + keywords.length + (role ? 2 : 0),
    domains,
    keywords,
    role,
  };
}

export function scoreSignal(
  signal: MatchableSignal,
  mandate: Mandate,
  feedsOfSignal: string[],
): number {
  return matchSignal(signal, mandate, feedsOfSignal).score;
}

export function relevanceLabel(score: number): "high" | "some" | null {
  if (score >= 4) return "high";
  if (score >= 1) return "some";
  return null;
}

/** One-line human explanation for the badge tooltip. */
export function matchReason(m: MandateMatch): string {
  const parts: string[] = [];
  if (m.role) parts.push("the recommended action addresses your role");
  if (m.domains.length) parts.push(`domains: ${m.domains.join(", ")}`);
  if (m.keywords.length) parts.push(`keywords: ${m.keywords.join(", ")}`);
  return parts.length ? `Matches your mandate — ${parts.join("; ")}` : "";
}
