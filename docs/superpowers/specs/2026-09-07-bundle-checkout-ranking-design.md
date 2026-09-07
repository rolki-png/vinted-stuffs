# Bundle checkout-utility ranking

Date: 2026-09-07
Status: approved for planning
Repo: `vinted-stuffs`
Depends on: `2026-09-07-buy-utility-scoring-design.md` (v2 listing `buy_score`)

## Problem

The Bundles tab lists wardrobe opportunities roughly in persistence / newest order.
Solo keeps already have a calculated 0–100 `buy_score` and optional pairwise rank.
Multi-item carts do not: a strong keep-bundle, a mediocre value haul, and a
fee-gate-only near haul are not ordered by how good the *checkout* is as a
purchase.

The buyer wants one answer for carts: **how good is this multi-item purchase for
me?** and a desk control to switch between chronological and best→worst order.

## Goals

- Add a deterministic, versioned `bundle_score` (0–100) meaning checkout purchase
  utility, keep-anchored on member v2 listing scores.
- Rank scored opportunities best→worst while leaving unscored carts out of that
  crown.
- Let the Bundles tab toggle **Newest → oldest** vs **Best → worst**.
- Persist scores on bundle rows so ntfy/export/desk share one number.
- Keep the calculator explainable, testable, and safe when members lack v2 scores.

## Non-goals

- Pairwise / Bradley–Terry ranking between bundles (v1).
- Promoting a haul into a Keep or changing listing qualification.
- Scoring `near_haul` / `index_near_bundle` with a guessed aggregate.
- Auto-submitting offers or changing offer guidance math.
- Live re-rank of git-persisted rows whenever a member listing is rescored
  (next bot run / backfill is enough; index carts stay fresher via DB).

## Decisions

| Topic | Decision |
|---|---|
| Primary meaning | Checkout purchase utility (not pure RON/item density) |
| Scale | Calculated integer 0–100; LLM never emits it |
| Aggregation | Keep-anchored: max Keep (or haul best item) + bounded extras/fee term |
| Who is ranked | `keep_bundle`, `value_haul`, `index_keep_bundle`, and carts with a usable v2 anchor |
| Who is unranked | `near_haul`, `index_near_bundle`, carts with no valid v2 anchor (`bundle_score = null`) |
| Best sort + unscored | Ranked first by score; unscored sink below by `kept_at` desc |
| Default desk sort | Newest → oldest (`kept_at` desc) |
| Persist vs read | Persist at bot write; pure formula also applied in snapshot for index keep carts |
| Pairwise | Out of scope for v1 |

## Scoring architecture

### Eligible members

Only items with v2 listing scores (`score_version` matching the buy-utility
version), a finite `buy_score` in 0–100, and `verification_concern != "block"`.
Blocked or legacy-only items are ignored for scoring. If no eligible anchor
exists, `bundle_score` is `null`.

### Anchor

- **`keep_bundle` / `index_keep_bundle`:** maximum `buy_score` among Keep-role
  or Keep-qualified members.
- **`value_haul`:** maximum `buy_score` among haul members (pseudo-keep). A high
  haul `bundle_score` does not change `kind` or Keep qualification.

### Extras term (versioned policy)

```text
anchor_score = buy_score(anchor)
extras = eligible members excluding the single anchor item
n = number of eligible members
extra_mean = mean(buy_score of extras)   # unused if extras empty

fee_relief = clamp(6 × (n - 1) / n, 0, 6)   # 0 when n == 1

quality_gap = anchor_score - extra_mean     # if extras empty, extras_term = 0
extras_term = clamp(
  0.15 × (extra_mean - 50)
  - 0.05 × max(quality_gap, 0)
  + fee_relief,
  -8, +12
)

bundle_score = round(clamp(anchor_score + extras_term, 0, 100))
```

Initial constants live in versioned config (e.g. under `bundle_scoring`), not
prompt prose. Changing them increments `bundle_score_version`.

### Confidence

```text
bundle_confidence = min(
  anchor.score_confidence,
  mean(member.score_confidence for eligible members)
)
```

