# Desk Taste Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Bought desk outcomes and hybrid taste learning so Remove/Bought feedback cuts bad alerts within hunt families.

**Architecture:** Extend Cockroach `listing_vetoes` with `bought` + outcome snapshot columns; desk writes enrichment on veto; bot suppresses removed∪bought, injects family few-shots into scoring prompt, and hard-suppresses keep/alert for repeated Remove patterns with no Bought counter-example.

**Tech Stack:** Python 3 + unittest (`uv run`), TanStack Start desk (TS), Cockroach via psycopg/`pg`, existing `listing_vetoes` seam.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-06-desk-taste-learning-design.md`
- Domain language: Remove / Park / Bought / Keep / hunt family (update `CONTEXT.md`)
- Park learning weight ~0; never use Park in prompt or hard suppress
- Removed always omitted from all desk modes; Bought omitted from active, shown in bought mode
- Exact-id suppress: `removed` ∪ `bought`
- No ML; no config auto-rewrite; no desk re-ranking in this plan
- Keep Python and TS apply semantics aligned
- Prefer `uv run python -m unittest …` for Python tests

---

### Task 1: Pure taste_learning helpers (Python)

**Files:**
- Create: `python/taste_learning.py`
- Create: `python/tests/test_taste_learning.py`

**Interfaces:**
- Produces:
  - `resolve_family(hunt_name: str, watch: dict | None = None) -> str`
  - `normalize_brand(brand: str | None) -> str`
  - `normalize_size(size: str | None) -> str`
  - `pattern_key(family: str, brand: str | None, size: str | None) -> str | None`  # None if no brand
  - `build_taste_prompt_block(outcomes: list[dict], *, per_polarity: int = 5) -> str`
  - `hard_suppress(candidate: dict, outcomes: list[dict], *, min_removes: int = 3, require_zero_bought: bool = True) -> bool`
  - `taste_config(config: dict) -> dict`  # reads config["taste_learning"] with defaults

- [ ] **Step 1: Write failing tests**

```python
# python/tests/test_taste_learning.py
import unittest
from path_setup import ensure_python_path

ensure_python_path()
import taste_learning as tl


class TestFamily(unittest.TestCase):
    def test_maternity(self):
        self.assertEqual(tl.resolve_family("Seraphine maternity XL-L/XL"), "maternity")

    def test_sneakers(self):
        self.assertEqual(tl.resolve_family("New Balance 990 size 43"), "sneakers")

    def test_gym(self):
        self.assertEqual(tl.resolve_family("Lululemon gym M-L"), "gym")

    def test_knitwear(self):
        self.assertEqual(tl.resolve_family("Johnstons of Elgin M-L"), "knitwear")

    def test_watch_override(self):
        self.assertEqual(
            tl.resolve_family("Weird name", {"family": "gym"}),
            "gym",
        )

    def test_other(self):
        self.assertEqual(tl.resolve_family("Random thrift"), "other")


class TestPrompt(unittest.TestCase):
    def test_includes_bought_and_removed_not_parked(self):
        block = tl.build_taste_prompt_block(
            [
                {"status": "bought", "title": "Good shorts", "brand": "Nike", "size": "L", "price_ron": 40, "value_band": "steal", "deal_score": 9},
                {"status": "removed", "title": "Trash tee", "brand": "NoName", "size": "M", "price_ron": 80, "value_band": "skip", "deal_score": 3},
                {"status": "parked", "title": "Maybe", "brand": "X", "size": "L", "price_ron": 50, "value_band": "hunt", "deal_score": 8},
            ]
        )
        self.assertIn("Good shorts", block)
        self.assertIn("Trash tee", block)
        self.assertNotIn("Maybe", block)
        self.assertIn("Bought", block)
        self.assertIn("Removed", block)

    def test_empty_outcomes(self):
        self.assertEqual(tl.build_taste_prompt_block([]), "")


