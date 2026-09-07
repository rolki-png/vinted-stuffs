# Buy-Utility Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace directly guessed 1–10 listing scores with explainable 0–100 purchase utility, uncertainty-aware global ranking, and reason-scoped buyer feedback.

**Architecture:** A new pure Python calculator converts structured LLM factor extraction into versioned utility scores and confidence intervals. The bot applies hard gates and bounded pairwise Bradley–Terry ranking, persists v2 and legacy fields side by side, and exports a mixed-history-safe read model. The dashboard displays v2 evidence and captures optional Remove reasons without treating unexplained removals as taste.

**Tech Stack:** Python 3.12, `unittest`, Vercel AI Gateway, Google GenAI, CockroachDB/Postgres via psycopg, TypeScript/React/TanStack Start, Node assertion scripts.

## Global Constraints

- `score_version = 2` identifies the new scoring semantics.
- The LLM must never emit aggregate `buy_score`; only deterministic Python may calculate it.
- `buy_score` is an integer 0–100 and is not presented as a purchase probability.
- Keeps require `buy_score >= 85`, `score_confidence >= 0.60`, `hunt_fit = true`, and `verification_concern != "block"`.
- Pairwise ranking changes order only; it cannot change qualification or `buy_score`.
- `value_band` retains its legacy price-versus-quality meaning; `buy_band` is the new behavior band.
- Legacy scores are never multiplied by ten or averaged/ranked with v2 scores.
- Seller history does not reduce purchase utility; authenticity/condition uncertainty is represented by `verification_concern`.
- Unexplained, `other`, and `sold_unavailable` Remove actions have no taste-learning effect.
- Use `uv run --project python` for Python commands; add no Python dependency for the calculator or ranker.

---

### Task 1: Deterministic utility calculator

**Files:**
- Create: `python/buy_score.py`
- Create: `python/tests/test_buy_score.py`
- Create: `python/tests/fixtures/buy_score_golden.json`
- Modify: `python/config.json:1-20`

**Interfaces:**
- Produces: `score_config(config: dict | None) -> dict`
- Produces: `calculate_buy_score(extraction: dict, delivered_cost_ron: float, config: dict | None = None) -> dict`
- Produces: `buy_band(score: int) -> str`
- Produces: `is_v2_score(score: dict) -> bool`
- Returned score keys: `score_version`, `buy_score`, `buy_band`, `score_confidence`, `score_interval_low`, `score_interval_high`, `score_factors`, `factor_evidence`, `verification_concern`, `verification_reason`, `hunt_fit`, `reason`

- [ ] **Step 1: Write calculator tests**

Create `python/tests/test_buy_score.py` with table-driven tests for value monotonicity, confidence shrinkage, score bands, brand independence, bounds, personal-adjustment caps, and invalid replacement cost:

```python
import path_setup  # noqa: F401
import json
import unittest
from pathlib import Path

import buy_score as bs


def extraction(**overrides):
    factors = {
        "fit_probability": {"value": 0.95, "confidence": 0.9, "evidence": "target size"},
        "usefulness": {"value": 92, "confidence": 0.9, "evidence": "daily role"},
        "quality": {"value": 90, "confidence": 0.8, "evidence": "documented material"},
        "condition": {"value": 95, "confidence": 0.9, "evidence": "new without tags"},
        "versatility": {"value": 90, "confidence": 0.8, "evidence": "several settings"},
        "equivalent_replacement_cost": {
            "value": 450,
            "currency": "RON",
            "confidence": 0.8,
            "evidence": "conservative equivalent",
        },
        "duplication_probability": {"value": 0.05, "confidence": 0.8, "evidence": "new role"},
    }
    factors.update(overrides.pop("factors", {}))
    return {
        "id": 1,
        "hunt_fit": True,
        "verification_concern": "none",
        "verification_reason": "",
        "reason": "strong daily purchase",
        "factors": factors,
        "personal_adjustments": overrides.pop("personal_adjustments", {}),
        **overrides,
    }


class BuyScoreTests(unittest.TestCase):
    def test_higher_delivered_cost_cannot_improve_score(self):
        low = bs.calculate_buy_score(extraction(), 100, {})
        high = bs.calculate_buy_score(extraction(), 200, {})
        self.assertGreater(low["buy_score"], high["buy_score"])

    def test_missing_quality_shrinks_to_neutral_and_lowers_confidence(self):
        known = bs.calculate_buy_score(extraction(), 100, {})
        missing = extraction(
            factors={"quality": {"value": 50, "confidence": 0, "evidence": "unknown"}}
        )
        unknown = bs.calculate_buy_score(missing, 100, {})
        self.assertLess(unknown["buy_score"], known["buy_score"])
        self.assertLess(unknown["score_confidence"], known["score_confidence"])

    def test_brand_is_not_a_calculator_input(self):
        plain = bs.calculate_buy_score(extraction(brand="H&M"), 100, {})
        premium = bs.calculate_buy_score(extraction(brand="Lululemon"), 100, {})
        self.assertEqual(plain["buy_score"], premium["buy_score"])

    def test_adjustment_is_scoped_and_capped(self):
        row = bs.calculate_buy_score(
            extraction(personal_adjustments={"quality": -80, "value": 80}),
            100,
            {},
        )
        self.assertEqual(row["score_factors"]["personal_adjustments"]["quality"], -10)
        self.assertEqual(row["score_factors"]["personal_adjustments"]["value"], 10)

    def test_invalid_replacement_cost_is_not_keepable(self):
        row = bs.calculate_buy_score(
            extraction(
                factors={
                    "equivalent_replacement_cost": {
                        "value": 0,
                        "currency": "RON",
                        "confidence": 1,
                        "evidence": "invalid",
                    }
                }
            ),
            100,
            {},
        )
        self.assertEqual(row["buy_band"], "skip")
        self.assertEqual(row["verification_concern"], "block")

    def test_buy_bands(self):
        self.assertEqual(bs.buy_band(59), "skip")
        self.assertEqual(bs.buy_band(60), "bundle")
        self.assertEqual(bs.buy_band(75), "good")
        self.assertEqual(bs.buy_band(85), "keep")
        self.assertEqual(bs.buy_band(95), "exceptional")

    def test_cross_hunt_golden_examples(self):
        path = Path(__file__).parent / "fixtures" / "buy_score_golden.json"
        cases = json.loads(path.read_text())
        results = {
            case["name"]: bs.calculate_buy_score(
                case["extraction"], case["delivered_cost_ron"], {}
            )
            for case in cases
        }
        for case in cases:
            self.assertEqual(results[case["name"]]["buy_band"], case["expected_band"])
            if case.get("better_than"):
                self.assertGreater(
                    results[case["name"]]["buy_score"],
                    results[case["better_than"]]["buy_score"],
                )


if __name__ == "__main__":
    unittest.main()
```

Create `python/tests/fixtures/buy_score_golden.json` with buyer-reviewable cross-hunt
anchors:

