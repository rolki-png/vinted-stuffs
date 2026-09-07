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
