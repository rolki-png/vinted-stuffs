# Value Haul Hunt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Alert when one seller has enough useful men's gym pieces that delivered cost per useful item is strong — without requiring a premium keep.

**Architecture:** Parallel pipeline beside keep-bundles. Bundle-hunt seeds and gym closet crawls feed a prefilter + gate; one value-haul LLM call scores the cart; ntfy/persist use `kind: value_haul`. Premium `is_keep` / `assemble_bundles` stay unchanged.

**Tech Stack:** Python 3 (`scripts/vinted_bot.py`), new `scripts/value_haul.py`, unittest, existing Vinted CLI + Vercel AI Gateway, ntfy, dashboard JS.

## Global Constraints

- Do not relax `assemble_bundles` to allow extras-only keep-bundles.
- `bundle_hunt` watch hits never solo-alert and never pass `is_keep`.
- v1 scope: men's gym / training only (no sneakers, knitwear, maternity value hauls).
- Checkout extras stay RO 25 / HU·PL 40 / default 25.
- v1 does not write value-haul members into `bundle_pool.json`.
- Spec: `docs/superpowers/specs/2026-09-05-value-haul-hunt-design.md`.

---

## File structure

| File | Responsibility |
|---|---|
| `CONTEXT.md` | Domain terms: value haul, bundle hunt, keep-bundle |
| `scripts/config.json` | `value_haul` defaults + 1–2 `bundle_hunt` watches |
| `scripts/value_haul.py` | Pure helpers: size/gym prefilter, gate, payload/prompt, alert predicate, fingerprint, persist shape |
| `scripts/vinted_bot.py` | Wire discovery, closet limits, LLM call, ntfy, save; block keeps for `bundle_hunt` |
| `scripts/test_value_haul.py` | Unit tests for gate, prefilter, alert, fingerprint, payload |
| `scripts/test_keep_rules.py` | Extend: `bundle_hunt` never keep |
| `dashboard/app.js` (+ light CSS if needed) | Badge/filter for value haul vs keep-bundle |
| `scripts/serve_dashboard.py` | Count value-haul bundle items toward top sellers with haul score |

---

### Task 1: Domain + config

**Files:**
- Modify: `CONTEXT.md`
- Modify: `scripts/config.json`

**Interfaces:**
- Produces: config key `value_haul` (dict) and watches with optional `bundle_hunt: true`

- [ ] **Step 1: Extend `CONTEXT.md`**

After the existing **Bundle** / **Bundle extra** entries, add:

```markdown
**Value haul**:
Two or more useful gym pieces from one seller in one checkout, judged by delivered cost per useful item, not brand luxury. Alerted and stored as kind value_haul — no keep required.
_Avoid_: Keep-bundle (that still needs a keep)

**Bundle hunt**:
A watch with bundle_hunt true. Search hits are seeds only: they trigger closet inspection and never solo-alert or become keeps.
_Avoid_: Ordinary hunt, keep

**Keep-bundle**:
The existing bundle shape: at least one keep plus extras from the same seller. Stored as kind keep_bundle.
_Avoid_: Value haul
```

- [ ] **Step 2: Add `value_haul` block and seed watch to `scripts/config.json`**

Insert after `checkout_extra_ron`:

```json
  "value_haul": {
    "min_items": 3,
    "min_items_steal": 2,
    "steal_max_delivered_per_item_ron": 20,
    "strong_max_delivered_per_item_ron": 30,
    "excellent_max_delivered_per_item_ron": 25,
    "closet_crawl_limit": 36,
    "min_deal_score": 8,
    "keep_value_bands": ["steal", "hunt"],
    "max_candidates_to_score": 12,
    "max_value_hauls_per_run": 3
  },
```

Prepend to the `watches` array (so seeds run early):

```json
    {
      "name": "Gym bundle seeds M-L",
      "query": "sport",
      "country": "uk",
      "order": "newest_first",
      "per_page": 50,
      "price_to": 80,
      "hunt_price": 50,
      "bundle_hunt": true,
      "target_type": "men's gym clothing suitable for building a multi-item bundle",
      "target_sizes": ["M", "L"],
      "notes": "Individual item value can be modest. Looking for sellers with several useful men's gym pieces in M/L. H&M Sport/Move, Craft, Nike, Adidas, Under Armour, Puma, Reebok, Decathlon technical lines and similar are acceptable if several good-condition pieces can be bundled cheaply."
    },
```

- [ ] **Step 3: Commit**

```bash
git add CONTEXT.md scripts/config.json
git commit -m "$(cat <<'EOF'
Add value haul domain terms and bundle-hunt seed config.

EOF
)"
```

