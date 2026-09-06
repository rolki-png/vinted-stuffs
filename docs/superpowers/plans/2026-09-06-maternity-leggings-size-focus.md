# Maternity Leggings + XL/L/XL Size Focus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restrict maternity hunts to XL + L/XL only, prefer leggings in notes, add five maternity-leggings watches, and harden maternity scoring rules so plain L / M/L never qualify.

**Architecture:** Config-first change in `python/config.json` (sizes, rename, notes, new watches) plus a small maternity_rules string update in `python/vinted_bot.py`. Production = merge/push to `main` so GitHub Actions `vinted-bot.yml` loads the new config on the next cron.

**Tech Stack:** JSON hunt config; Python 3.12 bot; `unittest` for value_haul size matching.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-06-maternity-leggings-size-focus-design.md`
- Maternity `target_sizes` must be exactly `["L/XL", "XL"]` (order: L/XL then XL)
- Rename maternity watch names `L-XL` → `XL-L/XL`
- Do not change men's gym, sneaker, or knitwear watches
- No `size_ids` on maternity watches
- No non-maternity gym-brand leggings watches
- Tiffany Rose: size + rename only; no leggings preference in notes
- Country remains `ro`

---

## File structure

| File | Responsibility |
|---|---|
| `python/config.json` | Maternity sizes, renames, notes, five new leggings watches |
| `python/vinted_bot.py` | Hard maternity size rule + leggings in preferred garments |
| `python/tests/test_value_haul.py` | Assert L fails / L/XL+XL pass; update renamed seed name if referenced |
| `python/tests/test_bundle_offer.py` | Update renamed maternity watch name fixture if referenced |
| `docs/superpowers/specs/2026-09-06-maternity-leggings-size-focus-design.md` | Already written |
| `docs/superpowers/plans/2026-09-06-maternity-leggings-size-focus.md` | This plan |

---

### Task 1: Harden maternity size matching coverage in tests

**Files:**
- Modify: `python/tests/test_value_haul.py`
- Modify: `python/tests/test_bundle_offer.py` (watch name string only if present)

**Interfaces:**
- Consumes: `value_haul.size_matches(item, target_sizes)`
- Produces: tests that lock `["L/XL", "XL"]` behaviour before config rename lands

- [ ] **Step 1: Add failing/locking size tests**

In `python/tests/test_value_haul.py`, add (near existing `size_matches` tests):

```python
    def test_maternity_xl_lxl_rejects_plain_l(self):
        targets = ["L/XL", "XL"]
        self.assertFalse(vh.size_matches(item(1, "dress", size="L"), targets))
        self.assertFalse(vh.size_matches(item(1, "dress", size="M/L"), targets))
        self.assertFalse(vh.size_matches(item(1, "dress", size="L / 40 / 12"), targets))
        self.assertTrue(vh.size_matches(item(1, "dress", size="XL"), targets))
        self.assertTrue(vh.size_matches(item(1, "dress", size="L/XL"), targets))
```

Update any fixture `"name": "H&M Mama bundle seed L-XL"` → `"H&M Mama bundle seed XL-L/XL"` and `"Mamalicious maternity L-XL"` → `"Mamalicious maternity XL-L/XL"` in test files.

- [ ] **Step 2: Run the new test**

```bash
cd /home/rolki/projects/vinted-stuffs && uv run python -m unittest python.tests.test_value_haul.TestValueHaul.test_maternity_xl_lxl_rejects_plain_l -v
```

Expected: PASS (size_matches already supports this; this locks behaviour).

- [ ] **Step 3: Commit**

```bash
git add python/tests/test_value_haul.py python/tests/test_bundle_offer.py
git commit -m "$(cat <<'EOF'
Lock maternity XL/L-XL size matching in tests.

