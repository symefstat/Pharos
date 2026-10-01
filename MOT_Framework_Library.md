# MOT Framework Library — Lodestar's analytical backbone

This is the **distilled theory** that should govern how Lodestar interprets the world.
It is not a user feature; it is the app's *brain* — the basis for the theory-grounded
analyst agent and the compass for narrowing what we track and how we score it.

Distilled from the ingested MOT (TU Delft, Management of Technology) corpus; source
documents are cited so claims stay faithful to the coursework, not generic recall.

**The core principle (the "narrowing"):** most news is noise. The theory tells us which
moments are *strategically decisive*. Lodestar should surface and interpret **those**,
and downrank the rest. Each development is read through the lenses below and tagged with
*where it sits, what move it represents, and whether it is a decisive inflection.*

---

## A. Technology lifecycle & change

### A1 — The S-curve (technology performance) — *Schilling, MOT132A/TD*
**Idea:** A technology's performance vs. cumulative effort follows an S-curve: slow start →
rapid improvement → diminishing returns as it nears physical limits. A *discontinuous*
technology starts a new S-curve on a new knowledge base. The true limit is unknown in
advance, so switching too early or too late both destroy value.
**Signals to watch:** performance plateauing in an incumbent technology; a new approach
improving fast off a low base; capex pouring into a maturing curve (over-investment signal).
**Analyst use:** locate each technology on its S-curve; flag *discontinuities* (a new curve
starting) as high-value — that's where incumbents get displaced.

### A2 — Dominant design & the technology cycle — *Anderson & Tushman 1990; Schilling Ch.3*
**Idea:** A discontinuity opens an **era of ferment** (many competing designs), which
resolves into a **dominant design** (a stable architecture most producers adopt), after
which competition shifts to incremental improvement and *cost/scale*. Adopters often wait
for the standard before buying.
**Signals to watch:** proliferation of incompatible approaches (ferment); convergence on one
architecture; a standard being declared; competition shifting from features to price/scale.
**Analyst use:** identify whether a market is pre- or post-dominant-design. *Pre* = land-grab,
standards risk; *post* = scale/cost game. The moment a dominant design locks in is decisive.

### A3 — Development–diffusion pattern & niche strategies — *Ortt & Schoormans 2004; MOT131A (Ortt)*
**Idea:** Radically new high-tech products move through **innovation → adaptation →
stabilization** phases. There is usually a long gap between invention/first market
introduction and *large-scale* diffusion. During the adaptation phase, firms survive via
**early niches** (small applications where the immature tech is already good enough), using
specific niche strategies until a standard product enables mass diffusion.
**Analyst use:** distinguish *invention* and *first introduction* from *large-scale diffusion*
— hype often conflates them. Watch for early-niche traction as the real leading indicator,
and for the transition out of the adaptation phase.

### A4 — Three levels of analysis — *Ortt, MOT131A*
**Idea:** Innovation must be read at three levels: **(1) project** (a single firm's
development), **(2) pattern** (the development & diffusion of the technology across actors
over time), **(3) discipline / multi-technology** (competing & complementary technologies
interacting).
**Analyst use:** classify which level a development sits at, and explicitly check the
**multi-technology** level — competing vs complementary tech — which is where Lodestar's
cross-feed convergence detection earns its keep.

---

## B. Diffusion & adoption (market side)

### B1 — Rogers' adopter categories — *Rogers; Schilling Ch.13*
**Idea:** Adopters split into innovators (~2.5%), early adopters (~13.5%), early majority,
late majority, laggards. Early adopters are opinion leaders who bring new ideas into the
system.
**Analyst use:** map a product to its adopter group; opinion-leader/early-adopter uptake is
an early signal, but is *not yet* the mass market.

### B2 — Crossing the Chasm — *Moore; Schilling Ch.13*
**Idea:** There is a **chasm** between early adopters (visionaries) and the early majority
(pragmatists). Most technologies die there. Crossing requires a whole-product, a beachhead
segment, and credible commitments (fixed investment, guarantees).
**Analyst use:** the **chasm crossing** (early-adopters → early-majority) is one of the single
most decisive market signals — flag it explicitly. Distinguish "visionary buzz" from
"pragmatist adoption."

---

## C. Technology strategy (the firm's moves)

### C1 — Standards battles & format dominance — *van de Kaa et al. 2011; Schilling Ch.4*
**Idea:** When increasing returns to adoption exist, markets tip toward one standard. Winners
are decided by **installed base**, **availability of complementary goods**, and strategic
factors (timing, pricing, alliances, openness, reputation/credibility).
**Signals to watch:** moves to grow installed base (subsidies, bundling), complementary-goods
ecosystems forming, format/standard alliances, openness decisions.
**Analyst use:** detect *standards battles* as a first-class event; assess who leads on
installed base + complements. This is a decisive, winner-take-most moment.

### C2 — Timing of entry — *Schilling Ch.5*
**Idea:** First-mover advantages: brand loyalty, technological leadership, preemption of
scarce assets, exploiting buyer switching costs, reaping increasing returns. But first movers
also bear risk; *early followers* and *late entrants* sometimes win.
**Analyst use:** classify a market entry as first-mover / fast-follower / late; judge whether
the advantages (switching costs, increasing returns) actually favor the mover.