---

### Task 2: Prefilter + gate helpers (TDD)

**Files:**
- Create: `scripts/value_haul.py`
- Create: `scripts/test_value_haul.py`

**Interfaces:**
- Produces:
  - `value_haul_config(config: dict) -> dict`
  - `size_matches(item: dict, target_sizes: list[str]) -> bool`
  - `looks_like_gymwear(item: dict, watch: dict) -> bool`
  - `prefilter_candidates(items: list, watch: dict, config: dict) -> list`
  - `rough_delivered_per_item(items: list, checkout_extra: float) -> float | None`
  - `passes_value_haul_gate(n: int, rough_per_item: float | None, vh: dict) -> bool`

- [ ] **Step 1: Write failing tests**

Create `scripts/test_value_haul.py`:

```python
import unittest

import value_haul as vh

VH = {
    "min_items": 3,
    "min_items_steal": 2,
    "steal_max_delivered_per_item_ron": 20,
    "max_candidates_to_score": 12,
}
WATCH = {
    "target_sizes": ["M", "L"],
    "target_type": "men's gym clothing suitable for building a multi-item bundle",
    "notes": "H&M Sport Nike Adidas",
}


def item(iid, title, brand="H&M", size="M", price="20"):
    return {
        "id": iid,
        "title": title,
        "brand_title": brand,
        "size_title": size,
        "price": {"amount": price, "currency_code": "GBP"},
        "status": "Very good",
    }


class GateTests(unittest.TestCase):
    def test_three_candidates_pass(self):
        self.assertTrue(vh.passes_value_haul_gate(3, 40.0, VH))

    def test_two_cheap_pass(self):
        self.assertTrue(vh.passes_value_haul_gate(2, 18.0, VH))

    def test_two_expensive_fail(self):
        self.assertFalse(vh.passes_value_haul_gate(2, 35.0, VH))

    def test_one_fails(self):
        self.assertFalse(vh.passes_value_haul_gate(1, 10.0, VH))


class PrefilterTests(unittest.TestCase):
    def test_size_m_slash_l_matches(self):
        self.assertTrue(vh.size_matches(item(1, "tee", size="M/L"), ["M", "L"]))

    def test_wrong_size_rejected(self):
        self.assertFalse(vh.size_matches(item(1, "tee", size="S"), ["M", "L"]))

    def test_gym_title_accepted(self):
        self.assertTrue(vh.looks_like_gymwear(item(1, "H&M Sport póló"), WATCH))

    def test_random_home_rejected(self):
        self.assertFalse(
            vh.looks_like_gymwear(item(1, "Ikea cushion cover", brand="Ikea"), WATCH)
        )

    def test_prefilter_caps_and_keeps_gym(self):
        items = [
            item(1, "Nike training tee", price="15"),
            item(2, "Adidas gym short", size="L", price="18"),
            item(3, "H&M Sport top", price="12"),
            item(4, "Candle holder", brand="Home", size="M", price="5"),
        ]
        out = vh.prefilter_candidates(items, WATCH, {"value_haul": VH})
        ids = [x["id"] for x in out]
        self.assertIn(1, ids)
        self.assertIn(2, ids)
        self.assertIn(3, ids)
        self.assertNotIn(4, ids)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd /home/rolki/projects/vinted-stuffs
uv run python -m unittest scripts.test_value_haul -v
```

Expected: `ModuleNotFoundError` or import failure for `value_haul`.

If import path fails because tests live under `scripts/`, run:

```bash
cd /home/rolki/projects/vinted-stuffs/scripts && uv run python -m unittest test_value_haul -v
```

(Match whatever pattern `test_keep_rules.py` already uses in this repo.)

- [ ] **Step 3: Implement `scripts/value_haul.py`**

