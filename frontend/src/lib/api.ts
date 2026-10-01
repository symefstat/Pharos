/** Typed client for the Pharos API. Types mirror the payload assembled in
 *  backend/app/capital.py (which in turn mirrors analytics.financials /
 *  analytics.mot_analyst output). */

export interface TopRD {
  entity: string;
  pct: number;
}
export interface BiggestReaction {
  company: string;
  pct: number;
}
export interface Kpis {
  deals: number;
  commitment: number;
  option: number;
  ratio: string;
  top_rd: TopRD | null;
  biggest_reaction: BiggestReaction | null;
  total_market_cap: number;
}
export interface Posture {
  commitment: number;
  option: number;
  stance: string;
  maturity: string | null;
  flag: "aligned" | "over-extension" | "timid" | "low-confidence" | "none" | string;
  n: number;
}
export interface LandscapePoint {
  entity: string;
  sector: string;
  intensity: number;
  rd_pct: number;
  capex_pct: number;
  multiple: number;
  market_cap: number;
}
export interface SectorRow {
  sector: string;
  companies: number;
  market_cap: number;
  intensity: number | null;
  multiple: number | null;
  rd: number | null;
  commitment: number;
  option: number;
}
export interface ShareRow {
  sector: string;
  market_cap: number;
  share: number;
  delta: number | null;
}
export interface DealFlowRow {
  week: string;
  kind: "commitment" | "option";
  count: number;
}
export interface Move {
  title: string | null;
  feed: string | null;
  kind: string;
  url: string | null;
  companies: string[];
  published_at: string | null;
}
export interface Board {
  commitment: Move[];
  option: Move[];
  counts: { commitment: number; option: number; unclear: number };
  shown: number;
}
export interface ConcItem {
  feed?: string;
  entity?: string;
  count: number;
}
export interface Concentration {
  total: number;
  by_feed: ConcItem[];
  by_entity: ConcItem[];
}
export interface Reaction {
  company: string;
  symbol: string;
  title: string | null;
  url: string | null;
  feed: string | null;
  pct: number;
  direction: "up" | "down" | "flat";
  event_date: string;
  base_date: string;
  post_date: string;
}
export interface Divergence {
  confirmed: Reaction[];
  shrugged: Reaction[];
  n: number;
  n_confirmed: number;
  n_shrugged: number;
  divergence_rate: number | null;
}
export interface MSItem {
  title: string | null;
  feed: string | null;
  url: string | null;
  companies: string[];
  impact: string | null;
}
export interface MarketStructure {
  concentrating: MSItem[];
  regulatory: MSItem[];
  counts: { concentrating: number; regulatory: number };
}
export interface Scorecard {
  entity: string;
  symbol: string | null;
  sector: string | null;
  market_cap: number | null;
  revenue: number | null;
  rd_intensity: number | null;
  multiple: number | null;
  investment_intensity: number | null;
  cash: number | null;
  reaction: Reaction | null;
  signal: string;
  /** How rd_expense was obtained when it isn't the plain yfinance row, e.g.
   *  "curated-override (20-F FY2026)" (Toyota). Absent until the fx_asof
   *  migration lands the column. */
  rd_basis?: string | null;
}
export interface Coverage {
  mentions: number;
  tracked_mentions: number;
  untracked_mentions: number;
  coverage: number | null;
  tracked_entities: number;
  untracked_entities: number;
  top_untracked: [string, number][];
}

export interface CapitalPayload {
  have_fin: boolean;
  have_prices: boolean;
  row_count: number;
  /** As-of date + source of the FX rates behind the stored USD figures — dates
   *  the exhibit source captions. Null until migrations/2026-07-03_fx_asof.sql
   *  is applied and financials_run has written through it. */
  fx_as_of: string | null;
  fx_source: string | null;
  posture: Posture;
  kpis: Kpis | null;
  synthesis: string;
  board: Board;
  board_read: string;
  deal_flow: DealFlowRow[];
  concentration: Concentration;
  market_structure: MarketStructure;
  market_structure_read: string;
  coverage: Coverage;
  tracked_tickers: number;
  landscape: LandscapePoint[];
  sector_rollup: SectorRow[];
  market_cap_share: ShareRow[];
  companies: Scorecard[];
  reactions: Reaction[];
  divergence: Divergence | null;
  divergence_read: string | null;
}

/* ── Forecasts ─────────────────────────────────────────────────────────────── */
export interface TrackRecord {
  total: number;
  open: number;
  resolved: number;
  /** Resolved price calls held out of the pooled headline (scored in their own category). */
  quarantined_resolved: number;
  hits: number;
  misses: number;
  partials: number;
  accuracy: number | null;
  brier: number | null;
  /** Naive-baseline comparison, same resolved population as accuracy/brier.
   *  Observed hit share among resolved (hit=1, partial=0.5, miss=0). */
  base_rate: number | null;
  /** "Always predict the majority outcome" → max(p, 1−p). */
  baseline_accuracy: number | null;
  /** "Always forecast the base rate" (climatology) → p·(1−p). */
  baseline_brier: number | null;
  /** 1 − brier/baseline_brier; null when the outcome never varies (no test yet). */
  brier_skill: number | null;
  /** accuracy − baseline_accuracy, in percentage points. */
  accuracy_edge_pp: number | null;
}
export interface CategoryRow extends TrackRecord {
  category: string;
  /** What this category is graded against: "external" (public world events —
   *  independently verifiable), "internal" (Pharos's own future labels — a
   *  consistency measure), or "quarantined" (price direction). */
  basis?: "external" | "internal" | "quarantined" | string;
}

