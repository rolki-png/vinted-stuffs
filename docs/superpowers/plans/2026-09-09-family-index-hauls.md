# Family Index Hauls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group already-scored hunt-fit listings (`buy_score` ≥ 60) into same-seller, same-family carts and give every such cart a `bundle_score`, including no-Keep `index_near_bundle`.

**Architecture:** Keep the existing index assemblers (`index_bundle_opportunities` / `indexBundleOpportunities`) and the keep-anchored `bundle_score` formula. Change the group key from `seller_id` to `(seller_id, family)` via `resolve_family` / `resolveFamily`. Remove `index_near_bundle` from unranked kinds. Desk Bundles tab filters by that `family` field.

**Tech Stack:** Python 3.12 unittest (`uv run` from `python/`), Node `node:assert` scripts, DealDesk + Cockroach snapshot.

## Global Constraints

- Member bar stays v2, hunt fit, not blocked, `buy_score` ≥ 60 (`buy_band` in bundle / good / keep / exceptional).
- Group key is `seller_id` + hunt family from hunt name (`maternity` / `gym` / `sneakers` / `knitwear` / `other`).
- Dedup one listing id per cart (higher `buy_score` wins). Min 2 members.
- `index_keep_bundle` iff at least one Keep and at least one extra; otherwise `index_near_bundle`.
- `near_haul` stays `bundle_score = null`. Do not expand closet crawl. Do not change hunt-time `assemble_bundles`.
- Python and JS assemblers must stay equivalent. LLM never emits `bundle_score`.
- Prefer `uv run python -m unittest …` for Python tests.

## File map

| File | Responsibility |
|---|---|
| `python/bundle_score.py` | Unranked kinds; formula |
| `src/server/bundleScore.js` | Same, JS |
| `python/scored_store.py` | Index carts from scored rows |
| `src/server/scoredDb.ts` | Live index carts |
| `src/server/snapshot.ts` | Fill `family` on hunt-time + index carts |
| `src/components/DealDesk.tsx` | Bundles Family filter |
| `CONTEXT.md` | Bundle score language |

---

### Task 1: Score `index_near_bundle`

**Files:**
- Modify: `python/bundle_score.py` (`UNRANKED_KINDS`)
- Modify: `src/server/bundleScore.js` (`UNRANKED_KINDS`)
- Modify: `python/tests/test_bundle_score.py`
- Modify: `scripts/test-bundle-score.mjs`
- Modify: `CONTEXT.md` (Bundle score paragraph)

**Interfaces:**
- Consumes: `calculate_bundle_score(members, *, kind=None, config=None) -> dict` / `calculateBundleScore(members, { kind, config })`
- Produces: `index_near_bundle` returns finite `bundle_score` when members are eligible v2; `near_haul` still null

- [ ] **Step 1: Write the failing Python test**

Replace `test_index_near_always_null` in `python/tests/test_bundle_score.py` with:

```python
    def test_index_near_is_scored(self):
        result = bs.calculate_bundle_score(
            [member(1, 71), member(2, 64)],
            kind="index_near_bundle",
        )
        self.assertIsNotNone(result["bundle_score"])
        self.assertGreaterEqual(result["bundle_score"], 60)
        self.assertLessEqual(result["bundle_score"], 100)
        self.assertEqual(result["bundle_anchor_item_id"], 1)

    def test_near_haul_always_null(self):
        result = bs.calculate_bundle_score(
            [member(1, 90, role="haul"), member(2, 80, role="haul")],
            kind="near_haul",
        )
        self.assertIsNone(result["bundle_score"])
```

Keep the existing `test_near_haul_always_null` once (do not duplicate if it already exists; only change the index_near test).

- [ ] **Step 2: Run Python test to verify it fails**

Run:

```bash
cd python && uv run python -m unittest tests.test_bundle_score.BundleScoreTests.test_index_near_is_scored -v
```

Expected: FAIL — `bundle_score` is `None`.

- [ ] **Step 3: Add a JS assertion**

Append to `scripts/test-bundle-score.mjs` before the final `console.log`:

```js
const indexNear = calculateBundleScore(
  [
    {
      id: 1,
      role: 'extra',
      score_version: 2,
      buy_score: 71,
      score_confidence: 0.8,
      verification_concern: 'none',
      hunt_fit: true,
    },
    {
      id: 2,
      role: 'extra',
      score_version: 2,
      buy_score: 64,
      score_confidence: 0.8,
      verification_concern: 'none',
      hunt_fit: true,
    },
  ],
  { kind: 'index_near_bundle', config: {} },
)
assert.ok(indexNear.bundle_score != null)
assert.equal(indexNear.bundle_anchor_item_id, 1)

const stillNear = calculateBundleScore(
  [
    { id: 1, role: 'haul', score_version: 2, buy_score: 90, score_confidence: 0.8, verification_concern: 'none' },
    { id: 2, role: 'haul', score_version: 2, buy_score: 80, score_confidence: 0.8, verification_concern: 'none' },
  ],
  { kind: 'near_haul', config: {} },
)
assert.equal(stillNear.bundle_score, null)
```

- [ ] **Step 4: Run JS test to verify it fails**

Run: `node scripts/test-bundle-score.mjs`

Expected: FAIL on `indexNear.bundle_score != null`.

- [ ] **Step 5: Minimal implementation**

In `python/bundle_score.py` and `src/server/bundleScore.js`, set:

```python
UNRANKED_KINDS = frozenset({"near_haul"})
```

```js
const UNRANKED_KINDS = new Set(['near_haul'])
```

In `CONTEXT.md`, change the **Bundle score** paragraph so `index_near_bundle` is scored; only hunt-time `near_haul` stays null.

- [ ] **Step 6: Re-run tests**

```bash
cd python && uv run python -m unittest tests.test_bundle_score -v
node scripts/test-bundle-score.mjs
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add python/bundle_score.py src/server/bundleScore.js python/tests/test_bundle_score.py scripts/test-bundle-score.mjs CONTEXT.md
git commit -m "$(cat <<'EOF'
Score index near-bundles with the keep-anchored checkout formula.

EOF
)"
```

---

### Task 2: Family-keyed Python index carts

**Files:**
- Modify: `python/scored_store.py` (`index_bundle_opportunities`)
- Modify: `python/tests/test_scored_store.py`

**Interfaces:**
- Consumes: `taste_learning.resolve_family(hunt_name: str, watch: dict | None = None) -> str`
- Produces: each opportunity has `family: str`; same seller can emit one cart per family; skip-band still excluded

- [ ] **Step 1: Write the failing tests**

In `python/tests/test_scored_store.py`, update `test_index_bundle_opportunities` so members include `score_confidence: 0.8` and `watch` that maps to `other` (keep `"H"`), then:

```python
        self.assertEqual(opps[0]["family"], "other")
        self.assertIsNotNone(opps[0].get("bundle_score"))
```

(Remove `self.assertIsNone(opps[0].get("bundle_score"))`.)

Add:

```python
    def test_index_bundles_split_by_family(self):
        conf = {
            "score_version": 2,
            "buy_band": "bundle",
            "hunt_fit": True,
            "seller_id": 9,
            "seller": "s",
            "verification_concern": "none",
            "score_confidence": 0.8,
            "scored_at": "2026-09-05T02:00:00+00:00",
        }
        rows = [
            {**conf, "id": 1, "watch": "Mamalicious maternity XL-L/XL", "title": "mama a", "price": 40, "buy_score": 71},
            {**conf, "id": 2, "watch": "Seraphine maternity", "title": "mama b", "price": 50, "buy_score": 68},
            {**conf, "id": 3, "watch": "Craft ADV M-L", "title": "gym a", "price": 30, "buy_score": 72},
            {**conf, "id": 4, "watch": "Craft ADV M-L", "title": "gym b", "price": 30, "buy_score": 64},
            {**conf, "id": 5, "watch": "Mamalicious maternity XL-L/XL", "title": "skip", "price": 10, "buy_score": 40, "buy_band": "skip"},
        ]
        opps = ss.index_bundle_opportunities(rows, min_items=2)
        families = sorted(o["family"] for o in opps)
        self.assertEqual(families, ["gym", "maternity"])
        mama = next(o for o in opps if o["family"] == "maternity")
        self.assertEqual(sorted(it["id"] for it in mama["items"]), [1, 2])
        self.assertEqual(mama["kind"], "index_near_bundle")
        self.assertIsNotNone(mama["bundle_score"])
        gym = next(o for o in opps if o["family"] == "gym")
        self.assertEqual(sorted(it["id"] for it in gym["items"]), [3, 4])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd python && uv run python -m unittest tests.test_scored_store.ScoredStoreTests.test_index_bundles_split_by_family tests.test_scored_store.ScoredStoreTests.test_index_bundle_opportunities -v
```