```python
"""Value-haul helpers: prefilter, gate, scoring payload (no I/O)."""

from __future__ import annotations

GYM_TOKENS = (
    "sport", "training", "gym", "running", "workout", "fitness",
    "nike", "adidas", "lululemon", "under armour", "underarmour",
    "puma", "reebok", "craft", "decathlon", "h&m", "hm move", "hm sport",
    "ten thousand", "compression", "dry-fit", "dri-fit", "tech tee",
)


def value_haul_config(config: dict) -> dict:
    defaults = {
        "min_items": 3,
        "min_items_steal": 2,
        "steal_max_delivered_per_item_ron": 20,
        "strong_max_delivered_per_item_ron": 30,
        "excellent_max_delivered_per_item_ron": 25,
        "closet_crawl_limit": 36,
        "min_deal_score": 8,
        "keep_value_bands": ["steal", "hunt"],
        "max_candidates_to_score": 12,
        "max_value_hauls_per_run": 3,
    }
    merged = dict(defaults)
    merged.update(config.get("value_haul") or {})
    return merged


def _listing_amount(item: dict):
    raw = (item.get("price") or {}).get("amount")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def size_matches(item: dict, target_sizes: list[str]) -> bool:
    if not target_sizes:
        return True
    raw = f"{item.get('size_title') or ''} {item.get('title') or ''}".upper()
    targets = [t.upper() for t in target_sizes]
    for t in targets:
        if t in raw.replace(" ", ""):
            return True
        # token-ish: " M ", "M/", "/M", "M-L"
        for sep in (" ", "/", "-", ","):
            if f"{sep}{t}{sep}" in f" {raw.replace('-', '/')} ":
                return True
            if raw.startswith(t + sep) or raw.endswith(sep + t):
                return True
    # ambiguous M/L style already covered by membership of either letter
    compact = raw.replace(" ", "")
    if "/" in compact or "-" in compact:
        parts = compact.replace("-", "/").split("/")
        if any(p.strip() in targets for p in parts):
            return True
    return False


def looks_like_gymwear(item: dict, watch: dict) -> bool:
    blob = f"{item.get('title') or ''} {item.get('brand_title') or ''}".lower()
    if any(tok in blob for tok in GYM_TOKENS):
        return True
    notes = (watch.get("notes") or "").lower()
    for word in notes.replace(",", " ").split():
        if len(word) >= 4 and word in blob:
            return True
    target = (watch.get("target_type") or "").lower()
    if "gym" in target or "training" in target or "sport" in target:
        if any(w in blob for w in ("tee", "t-shirt", "short", "legging", "hoodie", "tank", "top", "póló", "tricou")):
            return True
    return False


def rough_delivered_per_item(items: list, checkout_extra: float) -> float | None:
    if not items:
        return None
    total = 0.0
    for it in items:
        amt = _listing_amount(it)
        if amt is None:
            return None
        total += amt
    return (total + float(checkout_extra)) / len(items)


def passes_value_haul_gate(n: int, rough_per_item: float | None, vh: dict) -> bool:
    min_items = int(vh.get("min_items", 3))
    min_steal = int(vh.get("min_items_steal", 2))
    steal_cap = float(vh.get("steal_max_delivered_per_item_ron", 20))
    if n >= min_items:
        return True
    if n >= min_steal and rough_per_item is not None and rough_per_item <= steal_cap:
        return True
    return False


def prefilter_candidates(items: list, watch: dict, config: dict) -> list:
    vh = value_haul_config(config)
    sizes = watch.get("target_sizes") or []
    scored = []
    for it in items:
        if _listing_amount(it) is None:
            continue
        if not size_matches(it, sizes):
            continue
        if not looks_like_gymwear(it, watch):
            continue
        title = (it.get("title") or "").lower()
        brand = (it.get("brand_title") or "").lower()
        fit = sum(1 for tok in GYM_TOKENS if tok in f"{title} {brand}")
        price = _listing_amount(it) or 9999
        scored.append((fit, -price, it))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    cap = int(vh.get("max_candidates_to_score", 12))
    return [t[2] for t in scored[:cap]]
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd /home/rolki/projects/vinted-stuffs/scripts && uv run python -m unittest test_value_haul -v
```

- [ ] **Step 5: Commit**

```bash
git add scripts/value_haul.py scripts/test_value_haul.py
git commit -m "$(cat <<'EOF'
Add value-haul prefilter and gate helpers with tests.

EOF
)"
```

---

### Task 3: `bundle_hunt` never becomes a keep

**Files:**
- Modify: `scripts/vinted_bot.py` (`is_keep`)
- Modify: `scripts/test_keep_rules.py`

**Interfaces:**
- Consumes: `watch.get("bundle_hunt")`
- Produces: `is_keep(...)` → False when `bundle_hunt` is true

- [ ] **Step 1: Write failing test** in `scripts/test_keep_rules.py`

```python
    def test_bundle_hunt_watch_never_keep(self):
        item = {"price": {"amount": "200", "currency_code": "GBP"}}
        score = {
            "deal_score": 10,
            "value_band": "steal",
            "hunt_fit": True,
            "scam_risk": "low",
        }
        watch = {
            "target_type": "men's gym clothing",
            "bundle_hunt": True,
            "min_deal_score": 8,
        }
        self.assertFalse(bot.is_keep(score, CONFIG, watch, item))
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd /home/rolki/projects/vinted-stuffs/scripts && uv run python -m unittest test_keep_rules.KeepRuleTests.test_bundle_hunt_watch_never_keep -v
```

