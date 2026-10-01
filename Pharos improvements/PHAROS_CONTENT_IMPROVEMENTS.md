# Pharos Content Improvements

The highest-value move is to pause new features and make the existing content defensible. The improvements below are ordered by priority.

## P0 — Publication blockers

### 1. Add a mandatory editorial approval gate

Do not automatically publish high-impact recommendations such as enter, exit, scale, slow investment, or commit capital. Require human approval until the system has demonstrated reliable content quality.

### 2. Separate fact, interpretation, and recommendation

Every signal should visibly contain:

- Observed facts
- Pharos's interpretation
- Recommended action
- Evidence gaps
- What would prove the interpretation wrong

This prevents an inference from appearing like a sourced fact.

### 3. Separate curated stage from detected transition

Show three distinct values:

- Curated world-state stage
- Current news-derived stage
- Verified transition, if one occurred

Never say "just crossed," "jumped," or "locked today" when the displayed stage was raised by a curated anchor.

### 4. Expose the evidence behind every curated anchor

The anchor should have:

- Named sources
- Direct links
- Assessment date
- Author or reviewer
- Confidence
- Reasoning
- Next review date

Currently, the linked news stories do not always explain the displayed lifecycle placement.

### 5. Validate publication dates separately from event dates

Store:

- `published_at`
- `event_date`
- `effective_date`
- `retrieved_at`

Reject future publication dates automatically. A regulation taking effect next week must not appear to have been published next week.

### 6. Deduplicate underlying events

Multiple articles about the same transaction, regulation, or product announcement should count as one event with multiple sources—not several separate signals or deals.

### 7. Measure genuine source independence

Replace "three sources" with a stricter assessment:

- Three articles
- Two publishers
- One underlying event
- One primary source
- One genuinely independent confirmation

Strong conclusions should require independent evidence, not syndicated repetition.

### 8. Enforce recommendation proportionality

A single article may justify "investigate" or "monitor." It should not justify "exit," "scale," or "slow commitments."

Suggested ladder:

- One credible source: monitor
- Two independent sources: investigate or prepare
- Multiple sources plus quantitative evidence: act
- Act plus irreversible commitment: human approval required

### 9. Block unsupported causal language

Automatically reject words such as:

- Confirms
- Causes
- Triggers
- Proves
- Locks in
- Wins
- Will dominate

Allow them only when the evidence establishes the mechanism, not merely correlation.

### 10. Make every forecast gradable by its deadline

A forecast must be rejected if:

- Its falsifier occurs after its resolution date
- The outcome requires subjective reinterpretation
- The threshold is missing
- The data source is not specified
- The geographical or market scope is unclear

## P1 — Improve analytical quality

### 11. Create hard evidence gates for each MOT framework

Examples:

- **Dominant design:** standardisation or consolidation evidence from at least two independent events
- **Chasm crossing:** evidence of pragmatist purchasing, repeat adoption, or whole-product readiness
- **Appropriability:** an identified scarce complementary asset and a mechanism for capturing value
- **Standards battle:** competing standards plus switching costs, installed base, or network effects
- **Discontinuity:** a new performance trajectory, not simply an improved product

If the requirements are not met, downgrade the claim to "early evidence" or a watch item.

### 12. Re-evaluate every current technology placement

Review the 14 tracked technologies manually and record:

- Correct maturity stage
- Correct adoption stage
- Supporting primary evidence
- Scope of the assessment
- Important disagreements
- Confidence
- Whether the category is actually a technology

### 13. Stop treating media volume as market momentum

Rename article counts to **media attention**.

Use "market momentum" only when supported by signals such as:

- Revenue
- Orders
- Deployment
- Procurement
- Production capacity
- Patents
- Hiring
- Funding
- Regulatory approval
- Customer adoption

### 14. Introduce an evidence-strength score

Score each signal using factors such as:

- Primary versus secondary source
- Number of independent events
- Quantitative evidence
- Recency
- Source agreement
- Contradictory evidence
- Sample size
- Directness of evidence

Keep evidence strength separate from model confidence.

### 15. Require contradictory evidence

Every decisive signal should answer:

- What evidence points the other way?
- Why does the main interpretation survive?
- What uncertainty remains?

If no counterevidence search was performed, say so.

### 16. Improve source hierarchy

Prefer sources in this order:

1. Regulatory filings and official statistics
2. Company filings and investor materials
3. Standards bodies and regulators
4. Peer-reviewed research
5. Reuters/AP and established specialist publications
6. Trade press
7. Company press releases
8. Aggregators and blogs

Display the source type beside each citation.

### 17. Human-verify the gold set

Stop calling it a gold set until labels are reviewed.

Complete:

- At least two human reviewers
- Written labeling guidance
- Blind independent labeling
- Cohen's kappa or another agreement measure
- Adjudication of disagreements
- Confusion matrices
- Per-domain performance

### 18. Re-evaluate the current Strategist prompt

The prompt has improved, but current outputs must demonstrate the improvement.

Re-run:

- Theory fidelity
- Grounding
- Overclaim rate
- Falsifier quality
- Recommendation proportionality
- Source independence
- Contradiction handling

