# Task 6 report: mixed-history-safe dashboard read model

## Outcome

Implemented the version-safe dashboard read model and closed the Task 4
listing-veto score-context dependency.

- Added shared score semantics for v2 detection, display scores, keep
  qualification, seller-row scale selection, global score ordering, histogram
  bins, score-field export, and v2-preferred row merging.
- Exported all twelve v2 score/rank fields from Cockroach while preserving JSON
  factor/evidence objects and adding `legacy_score`.
- Made keep/index/last-run/pool and bundle deduplication prefer valid v2 rows over
  legacy rows regardless of source.
- Sorted dashboard finds with ranked v2 rows first, then unranked v2 utility
  scores, then legacy rows.
- Rebuilt seller aggregates from one score scale per seller. When v2 rows exist,
  legacy rows remain visible but do not affect best score, average, keeps, bands,
  or seller-order tie-breaks.
- Added normalized ten-point `score_histogram_bins` to the snapshot.
- Added nullable `score_version`, `buy_score`, and `buy_band` to Python and
  TypeScript listing-veto DDL, runtime alters, writes, reads/enrichment, API
  intake, and memory behavior.
- Added standalone migration `python/sql/005_listing_veto_v2_scores.sql`.
- Veto score-context writes clear the opposite score scale, while metadata-only
  updates preserve the current score context.
- No dashboard UI was changed.

## RED evidence

1. `node scripts/test-score-semantics.mjs`
   - Failed with `ERR_MODULE_NOT_FOUND` for
     `src/server/scoreSemantics.js`.
2. Expanded score-semantic test:
   - Failed because `preferredScoreRow`/merge and ordering exports did not exist.
3. JSON score-field regression:
   - Failed because serialized factor JSON remained a string rather than an
     object.
4. `node scripts/test-listing-veto-v2.mjs`
   - Failed with `ERR_MODULE_NOT_FOUND` for
     `src/server/listingVetoEnrichment.js`.
5. Veto API intake regression:
   - Failed because `score_version`, `buy_score`, and `buy_band` were absent from
     the route enrichment keys.
6. Focused Python command:

   ```text
   source "$HOME/.local/bin/env" && PYTHONPATH=python/tests \
     uv run --project python --no-sync python -m unittest \
     python.tests.test_listing_vetoes.MemoryStoreTests.test_v2_enrichment_round_trip_and_legacy_stale_clearing \
     python.tests.test_listing_vetoes.MemoryStoreTests.test_metadata_update_preserves_v2_score_context -v
   ```

   - Failed with `KeyError: 'score_version'` in both tests before production
     changes.

The root-level module form needs `PYTHONPATH=python/tests` because the existing
test module imports `path_setup` as a top-level module. Discovery mode does not
need this addition.

## Verification evidence

Focused Node:

```text
node scripts/test-score-semantics.mjs &&
node scripts/test-listing-veto-v2.mjs &&
node --disable-warning=ExperimentalWarning --experimental-strip-types \
  scripts/test-dashboard-snapshot.mjs
```

Result: exit 0; `ok score-semantics`, `ok listing-veto-v2`, and
`ok dashboard-snapshot`.

Focused Python:

```text
source "$HOME/.local/bin/env" && PYTHONPATH=python/tests \
  uv run --project python --no-sync python -m unittest \
  python.tests.test_listing_vetoes -v
```

Result: 21 tests passed.

Desk suite:

```text
npm run test:desk
```

Result: exit 0; all eight scripts passed, including the three Task 6 scripts.

Production build:

```text
npm run build
```

Result: exit 0; client, SSR, and Nitro production builds completed.

Scoped full Python suite:

```text
source "$HOME/.local/bin/env" && \
  uv run --project python --no-sync \
  python -m unittest discover -s python/tests -v
```

Result: 173 tests passed.

Additional checks:

- `git diff --check` passed.
- No root or Python `uv.lock` was created.
- Implementation commit: `19489ec feat: expose version-safe utility scores to the desk`.

## Self-review