- [ ] **Step 3: Patch `is_keep`** at the top of the function body in `scripts/vinted_bot.py`:

```python
def is_keep(score: dict, config: dict, watch: dict, item: dict | None = None) -> bool:
    """True only for a true-fit, high price-quality listing that is not high-risk."""
    if watch.get("bundle_hunt"):
        return False
    if not score or score.get("scam_risk") == "high":
        return False
    # ... existing body unchanged ...
```

- [ ] **Step 4: Run keep tests — expect PASS**

```bash
cd /home/rolki/projects/vinted-stuffs/scripts && uv run python -m unittest test_keep_rules -v
```

- [ ] **Step 5: Commit**

```bash
git add scripts/vinted_bot.py scripts/test_keep_rules.py
git commit -m "$(cat <<'EOF'
Block solo keeps for bundle_hunt seed watches.

EOF
)"
```

---

### Task 4: Payload, prompt, parse, alert predicate

**Files:**
- Modify: `scripts/value_haul.py`
- Modify: `scripts/test_value_haul.py`

**Interfaces:**
- Produces:
  - `build_haul_payload(seller: str, seller_country: str, checkout_extra: float, items: list, watch: dict) -> dict`
  - `value_haul_prompt(payload: dict, vh: dict) -> str`
  - `parse_value_haul_score(raw: str) -> dict | None`
  - `useful_items(items: list, score: dict) -> list`
  - `is_value_haul_alert(score: dict, useful: list, checkout_extra: float, vh: dict) -> bool`

- [ ] **Step 1: Add failing tests** to `test_value_haul.py`

```python
class PayloadAndAlertTests(unittest.TestCase):
    def test_payload_totals(self):
        items = [
            item(1, "H&M Sport", price="16.67"),
            item(2, "H&M Sport", size="L", price="16.67"),
            item(3, "Nike tee", price="16.66"),
        ]
        payload = vh.build_haul_payload("robert", "hu", 40.0, items, WATCH)
        self.assertEqual(payload["kind"], "value_haul")
        self.assertEqual(payload["matching_items"], 3)
        self.assertAlmostEqual(payload["total_listing_price"], 50.0, places=1)
        self.assertAlmostEqual(payload["estimated_total"], 90.0, places=1)
        self.assertIn("value_haul", vh.value_haul_prompt(payload, VH).lower())

    def test_parse_object(self):
        raw = '{"deal_score":9,"value_band":"steal","useful_item_count":3,"effective_price_per_useful_item":21.2,"hunt_fit":true,"scam_risk":"low","reason":"good","reject_ids":[]}'
        score = vh.parse_value_haul_score(raw)
        self.assertEqual(score["deal_score"], 9)

    def test_alert_requires_gate_after_rejects(self):
        items = [item(1, "a"), item(2, "b"), item(3, "c")]
        score = {
            "deal_score": 9,
            "value_band": "steal",
            "hunt_fit": True,
            "scam_risk": "low",
            "reject_ids": [1],
            "effective_price_per_useful_item": 18.0,
            "useful_item_count": 2,
        }
        useful = vh.useful_items(items, score)
        self.assertEqual(len(useful), 2)
        self.assertTrue(vh.is_value_haul_alert(score, useful, 25.0, VH))

    def test_alert_rejects_high_scam(self):
        items = [item(1, "a"), item(2, "b"), item(3, "c")]
        score = {
            "deal_score": 9,
            "value_band": "steal",
            "hunt_fit": True,
            "scam_risk": "high",
            "reject_ids": [],
            "effective_price_per_useful_item": 15.0,
        }
        self.assertFalse(vh.is_value_haul_alert(score, items, 25.0, VH))
```

- [ ] **Step 2: Run — expect FAIL** (missing functions)

- [ ] **Step 3: Append implementations to `value_haul.py`**