### C3 — Appropriability & complementary assets — *Teece 1986; Schilling Ch.9*
**Idea:** Whether an innovator *captures* the value it creates ("appropriability") depends on
how easily the innovation is imitated (tacit/socially-complex knowledge, IP regime) and on
who controls the **complementary assets** (manufacturing, distribution, brand). Weak
appropriability + key complements held by others → imitators/incumbents capture the rents.
**Analyst use:** for any breakthrough, ask *who will capture the value* — the innovator, or
the owner of complementary assets? A patent/IP move or a complementary-asset grab is decisive.

### C4 — Platforms & network effects — *Gawer 2014; Katz–Shapiro*
**Idea:** Two-sided platforms create value via cross-side **network effects** (demand-side
economies of scale); strong network effects drive self-reinforcing feedback and can produce
**winner-take-all**.
**Analyst use:** detect platform plays and network-effect dynamics; flag when a market is
tipping winner-take-all. A move to build/extend a platform is strategically decisive.

---

## D. Economics (the competitive environment) — *Economic Foundations, MOT112A*

### D1 — Market structure
**Idea:** Competition is shaped by seller concentration, product differentiation, and entry
barriers → perfect competition / monopolistic competition / oligopoly / monopoly. Standards
+ network effects push toward oligopoly/monopoly.
**Analyst use:** name the market structure; standards/platform dynamics that concentrate a
market are decisive (and invite regulation — see D2).

### D2 — Market failure & regulation
**Idea:** Regulation is a *response to market failure* — imperfect markets/market power,
externalities, public goods, information asymmetry. Read government action through this lens.
**Analyst use:** frame a regulatory/geopolitics development as *which market failure it
targets* (e.g., antitrust → market power; subsidies/tariffs → externality/industrial policy).

### D3 — Game theory
**Idea:** Strategic interaction (oligopoly, standards, cartels) is a game: Nash equilibria,
subgame perfection, trigger strategies, principal–agent problems.
**Analyst use:** read standards battles and competitive moves as games — credible commitments,
preemption, retaliation.

---

## E. Finance & valuation — *Berk & DeMarzo, MOT111A*

### E1 — Investment appraisal
**Idea:** Value = NPV (discounted cash flows); IRR, payback as supporting lenses. Funding/M&A
moves are bets on future cash flows under uncertainty.
**Analyst use:** read funding rounds, capex, and M&A as *investment decisions* — does the
move plausibly create value, and what does the valuation imply about expected diffusion?

### E2 — Real options & staged investment
**Idea:** Under uncertainty, the *option* to invest later has value; optimally stage
investments — make smaller, riskier bets first to gain information before committing.
**Analyst use:** frame early-stage / pilot / staged commitments as real options — the firm is
buying information, not yet betting the company. Distinguishes a hedge from a full commitment.

---

## F. Decision-making — *Inter/intra-org Decision Making, MOT123A*
**Idea:** Real decisions are not purely rational: bounded rationality and limited
information-processing (reliance on schemas), individual & collective **biases**, and
**multi-actor** networks with competing interests and positional power. Process is often
"chaotic," not well-planned.
**Analyst use:** present a development as a *decision under uncertainty* — name the actors and
their interests, and flag where bias/positionality (not evidence) is likely driving it. Avoid
treating organizational moves as if they were rational and fully informed.

---

## G. Epistemology & rigor — *Epistemology & Ethics / Research Methods, MOT142A/141A*
**Idea:** **Falsificationism (Popper):** science eliminates false theories; you cannot verify,
only fail-to-falsify. Be explicit about what data *can* and *cannot* conclude; watch for
fallacies; rate reliability/validity of claims.
**Analyst use:** this is the analyst's *epistemic discipline* — state confidence, distinguish
a corroborated signal from an unfalsified guess, name the evidence and its limits, and never
overstate what a single data point implies. Pair with adversarial verification.

---

## What this means for Lodestar (the operating doctrine)

The theory-grounded analyst should read every significant development and answer:

1. **Lifecycle** — where on the S-curve / dominant-design cycle? Is this a *discontinuity*? (A1–A2)
2. **Diffusion** — which phase / adopter group? Is this a *chasm crossing* or just visionary buzz? (A3, B1–B2)
3. **Strategic move** — standards battle, entry-timing, appropriability/complements, or platform? Who captures the value? (C1–C4)
4. **Market & regulation** — what structure, and which market failure does any regulation target? (D1–D3)
5. **Capital** — what does the investment/valuation imply; is it a real option or a full commitment? (E1–E2)
6. **Decision quality** — who are the actors, and is bias/positionality driving this? (F)
7. **Confidence** — what can we actually conclude, and how sure are we? (G)

**Decisive signals to surface (and everything else to downrank):**
discontinuities / new S-curves · a dominant design locking in · early-niche traction · chasm
crossings · standards-battle moves (installed base, complements, openness) · first-mover /
appropriability / platform plays · market-structure-concentrating events · market-failure
regulation · large staged-vs-committed capital bets.

That list is the *narrowing function*: Lodestar's job is to find these moments across the
feeds and interpret them with the frameworks above — not to mirror the news.
