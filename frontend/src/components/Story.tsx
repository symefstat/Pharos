import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import type { Story } from "../lib/api";
import { StoryLink, Badge } from "./ui";
import { cn } from "../lib/utils";
import { pubDate } from "../lib/format";

/* Sentiment is a STATE, so the dot wears status tokens (good / critical) with
   `--color-flat` for neutral — never a categorical slot (DESIGN.md §1.4). The
   dot never travels alone: list rows pair it with the sentiment word, compact
   rows carry it in the accessible title/aria text. */
const SENT: Record<string, string> = {
  positive: "var(--color-status-good)",
  negative: "var(--color-status-critical)",
  neutral: "var(--color-flat)",
};

function sentimentOf(story: Story): { word: string; color: string } {
  const raw = (story.sentiment ?? "neutral").toLowerCase();
  return { word: raw in SENT ? raw : "neutral", color: SENT[raw] ?? SENT.neutral };
}

/** Safely read an untyped (index-signature) string field off a story row. */
function strField(story: Story, key: string): string | undefined {
  const v = story[key];
  return typeof v === "string" && v.trim() ? v : undefined;
}

/* ── MOT chips ──────────────────────────────────────────────────────────────
   Compact labeled chips for the classifier's MOT dimensions. Every chip
   carries its dimension name + value as TEXT — never color alone. Values are
   nominal/ordinal facts, not series or states, so the chips stay neutral;
   the one emphasis ("material" impact) wears the brand tint, keeping status
   tokens reserved for good/bad and categorical slots for series identity. */
const MOT_FIELDS: Array<[key: string, label: string]> = [
  ["maturity_stage", "maturity"],
  ["adoption_stage", "adoption"],
  ["business_impact", "impact"],
  ["scope", "scope"],
];

export function MotChips({ story, className }: { story: Story; className?: string }) {
  const chips = MOT_FIELDS.flatMap(([key, label]) => {
    const value = strField(story, key);
    return value ? [{ label, value: value.replace(/[-_]/g, " ").toLowerCase() }] : [];
  });
  if (!chips.length) return null;
  return (
    <div className={cn("flex flex-wrap gap-1", className)}>
      {chips.map((c) => {
        const emphasis = c.label === "impact" && c.value === "material";
        return (
          <span
            key={c.label}
            className={cn(
              "inline-flex items-baseline gap-1 rounded-md px-1.5 py-0.5 text-[10.5px] leading-4",
              emphasis ? "bg-brand-soft" : "border border-line bg-canvas",
            )}
          >
            <span className={cn("font-medium", emphasis ? "text-brand" : "text-faint")}>{c.label}</span>
            <span className={cn("font-semibold", emphasis ? "text-brand-ink" : "text-ink-soft")}>{c.value}</span>
          </span>
        );
      })}
    </div>
  );
}

/** Sentiment as a small dot + word — the word carries the meaning, the dot
 *  reinforces it (never color alone). */
function SentimentTag({ story }: { story: Story }) {
  const { word, color } = sentimentOf(story);
  return (
    <span className="inline-flex items-center gap-1 text-muted">
      <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: color }} />
      {word}
    </span>
  );
}

// Stable gradient placeholder per feed — so a card without an image still has colour.
const GRADS = [
  ["#3a5cd0", "#6d8be8"],
  ["#18895a", "#4cb98a"],
  ["#c2410c", "#ef8b56"],
  ["#7c3aed", "#a779f0"],
  ["#0e7490", "#39a7c0"],
  ["#be185d", "#e8639b"],
];
function gradFor(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  const [a, b] = GRADS[h % GRADS.length];
  return `linear-gradient(135deg, ${a}, ${b})`;
}

function ArticleImage({ story, className }: { story: Story; className?: string }) {
  const [failed, setFailed] = useState(false);
  const feed = story._feed_label || story.feed_label || "";
  if (story.image_url && !failed) {
    return (
      <img
        src={story.image_url}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
        className={className}
      />
    );
  }
  // Fallback: a coloured gradient with the feed label, so every card is visual.
  return (
    <div
      className={`flex items-end ${className ?? ""}`}
      style={{ backgroundImage: gradFor(feed || story.title || "x") }}
    >
      <span className="p-2.5 text-[11px] font-medium text-white/90">{feed}</span>
    </div>
  );
}

/** Small right-aligned thumbnail for list rows — only when the story ships an
 *  image; silently absent otherwise (no placeholder noise in a dense list). */
function Thumb({ src }: { src: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <img
      src={src}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className="h-14 w-20 shrink-0 rounded-lg border border-line object-cover"
    />
  );
}