```python
import json


def build_haul_payload(seller, seller_country, checkout_extra, items, watch):
    listing_sum = sum(_listing_amount(it) or 0 for it in items)
    n = len(items)
    estimated = listing_sum + float(checkout_extra)
    return {
        "kind": "value_haul",
        "seller": seller,
        "seller_country": seller_country or "ro",
        "checkout_extra_ron": float(checkout_extra),
        "matching_items": n,
        "total_listing_price": listing_sum,
        "estimated_total": estimated,
        "effective_price_per_item": (estimated / n) if n else None,
        "items": [
            {
                "id": it.get("id"),
                "title": it.get("title"),
                "brand": it.get("brand_title"),
                "size": it.get("size_title"),
                "price": _listing_amount(it),
                "status": it.get("status"),
            }
            for it in items
        ],
        "hunt": {
            "target_type": watch.get("target_type"),
            "target_sizes": watch.get("target_sizes") or [],
            "notes": watch.get("notes") or "",
        },
    }


def value_haul_prompt(payload: dict, vh: dict) -> str:
    strong = vh.get("strong_max_delivered_per_item_ron", 30)
    excellent = vh.get("excellent_max_delivered_per_item_ron", 25)
    steal = vh.get("steal_max_delivered_per_item_ron", 20)
    return f"""This is a BUNDLE / value haul hunt.

Do not judge the items only by individual resale value.

A bundle can be an outstanding deal when:
- at least 3 useful pieces fit the buyer (or 2 if delivered cost per useful item is steal-level)
- one shipping charge covers the order
- total delivered cost per useful item is low
- condition is very good or better
- the pieces are genuinely usable for gym/training
- there is little filler or junk

For ordinary gym brands:
- under ~{strong} GBP delivered per useful item = strong (value_band hunt if score high enough)
- under ~{excellent} GBP = excellent
- around ~{steal} GBP or less = steal

Reject bundles where the apparent low price is achieved by including wrong sizes,
worn-out pieces, casual cotton tees with little gym value, or items the buyer is unlikely to use.

Return ONE JSON object:
{{
  "deal_score": <1-10>,
  "value_band": "steal"|"hunt"|"acceptable"|"skip",
  "useful_item_count": <int>,
  "effective_price_per_useful_item": <number>,
  "hunt_fit": <true|false>,
  "scam_risk": "low"|"medium"|"high",
  "reason": "<one short sentence>",
  "reject_ids": [<item ids that are filler/wrong>]
}}

Cart:
{json.dumps(payload, ensure_ascii=False)}
"""


def parse_value_haul_score(raw: str) -> dict | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and "deal_score" in parsed:
        return parsed
    if isinstance(parsed, dict):
        for key in ("haul", "score", "result"):
            inner = parsed.get(key)
            if isinstance(inner, dict) and "deal_score" in inner:
                return inner
    return None


def useful_items(items: list, score: dict) -> list:
    rejected = {str(x) for x in (score.get("reject_ids") or [])}
    return [it for it in items if str(it.get("id")) not in rejected]


def is_value_haul_alert(score: dict, useful: list, checkout_extra: float, vh: dict) -> bool:
    if not score or score.get("scam_risk") == "high":
        return False
    if score.get("hunt_fit") is not True:
        return False
    bands = set(vh.get("keep_value_bands") or ["steal", "hunt"])
    if (score.get("value_band") or "skip") not in bands:
        return False
    try:
        deal = int(score.get("deal_score"))
    except (TypeError, ValueError):
        return False
    if deal < int(vh.get("min_deal_score", 8)):
        return False
    n = len(useful)
    per = score.get("effective_price_per_useful_item")
    try:
        per_f = float(per) if per is not None else rough_delivered_per_item(useful, checkout_extra)
    except (TypeError, ValueError):
        per_f = rough_delivered_per_item(useful, checkout_extra)
    return passes_value_haul_gate(n, per_f, vh)
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd /home/rolki/projects/vinted-stuffs/scripts && uv run python -m unittest test_value_haul -v
```

- [ ] **Step 5: Commit**

```bash
git add scripts/value_haul.py scripts/test_value_haul.py
git commit -m "$(cat <<'EOF'
Add value-haul payload, prompt, and alert predicate.

EOF
)"
```

---

### Task 5: Fingerprint + persist row + ntfy helper

**Files:**
- Modify: `scripts/value_haul.py`
- Modify: `scripts/test_value_haul.py`
- Modify: `scripts/vinted_bot.py` (add `send_ntfy_value_haul`)

**Interfaces:**
- Produces:
  - `value_haul_fingerprint(seller_id, useful_items: list) -> str`
  - `value_haul_record(haul: dict, score: dict, useful: list, watch_name: str, kept_at: str) -> dict`
  - `send_ntfy_value_haul(topic: str, haul: dict, score: dict, useful: list) -> None` in `vinted_bot.py`

- [ ] **Step 1: Failing fingerprint test**

```python
class FingerprintTests(unittest.TestCase):
    def test_fingerprint_sorted_useful_only(self):
        items = [item(3, "c"), item(1, "a"), item(2, "b")]
        score = {"reject_ids": [2]}
        useful = vh.useful_items(items, score)
        self.assertEqual(vh.value_haul_fingerprint(99, useful), "99:1,3")
```

