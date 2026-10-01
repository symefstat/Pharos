/* ── Glossary — one-line glosses for MOT / forecasting terms ────────────────────
   The Methodology page explains everything at length, but nobody leaves a chart
   mid-read to find a definition. These power `title` tooltips (the pattern
   already used for sourcing-tier and mandate chips) wherever a term of art
   appears on a badge, KPI label, or section heading. Keep each gloss to one
   plain-English sentence — it renders as a native browser tooltip. */

export const GLOSSARY: Record<string, string> = {
  // MOT lenses / strategic moves (Briefing signal badges, MOT matrix)
  "market-structure shift":
    "The industry's shape is changing — who holds pricing power, who consolidates, who exits.",
  "market-failure regulation":
    "Government is rewriting the rules of the game — the constraint is regulatory, not technical.",
  appropriability:
    "Who actually captures the profit from an innovation — via patents, secrecy, or control of scarce complementary assets.",
  "platform play":
    "Building an installed base others must plug into, so network effects and switching costs do the defending.",
  "standards battle":
    "Rival designs compete to become the industry default; installed base, complements, openness, and timing decide it.",
  "entry timing":
    "The first-mover vs fast-follower question — whether moving now beats waiting for the dominant design.",
  disruption:
    "A cheaper, initially-worse technology improving fast enough to overtake incumbents from below.",
  collaboration:
    "Allying, licensing, or partnering instead of competing head-on.",

  // Forecast scoring (Track record, Briefing banner)
  brier:
    "Accuracy score for probability forecasts: 0 is perfect, 0.25 is a 50/50 coin flip — lower is better.",
  calibration:
    "Whether stated confidence matches reality — of the calls made at 80%, roughly 80% should come true.",

  // Capital vocabulary
  "real option":
    "A small, reversible stake — a pilot, minority round, or partnership — that buys the right to commit later once uncertainty resolves.",
  commitment:
    "A large, hard-to-reverse bet — an acquisition or big capex — that only pays if the thesis is right now.",
  "commit:option":
    "Ratio of irreversible bets (acquisitions, big capex) to reversible ones (pilots, funding rounds, partnerships) — a read on how convinced capital is.",

  // Sourcing quality (Briefing source chips)
  "single-tier sourcing":
    "Every source cited for this signal is an unrecognized outlet — no wire, major, or trade press among them.",
};

/** Case/spacing-insensitive lookup; returns undefined when we have no gloss. */
export function glossFor(term: string | null | undefined): string | undefined {
  if (!term) return undefined;
  return GLOSSARY[term.trim().toLowerCase().replace(/[–—]/g, "-")];
}