/** External (world-graded, citable) vs internal (self-referential) split. */
export interface RecordsByBasis {
  external: TrackRecord;
  internal: TrackRecord;
}
export interface CalBin {
  band: string;
  predicted: number;
  actual: number;
  n: number;
}
export interface HeadlineCat extends CategoryRow {
  verdict: string;
}
export interface Headline extends TrackRecord {
  state: string;
  verdict: string;
  categories: HeadlineCat[];
  /** World-graded (external) cut — while `resolved` here is 0, the pooled
   *  accuracy/Brier above are internal-consistency numbers and must be
   *  labelled as such wherever they render. */
  external?: {
    resolved: number;
    open: number;
    hits: number;
    misses: number;
    accuracy: number | null;
    brier: number | null;
  };
}
export interface OpenRow {
  Category: string;
  Forecast: string;
  "Conf %": number;
  Horizon: string;
  "Resolve by": string;
  Type: string;
}
export interface HeroCall {
  claim: string | null;
  confidence: number;
  category: string;
  resolve_by: string | null;
  horizon: string | null;
}
export interface OverdueCall {
  id: number;
  claim: string | null;
  confidence: number;
  category: string;
  resolve_by: string | null;
}
export interface ResolvedRow {
  id: number;
  claim: string | null;
  outcome: "hit" | "miss" | "partial" | string;
  made_on: string | null;
  resolved_on: string | null;
  resolution_note: string | null;
  confidence: number;
  category: string;
}
export interface ForecastsPayload {
  summary: string;
  track_record: TrackRecord;
  records_by_basis: RecordsByBasis;
  categories: CategoryRow[];
  calibration_bins: CalBin[];
  calibration_verdict: string;
  open_table: OpenRow[];
  hero: HeroCall[];
  overdue: OverdueCall[];
  resolved: ResolvedRow[];
}

/* ── Home (landing page) — one cheap cached payload ────────────────────────── */
export interface HomeToday {
  as_of: string | null;
  bottom_line: string;
  confidence: string | null;
  signal_count: number;
  top_signal: string | null;
}
export interface HomeTechExample {
  tech: string;
  label: string;
  domain: string;
  maturity: string | null;
  articles: number;
}
export interface HomeRadarExample {
  label: string;
  status: string;
  mentions: number;
  sources: number;
  papers: number;
  first_detected: string | null;
}
export interface HomePayload {
  radar_example?: HomeRadarExample | null;
  today: HomeToday | null;
  record: { external: TrackRecord; resolved: number; open: number; total: number };
  tech: { on_curve: number; watching: number; examples: HomeTechExample[] };
  pulse: { articles_7d: number; feeds_active: number };
  falsifier_events: number;
}

/** Candidate evidence that an open forecast's falsifier may have triggered —
 *  detection only, never an auto-resolution (grading stays human). */
export interface FalsifierEvent {
  id: number;
  pred_id: number;
  claim: string | null;
  falsifier: string | null;
  article_title: string | null;
  article_url: string | null;
  published_at: string | null;
  /** Vector cosine similarity, or keyword-overlap fraction (both 0..1). */
  score: number | null;
  detected_at: string | null;
}
export interface FalsifierEventsPayload {
  events: FalsifierEvent[];
  count: number;
}

/* ── Theses (the investor's private thesis book — admin-only API) ──────────── */
export interface Thesis {
  id: number;
  claim: string;
  falsifier: string;
  confirmer: string | null;
  created_at: string | null;
}
/** Candidate evidence that a thesis's confirmer/falsifier matched fresh news —
 *  detection only; the admin reviews it (nothing changes the thesis itself). */
export interface ThesisEvent {
  id: number;
  thesis_id: number;
  claim: string | null;
  /** The falsifier|confirmer text as matched (snapshot). */
  matched: string | null;
  label: "confirms" | "falsifies" | string;
  article_title: string | null;
  article_url: string | null;
  published_at: string | null;
  /** Keyword-overlap fraction (0..1). */
  score: number | null;
  detected_at: string | null;
}
export interface ThesisEventsPayload {
  events: ThesisEvent[];
  count: number;
}

/* ── Public ledger ─────────────────────────────────────────────────────────── */
export interface LedgerRow {
  fingerprint: string | null;
  kind: string | null;
  category: string;
  subject: string | null;
  claim: string | null;
  made_on: string | null;
  resolve_by: string | null;
  resolved_on: string | null;
  status: "open" | "resolved";
  outcome: "hit" | "miss" | "partial" | string | null;
  confidence: number | null;
  horizon: string | null;
  /** Locked at creation for the calibrated event kinds (count or % move). */
  threshold: number | null;
  threshold_basis: string | null;
  /** Locked stage window for the stage-transition kinds. */
  from_stage: string | null;
  to_stage: string | null;
  /** The resolver's note — what actually graded this call. */
  evidence: string | null;
  /** Held out of the pooled headline; scored in its own category. */
  quarantined: boolean;
}
export interface LedgerTech {
  tech: string;
  label: string;
  domain: string | null;
  /** The anchored display stage; null when out of the current news window. */
  current_stage: string | null;
  anchored: boolean;
  open: LedgerRow[];
  resolved: LedgerRow[];
}
export interface LedgerPayload {
  generated_at: string;
  /** sha256 hex of the canonical JSON of `forecasts` — see digest_recipe. */
  ledger_digest: string;
  digest_recipe: string;
  /** Recent daily digest anchors (append-only chain, newest first). */
  digest_history?: { as_of: string; digest: string; row_count: number }[];
  digest_note?: string;
  stats: Headline;
  records_by_basis: RecordsByBasis;
  categories: CategoryRow[];
  calibration_bins: CalBin[];
  forecasts: LedgerRow[];
  technologies: LedgerTech[];
  policy: {
    quarantined_kinds: string[];
    min_resolve_days: number;
    headline_accuracy_floor: number;
    internal_kinds_note?: string;
  };
}