- [ ] **Step 2: Implement fingerprint + record in `value_haul.py`**

```python
def value_haul_fingerprint(seller_id, useful_items: list) -> str:
    ids = sorted(str(it.get("id")) for it in useful_items)
    return f"{seller_id}:" + ",".join(ids)


def value_haul_record(haul: dict, score: dict, useful: list, watch_name: str, kept_at: str) -> dict:
    listing_sum = sum(_listing_amount(it) or 0 for it in useful)
    extra = float(haul.get("checkout_extra_ron") or 0)
    return {
        "kept_at": kept_at,
        "kind": "value_haul",
        "seller": haul.get("seller"),
        "seller_id": haul.get("seller_id"),
        "country": haul.get("country"),
        "checkout_extra_ron": extra,
        "listing_sum": listing_sum,
        "checkout_total": listing_sum + extra,
        "deal_score": score.get("deal_score"),
        "value_band": score.get("value_band"),
        "reason": score.get("reason"),
        "watch": watch_name,
        "effective_price_per_useful_item": score.get("effective_price_per_useful_item"),
        "items": [
            {
                "role": "haul",
                "id": it.get("id"),
                "title": it.get("title"),
                "price": _listing_amount(it),
                "url": it.get("url"),
                "watch": watch_name,
                "deal_score": score.get("deal_score"),
            }
            for it in useful
        ],
    }
```

- [ ] **Step 3: Add `send_ntfy_value_haul` next to `send_ntfy_bundle` in `vinted_bot.py`**

Mirror `send_ntfy_bundle` but title/body like:

```python
def send_ntfy_value_haul(topic: str, haul: dict, score: dict, useful: list) -> None:
    n = len(useful)
    seller = haul.get("seller") or haul.get("seller_id")
    per = score.get("effective_price_per_useful_item")
    total = haul.get("checkout_total")
    title = f"value haul {n} @ {seller}: ~{per} GBP/item ({total:.0f} total)" if per is not None and total is not None else f"value haul {n} @ {seller}"
    lines = [
        score.get("reason") or "",
        f"{haul.get('listing_sum', 0):.0f} + {haul.get('checkout_extra_ron', 0):.0f} = {haul.get('checkout_total', 0):.0f} GBP",
    ]
    for it in useful:
        lines.append(f"- {it.get('title')} ({listing_amount(it)} GBP)")
    # POST to ntfy like send_ntfy_bundle; Click = seller profile URL
```

Copy the exact `requests.post` / headers pattern from `send_ntfy_bundle` in the same file.

- [ ] **Step 4: Run tests — PASS; commit**

```bash
cd /home/rolki/projects/vinted-stuffs/scripts && uv run python -m unittest test_value_haul -v
git add scripts/value_haul.py scripts/test_value_haul.py scripts/vinted_bot.py
git commit -m "$(cat <<'EOF'
Add value-haul fingerprint, persist shape, and ntfy helper.

EOF
)"
```

---

### Task 6: Wire discovery + scoring into the run loop

**Files:**
- Modify: `scripts/vinted_bot.py` (main run path ~1079–1250)
- Optionally add: `scripts/test_value_haul_wire.py` with a small pure function test if you extract `collect_value_haul_jobs`

**Interfaces:**
- Consumes: all Task 2–5 helpers; `get_seller_closets`, `checkout_extra_ron`, `score_with_gateway` / Gemini path
- Produces: `evaluate_value_hauls(...)` returning list of alertable haul dicts; main loop sends ntfy + saves rows with `kind`

**Design to implement in `vinted_bot.py`:**

1. Split watches: `bundle_hunts = [w for w in watches if w.get("bundle_hunt")]`, `premium = [w for w in watches if not w.get("bundle_hunt")]`.
2. For bundle_hunt search results: **do not** call `score_batch`. Instead `mark_seen`, collect `(seller_id, country, watch)` seeds. Attach profiles only as needed for country.
3. Existing premium scoring + closet crawl unchanged for premium watches, but:
   - When building crawl jobs, if seller is also a value-haul seed, use `value_haul_config(config)["closet_crawl_limit"]` (36) for that seller’s fetch.
   - After closets return, for each seed/path-B seller, run `prefilter_candidates` against closet items (+ any already-scored hunt-fit gym items from that seller this run).