EOF
)"
```

---

### Task 2: Update maternity_rules in the scorer

**Files:**
- Modify: `python/vinted_bot.py` (`_scoring_prompt` maternity_rules block)

**Interfaces:**
- Consumes: watches whose `target_type` contains `"maternity"`
- Produces: prompt text that hard-rejects plain L / M/L / XXL and prefers leggings

- [ ] **Step 1: Replace maternity_rules string**

In `_scoring_prompt`, replace the maternity_rules assignment with:

```python
        maternity_rules = (
            "For maternity clothing, do not reward an item simply because it is cheap. "
            "Prefer fewer, higher-value purchases over accumulating basics. "
            "Give 9–10 when several hold: premium maternity-specific construction; "
            "leggings (gym + everyday), dresses, trousers, knitwear, outerwear and "
            "substantial pieces; garments usable both during pregnancy and "
            "postpartum/nursing; excellent or unused condition; unusually large "
            "absolute savings versus retail. "
            "Give 8 for a true XL or L/XL hunt-fit in very-good+ condition at or under "
            "hunt price when the piece is genuinely useful maternity/nursing wear. "
            "A 30-50 RON basic maternity T-shirt sold individually is a skip. "
            "Size target is women's XL and L/XL only (also accept clear text equivalents "
            "like L-XL, L / XL, LXL). Plain L, M, M/L, S/M, XL/XXL, and XXL never qualify."
        )
```

- [ ] **Step 2: Sanity-check the string is present**

```bash
cd /home/rolki/projects/vinted-stuffs && python3 -c "
from pathlib import Path
t = Path('python/vinted_bot.py').read_text()
assert 'Plain L, M, M/L' in t
assert 'M/L or XL/XXL may qualify' not in t
assert 'leggings (gym + everyday)' in t
print('ok')
"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add python/vinted_bot.py
git commit -m "$(cat <<'EOF'
Harden maternity scoring to XL/L-XL and prefer leggings.

EOF
)"
```

---

### Task 3: Rewrite maternity watches in config

**Files:**
- Modify: `python/config.json`

**Interfaces:**
- Consumes: every watch whose name/target indicates maternity / Mama seed
- Produces: renamed watches, `target_sizes: ["L/XL","XL"]`, leggings-first notes, five new leggings watches

- [ ] **Step 1: Transform existing maternity watches via script**

Run:

```bash
cd /home/rolki/projects/vinted-stuffs && python3 <<'PY'
import json
from pathlib import Path

path = Path("python/config.json")
cfg = json.loads(path.read_text())

LEGGINGS_LEAD = (
    "Prioritise maternity/over-bump or nursing-friendly leggings suitable for gym "
    "and everyday. Size target is XL or L/XL only — reject plain L and M/L. "
)

def is_maternity(w: dict) -> bool:
    blob = f"{w.get('name','')} {w.get('target_type','')}".lower()
    return "maternity" in blob or "mama" in blob

def rename(name: str) -> str:
    return name.replace(" L-XL", " XL-L/XL")

for w in cfg["watches"]:
    if not is_maternity(w):
        continue
    w["name"] = rename(w["name"])
    w["target_sizes"] = ["L/XL", "XL"]
    notes = (w.get("notes") or "").strip()
    # Tiffany Rose: size/rename only
    if "tiffany rose" in w["name"].lower():
        if "plain L" not in notes:
            w["notes"] = (
                notes + " Size target is XL or L/XL only — reject plain L and M/L."
            ).strip()
        continue
    if w.get("bundle_hunt"):
        w["notes"] = (
            "Bundle seed: never solo-alert; closet-hunt for multi-piece XL/L-XL "
            "maternity value hauls, especially leggings. "
            + notes.replace("L/XL maternity", "XL/L-XL maternity")
        )
        # avoid duplicated seed boilerplate if already present
        if notes.lower().startswith("bundle seed"):
            w["notes"] = (
                "Bundle seed: never solo-alert; closet-hunt for multi-piece XL/L-XL "
                "maternity value hauls, especially leggings. Prefer several useful "
                "XL or L/XL maternity pieces from the same seller."
            )
        continue
    if not notes.lower().startswith("prioritise maternity/over-bump"):
        w["notes"] = (LEGGINGS_LEAD + notes).strip()