(Use the actual test class name if it is not `ScoredStoreTests` — grep `class .*test_index_bundle` in that file.)

Expected: FAIL — both carts still one seller group, or `family` missing / score still None.

- [ ] **Step 3: Implement grouping**

In `python/scored_store.py` `index_bundle_opportunities`, import `resolve_family` from `taste_learning`. Replace `by_seller` with grouping on `(str(seller_id), resolve_family(row.get("watch") or row.get("hunt_name") or ""))`. After building each `row`, set `row["family"] = family`. Pass `score_confidence` through `items` if not already (it already is). Do not change `_bundle_eligible`.

Sketch:

```python
    import taste_learning as tl

    by_group: dict[tuple[str, str], list] = {}
    for row in export_rows:
        if not _bundle_eligible(row):
            continue
        sid = row.get("seller_id")
        if sid is None:
            continue
        family = tl.resolve_family(row.get("watch") or row.get("hunt_name") or "")
        by_group.setdefault((str(sid), family), []).append(row)

    for (sid, family), rows in by_group.items():
        # existing dedup / kind / offer / apply_to_row
        row["family"] = family
```

- [ ] **Step 4: Re-run tests**

```bash
cd python && uv run python -m unittest tests.test_scored_store -v
```

Expected: PASS (including keep-bundle v2 test still one gym/other cart).

- [ ] **Step 5: Commit**

```bash
git add python/scored_store.py python/tests/test_scored_store.py
git commit -m "$(cat <<'EOF'
Group index hauls by seller and hunt family.

EOF
)"
```

---

### Task 3: Family-keyed JS index carts + snapshot family

**Files:**
- Modify: `src/server/scoredDb.ts` (`indexBundleOpportunities`)
- Modify: `src/server/snapshot.ts` (`dashboardBundle`)
- Modify: `scripts/test-dashboard-snapshot.mjs`

**Interfaces:**
- Consumes: `resolveFamily(huntName, watch?)` from `src/server/tasteLearning.ts`
- Produces: `indexBundleOpportunities` returns `{ family, kind, items, bundle_score, ... }` matching Python; hunt-time bundles get `family` if missing

- [ ] **Step 1: Write the failing snapshot/assembler test**

In `scripts/test-dashboard-snapshot.mjs`, after the existing `indexBundleOpportunities(bundleRows)` assertions (those rows use watch `"Gym"` — add `assert.equal(opportunities[0].family, "gym")` and `assert.ok(v2Bundle.bundle_score != null)`).

Add a second fixture:

```js
const familySplit = indexBundleOpportunities([
	v2(21, 71, 1, {
		buy_band: "bundle",
		watch: "Mamalicious maternity XL-L/XL",
		seller_id: 99,
	}),
	v2(22, 68, 2, {
		buy_band: "bundle",
		watch: "Seraphine maternity",
		seller_id: 99,
	}),
	v2(23, 72, 1, {
		buy_band: "bundle",
		watch: "Craft ADV M-L",
		seller_id: 99,
	}),
	v2(24, 64, 2, {
		buy_band: "bundle",
		watch: "Craft ADV M-L",
		seller_id: 99,
	}),
]);
assert.equal(familySplit.length, 2);
assert.deepEqual(
	familySplit.map((b) => b.family).sort(),
	["gym", "maternity"],
);
const mama = familySplit.find((b) => b.family === "maternity");
assert.deepEqual(mama.items.map((i) => i.id).sort(), [21, 22]);
assert.ok(mama.bundle_score != null);
```

- [ ] **Step 2: Run test to verify it fails**

```bash
node --disable-warning=ExperimentalWarning --experimental-strip-types scripts/test-dashboard-snapshot.mjs
```

Expected: FAIL on `family` or `length === 2`.

- [ ] **Step 3: Implement JS grouping**