/* ── Explore ───────────────────────────────────────────────────────────────── */
export interface FeedOpt {
  key: string;
  label: string;
}
export interface MomentumItem {
  feed: string;
  recent: number;
  prior: number;
  pct: number;
  thin: boolean;
}
export interface VoiceSlice {
  name: string;
  count: number;
  share: number;
  delta: number | null;
}
export interface NameCount {
  name: string;
  count: number;
}
export interface VolumePoint {
  date: string;
  feed: string;
  count: number;
}
export interface SentimentPoint {
  date: string;
  positive: number;
  negative: number;
  neutral: number;
  net: number;
  // Index signature so the array is assignable to the chart helpers'
  // Record<string, unknown>[] params (seriesTable / TimeSeries).
  [key: string]: number | string;
}
export interface TrendsPayload {
  feeds: FeedOpt[];
  feed: string;
  multi: boolean;
  weighted: boolean;
  empty: boolean;
  headline: string;
  kpis: {
    articles: number;
    net: number;
    pos: number;
    neg: number;
    /** Solid base → {pct, thin:false}; every feed thin → biggest absolute riser
     *  with raw counts ({recent, prior, thin:true}) — a % would be an artifact. */
    leader:
      | { feed: string; pct: number; thin: false }
      | { feed: string; recent: number; prior: number; thin: true }
      | null;
    /** Aggregate recent-vs-prior-half volume; `thin` = prior half too small for
     *  the % to be trustworthy (headline swaps in low-base wording). */
    volume_trend: { recent: number; prior: number; pct: number; thin: boolean };
  };
  momentum: MomentumItem[];
  voice: { slices: VoiceSlice[]; total: number; n_entities: number };
  volume: VolumePoint[];
  sentiment: SentimentPoint[];
  breakdowns: Record<string, NameCount[]>;
}
export interface Story {
  title?: string;
  url?: string;
  summary?: string;
  sentiment?: string;
  companies?: string[];
  tags?: string[];
  image_url?: string | null;
  business_impact?: string;
  source_name?: string;
  _feed_label?: string;
  feed_label?: string;
  published_at?: string;
  [k: string]: unknown;
}
export interface EntityProfile {
  entity: string;
  read: string;
  weighted: number;
  total: number;
  feeds_count: number;
  sentiment: Record<string, number>;
  by_feed: Record<string, number>;
  series: VolumePoint[];
  co_mentions: NameCount[];
  stories: Story[];
}
export interface TechItem {
  label: string;
  domain: string;
  maturity: string;
  adoption: string;
  articles: number;
  entrants: number;
  move: string;
  scurve: number | null;
}

/* ── MOT Analyst ───────────────────────────────────────────────────────────── */
export interface TechPoint {
  /** registry key (technologies.py) — stable identity, used by the dossier export */
  tech: string | null;
  label: string;
  domain: string;
  maturity: string;
  adoption: string;
  move: string;
  articles: number;
  entrants: number;
  coverage: number;
  x: number | null;
  mixed: boolean;
  on_curve: boolean;
  ax: number | null;
  adoption_coverage: number;
  adoption_mixed: boolean;
  on_adoption_curve: boolean;
  regime: string | null;
  /* world-truth overlay: coverage floor + curated anchors + taxonomy fit */
  thin_signal: boolean;
  /* evidence floor: too few stage articles to place — table row only, no dot */
  watching: boolean;
  anchored: boolean;
  maturity_anchored: boolean;
  adoption_anchored: boolean;
  news_maturity: string | null;
  news_adoption: string | null;
  anchor_as_of: string | null;
  lifecycle_fit: boolean;
  lifecycle_note: string | null;
  /** Self-serve tracked technology (tracked_technologies row) — archivable. */
  is_custom?: boolean;
  /* per-curve view fields set by the Mot page when mapping onto a curve */
  curve_anchored?: boolean;
  news_stage?: string | null;
  /* ghost dot (frontend-derived): below the evidence floor this window —
     placed at its last recorded stage from the stage-history table */
  ghost?: boolean;
  ghost_as_of?: string | null;
}
export interface Seam {
  domains: [string, string];
  bridges: { entity: string; mentions: number; feeds?: Record<string, number> }[];
  n_bridges: number;
  strength?: number;
}
export interface CoMatrix {
  labels: string[];
  domains: string[];
  matrix: number[][];
}
export interface MotScorecard {
  entity: string;
  mentions: number;
  feeds: string[];
  questions: { q: string; a: string }[];
}
export interface BenchCurve {
  key: string;
  label: string;
  metric: string;
  unit: string;
  lower_is_better: boolean;
  note: string;
  series: { date: string; value: number }[];
}
export interface MeasuredCurve {
  tech_key: string;
  label: string;
  unit: string;
  series: { year: number; value: number }[];
  source: { org: string; publication: string; url: string; retrieved: string };
  direction_note: string;
}
export interface DiffusionPoint {
  stage: string;
  z: number;
  y: number;
  count: number;
  top: string;
  crossed: boolean;
}
export interface MoveCell {
  maturity: string;
  move: string;
  count: number;
}
export interface Transition {
  technology: string;
  label: string;
  domain: string;
  dimension: string;
  from: string;
  to: string;
  as_of: string | null;
  contested: boolean;
  modal_share: number | null;
  backward: boolean;
  confirmed: boolean;
  suspect: boolean;
}
/** One dated standards-battle read harvested from a Strategist brief. */
export interface StandardsObservation {
  as_of: string | null;
  leader: string;
  basis: string[];
  read: string;
  title: string;
}
/** A contested standard's timeline: who leads, on which of the four factors
 *  (installed base / complementary goods / openness / timing), over time. */