```json
[
  {
    "name": "hm_daily_right_fit",
    "delivered_cost_ron": 60,
    "expected_band": "good",
    "better_than": "lululemon_worn_wrong_role",
    "extraction": {
      "id": 1,
      "hunt_fit": true,
      "verification_concern": "none",
      "reason": "useful daily layer",
      "factors": {
        "fit_probability": {"value": 0.95, "confidence": 1, "evidence": "known size"},
        "usefulness": {"value": 95, "confidence": 1, "evidence": "daily role"},
        "quality": {"value": 70, "confidence": 1, "evidence": "adequate construction"},
        "condition": {"value": 95, "confidence": 1, "evidence": "unused"},
        "versatility": {"value": 90, "confidence": 1, "evidence": "many settings"},
        "equivalent_replacement_cost": {"value": 150, "currency": "RON", "confidence": 1, "evidence": "equivalent daily item"},
        "duplication_probability": {"value": 0.1, "confidence": 1, "evidence": "distinct role"}
      }
    }
  },
  {
    "name": "lululemon_worn_wrong_role",
    "delivered_cost_ron": 120,
    "expected_band": "skip",
    "extraction": {
      "id": 2,
      "hunt_fit": true,
      "verification_concern": "inspect",
      "reason": "premium label but worn and rarely useful",
      "factors": {
        "fit_probability": {"value": 0.8, "confidence": 1, "evidence": "uncertain cut"},
        "usefulness": {"value": 60, "confidence": 1, "evidence": "occasional role"},
        "quality": {"value": 75, "confidence": 1, "evidence": "older technical line"},
        "condition": {"value": 40, "confidence": 1, "evidence": "visible wear"},
        "versatility": {"value": 70, "confidence": 1, "evidence": "gym only"},
        "equivalent_replacement_cost": {"value": 300, "currency": "RON", "confidence": 1, "evidence": "equivalent used piece"},
        "duplication_probability": {"value": 0.2, "confidence": 1, "evidence": "similar item owned"}
      }
    }
  },
  {
    "name": "maternity_daily_postpartum",
    "delivered_cost_ron": 100,
    "expected_band": "keep",
    "extraction": {
      "id": 3,
      "hunt_fit": true,
      "verification_concern": "none",
      "reason": "high-use maternity and postpartum piece",
      "factors": {
        "fit_probability": {"value": 0.98, "confidence": 1, "evidence": "exact target size"},
        "usefulness": {"value": 98, "confidence": 1, "evidence": "daily and postpartum"},
        "quality": {"value": 90, "confidence": 1, "evidence": "maternity construction"},
        "condition": {"value": 95, "confidence": 1, "evidence": "unused"},
        "versatility": {"value": 95, "confidence": 1, "evidence": "pregnancy and nursing"},
        "equivalent_replacement_cost": {"value": 450, "currency": "RON", "confidence": 1, "evidence": "conservative equivalent"},
        "duplication_probability": {"value": 0, "confidence": 1, "evidence": "needed role"}
      }
    }
  },
  {
    "name": "sneaker_exceptional_use",
    "delivered_cost_ron": 150,
    "expected_band": "keep",
    "better_than": "hm_daily_right_fit",
    "extraction": {
      "id": 4,
      "hunt_fit": true,
      "verification_concern": "none",
      "reason": "excellent durable everyday sneaker",
      "factors": {
        "fit_probability": {"value": 1, "confidence": 1, "evidence": "known model and size"},
        "usefulness": {"value": 95, "confidence": 1, "evidence": "frequent wear"},
        "quality": {"value": 95, "confidence": 1, "evidence": "durable construction"},
        "condition": {"value": 98, "confidence": 1, "evidence": "near new"},
        "versatility": {"value": 90, "confidence": 1, "evidence": "daily outfits"},
        "equivalent_replacement_cost": {"value": 700, "currency": "RON", "confidence": 1, "evidence": "same-tier replacement"},
        "duplication_probability": {"value": 0.02, "confidence": 1, "evidence": "needed rotation"}
      }
    }
  }
]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
uv run --project python python -m unittest python.tests.test_buy_score -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'buy_score'`.

- [ ] **Step 3: Implement the pure calculator**

Create `python/buy_score.py`. Use these defaults and formulas exactly:

```python
from __future__ import annotations

import math
from typing import Any

SCORE_VERSION = 2
FACTOR_WEIGHTS = {
    "usefulness": 0.30,
    "quality": 0.20,
    "condition": 0.15,
    "versatility": 0.10,
    "value": 0.25,
}
DEFAULTS = {
    "keep_min_score": 85,
    "bundle_min_score": 60,
    "min_keep_confidence": 0.60,
    "duplication_penalty": 15.0,
    "absolute_saving_full_scale_ron": 200.0,
    "personal_adjustment_cap": 10.0,
}
VALID_VERIFICATION = {"none", "inspect", "block"}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def score_config(config: dict | None) -> dict:
    raw = (config or {}).get("buy_scoring") or {}
    out = dict(DEFAULTS)
    out.update({key: raw[key] for key in DEFAULTS if key in raw})
    out["factor_weights"] = dict(FACTOR_WEIGHTS)
    supplied = raw.get("factor_weights")
    if isinstance(supplied, dict):
        out["factor_weights"].update(
            {key: float(supplied[key]) for key in FACTOR_WEIGHTS if key in supplied}
        )
    total = sum(out["factor_weights"].values())
    if not math.isclose(total, 1.0, abs_tol=1e-9):
        raise ValueError("buy_scoring.factor_weights must sum to 1")
    return out


def _number(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _factor(raw: dict, key: str, *, probability: bool = False) -> tuple[float, float, str]:
    field = raw.get(key) if isinstance(raw.get(key), dict) else {}
    neutral = 0.5 if probability else 50.0
    high = 1.0 if probability else 100.0
    value = clamp(_number(field.get("value"), neutral), 0.0, high)
    confidence = clamp(_number(field.get("confidence"), 0.0), 0.0, 1.0)
    adjusted = neutral + confidence * (value - neutral)
    return adjusted, confidence, str(field.get("evidence") or "unknown")[:240]


def buy_band(score: int) -> str:
    if score >= 95:
        return "exceptional"
    if score >= 85:
        return "keep"
    if score >= 75:
        return "good"
    if score >= 60:
        return "bundle"
    return "skip"


def is_v2_score(score: dict) -> bool:
    return int(score.get("score_version") or 0) == SCORE_VERSION and score.get("buy_score") is not None


def calculate_buy_score(
    extraction: dict,
    delivered_cost_ron: float,
    config: dict | None = None,
) -> dict:
    cfg = score_config(config)
    raw = extraction.get("factors") if isinstance(extraction.get("factors"), dict) else {}
    delivered = max(0.0, _number(delivered_cost_ron, 0.0))
    replacement_field = (
        raw.get("equivalent_replacement_cost")
        if isinstance(raw.get("equivalent_replacement_cost"), dict)
        else {}
    )
    replacement = _number(replacement_field.get("value"), 0.0)
    replacement_confidence = clamp(
        _number(replacement_field.get("confidence"), 0.0), 0.0, 1.0
    )
    invalid_value = replacement <= 0
    if invalid_value:
        value_raw = 0.0
        replacement_confidence = 0.0
    else:
        saving = replacement - delivered
        relative = clamp(50.0 + 50.0 * saving / replacement, 0.0, 100.0)
        absolute = clamp(
            50.0
            + 50.0 * saving / float(cfg["absolute_saving_full_scale_ron"]),
            0.0,
            100.0,
        )
        value_raw = 0.60 * relative + 0.40 * absolute
    values: dict[str, float] = {}
    confidences: dict[str, float] = {}
    evidence: dict[str, str] = {}
    for key in ("usefulness", "quality", "condition", "versatility"):
        values[key], confidences[key], evidence[key] = _factor(raw, key)
    values["value"] = 50.0 + replacement_confidence * (value_raw - 50.0)
    confidences["value"] = replacement_confidence
    evidence["value"] = str(replacement_field.get("evidence") or "unknown")[:240]
    fit, fit_confidence, fit_evidence = _factor(raw, "fit_probability", probability=True)
    duplicate, duplicate_confidence, duplicate_evidence = _factor(
        raw, "duplication_probability", probability=True
    )
    requested = extraction.get("personal_adjustments")
    requested = requested if isinstance(requested, dict) else {}
    applied: dict[str, float] = {}
    cap = float(cfg["personal_adjustment_cap"])
    for key in ("usefulness", "quality", "condition", "versatility", "value"):
        adjustment = clamp(_number(requested.get(key), 0.0), -cap, cap)
        values[key] = clamp(values[key] + adjustment, 0.0, 100.0)
        applied[key] = adjustment
    fit_adjustment = clamp(_number(requested.get("fit_probability"), 0.0), -cap, cap)
    duplicate_adjustment = clamp(
        _number(requested.get("duplication_probability"), 0.0), -cap, cap
    )
    fit = clamp(fit + fit_adjustment / 100.0, 0.0, 1.0)
    duplicate = clamp(duplicate + duplicate_adjustment / 100.0, 0.0, 1.0)
    applied["fit_probability"] = fit_adjustment
    applied["duplication_probability"] = duplicate_adjustment
    base = sum(cfg["factor_weights"][key] * values[key] for key in FACTOR_WEIGHTS)
    raw_utility = fit * base - float(cfg["duplication_penalty"]) * duplicate
    score = 0 if invalid_value else round(clamp(raw_utility, 0.0, 100.0))
    sigma_fit = 0.25 * (1.0 - fit_confidence)
    sigma_duplicate = 0.25 * (1.0 - duplicate_confidence)
    variance = (base * sigma_fit) ** 2
    variance += sum(
        (fit * cfg["factor_weights"][key] * 25.0 * (1.0 - confidences[key])) ** 2
        for key in FACTOR_WEIGHTS
    )
    variance += (float(cfg["duplication_penalty"]) * sigma_duplicate) ** 2
    half_width = 1.645 * math.sqrt(variance)
    score_confidence = min(
        fit_confidence,
        sum(cfg["factor_weights"][key] * confidences[key] for key in FACTOR_WEIGHTS),
    )
    verification = str(extraction.get("verification_concern") or "none").lower()
    verification = verification if verification in VALID_VERIFICATION else "block"
    if invalid_value:
        verification = "block"
    return {
        "id": extraction.get("id"),
        "score_version": SCORE_VERSION,
        "buy_score": score,
        "buy_band": buy_band(score),
        "score_confidence": round(score_confidence, 4),
        "score_interval_low": round(clamp(raw_utility - half_width, 0.0, 100.0)),
        "score_interval_high": round(clamp(raw_utility + half_width, 0.0, 100.0)),
        "score_factors": {
            **values,
            "fit_probability": round(fit, 4),
            "duplication_probability": round(duplicate, 4),
            "delivered_cost_ron": round(delivered, 2),
            "equivalent_replacement_cost_ron": round(replacement, 2),
            "personal_adjustments": applied,
        },
        "factor_evidence": {
            **evidence,
            "fit_probability": fit_evidence,
            "duplication_probability": duplicate_evidence,
        },
        "verification_concern": verification,
        "verification_reason": str(extraction.get("verification_reason") or "")[:240],
        "hunt_fit": extraction.get("hunt_fit") is True,
        "reason": str(extraction.get("reason") or "")[:240],
    }
```

