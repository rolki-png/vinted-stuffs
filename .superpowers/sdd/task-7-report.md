# Task 7 report: dashboard utility evidence and mixed-history controls

## Outcome

Implemented the v2 dashboard presentation boundary and optional Remove reasons.

- Added `scoreView.js` helpers backed by the shared server score semantics for
  display, filtering, ordering, keep counts, seller ordering, histogram bins,
  factor evidence, and veto score context.
- Score sorts keep valid v2 rows ahead of legacy rows and malformed declared-v2
  rows. Current pairwise ranks are used only when every visible valid-v2 row has
  a valid rank and rank confidence; mixed ranked/unranked rows fall back to
  `buy_score`.
- Score thresholds are explicitly v2 `/100` filters (`60+`, `75+`, `85+`,
  `95+`). Legacy rows cannot satisfy them and have a separate `Legacy only /10`
  option. Band filters are likewise split into v2 and legacy groups.
- Find and bundle rows show v2 score `/100`, interval, confidence, rank, band,
  factor evidence, verification concern, and verification reason. Historical
  rows are labelled `Legacy /10`; malformed v2 rows are labelled invalid and
  never fall back to legacy score fields.
- Dashboard keep stats use shared keep qualification and report v2 and legacy
  counts separately. A non-qualifying v2 row with historical `source: keep`
  does not count as a keep.
- Seller score sorts never compare `/100` and `/10` values. Seller rows identify
  their scale, qualification family, and family-specific bands.
- The run histogram renders only v2 ten-point bins. A legacy score-key histogram
  produces an explicit historical-run empty state.
- Veto requests derive score context from the current find or bundle-member
  snapshot. Valid v2 rows send the complete `score_version`/`buy_score`/
  `buy_band` triple; valid legacy rows send the complete `deal_score`/
  `value_band` pair; incomplete or malformed score families send neither.
- Added an optional Remove reason selector while preserving one-click Remove.
  Reasons are never sent for Bought, Park, or Undo. The selector resets after a
  successful write and whenever the listing/status changes. The existing
  learning layer continues to treat `other` and `sold_unavailable` as
  non-learning reasons.

## RED evidence

1. Initial focused run:

   ```text
   node scripts/test-score-view.mjs
   ```

   Failed with `ERR_MODULE_NOT_FOUND` for
   `src/components/scoreView.js`.

2. Expanded helper-contract run after the minimal presentation module existed:

   ```text
   node scripts/test-score-view.mjs
   ```

   Failed because the module did not export `factorRows` (the expanded contract
   also covered explicit v2/legacy filters, global rank safety, seller scale
   ordering, keep counts, complete veto payloads, and missing-data-safe factor
   rows).

Both failures occurred before the corresponding production behavior was added.

## Verification evidence

Implementation commit before full verification:

```text
b443789 feat: show utility evidence and removal reasons
```

Focused presentation test:

```text
node scripts/test-score-view.mjs
```

Result: exit 0; `ok score-view`.

Desk suite:

```text
npm run test:desk
```

Result: exit 0; all ten scripts passed, including score semantics, score view,
veto schema/store, and dashboard snapshot coverage.

Production build:

```text
npm run build
```

Result: exit 0; Vite client, SSR, and Nitro production builds completed.

Task-file formatting:

```text
npx prettier --check src/components/scoreView.js \
  scripts/test-score-view.mjs src/components/DealDesk.tsx \
  src/styles.css package.json
```

Result: exit 0; all Task 7 files use Prettier style.

Additional checks:

- `npx eslint src/components/DealDesk.tsx` — exit 0.
- `git diff --check HEAD^ HEAD` — exit 0.
- Worktree was clean after the implementation commit.

## Self-review and concerns

- Search of `DealDesk.tsx` found no remaining client-side score arithmetic on
  `deal_score`, `best_score`, or `avg_score`; legacy fields remain only in types
  and explicitly labelled historical presentation.
- The score-view fixture covers a legacy 10 beside v2 60/95, malformed v2 data,
  mixed ranked/unranked v2 rows, fully current ranked rows, ascending and
  descending score order, a legacy 9 against a v2 85 threshold, complete v2 and
  legacy veto contexts, non-Remove reason omission, and absent factor evidence.
- `npm run check` remains nonzero because the repository already contains 41
  unrelated files that fail the global Prettier check. The Task 7 files pass a
  targeted check; formatting all historical docs, configs, server files, and
  tests was kept outside this task.
- The ESLint TypeScript project excludes the new plain-JavaScript helper, so
  invoking ESLint on `scoreView.js` reports a project-inclusion parser error.
  Its executable Node contract and both production bundles pass.
- There is no browser-component test harness in this repository. Remove-reason
  payload behavior is covered through the pure helper, and the React component
  compiles in both client and SSR builds, but selector click/reset behavior is
  not automated at the DOM level.