export interface StandardsBattle {
  battle: string;
  observations: StandardsObservation[];
  current_leader: string | null;
  factor_counts: Record<string, number>;
  first_seen: string | null;
  last_seen: string | null;
  leader_changes: number;
  single_observation: boolean;
}
/** One run of consecutive daily snapshots holding the same lifecycle stage. */
export interface StageSegment {
  stage: string;
  from: string;
  to: string;
  snapshots: number;
}
/** A technology's long-run stage record (never-pruned daily snapshots, RLE). */
export interface TechStageHistory {
  tech: string;
  label: string;
  domain: string | null;
  maturity: StageSegment[];
  adoption: StageSegment[];
  first_seen: string;
  last_seen: string;
  snapshots: number;
}
export interface StageHistoryPayload {
  days: number;
  from: string;
  to: string;
  maturity_order: string[];
  adoption_order: string[];
  technologies: TechStageHistory[];
  note: string;
}
export interface MotPayload {
  feeds: FeedOpt[];
  scope: string;
  classified: number;
  total: number;
  scurve_interpret: string;
  technologies: TechPoint[];
  evidence_floor: number;
  maturity_order: string[];
  adoption_order: string[];
  diffusion: DiffusionPoint[];
  diffusion_interpret: string;
  moves: MoveCell[];
  move_order: string[];
  move_interpret: string;
  transitions: Transition[];
  /** Standards battles harvested from the Strategist brief history. */
  standards: StandardsBattle[];
  /** Valid domain labels for the self-serve technology-tracking form. */
  tech_domains: string[];
  convergence: Seam[];
  convergence_interpret: string;
  comatrix: CoMatrix;
  scorecards: MotScorecard[];
  performance_curves: BenchCurve[];
  adoption_curves: BenchCurve[];
  measured_curves: MeasuredCurve[];
  browse: Story[];
}

/* ── Briefing ──────────────────────────────────────────────────────────────── */
export interface Signal {
  title: string;
  implication: string;
  lens?: string;
  impact?: string;
  confidence?: string;
  action?: string;
  action_rationale?: string;
  value_capture?: string;
  standards?: { leader?: string; basis?: string[]; read?: string };
  falsifier?: string;
  sources?: string[];
  horizon?: string;
  /** Tracked technologies this signal is about — dossier door chips (≤2). */
  techs?: { key: string; label: string }[];
  /** Decision owner lifted from the rationale's addressee clause (serve-time). */
  owner?: string | null;
  /** Which persona the signal addresses: strategy | investment | both. */
  persona?: string;
}
export interface Convergence {
  theme: string;
  feeds?: string[];
  implication: string;
  sources?: string[];
}
export interface WatchItem {
  item: string;
  why: string;
  horizon?: string;
}
export interface StrategistRead {
  format?: string;
  bottom_line?: string;
  confidence?: string;
  signals?: Signal[];
  convergence?: Convergence[];
  watch?: WatchItem[];
  scenarios?: { base?: string; bull?: string; bear?: string };
}
export interface PortfolioItem {
  action: string;
  count: number;
  titles: string[];
}
export interface Strategist {
  as_of: string | null;
  focus: string | null;
  window_days: number | null;
  read: StrategistRead;
  portfolio: PortfolioItem[];
  stories: Story[];
}
export interface WatchlistItem {
  id: number;
  kind: string;
  value: string;
}
/** A watched entity's recent strategic move (Phase 3 🏢) — the lens tagged a
 *  story about the entity with a move classification (GET /api/watchlist `moves`). */
export interface WatchlistMove {
  entity: string;
  move: string;
  title?: string | null;
  url?: string | null;
  feed?: string | null;
  published_at?: string | null;
  impact?: string | null;
}
/** GET /api/watchlist item — the management view of a tracked term. */
export interface WatchlistEntry {
  id: number | null;
  kind: string;
  term: string;
  label: string;
  added_on: string | null;
  /** Recent strategic moves (last 7d) when kind === "entity"; additive field. */
  moves?: WatchlistMove[];
}
/** GET /api/briefing/since — what landed after the visitor's last-visit ts. */
export interface SinceCounts {
  resolved: number;
  transitions: number;
}
export interface WatchlistAlert {
  type: string;
  subject: string;
  detail?: string;
  feed?: string;
  title?: string;
  url?: string;
}
export interface FeedHealth {
  label: string;
  icon: string;
  key: string;
  has_key: boolean;
  rows: number;
  classified: number | null;
  last_fetched: string | null;
  last_rollup: string | null;
}
export interface PulseStats {
  total: number;
  material: number;
  sentiment: Record<string, number>;
  per_feed: Record<string, number>;
  top_companies_weighted?: [string, number][];
  top_companies?: [string, number][];
}
export interface BriefingRadarItem {
  key: string;
  label: string;
  why: string;
  mentions: number;
  sources: number;
  papers: number;
  research_stage: boolean;
  first_detected: string | null;
}
export interface BriefingPayload {
  calibration: { headline: Headline; tagline: string };
  strategist: Strategist | null;
  watchlist: { items: WatchlistItem[]; alerts: WatchlistAlert[] };
  pulse: { stats: PulseStats; top_stories: Story[]; health: FeedHealth[] };
  radar?: BriefingRadarItem[];
}