- [ ] **Step 4: Add versioned scoring configuration**

Add this top-level block to `python/config.json`:

```json
"buy_scoring": {
  "score_version": 2,
  "keep_min_score": 85,
  "bundle_min_score": 60,
  "min_keep_confidence": 0.6,
  "duplication_penalty": 15,
  "absolute_saving_full_scale_ron": 200,
  "personal_adjustment_cap": 10,
  "pairwise_max_candidates": 20,
  "pairwise_neighbors": 2,
  "factor_weights": {
    "usefulness": 0.3,
    "quality": 0.2,
    "condition": 0.15,
    "versatility": 0.1,
    "value": 0.25
  }
},
```

- [ ] **Step 5: Run calculator and config tests**

Run:

```bash
uv run --project python python -m unittest python.tests.test_buy_score -v
node scripts/test-hunt-config.mjs
```

Expected: all `test_buy_score` cases pass and `ok hunt-config` prints.

- [ ] **Step 6: Commit**

```bash
git add python/buy_score.py python/tests/test_buy_score.py \
  python/tests/fixtures/buy_score_golden.json python/config.json
git commit -m "feat: add deterministic buy utility calculator"
```

---

### Task 2: Versioned score persistence

**Files:**
- Create: `python/sql/003_buy_utility_scores.sql`
- Modify: `python/scored_store.py:10-108, 178-339, 479-518`
- Modify: `python/tests/test_scored_store.py`

**Interfaces:**
- Consumes: the score dictionary returned by `buy_score.calculate_buy_score`
- Produces: `row_from_item_score(...)` that persists either legacy or v2 scores
- Produces: cached/exported v2 fields with JSON objects, not JSON strings
- Invariant: listing-only upserts never erase either legacy or v2 score data

- [ ] **Step 1: Add failing persistence tests**

Extend `python/tests/test_scored_store.py`:

```python
    def test_v2_round_trip_preserves_structured_score(self):
        score = {
            "id": 99,
            "score_version": 2,
            "buy_score": 88,
            "buy_band": "keep",
            "score_confidence": 0.74,
            "score_interval_low": 82,
            "score_interval_high": 93,
            "score_factors": {"quality": 84, "value": 91},
            "factor_evidence": {"quality": "dense fabric"},
            "verification_concern": "inspect",
            "verification_reason": "confirm care label",
            "hunt_fit": True,
            "reason": "high expected use",
            "rank_position": 2,
            "rank_confidence": "medium",
        }
        row = ss.row_from_item_score(
            {
                "id": 99,
                "title": "technical shorts",
                "price": {"amount": "80", "currency_code": "RON"},
                "user": {"id": 7, "login": "seller"},
                "_profile": {"country_code": "ro"},
            },
            score,
            "Gym",
            "search",
        )
        store = ss.MemoryScoredStore()
        store.upsert_score(row)
        cached = ss.candidate_from_cached(store.load_by_seller(7)[0], {"name": "Gym"})
        exported = ss.export_row(store.load_by_seller(7)[0])
        self.assertEqual(cached["score"]["buy_score"], 88)
        self.assertEqual(cached["score"]["score_factors"]["quality"], 84)
        self.assertEqual(exported["score_version"], 2)
        self.assertEqual(exported["buy_band"], "keep")
        self.assertIsNone(exported["deal_score"])

    def test_listing_only_upsert_does_not_wipe_v2_score(self):
        store = ss.MemoryScoredStore()
        scored = ss.row_from_item_score(
            {
                "id": 101,
                "title": "dress",
                "price": {"amount": "90", "currency_code": "RON"},
                "user": {"id": 8, "login": "seller"},
                "_profile": {"country_code": "ro"},
            },
            {
                "score_version": 2,
                "buy_score": 90,
                "buy_band": "keep",
                "score_confidence": 0.8,
                "score_interval_low": 86,
                "score_interval_high": 94,
                "score_factors": {},
                "factor_evidence": {},
                "verification_concern": "none",
                "verification_reason": "",
                "hunt_fit": True,
                "reason": "strong",
            },
            "Maternity",
            "search",
        )
        store.upsert_score(scored)
        store.upsert_score(
            ss.row_from_item(
                {
                    "id": 101,
                    "title": "dress updated",
                    "price": {"amount": "85", "currency_code": "RON"},
                    "user": {"id": 8, "login": "seller"},
                    "_profile": {"country_code": "ro"},
                },
                "Maternity",
                "backfill",
            )
        )
        loaded = store.load_by_seller(8)[0]
        self.assertEqual(loaded["buy_score"], 90)
        self.assertEqual(loaded["title"], "dress updated")
```

- [ ] **Step 2: Run the persistence tests and verify they fail**

Run:

```bash
uv run --project python python -m unittest python.tests.test_scored_store -v
```

Expected: FAIL because v2 fields are absent from cached/exported rows.

- [ ] **Step 3: Add the additive Cockroach migration**

Create `python/sql/003_buy_utility_scores.sql`:

```sql
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS score_version INT NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS buy_score INT NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS buy_band TEXT NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS score_confidence DOUBLE PRECISION NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS score_interval_low INT NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS score_interval_high INT NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS score_factors JSONB NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS factor_evidence JSONB NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS verification_concern TEXT NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS verification_reason TEXT NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS rank_position INT NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS rank_confidence TEXT NULL;

CREATE INDEX IF NOT EXISTS scored_listings_v2_rank_idx
  ON scored_listings (score_version, rank_position)
  WHERE score_version = 2;
```

- [ ] **Step 4: Extend Python DDL, queries, and adapters**

In `python/scored_store.py`, add the twelve columns to `DDL`, `ALTERS`,
`UPSERT_SQL`, `LOAD_BY_SELLER_SQL`, and `LOAD_RECENT_SQL`. For scored upserts,
update all v2 columns only when `EXCLUDED.has_score` is true. Add helpers:

```python
import json

V2_FIELDS = (
    "score_version",
    "buy_score",
    "buy_band",
    "score_confidence",
    "score_interval_low",
    "score_interval_high",
    "score_factors",
    "factor_evidence",
    "verification_concern",
    "verification_reason",
    "rank_position",
    "rank_confidence",
)


def _json_object(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
```

`row_from_item()` initializes all `V2_FIELDS` to `None`.
`row_from_item_score()` branches on `score_version == 2`: v2 rows copy all v2
fields, set `deal_score`, `value_band`, and `scam_risk` to `None`, and retain
`hunt_fit`/`reason`; legacy rows preserve current behavior. Serialize the two JSON
parameters with `json.dumps()` before SQL execution and decode them in
`candidate_from_cached()` and `export_row()`. Extend `MemoryScoredStore` scored-field
merging with `V2_FIELDS`.

- [ ] **Step 5: Keep v2 and legacy index bundles separate**

Change `index_bundle_opportunities()` to partition rows by
`(seller_id, "v2" if score_version == 2 else "legacy")`. For v2 groups:

```python
def _bundle_eligible(row: dict) -> bool:
    if int(row.get("score_version") or 0) == 2:
        return (
            row.get("hunt_fit") is True
            and row.get("buy_band") in {"bundle", "good", "keep", "exceptional"}
            and row.get("verification_concern") != "block"
        )
    return (
        row.get("hunt_fit") is not False
        and row.get("value_band") != "skip"
        and (not row.get("has_score") or int(row.get("deal_score") or 0) >= 6)
    )


def _bundle_is_keep(row: dict) -> bool:
    if int(row.get("score_version") or 0) == 2:
        return (
            int(row.get("buy_score") or 0) >= 85
            and float(row.get("score_confidence") or 0) >= 0.60
            and row.get("verification_concern") != "block"
        )
    return (
        int(row.get("deal_score") or 0) >= 9
        and row.get("value_band") in {"steal", "hunt"}
    )
```