### 19. Add a "do not publish" outcome

The system should be allowed to conclude:

> No development this period meets the evidence threshold for a decisive strategic signal.

This is better than filling the briefing with weak recommendations.

### 20. Improve scenarios

Replace short bull/base/bear variations with:

- Scenario
- Probability range
- Key assumptions
- Trigger
- Leading indicators
- Strategic consequence
- Recommended response

## P1 — Repair the forecast record

### 21. Make external forecasts the headline

The leading message should be:

> 218 externally verifiable calls open; zero resolved.

Internal accuracy should appear as a secondary consistency measure, not as evidence of forecasting skill.

### 22. Compare every forecast category against a baseline

Show:

- Pharos accuracy
- Naive baseline
- Difference in percentage points
- Brier score
- Brier skill score
- Sample size
- Confidence interval

If Pharos does not beat the baseline, state "no demonstrated skill."

### 23. Remove duplicate and conflicting forecasts

Group forecasts by technology and proposition. Do not allow several differently worded versions of essentially the same call to inflate the ledger.

### 24. Align forecast, falsifier, and resolution terms

Each forecast needs one coherent contract:

- Claim
- Scope
- Probability
- Made date
- Resolution date
- Outcome threshold
- Authoritative data source
- Falsifier
- Grading rule

### 25. Demonstrate historical digest anchoring

Populate and expose the digest history. A checksum of today's JSON proves current-file integrity; it does not prove that the historical record was never changed.

## P2 — Improve investment and capital content

### 26. Rename the Capital event study

Until market adjustment is added, call it:

> Three-day price movement around reported events

Avoid "market confirmed" or "market rejected."

### 27. Use benchmark-adjusted returns

Add:

- Market return
- Sector return
- Beta-adjusted expected return
- Abnormal return
- Confounding company announcements
- Event-window sensitivity

### 28. Use one economic event, not one article, as the unit

A transaction covered by five publishers should create:

- One event
- Five sources
- One event date
- One price-reaction calculation
- One set of affected companies

### 29. Fix company-event attribution

Do not attach a stock reaction to every company mentioned in an article. Identify:

- Primary company
- Counterparty
- Competitor
- Supplier
- Incidental mention

### 30. Deepen company analysis

Add:

- Revenue growth
- Gross and operating margins
- Free cash flow
- Enterprise value
- Forward and historical valuation
- Consensus revisions
- Capital requirements
- Unit economics
- Competitive position
- Thesis risks
- Bull/base/bear valuation

### 31. Separate strategic attractiveness from stock attractiveness

A promising technology does not automatically imply an attractive investment.

Show separately:

- Technology outlook
- Company competitive position
- Value-capture ability
- Financial quality
- Valuation
- Investment conclusion

## P2 — Improve Radar

### 32. Rename the initial Radar signal

Use "untracked attention" rather than "emerging technology" until stronger evidence appears.

### 33. Define what qualifies as a technology

Exclude or separately classify:

- Broad trends
- Business models
- Payment structures
- Regulations
- Applications
- Industry categories

### 34. Add promotion criteria

A candidate should enter tracking only when it has:

- A precise definition
- Evidence from multiple independent events
- At least one non-media signal
- A credible lifecycle taxonomy
- Named companies or research groups
- A reason it matters strategically
- A measurable 90-day forecast

### 35. Improve research-paper matching

Require semantic relevance to the exact technology, not just shared words such as "agent," "AI," or "learning."

### 36. Measure detection lead time honestly

Compare:

- First Pharos detection
- First credible technical publication
- First material funding event
- First major industry coverage
- First commercial deployment
- Date added to tracking

Then Pharos can demonstrate whether Radar is actually early.

## P2 — Editorial and positioning improvements

### 37. Narrow the primary audience

Choose one primary reader for the briefing, such as:

> Corporate technology-strategy teams making horizon-scanning and capability-investment decisions.

Investors can remain a secondary audience.

### 38. Reduce recommendation strength until validation improves

Prefer:

- Investigate
- Validate
- Monitor
- Prepare
- Run a pilot
- Seek supplier options

Reserve enter, exit, scale, and commit for human-reviewed analysis.

### 39. Create a content corrections log

Publish:

- Original claim
- Correction
- Reason
- Date
- Affected forecasts or analyses
- Whether scores changed

### 40. Use precise credibility labels

Replace ambiguous terms:

- "Gold set" → provisional evaluation set
- "Market signal" → media-attention signal
- "Market confirmed" → stock moved positively in the event window
- "Well-calibrated" → internal categories currently appear calibrated; external record pending
- "Detected before the market" → detected before addition to the Pharos registry

## Recommended first four weeks

If only five changes are implemented, choose these:

1. Separate curated stage, news-derived stage, and verified transition.
2. Add the fact/interpretation/recommendation/evidence-gap structure.
3. Deduplicate articles into underlying events.
4. Enforce independent-source and theory-precondition gates.
5. Require human approval for consequential recommendations.

After that, re-evaluate a full month of briefings. Do not judge the changes by how impressive the new text sounds; judge them by whether grounding, theory fidelity, overclaim, and recommendation-quality metrics improve.