/* ── Feeds & Ask ───────────────────────────────────────────────────────────── */
export interface FeedGroup {
  key: string;
  label: string;
  icon: string;
  count: number;
  stories: Story[];
}
export interface FeedsPayload {
  feeds: FeedGroup[];
}
export interface AskSource {
  label?: string;
  title?: string;
  url?: string;
  feed?: string;
  source_file?: string;
  similarity?: number;
}
export interface AskResponse {
  configured: boolean;
  answer: string;
  thinking?: string;
  stories: AskSource[];
  theory: AskSource[];
}

/** SSE events streamed by POST /api/ask/stream. */
export type AskEvent =
  | { type: "stage"; label: string }
  | { type: "meta"; stories: AskSource[]; theory: AskSource[] }
  | { type: "tick"; elapsed: number }
  | {
      type: "done";
      configured?: boolean;
      answer: string;
      thinking?: string;
      stories: AskSource[];
      theory: AskSource[];
    }
  | { type: "error"; message: string };

/* ── Prosus ────────────────────────────────────────────────────────────────── */
export interface ProsusCompany {
  slug: string;
  name: string;
  aliases: string[];
  segment: string;
  tier: "core" | "ventures" | string;
  regions: string[];
  ownership: string | null;
  status: "active" | "exited" | string;
  notes: string | null;
}
export interface ProsusCount {
  key: string;
  label: string;
  count: number;
}
export interface ProsusStory extends Story {
  country?: string | null;
  region?: string;
  prosus_tags?: string[];
  scope?: string;
  _feed_key?: string;
  _feed_icon?: string;
}
export interface ProsusForecast {
  claim: string | null;
  subject: string | null;
  status: "open" | "resolved" | string;
  outcome: string | null;
  confidence: number | null;
  made_on: string | null;
  resolve_by: string | null;
  prosus_tags: string[];
  [k: string]: unknown;
}
export interface ProsusPayload {
  configured: boolean;
  companies: ProsusCompany[];
  segments: ProsusCount[];
  regions: ProsusCount[];
  stories: ProsusStory[];
  total_stories: number;
  forecasts: ProsusForecast[];
}

/* ── Actions (agent-triggering background jobs) ────────────────────────────── */
export interface JobStep {
  msg: string;
  ok: boolean;
}
export interface Job {
  id: string;
  kind: string;
  status: "running" | "done" | "error";
  steps: JobStep[];
  error: string | null;
  started: number;
  finished: number | null;
}

// In prod the SPA and API live on different origins (e.g. Render static site +
// web service), so prefix every request with VITE_API_URL. Left empty in dev,
// where the Vite proxy / same-origin serves /api directly.
const API_BASE: string = import.meta.env.VITE_API_URL ?? "";
/* ── Technology Dossier (/tech/:key) ──────────────────────────────────────────── */
export interface DossierForecast {
  kind: string | null;
  claim: string | null;
  confidence: number | null;
  horizon: string | null;
  made_on: string | null;
  resolve_by: string | null;
  falsifier: string | null;
  outcome: string | null;
  resolved_on: string | null;
  evidence: string | null;
}
export interface DossierCapitalMove {
  title: string | null;
  feed: string | null;
  kind: "commitment" | "option" | "unclear";
  url: string | null;
  companies: string[];
  published_at: string | null;
}
export interface RadarStory {
  title: string;
  url: string | null;
  source: string | null;
  date: string | null;
}
export interface RadarCandidate {
  key: string;
  label: string;
  keywords: string[];
  domain_hint: string | null;
  why: string | null;
  evidence: {
    mentions: number;
    sources: number;
    feeds: string[];
    first_seen: string;
    last_seen: string;
    stories: RadarStory[];
    /* research stream (Radar v2) — absent on rows scanned before it shipped */
    papers?: number;
    research_stage?: boolean;
    paper_items?: RadarStory[];
    /* directed scans (Radar v3): the analyst's brief that surfaced this row */
    found_via?: string;
    /* graded detection call locked at promotion (Radar v5) */
    ledger_pred_id?: number;
    /* dismissal-with-memory (Radar v6): set when a dismissed candidate came back */
    resurfaced?: { was: number; now: number; dismissed_at?: string | null };
    dismissed_at?: string;
    dismissed_signal?: number;
    /* emergence-map extras (Radar v4) — absent on rows from earlier scans */
    weekly?: number[];
    adjacent?: { tech: string; label: string; n: number }[];
  };
  status: "new" | "dismissed" | "promoted" | string;
  first_detected: string;
  last_updated: string;
}
export interface TrackedCoord {
  tech: string;
  label: string;
  domain: string;
  stories: number;
  papers: number;
}
export interface RadarScan {
  at: string;
  brief: string | null;
  corpus: number;
  papers: number;
  proposed: number;
  surfaced: number;
  rejected: number;
  tracked_coords?: TrackedCoord[] | null;
}
export interface RadarPayload {
  candidates: RadarCandidate[];
  scout_configured: boolean;
  domains: string[];
  gate: { mentions: number; sources: number; spread_days: number; papers?: number };
  last_scan: RadarScan | null;
}
export interface RadarOrigin {
  first_detected: string | null;
  why: string | null;
  mentions: number;
  sources: number;
  papers: number;
  research_stage: boolean;
  found_via: string | null;
  ledger_pred_id: number | null;
}
export interface TechDossier {
  tech: string;
  label: string;
  domain: string;
  as_of: string;
  radar_origin?: RadarOrigin | null;
  placement: {
    maturity: string | null;
    adoption: string | null;
    watching: boolean;
    thin_signal: boolean;
    evidence: number;
    evidence_floor: number;
    anchored: boolean;
    anchor_as_of: string | null;
    lifecycle_fit: boolean;
    lifecycle_note: string | null;
  };
  /** Composed verdict paragraphs (markdown **bold** markers) — the analysis
   *  the page opens with; sections with nothing to say are omitted. */
  read: string[];
  /** Agent-written narrative (Dossier Analyst, cached per refresh) — rendered
   *  in place of `read` when present; null degrades to the deterministic read. */
  agent_read: { text: string; as_of: string } | null;
  players: { name: string; mentions: number }[];
  transitions: {
    dimension: string;
    from: string;
    to: string;
    as_of: string | null;
    contested: boolean;
    confirmed: boolean;
    backward: boolean;
  }[];
  open_forecasts: DossierForecast[];
  resolved_forecasts: DossierForecast[];
  stories: { title: string | null; date: string | null; source: string | null; url: string | null }[];
  capital: {
    commitment: DossierCapitalMove[];
    option: DossierCapitalMove[];
    counts: { commitment: number; option: number };
  };
  /** Funding-round signal — evidence independent of news classification.
   *  null until 'SQL Tables/funding_rounds.sql' is applied and rounds ingested. */
  funding: {
    window_days: number;
    rounds: number;
    total_usd: number;
    early: number;
    late: number;
    trajectory: { quarter: string; total_usd: number; rounds: number }[];
    latest: {
      company: string | null;
      round_type: string | null;
      amount_usd: number | null;
      announced_on: string | null;
      source_url: string | null;
    }[];
    read: string | null;
  } | null;
  measured_curve: {
    label: string | null;
    unit: string | null;
    series: { year: number; value: number }[];
    source: { org?: string; publication?: string; url?: string; retrieved?: string };
    direction_note: string | null;
  } | null;
  methodology: string;
}