Sort/dedupe v2 members by `buy_score`; sort/dedupe legacy groups by `deal_score`.
Include `score_version`, `buy_score`, `buy_band`, intervals, and rank on each
exported bundle item.

- [ ] **Step 6: Run persistence tests**

Run:

```bash
uv run --project python python -m unittest python.tests.test_scored_store -v
```

Expected: all persistence, cache revival, and bundle-opportunity tests pass.

- [ ] **Step 7: Commit**

```bash
git add python/sql/003_buy_utility_scores.sql python/scored_store.py python/tests/test_scored_store.py
git commit -m "feat: persist versioned buy utility scores"
```

---

### Task 3: Reason-coded feedback and conservative taste input

**Files:**
- Create: `python/sql/004_listing_veto_reason.sql`
- Modify: `python/listing_vetoes.py`
- Modify: `python/taste_learning.py`
- Modify: `python/tests/test_listing_vetoes.py`
- Modify: `python/tests/test_taste_learning.py`
- Create: `src/server/listingFeedback.js`
- Modify: `src/server/listingVetoes.ts`
- Modify: `src/routes/api/veto.ts`
- Create: `scripts/test-listing-veto-reasons.mjs`
- Modify: `package.json:8-18`

**Interfaces:**
- Produces: `VALID_REMOVE_REASONS`
- Changes: `set_status(item_id, status, enrichment=None, reason_code=None)`
- Changes: `setVetoStatus(itemId, status, enrichment, reasonCode = null)`
- Produces: `build_taste_prompt_block()` that excludes unreasoned removals and only emits a negative reason after three same-family examples

- [ ] **Step 1: Add failing Python feedback tests**

Add tests asserting:

```python
    def test_remove_reason_round_trip_and_no_stale_reason(self):
        store = lv.MemoryVetoStore()
        store.set_status(1, "removed", {"hunt_family": "gym"}, "poor_value")
        self.assertEqual(store.load_outcomes()[0]["reason_code"], "poor_value")
        store.set_status(1, "bought", {"hunt_family": "gym"})
        self.assertIsNone(store.load_outcomes()[0]["reason_code"])

    def test_invalid_remove_reason_rejected(self):
        store = lv.MemoryVetoStore()
        with self.assertRaisesRegex(ValueError, "invalid remove reason"):
            store.set_status(1, "removed", {}, "brand_bad")
```

Replace broad-Remove taste tests with:

```python
    def test_unreasoned_and_nonlearning_removes_are_excluded(self):
        block = tl.build_taste_prompt_block(
            [
                {"status": "removed", "reason_code": None, "title": "unknown"},
                {"status": "removed", "reason_code": "other", "title": "other"},
                {"status": "removed", "reason_code": "sold_unavailable", "title": "sold"},
            ]
        )
        self.assertEqual(block, "")

    def test_three_consistent_reasons_emit_factor_scoped_guidance(self):
        rows = [
            {
                "status": "removed",
                "reason_code": "poor_value",
                "hunt_family": "gym",
                "title": f"shorts {i}",
                "brand": "Nike",
                "size": "L",
            }
            for i in range(3)
        ]
        block = tl.build_taste_prompt_block(rows)
        self.assertIn("poor_value", block)
        self.assertIn("value adjustment only", block)
```

- [ ] **Step 2: Run Python feedback tests and verify failure**

Run:

```bash
uv run --project python python -m unittest \
  python.tests.test_listing_vetoes python.tests.test_taste_learning -v
```

Expected: FAIL because `reason_code` is unsupported and unreasoned Remove still
appears as a strong negative.

- [ ] **Step 3: Add reason schema and Python store support**

Create `python/sql/004_listing_veto_reason.sql`:

```sql
ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS reason_code TEXT NULL;
```

In `python/listing_vetoes.py` define:

```python
VALID_REMOVE_REASONS = frozenset({
    "sold_unavailable",
    "wrong_size",
    "bad_fit_style",
    "low_quality_condition",
    "poor_value",
    "rarely_useful",
    "already_own_similar",
    "other",
})


def coerce_reason(status: str, reason_code: str | None) -> str | None:
    if status != STATUS_REMOVED or reason_code is None or str(reason_code).strip() == "":
        return None
    reason = str(reason_code).strip()
    if reason not in VALID_REMOVE_REASONS:
        raise ValueError(f"invalid remove reason: {reason}")
    return reason
```

Add `reason_code` to DDL, ALTER, INSERT/UPSERT, SELECT, in-memory rows, and outcome
column lists. Always overwrite `reason_code` on status changes so Bought/Park cannot
retain an old Remove reason.

- [ ] **Step 4: Replace ambiguous taste learning**

In `python/taste_learning.py`:

- delete generic `Removed (strong negative)` behavior;
- include Bought as positive context;
- group removed outcomes by `reason_code`;
- discard omitted, `other`, and `sold_unavailable`;
- include a negative group only when at least three examples share that reason in
  the already family-filtered outcome list;
- emit one of these exact scope labels:

```python
REASON_SCOPES = {
    "wrong_size": "fit_probability adjustment only",
    "bad_fit_style": "fit_probability adjustment only",
    "low_quality_condition": "quality/condition adjustment only",
    "poor_value": "value adjustment only",
    "rarely_useful": "usefulness adjustment only",
    "already_own_similar": "duplication_probability adjustment only",
}
```

Remove `hard_suppress()` and the bot call path that treats a repeated unexplained
brand/size Remove as a veto. V2 personalization is bounded by calculator-validated
`personal_adjustments`; legacy candidates receive no newly inferred hard veto.

- [ ] **Step 5: Add failing Node reason tests**

Create `scripts/test-listing-veto-reasons.mjs`:

```javascript
import assert from "node:assert/strict"
import {
  coerceRemoveReason,
  feedbackParams,
} from "../src/server/listingFeedback.js"

assert.equal(coerceRemoveReason("removed", "poor_value"), "poor_value")
assert.equal(coerceRemoveReason("removed", null), null)
assert.equal(coerceRemoveReason("bought", "poor_value"), null)
assert.throws(
  () => coerceRemoveReason("removed", "brand_bad"),
  /invalid_remove_reason/,
)
assert.deepEqual(
  feedbackParams(7, "removed", {}, "rarely_useful").slice(0, 3),
  [7, "removed", "rarely_useful"],
)
console.log("ok listing-veto-reasons")
```

Create `src/server/listingFeedback.js`:

```javascript
const VALID_REMOVE_REASONS = new Set([
  "sold_unavailable",
  "wrong_size",
  "bad_fit_style",
  "low_quality_condition",
  "poor_value",
  "rarely_useful",
  "already_own_similar",
  "other",
])

function coerceRemoveReason(status, reasonCode) {
  if (status !== "removed" || reasonCode == null || String(reasonCode).trim() === "") {
    return null
  }
  const reason = String(reasonCode).trim()
  if (!VALID_REMOVE_REASONS.has(reason)) {
    const error = new Error("invalid_remove_reason")
    error.status = 400
    throw error
  }
  return reason
}

function feedbackParams(itemId, status, enrichment, reasonCode) {
  const id = Number(itemId)
  if (!Number.isFinite(id)) {
    const error = new Error("invalid_item_id")
    error.status = 400
    throw error
  }
  return [id, status, coerceRemoveReason(status, reasonCode), enrichment || {}]
}

export { VALID_REMOVE_REASONS, coerceRemoveReason, feedbackParams }
```

Import those pure helpers in `src/server/listingVetoes.ts` and make
`setVetoStatus()` use them. Add the schema column and bind it as the third SQL
parameter. In `src/routes/api/veto.ts`, pass
`body.reason_code ?? body.reasonCode ?? null`.

Add this script to `test:desk` before the existing scripts:

```json
"test:desk": "node scripts/test-listing-veto-reasons.mjs && node scripts/assert-no-react-void-meta.mjs && node scripts/test-github-contents-json.mjs && node scripts/test-hunt-config.mjs && node scripts/test-github-config-put.mjs"
```

- [ ] **Step 6: Run feedback tests**

Run:

```bash
uv run --project python python -m unittest \
  python.tests.test_listing_vetoes python.tests.test_taste_learning -v
npm run test:desk
```

Expected: Python tests pass and the Node run includes
`ok listing-veto-reasons`.

- [ ] **Step 7: Commit**

