# Buy-utility scoring and cross-hunt ranking

Date: 2026-09-07  
Status: approved for planning  
Repo: `vinted-stuffs`

## Problem

The current scorer asks the LLM for one `deal_score` from 1–10 and then treats that
ordinal label as both an alert threshold and a global ranking signal. This creates
three problems:

1. A larger scale alone would create false precision because the model would still
   guess one number directly.
2. A score of 9 is sorted above 8 even when uncertainty, hunt context, or different
   reasons for the grade make that ordering unreliable.
3. The score blends value, fit, quality, usefulness, condition, and seller risk, so
   neither the buyer nor the code can tell why an item qualified.

The buyer wants one cross-hunt answer: **how good a purchase is this for me?** A
maternity item, sneaker, and gym piece must be comparable, while preserving the
evidence and uncertainty behind the comparison.

## Goals

- Replace direct 1–10 model grading with a calculated 0–100 `buy_score`.
- Make keeps rarer and more defensible without forcing a target distribution.
- Rank qualified candidates across hunts while admitting close or uncertain ties.
- Use product-level evidence rather than assuming a premium brand is always better.
- Treat original retail price as weak supporting evidence, not value ground truth.
- Collect optional, reason-specific Remove feedback without interpreting every
  removal as broad dislike.
- Keep the scorer explainable, versioned, testable, and safe when extraction or
  pairwise ranking fails.

## Non-goals

- Claiming that an integer score is a purchase probability.
- Inferring personal preferences from unexplained Remove actions.
- Training a statistical model from the current sparse feedback set.
- Scraping original retail prices or building a full comparable-sales service in
  this version.
- Automatically rescoring every historical cached listing.

## Decisions

| Topic | Decision |
|---|---|
| Primary meaning | Overall personal purchase utility |
| Scale | Calculated integer 0–100 plus confidence interval |
| Comparability | Global across all hunts |
| Qualification | Hard gates, then `buy_score >= 85` with at least medium confidence |
| Ordering | Utility score first; pairwise reranking for close qualified candidates |
| Pairwise model | Bradley–Terry ranking over bounded comparisons |
| Seller/scam risk | Removed from utility; expose a separate verification concern |
| Personalization | Optional reason-specific feedback; unexplained feedback does not learn |
| Legacy scores | Label as legacy; never convert by multiplying by ten |

## Scoring architecture

### Structured extraction

The LLM does not emit `buy_score`. It returns bounded factor estimates, confidence,
short evidence, and any hard-gate facts:

| Factor | Range | Meaning |
|---|---:|---|
| `fit_probability` | 0–1 | Probability that size, cut, type, and hunt requirements work |
| `usefulness` | 0–100 | Expected frequency and importance of the wardrobe role |
| `quality` | 0–100 | Material, construction, and expected durability |
| `condition` | 0–100 | Remaining useful life based on stated and visible condition |
| `versatility` | 0–100 | Breadth of realistic outfits, settings, or life stages |
| `equivalent_replacement_cost` | money | Conservative cost of a realistic substitute |
| `duplication_probability` | 0–1 | Probability the item adds little beyond owned items |

Each factor includes:

- a confidence value from 0–1;
- one short evidence statement;
- `unknown` when the listing does not support an estimate.

Missing evidence is not positive evidence. Before aggregation, every factor is
shrunk toward neutral:

```text
adjusted_factor = 50 + confidence × (raw_factor - 50)
adjusted_fit = 0.5 + fit_confidence × (fit_probability - 0.5)
adjusted_duplication = 0.5 + duplication_confidence × (duplication_probability - 0.5)
```

This makes an unsupported claim less influential than a well-evidenced estimate.
Unknown 0–100 values use raw value 50 and confidence 0. Unknown probability
values use raw value 0.5 and confidence 0.

### Product and price evidence

- Brand may inform expected quality only when supported by the specific product
  line, material, construction, or credible product knowledge.
- A Lululemon item receives no automatic advantage over H&M. Fit, use, condition,
  product quality, and delivered price can reverse their order.
- Original retail price is one weak input to replacement value because MSRP can be
  inflated or irrelevant to the nearest substitute.
- The preferred value reference is the conservative cost of buying an equivalent
  item of similar function and quality, new or second-hand as appropriate.
- Delivered cost includes listing price plus estimated buyer fee and shipping.
- Absolute saving matters alongside percentage discount.

The model estimates and explains equivalent replacement cost; code calculates the
value factor after normalizing money to RON:

```text
saving = replacement_cost - delivered_cost
relative_value = clamp(50 + 50 × saving / replacement_cost, 0, 100)
absolute_value = clamp(50 + 50 × saving / 200 RON, 0, 100)
value = 0.60 × relative_value + 0.40 × absolute_value
```

`200 RON` is a versioned initial full-scale absolute saving, not prompt text.
Replacement cost at or below zero makes value invalid. This calculation makes
value monotonically decrease as delivered cost rises while recognizing that a
large absolute saving can matter more than the same percentage on a cheap basic.
Value confidence is the replacement-cost confidence; known checkout arithmetic
adds no model uncertainty.

### Deterministic utility calculation

Initial component weights are versioned configuration rather than prompt prose:

```text
usefulness  0.30
quality     0.20
condition   0.15
versatility 0.10
value       0.25
```

The calculation is:

```text
base = Σ(weight × adjusted_factor)
fit_adjusted = adjusted_fit × base
duplication_penalty = 15 × adjusted_duplication
raw_utility = fit_adjusted - duplication_penalty
buy_score = round(clamp(raw_utility, 0, 100))
```

Fit is multiplicative because an excellent item that probably does not fit is not
an excellent purchase. Duplication is a bounded penalty so it cannot overwhelm a
genuinely exceptional replacement or second-use case.

These are explicit initial policy weights, not claims of universal scientific
truth. They are tested against buyer-approved golden examples and changed only by
introducing a new `score_version`.

### Uncertainty

Confidence maps to factor standard deviation:

```text
sigma_factor = 25 × (1 - confidence)
sigma_probability = 0.25 × (1 - confidence)
score_confidence = min(fit_confidence, Σ(weight × factor_confidence))
```

The calculator propagates those deviations through the utility formula using
first-order variance propagation and an independence assumption:

```text
variance =
  (base × sigma_fit)^2
  + Σ((adjusted_fit × weight × sigma_factor)^2)
  + (15 × sigma_duplication)^2

interval_90 = clamp(raw_utility ± 1.645 × sqrt(variance), 0, 100)
```

The independence assumption is deliberately simple and documented; golden-example
calibration can widen intervals if it proves optimistic. The API and desk expose
the rounded 90% interval, for example `87 ± 5`, and an overall confidence label:

- `low`: confidence below 0.60;
- `medium`: 0.60–0.79;
- `high`: at least 0.80.

The interval communicates ordering uncertainty; it does not change the point-score
threshold. Low-confidence candidates cannot become keeps.

## Hard gates and bands

Hard gates run before utility qualification:

- wrong item type or incompatible size;
- not a genuine hunt fit;
- a material authenticity or condition concern that needs verification;
- insufficient listing evidence to establish basic identity or condition.

Seller age, feedback count, and item count do not directly lower utility. Vinted
Buyer Protection substantially limits monetary loss from non-delivery or material
misdescription. Residual concerns—counterfeit evidence, undisclosed wear, inaccurate
sizing, and dispute effort—appear separately as:

```text
verification_concern: none | inspect | block
verification_reason: short evidence
```

Only `block` prevents a keep. `inspect` remains visible for buyer review.

The display and behavior bands are:

| Score | Meaning | Behavior |
|---:|---|---|
| 0–59 | Skip | No alert or bundle role |
| 60–74 | Bundle extra | May ride with a keep when existing bundle rules pass |
| 75–84 | Good candidate | Display only; no keep alert |
| 85–94 | Keep candidate | Keep only if hard gates pass and confidence is medium/high |
| 95–100 | Exceptional | Same gates; highest-priority keep candidate |

Pairwise ranking never promotes a score below 85 into a keep.

## Cross-hunt pairwise ranking

After deterministic scoring:

1. Select global keep candidates that pass all gates.
2. Sort by `buy_score`.
3. Compare candidates only when their 90% intervals overlap.
4. Bound work to the top 20 candidates and compare each candidate with at most its
   two nearest score neighbors.
5. Ask the model which of each pair is the better purchase for this buyer, using
   the structured factors and evidence rather than brand names alone.
6. Fit Bradley–Terry latent strengths to the comparison outcomes.
7. Store a final `rank_position` and ranking confidence separately from
   `buy_score`.

The pairwise result orders the shortlist; it does not alter factors, qualification,
or score. If extraction is inconsistent, the comparison graph is disconnected, or
the pairwise call fails, the system falls back to deterministic score order and
marks ranking confidence low.

## Feedback and personalization

The desk adds an optional one-tap reason to Remove:

| Reason | Learning scope |
|---|---|
| `sold_unavailable` | No learning |
| `wrong_size` | Size and brand-fit evidence only |
| `bad_fit_style` | Style preference only |
| `low_quality_condition` | Quality/condition preference only |
| `poor_value` | Value sensitivity only |
| `rarely_useful` | Usefulness estimate only |
| `already_own_similar` | Duplication evidence only |
| `other` or omitted | No learning |

Bought is positive evidence and Park remains neutral. Reason-specific evidence may
affect prompts or the matching factor only after at least three consistent examples
within the same hunt family. A Bought counterexample prevents hard suppression.
Personal adjustments are capped at 10 factor points and can never override a hard
size/type gate.

The existing behavior that treats every Remove as a strong negative taste signal is
retired. Existing Remove rows without a reason remain tombstones but produce no
preference learning.

## Data model and compatibility

### Scored listings

Add these fields to the scored-listings schema and API shape:

- `score_version` integer;
- `buy_score` integer nullable;
- `score_confidence` numeric nullable;
- `score_interval_low` and `score_interval_high` integers nullable;
- `score_factors` JSON;
- `factor_evidence` JSON;
- `verification_concern` text;
- `verification_reason` text nullable;
- `rank_position` integer nullable;
- `rank_confidence` text nullable.

Keep `deal_score` during migration for historical display and rollback. Rows without
`score_version = 2` are explicitly `legacy` and cannot participate in mixed-scale
ranking or v2 qualification.

### Remove feedback

Add nullable `reason_code` to listing vetoes and carry it through the veto API,
dashboard snapshot, and desk mutation. Old clients may omit it.

### Migration

Do not map old scores to the new scale. At rollout:

1. Deploy additive schema and API changes.
2. Enable v2 for all newly scored listings.
3. Availability-check cached legacy rows scored 8–10.
4. Rescore only the still-active rows under v2.
5. Preserve all other legacy rows for history, labelled and excluded from v2
   ranking.

A prompt/calculator policy change increments `score_version`; cached scores are
never silently interpreted under new semantics.

## Desk changes

The Finds table shows:

- buy score and 90% interval;
- confidence;
- global rank when available;
- factor breakdown with evidence;
- value/behavior band;
- verification concern;
- legacy label for old rows.

Score filters become `60+`, `75+`, `85+`, and `95+`. The histogram uses ten-point
bins rather than rendering 100 individual bars. Seller best/average score excludes
legacy rows when v2 rows exist and never mixes scales.

The Remove control offers the optional reason choices. Omission remains one click
and produces no learning.

## Error handling

- Reject malformed factor output and retry extraction once through the existing
  scorer fallback path.
- Clamp all numeric inputs to their documented bounds.
- Unknown or missing factor evidence shrinks to neutral and cannot raise confidence.
- A listing with invalid score data cannot become a keep.
- Pairwise failure leaves the deterministic order intact.
- Database write failure retains the current hunt's in-memory result and logs the
  failed persistence without changing score semantics.
- Legacy rows are never silently compared with v2 rows.

## Testing and calibration

### Unit and property tests

- Higher delivered cost cannot improve an otherwise identical score.
- Worse condition cannot improve an otherwise identical score.
- Brand name alone cannot improve a score.
- Missing evidence cannot increase confidence.
- A hard size/type failure cannot qualify.
- Pairwise ranking cannot promote a sub-85 item.
- Pairwise failure falls back to deterministic order.
- Each Remove reason changes only its documented factor.
- Omitted, `other`, and `sold_unavailable` reasons do not learn.
- Legacy and v2 rows are not averaged or ranked together.

### Golden examples

Maintain buyer-reviewed examples across maternity, sneakers, gym, and premium basics.
Include deliberate reversals such as a useful, correctly fitting H&M item beating a
worn or unsuitable Lululemon item. Tests assert bands and ordering constraints, not
fragile exact scores unless validating the calculator itself.

### Monitoring

Record score-versioned histograms, keep qualification count, confidence distribution,
hard-gate reasons, and pairwise fallbacks. Use these to detect inflation or extraction
drift. Do not tune the model to produce a predetermined number of keeps.

As reasoned Bought/Remove evidence accumulates, evaluate ordering quality using
held-out outcomes before changing weights. Sparse implicit outcomes alone are not
enough to claim personalized calibration.

## Success criteria

- No new listing receives a directly guessed aggregate score.
- A keep always has v2 factors, score at least 85, medium/high confidence, and no
  blocking verification concern.
- Cross-hunt ordering is explicit and can represent uncertain ties.
- Brand and MSRP cannot independently make a listing qualify.
- Unexplained Remove actions have zero personalization effect.
- The desk explains why an item scored well and whether the ordering is uncertain.
- Existing history remains readable without contaminating v2 rankings.