/* ── Backtest study (Methodology page) ────────────────────────────────────────── */
export interface BacktestReport {
  key: string;
  label: string;
  window: [string, string];
  query: string;
  n_items: number;
  n_classified: number;
  quarters: { quarter: string; n: number; stage: string | null; modal_share: number | null }[];
  calls: { stage: string; quarter: string; evidence_n: number; modal_share: number | null }[];
  comparison: {
    stage: string;
    quarter: string;
    event: string;
    source: string;
    called_quarter: string | null;
    /** call − milestone in quarters; negative = called early; null = MISS. */
    lag_quarters: number | null;
    hit: boolean;
  }[];
  false_calls: { stage: string; quarter: string; evidence_n: number; modal_share: number | null }[];
  notes: string | null;
}
export interface BacktestPayload {
  reports: BacktestReport[];
  summary: { cases: number; milestones: number; hits: number; false_calls: number };
}

/* ── The Analyst — commissioned, ledger-gradable reports ─────────────────────── */
export interface AnalystPosture {
  posture: "invest" | "watch" | "partner" | "defend" | "avoid";
  addressee: string;
  confidence: number;
  falsifier: string;
  resolve_by: string;
}
export interface AnalystExhibits {
  mention_trend: { month: string; count: number }[];
  stage_table: {
    tech: string | null;
    label: string | null;
    maturity: string | null;
    adoption: string | null;
    watching: boolean;
    articles: number | null;
  }[];
  capital_split: { commitment: number; option: number };
  players: { name: string; mentions: number }[];
  funding: { rounds: number; early: number; late: number; read: string | null } | null;
}
export interface AnalystReportMeta {
  id: number;
  topic: string;
  posture: AnalystPosture;
  coverage: "adequate" | "thin";
  as_of: string;
  created_by: string;
  created_at: string;
  ledger_pred_id: number | null;
}
export interface AnalystReport extends AnalystReportMeta {
  report: string;
  exhibits: AnalystExhibits;
  citations: { label: string; title: string | null; url: string | null; feed: string | null; published_at: string | null }[];
  prompt_version: string;
}

export const apiUrl = (path: string): string => `${API_BASE}${path}`;

/* ── Admin auth token ──────────────────────────────────────────────────────────
 * The shared-admin bearer token gates the Prosus page and the agent-triggering
 * actions. It lives in sessionStorage, so it dies when the browser tab closes
 * ("until logout / browser close"). A 401 on any request drops it and fires
 * `AUTH_EVENT`, which the AuthProvider listens for to log the UI out. */
const TOKEN_KEY = "lodestar-auth-token";
export const AUTH_EVENT = "lodestar-auth-changed";

export const getToken = (): string | null => sessionStorage.getItem(TOKEN_KEY);

function setToken(token: string | null): void {
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
  window.dispatchEvent(new Event(AUTH_EVENT));
}
export const clearToken = (): void => setToken(null);