NEW = [
    {
        "name": "Broad maternity leggings RO XL-L/XL",
        "query": "colanti maternity",
        "country": "ro",
        "order": "newest_first",
        "per_page": 30,
        "price_to": 180,
        "hunt_price": 100,
        "target_type": "women's maternity or nursing leggings",
        "target_sizes": ["L/XL", "XL"],
        "notes": "Prefer true maternity/over-bump or nursing-friendly leggings suitable for gym and everyday. Reject fashion-only non-maternity leggings and wrong sizes (plain L, M/L).",
        "min_deal_score": 8,
    },
    {
        "name": "Broad maternity leggings EN XL-L/XL",
        "query": "maternity leggings",
        "country": "ro",
        "order": "newest_first",
        "per_page": 30,
        "price_to": 180,
        "hunt_price": 100,
        "target_type": "women's maternity or nursing leggings",
        "target_sizes": ["L/XL", "XL"],
        "notes": "Prefer true maternity/over-bump or nursing-friendly leggings suitable for gym and everyday. Reject fashion-only non-maternity leggings and wrong sizes (plain L, M/L).",
        "min_deal_score": 8,
    },
    {
        "name": "Mamalicious leggings XL-L/XL",
        "query": "mamalicious leggings",
        "country": "ro",
        "order": "newest_first",
        "per_page": 30,
        "price_to": 180,
        "hunt_price": 100,
        "target_type": "women's maternity or nursing leggings",
        "target_sizes": ["L/XL", "XL"],
        "notes": "Mamalicious maternity/nursing leggings only. Gym + everyday. XL or L/XL only.",
        "min_deal_score": 8,
        "brand_ids": [4694493],
    },
    {
        "name": "Seraphine leggings XL-L/XL",
        "query": "seraphine leggings",
        "country": "ro",
        "order": "newest_first",
        "per_page": 30,
        "price_to": 220,
        "hunt_price": 120,
        "target_type": "women's maternity or nursing leggings",
        "target_sizes": ["L/XL", "XL"],
        "notes": "Seraphine maternity/nursing leggings only. Gym + everyday. XL or L/XL only.",
        "min_deal_score": 8,
        "brand_ids": [133550],
    },
    {
        "name": "H&M Mama leggings XL-L/XL",
        "query": "h&m mama leggings",
        "country": "ro",
        "order": "newest_first",
        "per_page": 30,
        "price_to": 120,
        "hunt_price": 70,
        "target_type": "women's maternity or nursing leggings",
        "target_sizes": ["L/XL", "XL"],
        "notes": "H&M Mama maternity leggings only. Gym + everyday. XL or L/XL only. Cheap singles are weak unless exceptional condition.",
        "min_deal_score": 8,
    },
]

# Insert new leggings watches immediately before the first maternity watch
idx = next(i for i, w in enumerate(cfg["watches"]) if is_maternity(w))
# After transform, maternity already renamed; find first maternity again
idx = next(
    i for i, w in enumerate(cfg["watches"])
    if "maternity" in f"{w.get('name','')} {w.get('target_type','')}".lower()
    or "mama" in f"{w.get('name','')}".lower()
)
# Avoid duplicating if re-run
existing = {w["name"] for w in cfg["watches"]}
to_add = [w for w in NEW if w["name"] not in existing]
cfg["watches"][idx:idx] = to_add

path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
print("maternity watches:", sum(1 for w in cfg["watches"] if is_maternity(w)))
print("added:", [w["name"] for w in to_add])
PY
```

If the script’s bundle-seed note logic produces awkward duplication, hand-edit the three seed `notes` to the clean seed sentence from the script’s `if notes.lower().startswith("bundle seed")` branch.

- [ ] **Step 2: Validate config**

```bash
cd /home/rolki/projects/vinted-stuffs && python3 <<'PY'
import json
from pathlib import Path
cfg = json.loads(Path("python/config.json").read_text())