/** Compact one-line story: sentiment dot · linked title · feed · date. */
export function StoryRow({ story }: { story: Story }) {
  const feed = story._feed_label || story.feed_label;
  const { word, color } = sentimentOf(story);
  return (
    <li className="flex gap-2.5 py-2.5">
      <span
        className="mt-[5px] h-2 w-2 shrink-0 rounded-full"
        style={{ background: color }}
        title={`sentiment: ${word}`}
      />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] leading-snug">
          <StoryLink href={story.url}>{story.title}</StoryLink>
        </p>
        <p className="mt-0.5 text-[11.5px] text-faint">
          {feed}
          {story.published_at ? ` · ${pubDate(story.published_at)}` : ""}
        </p>
      </div>
    </li>
  );
}

/**
 * Scannable list row (Feeds tab): linked title · source + date muted ·
 * sentiment dot + word · MOT chips. Summary / companies / tags fold behind a
 * per-row expander — progressive disclosure per DESIGN.md §3, so a 48-story
 * list stays a scan, not a text wall.
 */
export function StoryListRow({
  story,
  showFeed = false,
  className,
}: {
  story: Story;
  /** Also name the feed in the meta line (off inside a single-feed list). */
  showFeed?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const feed = story._feed_label || story.feed_label;
  const source = story.source_name || (showFeed ? undefined : feed);
  const companies = story.companies ?? [];
  const tags = story.tags ?? [];
  const hasDetails = Boolean(story.summary || companies.length || tags.length);
  return (
    <li className={cn("flex gap-3 px-4 py-3 sm:px-5", className)}>
      <div className="min-w-0 flex-1">
        <p className="text-[13.5px] font-medium leading-snug">
          <StoryLink href={story.url}>{story.title}</StoryLink>
        </p>
        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-faint">
          {showFeed && feed && <span className="truncate">{feed}</span>}
          {source && <span className="truncate">{source}</span>}
          {story.published_at && <span>{pubDate(story.published_at)}</span>}
          <SentimentTag story={story} />
        </p>
        <MotChips story={story} className="mt-1.5" />
        {open && hasDetails && (
          <div className="mt-2 space-y-1 border-l-2 border-line pl-3">
            {story.summary && (
              <p className="max-w-3xl text-[12.5px] leading-relaxed text-muted">{story.summary}</p>
            )}
            {companies.length > 0 && (
              <p className="text-[11.5px] text-faint">Companies: {companies.join(", ")}</p>
            )}
            {tags.length > 0 && (
              <p className="text-[11.5px] text-faint">Tags: {tags.join(", ")}</p>
            )}
          </div>
        )}
      </div>
      {story.image_url && <Thumb src={story.image_url} />}
      {hasDetails && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          title={open ? "Hide details" : "Show summary"}
          className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center self-start rounded-md text-faint transition-colors hover:bg-canvas hover:text-ink"
        >
          {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          <span className="sr-only">{open ? "Hide details" : "Show details"}</span>
        </button>
      )}
    </li>
  );
}

/** Richer story card with image + summary (kept for API compatibility). */
export function StoryCard({ story }: { story: Story }) {
  const feed = story._feed_label || story.feed_label;
  const { word, color } = sentimentOf(story);
  const material = (story.business_impact ?? "").toLowerCase() === "material";
  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-line bg-surface transition-shadow hover:shadow-[0_4px_16px_rgba(20,24,29,0.08)]">
      <div className="relative h-36 w-full overflow-hidden bg-canvas">
        <ArticleImage story={story} className="h-full w-full object-cover" />
        {material && (
          <span className="absolute right-2 top-2">
            <Badge variant="brand">material</Badge>
          </span>
        )}
      </div>
      <div className="flex flex-1 flex-col p-4">
        <div className="mb-1.5 flex items-center gap-2">
          <span
            className="h-2 w-2 rounded-full"
            style={{ background: color }}
            title={`sentiment: ${word}`}
          />
          {feed && <span className="text-[11px] font-medium text-faint">{feed}</span>}
          {story.published_at && (
            <span className="text-[11px] text-faint">· {pubDate(story.published_at)}</span>
          )}
        </div>
        <p className="text-[13.5px] font-medium leading-snug">
          <StoryLink href={story.url}>{story.title}</StoryLink>
        </p>
        {story.summary && (
          /* No line-clamp: summaries are single sentences by contract (the
             extractor writes exactly one), so showing them whole is bounded —
             and a summary cut mid-sentence reads as a bug, not a design. */
          <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">{story.summary}</p>
        )}
      </div>
    </div>
  );
}