const authHeaders = (): Record<string, string> => {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
};

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(apiUrl(url), {
    headers: { Accept: "application/json", ...authHeaders() },
  });
  if (res.status === 401) {
    clearToken();
    throw new Error(`401 Unauthorized — ${url}`);
  }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${url}`);
  return res.json() as Promise<T>;
}

export const api = {
  capital: () => getJSON<CapitalPayload>("/api/capital"),
  forecasts: () => getJSON<ForecastsPayload>("/api/forecasts"),
  falsifierEvents: () => getJSON<FalsifierEventsPayload>("/api/forecasts/falsifier-events"),
  ledger: () => getJSON<LedgerPayload>("/api/ledger"),
  resolveForecast: async (
    pred_id: number,
    outcome: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const res = await fetch(apiUrl("/api/forecasts/resolve"), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ pred_id, outcome }),
    });
    if (res.status === 401) clearToken();
    const body = (await res.json().catch(() => ({}))) as {
      ok?: boolean;
      error?: string;
      detail?: string; // FastAPI HTTPException payload (guard rejections: 400/404/409)
    };
    if (!res.ok) {
      return { ok: false, error: body.detail ?? body.error ?? `${res.status} ${res.statusText}` };
    }
    return { ok: body.ok ?? false, error: body.error };
  },
  exploreTrends: (days: number, feed: string, weighted: boolean) =>
    getJSON<TrendsPayload>(`/api/explore/trends?days=${days}&feed=${feed}&weighted=${weighted}`),
  exploreEntities: (days: number) =>
    getJSON<{ universe: NameCount[] }>(`/api/explore/entities?days=${days}`),
  exploreEntity: (name: string, days: number) =>
    getJSON<EntityProfile>(`/api/explore/entity?name=${encodeURIComponent(name)}&days=${days}`),
  exploreTechnologies: () => getJSON<{ technologies: TechItem[] }>("/api/explore/technologies"),
  mot: (scope: string) => getJSON<MotPayload>(`/api/mot?scope=${encodeURIComponent(scope)}`),
  motHistory: (days: number) => getJSON<StageHistoryPayload>(`/api/mot/history?days=${days}`),
  techDossier: (key: string) => getJSON<TechDossier>(`/api/mot/tech/${encodeURIComponent(key)}`),
  methodologyBacktest: () => getJSON<BacktestPayload>("/api/methodology/backtest"),
  analystReports: () => getJSON<{ reports: AnalystReportMeta[] }>("/api/analyst"),
  analystReport: (id: number) => getJSON<AnalystReport>(`/api/analyst/${id}`),
  analystCommission: async (topic: string): Promise<{ ok: boolean; job?: string; error?: string }> => {
    const res = await fetch(apiUrl("/api/analyst"), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ topic }),
    });
    if (res.status === 401) clearToken();
    const body = (await res.json().catch(() => ({}))) as { id?: string; detail?: string };
    if (!res.ok) return { ok: false, error: body.detail ?? `${res.status} ${res.statusText}` };
    return { ok: true, job: body.id };
  },
  analystAsk: async (
    id: number,
    question: string,
    history: { role: string; content: string }[],
  ): Promise<{ ok: boolean; answer?: string; error?: string }> => {
    const res = await fetch(apiUrl(`/api/analyst/${id}/ask`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history }),
    });
    const body = (await res.json().catch(() => ({}))) as { answer?: string; detail?: string };
    if (!res.ok) return { ok: false, error: body.detail ?? `${res.status} ${res.statusText}` };
    return { ok: true, answer: body.answer };
  },
  analystLogCall: async (id: number): Promise<{ ok: boolean; pred_id?: number; error?: string }> => {
    const res = await fetch(apiUrl(`/api/analyst/${id}/log-call`), {
      method: "POST",
      headers: { ...authHeaders() },
    });
    if (res.status === 401) clearToken();
    const body = (await res.json().catch(() => ({}))) as { pred_id?: number; detail?: string };
    if (!res.ok) return { ok: false, error: body.detail ?? `${res.status} ${res.statusText}` };
    return { ok: true, pred_id: body.pred_id };
  },
  briefing: () => getJSON<BriefingPayload>("/api/briefing"),
  briefingSince: (ts: string) =>
    getJSON<SinceCounts>(`/api/briefing/since?ts=${encodeURIComponent(ts)}`),
  home: () => getJSON<HomePayload>("/api/home"),

  /* ── Watchlist management (read public; writes admin-gated) ──────────────── */
  watchlist: () => getJSON<{ items: WatchlistEntry[] }>("/api/watchlist"),
  addWatch: async (
    term: string,
  ): Promise<{ ok: boolean; error?: string; item?: { kind: string; term: string } }> => {
    const res = await fetch(apiUrl("/api/watchlist"), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ term }),
    });
    if (res.status === 401) clearToken();
    const body = (await res.json().catch(() => ({}))) as {
      ok?: boolean;
      detail?: string;
      item?: { kind: string; term: string };
    };
    if (!res.ok) return { ok: false, error: body.detail ?? `${res.status} ${res.statusText}` };
    return { ok: body.ok ?? false, item: body.item };
  },
  removeWatch: async (term: string): Promise<{ ok: boolean; error?: string }> => {
    const res = await fetch(apiUrl(`/api/watchlist/${encodeURIComponent(term)}`), {
      method: "DELETE",
      headers: { ...authHeaders() },
    });
    if (res.status === 401) clearToken();
    const body = (await res.json().catch(() => ({}))) as { ok?: boolean; detail?: string };
    if (!res.ok) return { ok: false, error: body.detail ?? `${res.status} ${res.statusText}` };
    return { ok: body.ok ?? false };
  },
  /* ── Radar (horizon scanning; read public, status writes admin-gated) ────── */
  radar: () => getJSON<RadarPayload>("/api/radar"),
  radarSetStatus: async (
    key: string,
    status: "new" | "dismissed" | "promoted",
  ): Promise<{ ok: boolean; error?: string }> => {
    const res = await fetch(apiUrl(`/api/radar/${encodeURIComponent(key)}/status`), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ status }),
    });
    if (res.status === 401) clearToken();
    const body = (await res.json().catch(() => ({}))) as { ok?: boolean; detail?: string };
    if (!res.ok) return { ok: false, error: body.detail ?? `${res.status} ${res.statusText}` };
    return { ok: body.ok ?? false };
  },
  /* ── Self-serve technology tracking (writes admin-gated) ─────────────────── */
  trackTechnology: async (
    label: string,
    domain: string,
    keywords: string[],
  ): Promise<{ ok: boolean; error?: string; technology?: { key: string; label: string } }> => {
    const res = await fetch(apiUrl("/api/mot/technologies"), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ label, domain, keywords }),
    });
    if (res.status === 401) clearToken();
    const body = (await res.json().catch(() => ({}))) as {
      ok?: boolean;
      detail?: string;
      technology?: { key: string; label: string };
    };
    if (!res.ok) return { ok: false, error: body.detail ?? `${res.status} ${res.statusText}` };
    return { ok: body.ok ?? false, technology: body.technology };
  },
  archiveTechnology: async (key: string): Promise<{ ok: boolean; error?: string }> => {
    const res = await fetch(apiUrl(`/api/mot/technologies/${encodeURIComponent(key)}`), {
      method: "DELETE",
      headers: { ...authHeaders() },
    });
    if (res.status === 401) clearToken();
    const body = (await res.json().catch(() => ({}))) as { ok?: boolean; detail?: string };
    if (!res.ok) return { ok: false, error: body.detail ?? `${res.status} ${res.statusText}` };
    return { ok: body.ok ?? false };
  },
  /* ── Theses (private thesis book — every call admin-gated) ───────────────── */
  theses: () => getJSON<{ theses: Thesis[] }>("/api/theses"),
  thesisEvents: () => getJSON<ThesisEventsPayload>("/api/theses/events"),
  addThesis: async (
    claim: string,
    falsifier: string,
    confirmer?: string,
  ): Promise<{ ok: boolean; error?: string; thesis?: Thesis }> => {
    const res = await fetch(apiUrl("/api/theses"), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ claim, falsifier, confirmer: confirmer || null }),
    });
    if (res.status === 401) clearToken();
    const body = (await res.json().catch(() => ({}))) as {
      ok?: boolean;
      detail?: string;
      thesis?: Thesis;
    };
    if (!res.ok) return { ok: false, error: body.detail ?? `${res.status} ${res.statusText}` };
    return { ok: body.ok ?? false, thesis: body.thesis };
  },
  archiveThesis: async (id: number): Promise<{ ok: boolean; error?: string }> => {
    const res = await fetch(apiUrl(`/api/theses/${id}`), {
      method: "DELETE",
      headers: { ...authHeaders() },
    });
    if (res.status === 401) clearToken();
    const body = (await res.json().catch(() => ({}))) as { ok?: boolean; detail?: string };
    if (!res.ok) return { ok: false, error: body.detail ?? `${res.status} ${res.statusText}` };
    return { ok: body.ok ?? false };
  },
  feeds: () => getJSON<FeedsPayload>("/api/feeds"),
  prosus: () => getJSON<ProsusPayload>("/api/prosus?days=30"),
  ask: (question: string, history: { role: string; content: string }[]) =>
    fetch(apiUrl("/api/ask"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history }),
    }).then((r) => r.json() as Promise<AskResponse>),
  /** Stream the answer via SSE, invoking `onEvent` for each parsed event. */
  askStream: async (
    question: string,
    history: { role: string; content: string }[],
    onEvent: (ev: AskEvent) => void,
  ): Promise<void> => {
    const res = await fetch(apiUrl("/api/ask/stream"), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ question, history }),
    });
    if (!res.ok || !res.body) {
      onEvent({ type: "error", message: `${res.status} ${res.statusText}` });
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let sep;
      // SSE frames are separated by a blank line.
      while ((sep = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, sep);
        buf = buf.slice(sep + 2);
        const line = frame.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        try {
          onEvent(JSON.parse(line.slice(5).trim()) as AskEvent);
        } catch {
          /* ignore malformed frame */
        }
      }
    }
  },
  runActionByPath: async (path: string, body?: unknown) => {
    const res = await fetch(apiUrl(path), {
      method: "POST",
      headers: body != null ? { "Content-Type": "application/json", ...authHeaders() } : { ...authHeaders() },
      body: body != null ? JSON.stringify(body) : undefined,
    });
    if (res.status === 401) {
      clearToken();
      return { status: "error", error: "Your admin session expired — please log in again." };
    }
    return res.json() as Promise<{ job_id?: string; status: string; error?: string }>;
  },
  actionStatus: (jid: string) => getJSON<Job>(`/api/actions/status/${jid}`),
  motScorecardRead: (entity: string) =>
    getJSON<{ read: StrategistRead | null; as_of?: string; entity?: string }>(
      `/api/mot/scorecard-read?entity=${encodeURIComponent(entity)}`,
    ),
  health: () => getJSON<{ status: string; supabase_configured: boolean }>("/api/health"),
  refresh: () => fetch(apiUrl("/api/refresh"), { method: "POST" }).then((r) => r.json()),

  /* ── Admin auth ──────────────────────────────────────────────────────────── */
  login: async (
    username: string,
    password: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const res = await fetch(apiUrl("/api/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const body = (await res.json().catch(() => ({}))) as { token?: string; detail?: string };
    if (!res.ok || !body.token) {
      return { ok: false, error: body.detail ?? `${res.status} ${res.statusText}` };
    }
    setToken(body.token);
    return { ok: true };
  },
  me: () => getJSON<{ username: string }>("/api/auth/me"),
};