```bash
git add python/sql/004_listing_veto_reason.sql python/listing_vetoes.py \
  python/taste_learning.py python/tests/test_listing_vetoes.py \
  python/tests/test_taste_learning.py src/server/listingFeedback.js \
  src/server/listingVetoes.ts \
  src/routes/api/veto.ts scripts/test-listing-veto-reasons.mjs package.json
git commit -m "feat: capture reason-scoped listing feedback"
```

---

### Task 4: Structured scorer and v2 qualification

**Files:**
- Modify: `python/vinted_bot.py:503-768, 1160-1255, 1377-1422, 1556-1619, 1999-2083, 2178-2217`
- Modify: `python/tests/test_keep_rules.py`
- Create: `python/tests/test_scoring_prompt.py`

**Interfaces:**
- Consumes: `buy_score.calculate_buy_score()`
- Produces: `_extraction_prompt(watch, items, taste_block="") -> str`
- Produces: `normalize_extractions(extractions, items, watch, config) -> list[dict]`
- Changes: `score_listings(..., config: dict, taste_block="")` returns calculated v2 scores
- Changes: `is_keep()` and `is_bundle_extra()` use v2 semantics, with explicit legacy fallback only for legacy cached rows

- [ ] **Step 1: Write prompt and qualification tests**

Create `python/tests/test_scoring_prompt.py`:

```python
import path_setup  # noqa: F401
import json
import unittest

import vinted_bot as bot


class ScoringPromptTests(unittest.TestCase):
    def setUp(self):
        self.watch = {
            "name": "Gym",
            "query": "gym shorts",
            "target_type": "men's gym shorts",
            "target_sizes": ["M", "L"],
            "notes": "technical shorts",
            "hunt_price": 100,
            "price_to": 180,
            "country": "ro",
        }
        self.items = [{
            "id": 1,
            "title": "Lululemon shorts",
            "price": {"amount": "80", "currency_code": "RON"},
            "brand_title": "Lululemon",
            "size_title": "L",
            "status": "Very good",
            "_profile": {"country_code": "ro"},
        }]

    def test_prompt_requests_factors_but_not_buy_score(self):
        prompt = bot._extraction_prompt(self.watch, self.items)
        self.assertIn("equivalent_replacement_cost", prompt)
        self.assertIn("duplication_probability", prompt)
        self.assertNotIn('"buy_score"', prompt)
        self.assertIn("brand alone", prompt.lower())

    def test_normalization_calculates_delivered_cost(self):
        extracted = [{
            "id": 1,
            "hunt_fit": True,
            "verification_concern": "none",
            "verification_reason": "",
            "reason": "useful",
            "personal_adjustments": {},
            "factors": {
                "fit_probability": {"value": 1, "confidence": 1, "evidence": "L"},
                "usefulness": {"value": 90, "confidence": 1, "evidence": "daily"},
                "quality": {"value": 90, "confidence": 1, "evidence": "material"},
                "condition": {"value": 90, "confidence": 1, "evidence": "very good"},
                "versatility": {"value": 90, "confidence": 1, "evidence": "broad"},
                "equivalent_replacement_cost": {
                    "value": 400, "currency": "RON", "confidence": 1, "evidence": "equivalent"
                },
                "duplication_probability": {"value": 0, "confidence": 1, "evidence": "none"},
            },
        }]
        scores = bot.normalize_extractions(extracted, self.items, self.watch, {
            "checkout_fees": {
                "ro": {
                    "estimated_shipping_ron": 15,
                    "buyer_fee_fixed_ron": 3,
                    "buyer_fee_pct": 0.05,
                }
            }
        })
        self.assertEqual(scores[0]["score_factors"]["delivered_cost_ron"], 102)
        self.assertEqual(scores[0]["score_version"], 2)


if __name__ == "__main__":
    unittest.main()
```

Replace legacy keep tests with v2 fixtures and retain one explicit legacy fixture:

```python
def v2(score=88, confidence=0.8, concern="none", hunt_fit=True):
    return {
        "score_version": 2,
        "buy_score": score,
        "buy_band": "keep" if score < 95 else "exceptional",
        "score_confidence": confidence,
        "hunt_fit": hunt_fit,
        "verification_concern": concern,
    }


class KeepRuleTests(unittest.TestCase):
    def test_v2_keep_requires_score_confidence_fit_and_clear_verification(self):
        watch = {"target_type": "men's gym clothing"}
        self.assertTrue(bot.is_keep(v2(), CONFIG, watch, {}))
        self.assertFalse(bot.is_keep(v2(score=84), CONFIG, watch, {}))
        self.assertFalse(bot.is_keep(v2(confidence=0.59), CONFIG, watch, {}))
        self.assertFalse(bot.is_keep(v2(concern="block"), CONFIG, watch, {}))
        self.assertFalse(bot.is_keep(v2(hunt_fit=False), CONFIG, watch, {}))

    def test_v2_bundle_extra_uses_buy_band(self):
        self.assertTrue(bot.is_bundle_extra({
            "score_version": 2,
            "buy_score": 68,
            "buy_band": "bundle",
            "hunt_fit": True,
            "verification_concern": "none",
        }, CONFIG))
```

- [ ] **Step 2: Run prompt/qualification tests and verify failure**

Run:

```bash
uv run --project python python -m unittest \
  python.tests.test_scoring_prompt python.tests.test_keep_rules -v
```

Expected: FAIL because `_extraction_prompt` and `normalize_extractions` do not exist
and keep logic still depends on `deal_score`/`scam_risk`.

- [ ] **Step 3: Replace the listing scoring prompt**

Replace `SCORING_PROMPT` with a factor-extraction prompt that defines this output
shape and explicitly forbids `buy_score`:

```text
Return one object per listing:
{
  "id": <listing id>,
  "hunt_fit": <boolean>,
  "verification_concern": "none" | "inspect" | "block",
  "verification_reason": "<evidence or empty>",
  "reason": "<one sentence purchase assessment>",
  "personal_adjustments": {
    "fit_probability": <-10..10>,
    "usefulness": <-10..10>,
    "quality": <-10..10>,
    "condition": <-10..10>,
    "versatility": <-10..10>,
    "value": <-10..10>,
    "duplication_probability": <-10..10>
  },
  "factors": {
    "fit_probability": {"value": <0..1>, "confidence": <0..1>, "evidence": "<short>"},
    "usefulness": {"value": <0..100>, "confidence": <0..1>, "evidence": "<short>"},
    "quality": {"value": <0..100>, "confidence": <0..1>, "evidence": "<short>"},
    "condition": {"value": <0..100>, "confidence": <0..1>, "evidence": "<short>"},
    "versatility": {"value": <0..100>, "confidence": <0..1>, "evidence": "<short>"},
    "equivalent_replacement_cost": {
      "value": <positive amount>,
      "currency": "RON",
      "confidence": <0..1>,
      "evidence": "<conservative equivalent>"
    },
    "duplication_probability": {"value": <0..1>, "confidence": <0..1>, "evidence": "<short>"}
  }
}
Never return buy_score. Do not reward brand or MSRP alone. Estimate a conservative
equivalent replacement, not aspirational retail. Seller age/history is not a utility
penalty. Use verification_concern only for item identity, authenticity, material
condition, or missing evidence.
```

Retain target type, sizes, hunt notes, maternity/gym hard exclusions, listing payload,
and reason-scoped taste block. Rename the builder `_extraction_prompt`; keep
`_scoring_prompt = _extraction_prompt` temporarily for callers/tests outside this
branch.

- [ ] **Step 4: Calculate v2 output after extraction**

Add:

```python
def normalize_extractions(
    extractions: list,
    items: list,
    watch: dict,
    config: dict,
) -> list:
    import buy_score as buy_score_mod

    by_id = {str(item.get("id")): item for item in items}
    out = []
    for extraction in extractions:
        item = by_id.get(str(extraction.get("id")))
        if not item:
            continue
        amount = listing_amount(item)
        if amount is None:
            continue
        country = _country(watch)
        delivered = amount + checkout_extra_ron(country, config, amount)
        out.append(
            buy_score_mod.calculate_buy_score(
                extraction,
                delivered_cost_ron=delivered,
                config=config,
            )
        )
    return out
```

Make Gateway/Gemini functions parse extraction objects. Make `score_listings()`
accept `config` and call `normalize_extractions()` before returning. If Gateway
returns malformed/empty factor output, use the existing Gemini fallback. If both
fail, return an empty list so the listing remains unscored rather than qualifying.

- [ ] **Step 5: Replace v2 keep, bundle, selection, snapshot logic**

At the start of `is_keep()` and `is_bundle_extra()`, branch on
`buy_score.is_v2_score(score)`. V2 keep logic is:

```python
cfg = buy_score_mod.score_config(config)
return (
    not watch.get("bundle_hunt")
    and score.get("hunt_fit") is True
    and int(score.get("buy_score") or 0) >= int(cfg["keep_min_score"])
    and float(score.get("score_confidence") or 0) >= float(cfg["min_keep_confidence"])
    and score.get("verification_concern") != "block"
)
```

V2 bundle extras require `buy_score >= bundle_min_score`, `hunt_fit`, and no block.
Keep the legacy branch only for cached/history rows without `score_version = 2`.
Update `select_best`, closet selection, bundle member serialization, best-deal
serialization, last-run top rows, and histograms to prefer `buy_score` for v2.
Store v2 histograms in ten-point keys (`"0-9"` through `"90-100"`) and include
`score_version` in `last_run.json`.

Update solo and bundle ntfy text to show `buy_score`, interval, `buy_band`, and
`verification_concern` for v2 rows. Preserve the current `/10` message only for
legacy rows. A v2 notification must never index `score["deal_score"]` or
`score["scam_risk"]`.

Change test-mode fake scores to valid v2 factor extraction followed by the real
calculator; do not hard-code `buy_score`.

- [ ] **Step 6: Run scorer and bot unit tests**

Run:

```bash
uv run --project python python -m unittest discover -s python/tests -v
```

Expected: all Python tests pass.

- [ ] **Step 7: Commit**

```bash
git add python/vinted_bot.py python/tests/test_keep_rules.py \
  python/tests/test_scoring_prompt.py
git commit -m "feat: score listings with structured purchase utility"
```

---

### Task 5: Uncertainty-aware Bradley–Terry shortlist ranking

**Files:**
- Create: `python/buy_ranking.py`
- Create: `python/tests/test_buy_ranking.py`
- Modify: `python/vinted_bot.py:1182-1255, 1999-2034`

**Interfaces:**
- Produces: `comparison_pairs(candidates: list[dict], config: dict) -> list[tuple[str, str]]`
- Produces: `bradley_terry_rank(candidate_ids: list[str], outcomes: list[dict]) -> list[str]`
- Produces: `rank_candidates(candidates, gateway_key, gemini_client, config) -> list[dict]`
- Candidate identity is `(item.id, watch)` serialized as `"<id>:<watch>"`, avoiding collisions when one listing is scored under multiple hunts.

- [ ] **Step 1: Write ranking tests**

Create `python/tests/test_buy_ranking.py`:

```python
import path_setup  # noqa: F401
import unittest

import buy_ranking as br


def candidate(iid, score, low, high, watch="H"):
    return {
        "item": {"id": iid, "title": str(iid)},
        "watch": watch,
        "score": {
            "score_version": 2,
            "buy_score": score,
            "buy_band": "keep",
            "score_confidence": 0.8,
            "score_interval_low": low,
            "score_interval_high": high,
            "verification_concern": "none",
            "hunt_fit": True,
        },
    }


class RankingTests(unittest.TestCase):
    def test_pairs_only_overlapping_qualified_neighbors(self):
        rows = [
            candidate(1, 92, 87, 96),
            candidate(2, 89, 85, 93),
            candidate(3, 85, 83, 87),
            candidate(4, 84, 80, 88),
        ]
        pairs = br.comparison_pairs(rows, {"buy_scoring": {"pairwise_neighbors": 1}})
        flattened = {key for pair in pairs for key in pair}
        self.assertNotIn("4:H", flattened)
        self.assertIn(("1:H", "2:H"), pairs)
        self.assertNotIn(("1:H", "3:H"), pairs)

    def test_bradley_terry_orders_pairwise_winner(self):
        order = br.bradley_terry_rank(
            ["1:H", "2:H", "3:H"],
            [
                {"left": "1:H", "right": "2:H", "winner": "left"},
                {"left": "1:H", "right": "3:H", "winner": "left"},
                {"left": "2:H", "right": "3:H", "winner": "left"},
            ],
        )
        self.assertEqual(order, ["1:H", "2:H", "3:H"])

    def test_empty_outcomes_fall_back_to_score_order(self):
        ranked = br.apply_rankings(
            [candidate(2, 88, 84, 92), candidate(1, 91, 87, 95)],
            [],
        )
        self.assertEqual([r["score"]["rank_position"] for r in ranked], [2, 1])
        self.assertTrue(all(r["score"]["rank_confidence"] == "low" for r in ranked))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run ranking tests and verify failure**

Run:

```bash
uv run --project python python -m unittest python.tests.test_buy_ranking -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'buy_ranking'`.

- [ ] **Step 3: Implement candidate selection and Bradley–Terry fitting**

Create `python/buy_ranking.py` with:

```python
from __future__ import annotations

from collections import defaultdict


def candidate_key(candidate: dict) -> str:
    return f"{candidate['item'].get('id')}:{candidate.get('watch') or ''}"


def _qualified(candidate: dict) -> bool:
    score = candidate.get("score") or {}
    return (
        int(score.get("score_version") or 0) == 2
        and int(score.get("buy_score") or 0) >= 85
        and float(score.get("score_confidence") or 0) >= 0.60
        and score.get("hunt_fit") is True
        and score.get("verification_concern") != "block"
    )


def _overlap(left: dict, right: dict) -> bool:
    ls, rs = left["score"], right["score"]
    return int(ls.get("score_interval_low") or 0) <= int(rs.get("score_interval_high") or 0) and int(
        rs.get("score_interval_low") or 0
    ) <= int(ls.get("score_interval_high") or 0)


def comparison_pairs(candidates: list[dict], config: dict) -> list[tuple[str, str]]:
    cfg = (config or {}).get("buy_scoring") or {}
    limit = int(cfg.get("pairwise_max_candidates", 20))
    neighbors = int(cfg.get("pairwise_neighbors", 2))
    rows = sorted(
        (row for row in candidates if _qualified(row)),
        key=lambda row: int(row["score"].get("buy_score") or 0),
        reverse=True,
    )[:limit]
    pairs = []
    for index, left in enumerate(rows):
        for right in rows[index + 1:index + 1 + neighbors]:
            if _overlap(left, right):
                pairs.append((candidate_key(left), candidate_key(right)))
    return pairs


def bradley_terry_rank(candidate_ids: list[str], outcomes: list[dict]) -> list[str]:
    strengths = {key: 1.0 for key in candidate_ids}
    wins = defaultdict(float)
    games = defaultdict(lambda: defaultdict(int))
    for outcome in outcomes:
        left, right = outcome.get("left"), outcome.get("right")
        if left not in strengths or right not in strengths or left == right:
            continue
        games[left][right] += 1
        games[right][left] += 1
        winner = outcome.get("winner")
        if winner == "left":
            wins[left] += 1.0
        elif winner == "right":
            wins[right] += 1.0
        elif winner == "tie":
            wins[left] += 0.5
            wins[right] += 0.5
    for _ in range(100):
        updated = {}
        for key in candidate_ids:
            denominator = sum(
                count / max(strengths[key] + strengths[other], 1e-9)
                for other, count in games[key].items()
            )
            updated[key] = wins[key] / denominator if denominator and wins[key] else 1e-6
        scale = sum(updated.values()) / max(len(updated), 1)
        strengths = {key: value / max(scale, 1e-9) for key, value in updated.items()}
    return sorted(candidate_ids, key=lambda key: (-strengths[key], key))


def _connected(candidate_ids: list[str], outcomes: list[dict]) -> bool:
    if len(candidate_ids) < 2:
        return True
    graph = {key: set() for key in candidate_ids}
    for outcome in outcomes:
        left, right = outcome.get("left"), outcome.get("right")
        if left in graph and right in graph and left != right:
            graph[left].add(right)
            graph[right].add(left)
    seen = set()
    pending = [candidate_ids[0]]
    while pending:
        key = pending.pop()
        if key in seen:
            continue
        seen.add(key)
        pending.extend(graph[key] - seen)
    return seen == set(candidate_ids)


def apply_rankings(candidates: list[dict], outcomes: list[dict]) -> list[dict]:
    qualified = [row for row in candidates if _qualified(row)]
    fallback = sorted(
        qualified,
        key=lambda row: (-int(row["score"].get("buy_score") or 0), candidate_key(row)),
    )
    ids = [candidate_key(row) for row in fallback]
    usable = bool(outcomes) and _connected(ids, outcomes)
    order = bradley_terry_rank(ids, outcomes) if usable else ids
    position = {key: index + 1 for index, key in enumerate(order)}
    mean_confidence = (
        sum(float(row.get("confidence") or 0) for row in outcomes) / len(outcomes)
        if usable
        else 0
    )
    confidence = (
        "high"
        if mean_confidence >= 0.80
        else "medium"
        if mean_confidence >= 0.60
        else "low"
    )
    for row in qualified:
        row["score"]["rank_position"] = position[candidate_key(row)]
        row["score"]["rank_confidence"] = confidence
    return candidates