class TestHardSuppress(unittest.TestCase):
    def test_suppress_after_threshold(self):
        outcomes = [
            {"status": "removed", "hunt_family": "gym", "brand": "Nike", "size": "L"},
            {"status": "removed", "hunt_family": "gym", "brand": "Nike", "size": "L"},
            {"status": "removed", "hunt_family": "gym", "brand": "nike", "size": "L"},
        ]
        cand = {"hunt_family": "gym", "brand": "Nike", "size": "L"}
        self.assertTrue(tl.hard_suppress(cand, outcomes, min_removes=3))

    def test_bought_blocks_suppress(self):
        outcomes = [
            {"status": "removed", "hunt_family": "gym", "brand": "Nike", "size": "L"},
            {"status": "removed", "hunt_family": "gym", "brand": "Nike", "size": "L"},
            {"status": "removed", "hunt_family": "gym", "brand": "Nike", "size": "L"},
            {"status": "bought", "hunt_family": "gym", "brand": "Nike", "size": "L"},
        ]
        cand = {"hunt_family": "gym", "brand": "Nike", "size": "L"}
        self.assertFalse(tl.hard_suppress(cand, outcomes, min_removes=3))

    def test_no_brand_never_suppress(self):
        outcomes = [{"status": "removed", "hunt_family": "gym", "brand": "", "size": "L"}] * 5
        self.assertFalse(
            tl.hard_suppress({"hunt_family": "gym", "brand": "", "size": "L"}, outcomes)
        )

    def test_cross_family_ignored(self):
        outcomes = [
            {"status": "removed", "hunt_family": "maternity", "brand": "Nike", "size": "L"}
        ] * 5
        self.assertFalse(
            tl.hard_suppress(
                {"hunt_family": "gym", "brand": "Nike", "size": "L"}, outcomes
            )
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests — expect FAIL** (`taste_learning` missing)

Run: `cd python && uv run python -m unittest tests.test_taste_learning -v`

- [ ] **Step 3: Implement `python/taste_learning.py`** per design (family keyword tables, prompt formatter, hard_suppress counting by pattern_key within family).

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add python/taste_learning.py python/tests/test_taste_learning.py
git commit -m "Add pure taste-learning helpers for family prompt and hard suppress."
```

---

### Task 2: Extend listing_vetoes (Python) for bought + enrichment + suppress ids

**Files:**
- Modify: `python/listing_vetoes.py`
- Modify: `python/tests/test_listing_vetoes.py`

**Interfaces:**
- Produces:
  - `STATUS_BOUGHT = "bought"`
  - `VALID_STATUSES` includes bought
  - `apply_to_finds` / `apply_to_bundles` modes: `active|parked|bought|all`
  - `load_suppress_ids()` on stores (= removed ∪ bought; legacy hidden as removed)
  - `set_status(item_id, status, enrichment: dict | None = None)`
  - `load_outcomes(family: str | None = None) -> list[dict]` (for learner; Memory + Psycopg)
  - Schema columns per design; `ADD COLUMN IF NOT EXISTS` in `ensure_schema`

Apply rules:
- removed: always omit
- bought: omit from `active` and `parked`; only show in `bought`; include in `all`
- parked: unchanged relative to active/all

- [ ] **Step 1: Extend tests** for bought mode, suppress ids, enrichment round-trip on MemoryVetoStore

- [ ] **Step 2: Run — FAIL / assert gaps**

- [ ] **Step 3: Implement schema + apply + store methods**

- [ ] **Step 4: PASS + commit**

```bash
git commit -m "Extend listing vetoes with Bought status, enrichment, and suppress ids."
```

---

### Task 3: Wire bot scoring + suppress to taste learning

**Files:**
- Modify: `python/vinted_bot.py` (prompt build, keep gate, suppress load)
- Modify: `python/tests/test_keep_rules.py` (or new `tests/test_taste_bot_hooks.py`)
- Modify: `python/config.json` — add optional `taste_learning` defaults block

**Interfaces:**
- Consumes: `taste_learning.*`, `listing_vetoes.load_suppress_ids`, `load_outcomes`
- Behavior:
  - Replace `load_removed_ids` usage for alert/keep filters with `load_suppress_ids`
  - After building base scoring prompt, append `build_taste_prompt_block` for watch family outcomes
  - After `is_keep(...)`, if keep and `hard_suppress(candidate_meta, family_outcomes)` → treat as not keep for alert/persist (still may store score)

- [ ] **Step 1: Unit test** hard_suppress + prompt append helpers used the way bot will (thin wrapper test if needed)

- [ ] **Step 2–4: Implement, PASS, commit**

```bash
git commit -m "Wire bot suppress and scoring prompt to family taste learning."
```

---

### Task 4: Mirror TS listingVetoes + API enrichment

**Files:**
- Modify: `src/server/listingVetoes.ts`
- Create: `src/server/tasteLearning.ts` (family resolve only, for enrichment)
- Modify: `src/routes/api/veto.ts` — accept enrichment fields
- Modify: `src/routes/api/dashboard.ts` — allow `bought` veto mode
- Modify: `src/server/snapshot.ts` if mode list duplicated

**Interfaces:**
- `setVetoStatus(itemId, status, enrichment?)`
- Modes include `bought`
- DDL + ALTER ADD COLUMN IF NOT EXISTS matching Python

- [ ] Implement with vitest if present; else keep pure helpers testable. Match Python apply semantics exactly.

- [ ] Commit: `Mirror Bought vetoes and enrichment on the TanStack desk server.`

---

### Task 5: DealDesk Bought UI + history

**Files:**
- Modify: `src/components/DealDesk.tsx`
- Modify: `src/styles.css` (`.pill.bought` if needed)

**Behavior:**
- VetoButtons: add Bought; when `bought`, show Undo
- Filter options: Active | Parked | Bought | All
- Toast with Undo for Bought
- `setVetoStatus` sends enrichment from find/item row (title, brand, size, price, band, score, hunt/watch name)
- Bought filter view doubles as history (same Finds table filtered)

- [ ] Manual sanity if possible; commit: `Add Bought button and Bought filter to the deal desk.`

---

### Task 6: Glossary + config defaults + verification

**Files:**
- Modify: `CONTEXT.md` — Bought, hunt family, taste learning
- Modify: `python/config.json` — `taste_learning` block

- [ ] Run full Python veto + taste + keep tests
- [ ] Run any desk unit/typecheck available (`pnpm` test/lint if exists)
- [ ] Commit docs/config
- [ ] Push `main` (user requested prod)

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| Bought status + Undo + history/filter | 2, 4, 5 |
| Outcome enrichment columns | 2, 4 |
| Exact-id suppress removed∪bought | 2, 3 |
| Family-scoped prompt bias | 1, 3 |
| Hard suppress hybrid | 1, 3 |
| Park ~0 learning | 1 |
| CONTEXT glossary | 6 |
| No ranking / config rewriter | out of scope |