- The integration fixture covers legacy-to-v2 replacement for the same listing
  across keep/index/run/pool inputs, global v2 sorting, preservation and labelling
  of legacy rows, version-safe seller aggregation, v2 histogram bins, DB export,
  JSON object handling, and separate v2/legacy index bundle groups.
- Python memory and mocked load tests cover v2 round-trip, metadata-only
  preservation, legacy replacement clearing stale v2 context, and field ordering.
- Python and TypeScript schema assertions cover matching column names and SQL
  types in create/runtime/standalone migration paths.
- Live Cockroach execution was not available in the test environment. SQL paths
  are covered by mocked/static assertions, memory behavior, the snapshot
  integration test, and the production server build.
- Direct snapshot integration testing uses Node 22's experimental TypeScript
  stripping with its warning disabled; production compilation uses Vite/Nitro.

---

## Task 6 review-fix pass

### Findings addressed

1. Valid v2 detection now requires declared version 2 plus an integer
   `buy_score` in `[0, 100]`. Dashboard ordering uses explicit valid-v2,
   legacy, and malformed-declared-v2 tiers; malformed v2 rows cannot fall back
   to legacy display, keep, seller, or bundle semantics.
2. Pairwise ranks are used only when both compared v2 rows have positive integer
   positions and `low`/`medium`/`high` rank confidence. Mixed ranked/unranked
   global lists ignore stale ranks and sort all valid v2 rows by `buy_score`,
   avoiding both freshness promotion and a non-transitive comparator cycle.
3. V2 sanitization clears `deal_score`, `value_band`, `scam_risk`, and legacy
   `reason`, while retaining `verification_reason`. It runs for DB exports,
   standalone rows, and merged rows.
4. A legacy `source: "keep"` survives a v2 replacement only when the winning v2
   row itself passes all v2 keep gates. Non-keep v2 replacements retain their
   actual source.
5. JS and Python veto enrichment now share the same three update decisions:
   `v2` only for a complete valid version/score/allowed-band triple, `legacy`
   only for a complete legacy score/band pair with no invalid v2 attempt, and
   `preserve` otherwise. SQL receives that explicit decision rather than
   inferring updates from nullable columns.
6. Partial or invalid score payloads bind null score values with `preserve`, so
   they cannot clear or partially overwrite either existing scale. Complete v2
   and legacy payloads clear the opposite scale.
7. Bundle members use Python-parity ordering: score tier, numeric score, then
   exceptional/steal tie-breaks. Dashboard freshness/rank ordering is not used.
8. `scripts/test-listing-veto-store.mjs` uses a mocked `pg.Client` to execute the
   TypeScript store path and verify 15 insert columns, 15 bound parameters,
   complete-v2/preserve/legacy decisions, and v2→partial→legacy state behavior.

### Review RED evidence

- `node scripts/test-score-semantics.mjs`
  - Invalid/fractional/out-of-range scores were accepted as v2.
  - A single old rank outranked a stronger unranked score.
  - Mixed ranked/unranked rows produced a stale-rank-first order.
  - Bundle tie/order tests showed rank semantics and insertion-order tie
    behavior instead of Python score ordering.
- `node --disable-warning=ExperimentalWarning --experimental-strip-types
  scripts/test-dashboard-snapshot.mjs`
  - Bundle members were `[12, 11]` instead of score-ordered `[11, 12]`.
  - Standalone DB v2 export retained `deal_score: 10`.
  - A malformed-v2-only seller was labelled legacy.
- `node scripts/test-listing-veto-v2.mjs`
  - `scoreUpdateDecision` did not exist.
  - Mixed invalid-v2 plus complete legacy input selected `legacy` instead of
    `preserve`.
- `node --disable-warning=ExperimentalWarning --experimental-strip-types
  scripts/test-listing-veto-store.mjs`
  - The store bound 14 parameters instead of the decision-aware 15.
- Focused Python review tests failed because partial v2 cleared legacy context,
  partial legacy cleared v2 context, and Psycopg params had no
  `score_update_kind`.

### Review verification

Focused Node:

```text
node scripts/test-score-semantics.mjs
node scripts/test-listing-veto-v2.mjs
node --disable-warning=ExperimentalWarning --experimental-strip-types \
  scripts/test-listing-veto-store.mjs
node --disable-warning=ExperimentalWarning --experimental-strip-types \
  scripts/test-dashboard-snapshot.mjs
```

Result: all four scripts exited 0.

Focused Python:

```text
source "$HOME/.local/bin/env" && PYTHONPATH=python/tests \
  uv run --project python --no-sync python -m unittest \
  python.tests.test_listing_vetoes -v
```

Result: 23 tests passed.

Full verification:

- `npm run test:desk` — all nine scripts passed.
- `source "$HOME/.local/bin/env" && uv run --project python --no-sync
  python -m unittest discover -s python/tests -v` — 175 tests passed.
- `npm run build` — client, SSR, and Nitro production builds passed.
- `git diff --check` passed; no `uv.lock` was created.

### Task 7 dependency and concerns

- Task 7 must replace `DealDesk.tsx` client-side `deal_score` filtering and
  sorting with the same valid-v2/legacy/malformed tier semantics. The server
  snapshot is safe, but the current client re-sorts rows using legacy fields and
  can undo server ordering until Task 7 lands.
- Live Cockroach execution remains unavailable in this environment. The updated
  SQL contract is covered by symmetric Python/JS decision tests, Python mocked
  params/load tests, the behavioral mocked TypeScript client test, and the
  production build.

---

## Task 6 re-review regression pass

### RED evidence

- `node scripts/test-score-semantics.mjs`
  - Legacy→legacy replacement returned `source: "index"` instead of preserving
    the prior `source: "keep"`.
  - Equal-score bundle rows were reordered by exceptional/steal bands instead
    of retaining stable input order.
- `node --disable-warning=ExperimentalWarning --experimental-strip-types
  scripts/test-dashboard-snapshot.mjs`
  - A seller with a valid legacy row plus a malformed declared-v2 sibling was
    labelled `score_version: 2` instead of legacy.
- `node --disable-warning=ExperimentalWarning --experimental-strip-types
  scripts/test-listing-veto-store.mjs`
  - A scoreless fresh veto with an authoritative v2 `scored_listings` row bound
    `preserve` and null score fields rather than the filled v2 triple.

### GREEN changes

- Veto writes now classify request score intent before coercion:
  - complete valid request v2 or legacy context wins;
  - any partial/invalid v2 request preserves the existing veto score context;
  - no request score fields allows a complete authoritative scored row to
    choose v2 or legacy;
  - legacy-only partial input can fill its missing legacy field only from a
    complete valid authoritative legacy row.
- The mocked TypeScript store test now behaviorally covers fresh v2 fill, fresh
  legacy fill, partial-v2 preservation across conflicts, partial-legacy
  completion, and a complete request winning over conflicting authoritative
  score data. Insert column/parameter arity remains covered.
- Legacy→legacy merges retain historical keep source. Legacy→v2 keeps retain it
  only when the winning v2 row itself qualifies as keep.
- Seller labels are derived from `sellerScoreRows`' selected valid family.
  Excluded malformed-v2 siblings no longer relabel a valid legacy seller.
- Bundle score ties now return comparator equality and rely on JavaScript's
  stable sort, matching Python indexed-bundle score-only ordering.

### Verification

- Focused Node: score semantics, veto enrichment, mocked TypeScript veto store,
  and dashboard snapshot scripts all passed.
- Focused Python: 23 listing-veto tests passed.
- `npm run test:desk`: all nine scripts passed.
- Full Python discovery: 175 tests passed.
- `npm run build`: client, SSR, and Nitro production builds passed.
- `git diff --check` passed; no `uv.lock` was created.

### Self-review

- The request-intent decision occurs on the original payload, before coercion
  creates nullable keys, so scoreless and explicitly partial requests remain
  distinguishable.
- Authoritative fill copies metadata independently from score context and only
  exposes a score family after full validation through the existing
  `prepareEnrichmentForWrite` boundary.
- Live Cockroach execution remains the only unavailable integration check; SQL
  conflict behavior is exercised through the mocked client and explicit
  update-decision simulation.