```

- [ ] **Step 4: Add one batched pairwise model call**

In `vinted_bot.py`, create a prompt containing only requested pairs and each
candidate's title, hunt, score factors, evidence, delivered price, and interval.
Require:

```json
{
  "comparisons": [
    {
      "left": "123:Gym",
      "right": "456:Maternity",
      "winner": "left",
      "confidence": 0.74,
      "reason": "higher expected everyday use"
    }
  ]
}
```

Accept only requested keys and `winner` in `left|right|tie`. Try Gateway, then
Gemini. Return `[]` after both fail. Call this after `merged` is assembled and
veto-suppressed but before bundle/solo selection. Apply ranks globally to active v2
keep candidates, then upsert ranked rows so rank fields reach Cockroach and exports.

- [ ] **Step 5: Run ranking and full Python tests**

Run:

```bash
uv run --project python python -m unittest \
  python.tests.test_buy_ranking -v
uv run --project python python -m unittest discover -s python/tests -v
```

Expected: all tests pass; no pairwise test changes `buy_score` or qualifies score 84.

- [ ] **Step 6: Commit**

```bash
git add python/buy_ranking.py python/tests/test_buy_ranking.py python/vinted_bot.py
git commit -m "feat: rank close buy candidates pairwise"
```

---

### Task 6: Mixed-history-safe dashboard read model

**Files:**
- Create: `src/server/scoreSemantics.js`
- Create: `scripts/test-score-semantics.mjs`
- Modify: `src/server/scoredDb.ts`
- Modify: `src/server/snapshot.ts`
- Modify: `package.json`

**Interfaces:**
- Produces: `isV2(row)`, `displayScore(row)`, `isKeep(row)`, `histogramBins(histogram)`
- Dashboard find rows expose all v2 fields and `legacy_score: boolean`
- Seller aggregates prefer v2 rows and never mix scales

- [ ] **Step 1: Write failing read-model tests**

Create `scripts/test-score-semantics.mjs`:

```javascript
import assert from "node:assert/strict"
import {
  displayScore,
  isKeep,
  sellerScoreRows,
  histogramBins,
} from "../src/server/scoreSemantics.js"

const v2 = {
  score_version: 2,
  buy_score: 88,
  buy_band: "keep",
  score_confidence: 0.7,
  hunt_fit: true,
  verification_concern: "none",
}
const legacy = { deal_score: 9, value_band: "steal", hunt_fit: true }
assert.equal(displayScore(v2), 88)
assert.equal(displayScore(legacy), 9)
assert.equal(isKeep(v2), true)
assert.equal(isKeep({ ...v2, score_confidence: 0.59 }), false)
assert.deepEqual(sellerScoreRows([legacy, v2]), [v2])
assert.deepEqual(
  histogramBins({ "80-89": 4, "90-100": 2 }),
  [
    { label: "80–89", count: 4 },
    { label: "90–100", count: 2 },
  ],
)
console.log("ok score-semantics")
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```bash
node scripts/test-score-semantics.mjs
```

Expected: FAIL with module-not-found for `scoreSemantics.js`.

- [ ] **Step 3: Implement shared score semantics**

Create `src/server/scoreSemantics.js`:

```javascript
function isV2(row) {
  return Number(row?.score_version || 0) === 2 && Number.isFinite(Number(row?.buy_score))
}

function displayScore(row) {
  if (isV2(row)) return Number(row.buy_score)
  const legacy = Number(row?.deal_score)
  return Number.isFinite(legacy) ? legacy : null
}

function isKeep(row) {
  if (isV2(row)) {
    return (
      Number(row.buy_score) >= 85 &&
      Number(row.score_confidence || 0) >= 0.6 &&
      row.hunt_fit === true &&
      row.verification_concern !== "block"
    )
  }
  return (
    Number(row?.deal_score || 0) >= 9 &&
    (row?.value_band === "steal" || row?.value_band === "hunt")
  )
}

function sellerScoreRows(rows) {
  const v2 = (rows || []).filter(isV2)
  return v2.length ? v2 : (rows || []).filter((row) => !isV2(row))
}

function histogramBins(histogram) {
  return Object.entries(histogram || {})
    .filter(([label]) => /^\d+-\d+$/.test(label))
    .sort(([left], [right]) => Number(left.split("-")[0]) - Number(right.split("-")[0]))
    .map(([label, count]) => ({
      label: label.replace("-", "–"),
      count: Number(count || 0),
    }))
}

export { isV2, displayScore, isKeep, sellerScoreRows, histogramBins }
```

- [ ] **Step 4: Export v2 DB fields**

Extend `src/server/scoredDb.ts` SELECT/export with all twelve v2 columns. JSONB
fields should remain objects. Set `legacy_score: !isV2(row)`. Partition index bundle
opportunities by version as in Python and use `buy_score`/`buy_band` only for v2
groups.

- [ ] **Step 5: Prevent scale mixing in snapshot aggregation**

In `src/server/snapshot.ts`, carry v2 fields through keep, index, last-run, pool,
and bundle merges. When deduping the same listing, prefer v2 over legacy regardless
of source. Build each seller's aggregate from `sellerScoreRows()` and use
`displayScore()`. Count keeps with `isKeep()`. Preserve legacy display rows but
never include them in a v2 seller average or v2 sort tie-break.

- [ ] **Step 6: Add the script to desk tests and verify**

Add `node scripts/test-score-semantics.mjs` to `test:desk`, then run:

```bash
npm run test:desk
npm run build
```

Expected: scripts print `ok`, including `ok score-semantics`, and Vite build exits 0.

- [ ] **Step 7: Commit**

```bash
git add src/server/scoreSemantics.js scripts/test-score-semantics.mjs \
  src/server/scoredDb.ts src/server/snapshot.ts package.json
git commit -m "feat: expose version-safe utility scores to the desk"
```

---

### Task 7: Utility evidence and optional Remove reasons in the desk

**Files:**
- Create: `src/components/scoreView.js`
- Create: `scripts/test-score-view.mjs`
- Modify: `src/components/DealDesk.tsx`
- Modify: `src/styles.css`
- Modify: `package.json`

**Interfaces:**
- Produces: `scoreLabel(find)`, `filterScore(find)`, `findComparator(sort)`
- `VetoButtons.onSet(id, status, reasonCode?)`
- Remove remains one-click, with an optional reason selector immediately beside it

- [ ] **Step 1: Write failing presentation-helper tests**

Create `scripts/test-score-view.mjs`:

```javascript
import assert from "node:assert/strict"
import {
  scoreLabel,
  numericScore,
  histogramRows,
} from "../src/components/scoreView.js"

assert.equal(
  scoreLabel({
    score_version: 2,
    buy_score: 87,
    score_interval_low: 82,
    score_interval_high: 92,
  }),
  "87 (82–92)",
)
assert.equal(scoreLabel({ deal_score: 9 }), "9 legacy")
assert.equal(numericScore({ score_version: 2, buy_score: 87 }), 87)
assert.equal(numericScore({ deal_score: 9 }), 9)
assert.deepEqual(histogramRows({ "80-89": 3, "90-100": 1 }), [
  { label: "80–89", count: 3 },
  { label: "90–100", count: 1 },
])
console.log("ok score-view")
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```bash
node scripts/test-score-view.mjs
```

Expected: FAIL with module-not-found for `scoreView.js`.

- [ ] **Step 3: Implement presentation helpers**

Create `src/components/scoreView.js`:

```javascript
function isV2(row) {
  return Number(row?.score_version || 0) === 2 && row?.buy_score != null
}

function numericScore(row) {
  const value = isV2(row) ? Number(row.buy_score) : Number(row?.deal_score)
  return Number.isFinite(value) ? value : 0
}

function scoreLabel(row) {
  if (!isV2(row)) return row?.deal_score == null ? "—" : `${row.deal_score} legacy`
  const low = Number(row.score_interval_low)
  const high = Number(row.score_interval_high)
  if (Number.isFinite(low) && Number.isFinite(high)) {
    return `${row.buy_score} (${low}–${high})`
  }
  return String(row.buy_score)
}

function histogramRows(histogram) {
  return Object.entries(histogram || {})
    .filter(([label]) => /^\d+-\d+$/.test(label))
    .sort(([left], [right]) => Number(left.split("-")[0]) - Number(right.split("-")[0]))
    .map(([label, count]) => ({ label: label.replace("-", "–"), count: Number(count || 0) }))
}