def is_mat(w):
    b = f"{w.get('name','')} {w.get('target_type','')}".lower()
    return "maternity" in b or "mama" in b

mats = [w for w in cfg["watches"] if is_mat(w)]
assert mats, "no maternity watches"
for w in mats:
    assert w["target_sizes"] == ["L/XL", "XL"], w["name"]
    assert " L-XL" not in w["name"], w["name"]
    assert "XL-L/XL" in w["name"] or "leggings" in w["name"].lower(), w["name"]
    if "tiffany" in w["name"].lower():
        assert "legging" not in (w.get("notes") or "").lower(), w["name"]
    elif not w.get("bundle_hunt"):
        assert "legging" in (w.get("notes") or "").lower(), w["name"]

leggings = [w for w in mats if "leggings" in w["name"].lower()]
assert len(leggings) == 5, [w["name"] for w in leggings]
assert not any(w.get("bundle_hunt") for w in leggings)
# men's gym still M/L
gym = next(w for w in cfg["watches"] if "Lululemon" in w["name"] or w["name"].startswith("Gym seed") or "gym" in w["name"].lower() and "M-L" in w["name"])
# just ensure a non-maternity watch still has M
non = next(w for w in cfg["watches"] if not is_mat(w) and "M" in w.get("target_sizes", []))
assert "M" in non["target_sizes"]
print("ok", len(mats), "maternity watches,", len(leggings), "leggings")
PY
```

Expected: `ok … maternity watches, 5 leggings`

- [ ] **Step 3: Run related unit tests**

```bash
cd /home/rolki/projects/vinted-stuffs && uv run python -m unittest python.tests.test_value_haul python.tests.test_bundle_offer -v
```

Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add python/config.json
git commit -m "$(cat <<'EOF'
Tighten maternity hunts to XL/L-XL and add leggings watches.

EOF
)"
```

---

### Task 4: Ship to production

**Files:**
- None (git + Actions)

**Interfaces:**
- Consumes: commits from Tasks 1–3 + design/plan docs
- Produces: `main` updated; next `vinted-deal-bot` cron uses new config

- [ ] **Step 1: Commit design + plan if untracked**

```bash
git add docs/superpowers/specs/2026-09-06-maternity-leggings-size-focus-design.md \
        docs/superpowers/plans/2026-09-06-maternity-leggings-size-focus.md
git commit -m "$(cat <<'EOF'
Document maternity XL/L-XL and leggings hunt design.

EOF
)"
```

Skip if already committed.

- [ ] **Step 2: Push to main**

```bash
git status
git push -u origin HEAD
```

If not on `main`, open a PR and merge, or push the current branch and merge — production bot reads `main` via Actions checkout.

- [ ] **Step 3: Confirm workflow will pick it up**

```bash
gh run list --workflow=vinted-bot.yml --limit 3
```

Optional: trigger once so new watches run sooner than the 15‑min cron:

```bash
gh workflow run vinted-bot.yml
```

Expected: workflow queued/running against the commit that contains the new maternity config.

---

## Spec coverage self-check

| Spec requirement | Task |
|---|---|
| `target_sizes` XL + L/XL only | Task 3 |
| Rename L-XL → XL-L/XL | Task 3 |
| Reject plain L / M/L / XXL in scorer | Task 2 |
| Leggings preferred in brand notes | Task 3 |
| Tiffany Rose no leggings preference | Task 3 validation |
| Five dedicated leggings watches | Task 3 |
| brand_ids Seraphine + Mamalicious | Task 3 NEW watches |
| No size_ids / no non-maternity gym leggings | Task 3 / Global Constraints |
| Production via main + Actions | Task 4 |
| size_matches L rejection locked | Task 1 |

## Placeholder scan

None intentional.
