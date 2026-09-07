# Bundle Checkout-Utility Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist keep-anchored `bundle_score` on scored carts and let the Bundles desk toggle Newest vs Best sort.

**Architecture:** Pure Python `bundle_score.calculate_bundle_score` mirrors a TS port for index keep carts. Bot/write paths and `snapshot` merge apply scores; desk sorts client-side.

**Tech Stack:** Python 3.12 + unittest, TypeScript/JS modules, existing DealDesk + scoredDb snapshot.

## Global Constraints

- LLM never emits `bundle_score`.
- `near_haul` / `index_near_bundle` always `bundle_score = null`.
- Null never sorts as zero under Best.
- Formula constants live under `bundle_scoring`; bump `bundle_score_version` on change.
- Shared golden fixtures must match Python and TS.

---

### Task 1: Python calculator + tests

**Files:**
- Create: `python/bundle_score.py`
- Create: `python/tests/test_bundle_score.py`
- Create: `python/tests/fixtures/bundle_score_golden.json`
- Modify: `python/config.json` (add `bundle_scoring`)

**Interfaces:**
- Produces: `BUNDLE_SCORE_VERSION`, `score_config`, `confidence_label`, `calculate_bundle_score(members, *, kind, config) -> dict`, `apply_to_row(row, config) -> dict`, `assign_bundle_ranks(rows) -> list`

- [ ] Calculator + unit/golden tests
- [ ] Config defaults

### Task 2: Wire Python write paths

**Files:**
- Modify: `python/value_haul.py` (apply score on records / merge helper)
- Modify: `python/scored_store.py` (`index_bundle_opportunities`)
- Modify: `python/vinted_bot.py` (keep_bundle rows + enrich value haul items from scored lookup + assign ranks before save)

- [ ] keep_bundle / value_haul / index rows get score fields
- [ ] near stays null
- [ ] `bundle_rank_position` assigned on save

### Task 3: TS port + snapshot

**Files:**
- Create: `src/server/bundleScore.js`
- Create: `scripts/test-bundle-score.mjs` (golden parity)
- Modify: `src/server/scoredDb.ts`, `src/server/snapshot.ts`
- Modify: `package.json` test scripts

- [ ] TS matches golden
- [ ] index keep scored; near null; mergeBundles recomputes

### Task 4: Desk sort UI

**Files:**
- Modify: `src/components/DealDesk.tsx`
- Modify: `scripts/test-deal-desk-presentation.mjs`
- Modify: `CONTEXT.md` (Bundle score term)

- [ ] Sort control `new-desc` / `best-desc`
- [ ] Show bundle score on ranked cards

### Task 5: Verify + commit

- [ ] `uv run --project python python -m unittest discover -s python/tests -v` (bundle_score + related)
- [ ] `npm run test:desk` (or targeted scripts)
- [ ] Commit (no push)