export { isV2, numericScore, scoreLabel, histogramRows }
```

- [ ] **Step 4: Update score display, filters, ranking, and evidence**

Extend `Find`/`BundleItem` types with v2 fields. In `DealDesk.tsx`:

- filter/sort v2 rows using `buy_score` and rank position, while legacy rows remain
  labelled and sort below v2 when displaying the global utility order;
- replace filter options with `60+`, `75+`, `85+`, `95+`; applying a 60+ v2 filter
  excludes legacy rows rather than comparing 9 with 60;
- show `scoreLabel()`, confidence, `buy_band`, rank, verification concern, and
  expandable factor/evidence rows;
- show legacy `value_band` only as supporting history;
- rename the Risk column to Verification;
- render histogram ten-point bins from the v2 run histogram.

Use a `<details>` block per v2 row:

```tsx
<details className="score-evidence">
  <summary>Why this score</summary>
  {Object.entries(f.score_factors || {})
    .filter(([key, value]) => typeof value === 'number' && !key.endsWith('_ron'))
    .map(([key, value]) => (
      <div className="factor-row" key={key}>
        <span>{key.replaceAll('_', ' ')}</span>
        <strong>{Number(value).toFixed(key.includes('probability') ? 2 : 0)}</strong>
        <small>{f.factor_evidence?.[key] || ''}</small>
      </div>
    ))}
</details>
```

- [ ] **Step 5: Add optional one-tap Remove reason**

Add this constant:

```tsx
const REMOVE_REASONS = [
  ['', 'No reason'],
  ['sold_unavailable', 'Sold / unavailable'],
  ['wrong_size', 'Wrong size'],
  ['bad_fit_style', 'Bad fit / style'],
  ['low_quality_condition', 'Low quality / condition'],
  ['poor_value', 'Poor value'],
  ['rarely_useful', 'Rarely useful'],
  ['already_own_similar', 'Already own similar'],
  ['other', 'Other'],
] as const
```

`VetoButtons` owns a selected reason string. Render the selector beside Remove and
pass `reasonCode || undefined` when clicked. Extend `setVetoStatus` to send
`reason_code` only for Removed. Bought/Park/Undo remain unchanged.

- [ ] **Step 6: Style evidence and reason controls**

Add focused styles:

```css
.score-evidence { margin-top: 0.35rem; color: var(--muted); }
.score-evidence summary { cursor: pointer; font-size: 0.8rem; }
.factor-row {
  display: grid;
  grid-template-columns: minmax(8rem, 1fr) 3rem minmax(12rem, 2fr);
  gap: 0.5rem;
  padding: 0.2rem 0;
}
.remove-controls { display: inline-flex; gap: 0.35rem; align-items: center; }
.remove-reason { max-width: 10rem; font: 500 0.8rem var(--sans); }
.legacy-score { color: var(--muted); font-size: 0.72rem; }
.verification-inspect { color: var(--hunt); }
.verification-block { color: var(--danger); }
```

- [ ] **Step 7: Run desk tests and build**

Add `node scripts/test-score-view.mjs` to `test:desk`, then run:

```bash
npm run test:desk
npm run check
npm run build
```

Expected: helper scripts print `ok`, Prettier check passes, and Vite build exits 0.

- [ ] **Step 8: Commit**

```bash
git add src/components/scoreView.js scripts/test-score-view.mjs \
  src/components/DealDesk.tsx src/styles.css package.json
git commit -m "feat: show utility evidence and removal reasons"
```

---

### Task 8: Active legacy rescore and rollout documentation

**Files:**
- Modify: `python/backfill_scored_listings.py`
- Create: `python/tests/test_backfill_scored_listings.py`
- Modify: `README.md`
- Modify: `CONTEXT.md`

**Interfaces:**
- Produces: `legacy_active_pairs(store, watch_by_name) -> list[tuple[str, str]]`
- CLI flag: `--legacy-active-v2`
- Selection: every scored dashboard row without `score_version = 2`
- Availability-check before any paid scoring call

- [ ] **Step 1: Write failing migration-selection tests**

Create `python/tests/test_backfill_scored_listings.py`:

```python
import path_setup  # noqa: F401
import unittest

import backfill_scored_listings as backfill


class FakeStore:
    def load_recent(self, limit):
        return [
            {"item_id": 1, "hunt_name": "Gym", "deal_score": 9, "score_version": None, "has_score": True, "reason": ""},
            {"item_id": 2, "hunt_name": "Gym", "deal_score": 7, "score_version": None, "has_score": True, "reason": ""},
            {"item_id": 3, "hunt_name": "Gym", "deal_score": 10, "score_version": 2, "has_score": True, "reason": ""},
            {"item_id": 4, "hunt_name": "Removed Hunt", "deal_score": 9, "score_version": None, "has_score": True, "reason": ""},
            {"item_id": 5, "hunt_name": "Gym", "deal_score": 1, "score_version": None, "has_score": True, "reason": "unavailable during backfill"},
        ]


class BackfillV2Tests(unittest.TestCase):
    def test_selects_all_scored_legacy_rows_for_active_hunts(self):
        pairs = backfill.legacy_active_pairs(FakeStore(), {"Gym": {"name": "Gym"}})
        self.assertEqual(pairs, [("1", "Gym"), ("2", "Gym")])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run migration test and verify failure**

Run:

```bash
uv run --project python python -m unittest \
  python.tests.test_backfill_scored_listings -v
```

Expected: FAIL because `legacy_active_pairs` does not exist.

- [ ] **Step 3: Implement the explicit v2 rescore mode**

Add:

```python
def legacy_active_pairs(store, watch_by_name: dict) -> list[tuple[str, str]]:
    rows = store.load_recent(50000)
    pairs = []
    for row in rows:
        hunt = row.get("hunt_name")
        if hunt not in watch_by_name:
            continue
        if not row.get("has_score"):
            continue
        if int(row.get("score_version") or 0) == 2:
            continue
        if row.get("reason") == "unavailable during backfill":
            continue
        pairs.append((str(row["item_id"]), str(hunt)))
    return sorted(set(pairs))
```

Add `--legacy-active-v2`. When set, use this pair source instead of seen-key
pending selection. Fetch availability first, score only live rows through the v2
`score_listings(..., config=config)` path, and upsert. Do not write v2 tombstones for
unavailable legacy rows; preserve their history. Production rollout repeats bounded
batches until every still-active dashboard row has `score_version = 2`.

- [ ] **Step 4: Update domain and operation docs**

In `CONTEXT.md`, redefine Keep as v2 `buy_score >= 85` with medium/high confidence,
document `buy_band`, and state that legacy 1–10 rows are display-only history.
Replace generic Remove strong-negative language with reason-scoped behavior.

In `README.md`:

- describe calculated utility and pairwise rank;
- remove “missing seller history is elevated scam risk”;
- document the manual rollout command:

```bash
uv run --project python python python/backfill_scored_listings.py \
  --legacy-active-v2 --limit 10000 --export
```

- update Python test instructions:

```bash
uv run --project python python -m unittest discover -s python/tests -v
```

- [ ] **Step 5: Run migration and full verification**

Run:

```bash
uv run --project python python -m unittest discover -s python/tests -v
npm run test:desk
npm run check
npm run build
git diff --check
```

Expected: all Python tests pass; Node scripts print `ok`; Prettier and Vite pass;
`git diff --check` emits no output.

Do not execute the paid `--legacy-active-v2` operation in automated tests or
during implementation without configured credentials and an explicit rollout run.

- [ ] **Step 6: Commit**

```bash
git add python/backfill_scored_listings.py \
  python/tests/test_backfill_scored_listings.py README.md CONTEXT.md
git commit -m "feat: add safe v2 legacy-score rollout"
```

---

## Final integration verification

- [ ] Run the complete Python and desk suites:

```bash
uv run --project python python -m unittest discover -s python/tests -v
npm run test:desk
npm run check
npm run build
```

- [ ] Inspect one synthetic v2 row through `row_from_item_score()` → memory store →
`export_row()` → dashboard score helpers and confirm these values survive:
`buy_score`, interval, confidence, factors/evidence, verification, and rank.

- [ ] Confirm a legacy score 9 and v2 score 88 are both visible but never averaged,
pair-compared, or threshold-compared.

- [ ] Confirm an unexplained Remove is persisted with `reason_code = NULL` and does
not appear in the negative taste block.

- [ ] Confirm score 84 never alerts even if pairwise comparisons prefer it.

- [ ] Review `git diff --check` and `git status --short`, then push all commits and
update the draft pull request without overwriting human-edited PR text.