In `src/server/scoredDb.ts`, import `resolveFamily` from `./tasteLearning.ts`. Group with key `` `${seller_id}:${resolveFamily(row.watch)}` ``. Set `family` on each opportunity object before `applyToRow`.

In `src/server/snapshot.ts` `dashboardBundle`, after spreading `bundle`:

```js
function dashboardBundle(bundle) {
	const watch =
		bundle?.family ||
		(bundle?.items || []).find((item) => item?.watch)?.watch ||
		bundle?.watch ||
		"";
	return applyToRow({
		...bundle,
		family: bundle?.family || resolveFamily(watch),
		items: (bundle?.items || []).map((item) => dashboardRow(item)),
	});
}
```

(`resolveFamily` is already imported in `snapshot.ts`.)

- [ ] **Step 4: Re-run tests**

```bash
node --disable-warning=ExperimentalWarning --experimental-strip-types scripts/test-dashboard-snapshot.mjs
node scripts/test-bundle-score.mjs
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/server/scoredDb.ts src/server/snapshot.ts scripts/test-dashboard-snapshot.mjs
git commit -m "$(cat <<'EOF'
Split live index hauls by hunt family and stamp family on bundle rows.

EOF
)"
```

---

### Task 4: Bundles tab Family filter

**Files:**
- Modify: `src/components/DealDesk.tsx`
- Modify: `scripts/test-deal-desk-presentation.mjs`

**Interfaces:**
- Consumes: snapshot `bundles[].family`, existing `family` state / `resolveFamily`
- Produces: Bundles list filtered by Family; Best sort unchanged

- [ ] **Step 1: Write the failing presentation test**

In `scripts/test-deal-desk-presentation.mjs` add:

```js
assert.match(source, /function bundleHuntFamily/);
assert.match(source, /bundleHuntFamily\(b\) === family/);
const bundlesTab = source.slice(source.indexOf('{tab === "bundles"'));
assert.match(bundlesTab, /Family/);
assert.match(bundlesTab, /<option value="maternity">/);
```

- [ ] **Step 2: Run test to verify it fails**

```bash
node scripts/test-deal-desk-presentation.mjs
```

Expected: FAIL — `bundleHuntFamily` not found.

- [ ] **Step 3: Implement filter**

Add `family?: string | null` on the `Bundle` type.

Near other helpers in `DealDesk.tsx`:

```tsx
function bundleHuntFamily(bundle: Bundle): string {
	if (bundle.family) return String(bundle.family);
	const watch =
		(bundle.items || []).find((item) => item.watch)?.watch || "";
	return resolveFamily(watch);
}
```

Change the bundles `useMemo` to filter then sort:

```tsx
	const bundles = useMemo(() => {
		const rows = (data?.bundles || []).filter(
			(b) => !family || bundleHuntFamily(b) === family,
		);
		return sortBundles(rows, bundleSort);
	}, [data, bundleSort, family]);
```

In the Bundles toolbar (same `<select>` options as Finds: All, maternity, gym, sneakers, knitwear, other), bind `value={family}` / `onChange` `setFamily`. Do not clear Hunt when changing Family from Bundles (Hunt only affects Finds). Reuse the existing `family` state so Finds and Bundles stay aligned.

Show `{b.family || bundleHuntFamily(b)}` on the card meta line.

- [ ] **Step 4: Re-run tests**

```bash
node scripts/test-deal-desk-presentation.mjs
node --disable-warning=ExperimentalWarning --experimental-strip-types scripts/test-dashboard-snapshot.mjs
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/DealDesk.tsx scripts/test-deal-desk-presentation.mjs
git commit -m "$(cat <<'EOF'
Filter Bundles by hunt family on the desk.

EOF
)"
```

---

## Self-review

- Spec member bar / kinds / min size / skip-band: covered by existing eligibility + Task 2 fixtures.
- Spec score `index_near_bundle`, not `near_haul`: Task 1.
- Spec family group key both assemblers: Tasks 2–3.
- Spec desk Family + Best: Task 4; Best already exists.
- Spec hunt-time assemble unchanged: no `vinted_bot.assemble_bundles` task.
- Spec closet crawl / ntfy out of scope: no tasks.
- `score_confidence` required for a numeric score: Task 2 fixtures include it; production LLM rows already have it.