Expose a coarse label with the same bands as listing confidence
(`low` / `medium` / `high`). **No bundle uncertainty interval in v1.**

### Invariants

- A worse anchor cannot produce a higher `bundle_score` than an otherwise
  identical cart.
- Adding a blocked or unscored item cannot raise `bundle_score`.
- Many mediocre extras (~60) cannot outrank a stronger-anchored cart with one
  solid extra under the documented clamps.
- `near_haul` / `index_near_bundle` always remain `null`.
- `null` is never treated as `0` in sorting.

## Data model

### Bundle row fields

| Field | Type | Meaning |
|---|---|---|
| `bundle_score` | int \| null | Checkout utility |
| `bundle_score_version` | int \| null | Formula/policy version |
| `bundle_confidence` | number \| null | 0–1 |
| `bundle_anchor_item_id` | id \| null | Anchor listing |
| `bundle_rank_position` | int \| null | 1..N among ranked carts after a run; null if unscored |

### Member fields

When writing or merging a scored cart, persist each item’s `buy_score` and
`score_confidence` (when known) on the bundle item so the desk can explain the
cart without a mandatory join.

### Write path

1. After assembling a `keep_bundle` or `value_haul`, call
   `calculate_bundle_score(members, config)` (members carry v2 scores; fee
   relief uses eligible count only).
2. Store the fields above on the row before append/save to
   `data/best_bundles.json`.
3. When a stronger haul supersedes a near haul, recompute (near → scored).
4. After each run that saves bundles, assign `bundle_rank_position` among rows
   with non-null `bundle_score` (stable tie-break: score desc, then `kept_at`
   desc, then fingerprint). Unscored rows keep `bundle_rank_position = null`.

### Backfill

One-shot backfill for existing `best_bundles.json` rows where member v2 scores
are available (from scored-listings cache / item fields). Otherwise leave
`bundle_score` null.

### Index opportunities (`snapshot.ts`)

- `index_near_bundle`: always null score.
- `index_keep_bundle`: apply the **same pure formula** in TypeScript using member
  v2 scores from Cockroach/indexed rows.
- Shared golden fixtures assert Python and TS outputs match. On ambiguity or
  missing anchor, emit null rather than a wrong number.

## Desk

Bundles tab toolbar **Sort**:

| Value | Behavior |
|---|---|
| `new-desc` (default) | `kept_at` descending |
| `best-desc` | Non-null `bundle_score` descending; ties via `bundle_rank_position` if set, else `kept_at`; then null scores by `kept_at` descending |

Ranked cards show bundle score and confidence (e.g. `Bundle 88 · med`). Unranked
cards omit the score or show `—`. Kind badges, veto filters, offer guidance, and
empty-state copy stay as today.

Out of scope for this change: kind filter chips, bundle score histogram.

## Error handling

- No valid v2 anchor → `bundle_score = null`; do not invent an LLM cart grade.
- Malformed member scores skipped; empty eligible set → null.
- All arithmetic inputs clamped; policy changes require `bundle_score_version`
  bump.
- Desk sort must not coerce null to zero.
- TS/Python fixture mismatch in CI fails the build; runtime prefers null over
  disagreeing ad-hoc math.

## Testing

### Unit / property

- Anchor dominance and monotonicity.
- Extras term and fee_relief bounds.
- Near / index-near always null.
- Blocked items ignored.
- Sort: `best-desc` places all ranked above all unscored; `new-desc` ignores score.

### Golden fixtures

Shared JSON cases (at least): strong keep-bundle, haul pseudo-keep, weak-extras
pile-on, single-extra cart, unscored near haul. Asserted from Python and TS.

## Success criteria

- Bundles tab can switch Newest vs Best without mental re-sorting.
- Top of Best are defendable keep-anchored carts; near hauls never appear as #1
  solely by recency under Best sort.
- Cards expose `bundle_score` and anchor identity, not a mystery grade.
- No new cart receives a directly guessed aggregate score from the model.