4. Path B triggers: sellers who had a premium scored row with `hunt_fit` and watch `target_type` containing `gym` / `training` / `sport` (men's gym only — skip maternity/sneaker/knit watches).
5. Deduplicate sellers: one evaluation per seller_id; prefer bundle_hunt watch metadata if present.
6. For each gated seller: build payload → LLM (`score_value_haul` wrapping gateway/gemini like `score_listings` but single object) → `is_value_haul_alert` → fingerprint vs `alerted_bundle_keys` → ntfy → append persist row with `kind: value_haul`.
7. Cap with `max_value_hauls_per_run`.
8. When saving keep-bundles, set `"kind": "keep_bundle"` on new rows.

- [ ] **Step 1: Add `score_value_haul` next to `score_listings`**

```python
def score_value_haul(payload: dict, config: dict, gateway_key: str, gemini_client) -> dict | None:
    import value_haul as vh
    vh_cfg = vh.value_haul_config(config)
    prompt = vh.value_haul_prompt(payload, vh_cfg) + '\nReturn a JSON object (not an array).'
    # Prefer gateway; on failure try gemini; on failure return None and log.
    # Parse with vh.parse_value_haul_score.
```

Implement by copying the HTTP/Gemini call shape from `score_with_gateway` / `score_with_gemini`, but use the value-haul prompt and parse a single object.

- [ ] **Step 2: Skip LLM scoring for bundle_hunt watches in the main search loop**

Replace the uniform `score_batch(watch, new_items)` loop with:

```python
    value_haul_seeds = []  # list of dicts: sid, country, watch, trigger_item
    for watch in watches:
        items = found.get(watch["name"], [])
        new_items = [it for it in items if not already_seen(state, it["id"], watch["name"])]
        if not full_sweep:
            new_items = new_items[: _max_new_items_per_watch(config)]
        if watch.get("bundle_hunt"):
            for it in new_items:
                mark_seen(state, it.get("id"), watch["name"])
                sid = seller_id(it)
                if sid is None:
                    continue
                value_haul_seeds.append({
                    "sid": sid,
                    "country": _country(watch),
                    "watch": watch,
                    "trigger_item": it,
                })
            print(f"Hunt '{watch['name']}': {len(items)} listed, {len(new_items)} seeds (no solo score)", file=sys.stderr)
            continue
        print(f"Hunt '{watch['name']}': {len(items)} listed, {len(new_items)} unseen to score", file=sys.stderr)
        score_batch(watch, new_items)
```

- [ ] **Step 3: After closet crawl, evaluate value hauls**

Pseudocode to place after closets are fetched (and after premium closet `score_batch`), before or after `assemble_bundles` — **independent** of keep-bundles:

```python
    import value_haul as vh
    vh_cfg = vh.value_haul_config(config)

    # Build seller → {watch, items[]} from seeds + path B gym hunt-fits + closet listings
    # Prefer bundle_hunt watch when present
    # prefilter → gate → score_value_haul → alert list
```

Concrete helper to add in `vinted_bot.py` (keep I/O here, pure logic in `value_haul`):

```python
def is_mens_gym_watch(watch: dict) -> bool:
    t = (watch.get("target_type") or "").lower()
    if "maternity" in t or "sneaker" in t or "knit" in t or "cashmere" in t:
        return False
    return any(x in t for x in ("gym", "training", "sport", "running", "compression"))
```

For each candidate seller:
1. Gather closet items from `closets_by_sid` (fetch with limit 36 if seed or gym path-B).
2. `cands = vh.prefilter_candidates(closet_items, watch, config)`.
3. `extra = checkout_extra_ron(country, config)`.
4. `rough = vh.rough_delivered_per_item(cands, extra)`.
5. If not `vh.passes_value_haul_gate(len(cands), rough, vh_cfg): continue`.
6. `payload = vh.build_haul_payload(...)`.
7. `score = score_value_haul(...)` (or fake score in `test_mode`).
8. `useful = vh.useful_items(cands, score)`.
9. If not `vh.is_value_haul_alert(...): continue`.
10. Fingerprint / dedup / ntfy / collect for persist.

In `test_mode`, fake score:

```python
{
  "deal_score": 9,
  "value_band": "steal",
  "useful_item_count": len(cands),
  "effective_price_per_useful_item": rough,
  "hunt_fit": True,
  "scam_risk": "low",
  "reason": "TEST MODE value haul",
  "reject_ids": [],
}
```

- [ ] **Step 4: Persist keep-bundles with `kind: keep_bundle`** and value hauls with `kind: value_haul` via `vh.value_haul_record`.

- [ ] **Step 5: Manual smoke (no commit required if no live keys)**

```bash
cd /home/rolki/projects/vinted-stuffs
SKIP_SCORING=1 NTFY_TOPIC=test uv run python scripts/vinted_bot.py
```

(`test_mode` is `SKIP_SCORING=1` in `main`.) Confirm stderr shows seed hunts as seeds and no crash.

- [ ] **Step 6: Commit**

```bash
git add scripts/vinted_bot.py
git commit -m "$(cat <<'EOF'
Wire value-haul discovery, scoring, and alerts into the bot run.

EOF
)"
```

---

### Task 7: Dashboard badge + seller stats

**Files:**
- Modify: `dashboard/app.js` (`renderBundles`)
- Modify: `dashboard/styles.css` (optional pill)
- Modify: `scripts/serve_dashboard.py` (bump score from value-haul rows)

**Interfaces:**
- Consumes: `bundle.kind` (`value_haul` | `keep_bundle` | missing → keep_bundle)

- [ ] **Step 1: Update `renderBundles` header**

In `dashboard/app.js`, inside the bundle `<article>`:

```javascript
    const kind = b.kind || "keep_bundle";
    const kindLabel = kind === "value_haul" ? "value haul" : "keep bundle";
    // in h3 or meta:
    // <span class="pill ${kind === "value_haul" ? "haul" : "keep"}">${kindLabel}</span>
```

Show `effective_price_per_useful_item` in meta when present:

```javascript
    const per = b.effective_price_per_useful_item != null
      ? ` · ~${Number(b.effective_price_per_useful_item).toFixed(0)} GBP/item`
      : "";
```

Update empty copy to mention value hauls.

- [ ] **Step 2: CSS** — reuse existing `.pill.keep` / add `.pill.haul` with a distinct but quiet color (not purple glow; match dashboard palette).

- [ ] **Step 3: `serve_dashboard.py`** — when iterating bundles, if `b.get("kind") == "value_haul"`, bump seller with `b.get("deal_score")` and `b.get("value_band")` once for the haul (and still count items).

```python
    for b in bundles if isinstance(bundles, list) else []:
        if b.get("kind") == "value_haul":
            bump(
                b.get("seller_id"),
                b.get("seller"),
                b.get("country"),
                b.get("deal_score"),
                b.get("value_band"),
                is_keep=b.get("value_band") in ("steal", "hunt"),
            )
        else:
            bump(b.get("seller_id"), b.get("seller"), b.get("country"), 0, None)
        for it in b.get("items") or []:
            ...
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/app.js dashboard/styles.css scripts/serve_dashboard.py
git commit -m "$(cat <<'EOF'
Show value hauls on the dashboard and count them for sellers.

EOF
)"
```

---

### Task 8: Regression sweep + spec status

**Files:**
- Modify: `docs/superpowers/specs/2026-09-05-value-haul-hunt-design.md` (status line → implemented)
- Run all unit tests

- [ ] **Step 1: Run full unit suite**

```bash
cd /home/rolki/projects/vinted-stuffs/scripts
uv run python -m unittest test_keep_rules test_bundle_pool test_value_haul test_profile_batch -v
```

Expected: all PASS.

- [ ] **Step 2: Spec status**

Change header `Status: approved for planning` → `Status: implemented`.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-09-05-value-haul-hunt-design.md
git commit -m "$(cat <<'EOF'
Mark value haul design implemented after unit verification.

EOF
)"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|---|---|
| Parallel pipeline; keep-bundles unchanged | 3, 6 |
| bundle_hunt seeds never solo alert/keep | 3, 6 |
| Path A + Path B discovery | 6 |
| Prefilter size + gym signals + cap | 2 |
| Gate ≥3 or ≥2+≤20 GBP | 2, 4 |
| One LLM haul score + prompt bands | 4, 6 |
| Alert predicate + reject_ids | 4 |
| ntfy distinct copy | 5, 6 |
| `kind` on best_bundles | 5, 6, 7 |
| Fingerprint dedup | 5, 6 |
| No value-haul pool writes | 6 (do not call pool for hauls) |
| Dashboard badge | 7 |
| Closet limit 36 for haul path | 6 |
| Unit tests listed in spec | 2, 3, 4, 5, 8 |
| CONTEXT terms | 1 |
| Config block + seed watch | 1 |

## Placeholder / consistency notes

- Import style for tests: run from `scripts/` as existing tests do (`import vinted_bot as bot`).
- `test_mode` is `SKIP_SCORING=1` in `main` — do not invent a second flag.
- Haul fingerprint shares `alerted_bundle_keys` with keep-bundles (same string shape `seller:ids`) as specified.
