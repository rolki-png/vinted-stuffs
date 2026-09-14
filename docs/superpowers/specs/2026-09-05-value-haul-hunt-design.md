# Value haul hunt

Date: 2026-09-05  
Status: implemented  
Repo: `vinted-stuffs` (bot in `scripts/vinted_bot.py`)

## Problem

The bot already finds **premium steals** (one listing worth shipping alone) and **keep-bundles** (at least one keep plus ride-along extras from the same seller).

It does **not** find **value hauls**: several ordinary gym pieces from one seller that become a strong deal only because shipping and buyer protection are paid once. Example: six H&M Sport tees at 100 GBP listing + ~27 GBP fees ≈ 21 GBP delivered per useful item — excellent wardrobe-building, weak as six solo scores.

Today that haul never alerts:

- Ordinary clothing at or under the solo floor (100 GBP) is not a keep unless `value_band` is `steal`.
- `assemble_bundles` requires at least one keep plus extras.
- Closet crawl exists, but everything still runs through the premium keep / extra rules.

## Goal

Add a parallel **value haul** path so the bot can alert when one seller has enough useful men's gym pieces in the buyer's sizes that the **delivered cost per useful item** is strong — without requiring any single keep.

Premium hunts and keep-bundles stay unchanged.

## Non-goals (v1)

- Value hauls for sneakers, knitwear, or maternity
- Relaxing `assemble_bundles` so extras-only keep-bundles form without a keep
- Cross-run pool merge for value hauls (“yesterday’s 2 + today’s 2”)
- Changing checkout-extra amounts (keep RO 25 / HU·PL 40 / default 25)

## Domain

Extend `CONTEXT.md` with:

| Term | Meaning |
|---|---|
| **Value haul** | Two or more useful gym pieces from one seller in one checkout, judged by delivered cost per useful item, not brand luxury. Persisted/alerted as `kind: value_haul`. |
| **Bundle hunt** | A watch with `bundle_hunt: true`. Its search hits are **seeds** only: they trigger closet inspection and never solo-alert or become keeps. |
| **Keep-bundle** | Existing bundle: ≥1 keep + extras. Persisted as `kind: keep_bundle`. |

Existing terms (keep, solo floor, closet crawl, checkout extra, seen key) stay as defined.

## Approaches considered

1. **Parallel value-haul pipeline** (chosen) — separate gate, one bundle-scoped LLM call, separate alert kind; keep path untouched.
2. Relax `assemble_bundles` to allow extras-only — reuses code but fights the current scorer’s premium bias and blurs meanings.
3. Config/prompt-only tweaks — cannot alert without a keep; does not close the gap.

## Architecture

Two discovery paths feed one evaluation pipeline:

```
[A] bundle_hunt watches              [B] existing men's gym hunts
    cheap/broad search                    search → per-item score
         │                                     │
         ▼                                     ▼
    seed listings                        hunt-fit → closet crawl (12)
    (never solo alert)                         │
         │                                     │
         ▼                                     │
    closet crawl (24–36) ◄─────────────────────┘
         │
         ▼
    per-seller prefilter (size + gym-ish signals)
         │
         ▼
    gate: ≥3 candidates  OR  ≥2 and rough delivered/item ≤ steal cap
         │
         ▼
    one LLM call: score_value_haul(...)
         │
         ▼
    alert if score ≥ 8, band steal|hunt, hunt_fit,
    and useful count still passes the gate
```

**Isolation**

| Unit | Does | Depends on |
|---|---|---|
| Bundle-hunt search | Emits seed item ids / sellers | Existing search CLI |
| Closet fetch | Active listings for a seller | Existing `get_seller_closets` |
| Prefilter + gate | Cheap candidate set; whether to call LLM | Config thresholds, size/title heuristics |
| `score_value_haul` | One LLM verdict for the cart | AI Gateway (same stack as item scorer) |
| Alert + persist | ntfy + `best_bundles` with `kind` | Fingerprint dedup state |

Premium `is_keep` / `assemble_bundles` are not called for value-haul decisions.

## Config

Global block (defaults):

```json
{
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
  }
}
```

Watch flag example (v1: one or two such watches):

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
}
```

Rules:

- If `bundle_hunt` is true, search hits never pass `is_keep` and never solo-alert.
- Path B uses the existing closet limit (12) unless the seller is already in a bundle-hunt crawl (then the higher limit applies for that fetch).
- Rough delivered/item for the gate: `(sum of candidate listing prices + checkout_extra_ron(seller_country)) / candidate_count`.
- Final useful count and per-useful price come from the LLM (after `reject_ids`).

## Prefilter

Before any LLM call, a listing may enter the candidate set if:

1. Size matches `target_sizes` (listing size field and/or title; allow ambiguous tokens like `M/L` when either side is wanted).
2. Title/brand looks gym-relevant (training/sport/gym/running tokens, known gym brands including mid-tier lines named in hunt notes) **or** clearly aligns with the seed watch `target_type` / `notes`.
3. Listing is active and has a parseable price.

Cap at `max_candidates_to_score` (prefer cheapest + strongest title fit) so the model does not see a dump of junk.

**Which hunt feeds the payload**

- Path A: the `bundle_hunt` watch that produced the seed (`target_type`, `target_sizes`, `notes`).
- Path B: the men's gym hunt that produced the hunt-fit trigger. Scoring still uses the value-haul prompt (not the per-item premium prompt); only the hunt metadata for fit judgment comes from that watch.

If both paths touch the same seller in one run, evaluate once: prefer Path A hunt metadata when a bundle-hunt seed was involved; otherwise Path B. One fingerprint, one LLM call.

## Gate

Call the LLM only if:

- `n >= min_items` (3), or
- `n >= min_items_steal` (2) **and** rough delivered/item ≤ `steal_max_delivered_per_item_ron` (20).

A single seed or single cheap tee never reaches the scorer as a haul.

## Bundle scorer

One LLM request per gated seller cart (not per item).

**Input shape**

```json
{
  "kind": "value_haul",
  "seller": "robert_k2000",
  "seller_country": "hu",
  "checkout_extra_ron": 40,
  "matching_items": 6,
  "total_listing_price": 100,
  "estimated_total": 140,
  "effective_price_per_item": 23.3,
  "items": [
    {
      "id": 1,
      "title": "H&M Sport póló",
      "brand": "H&M",
      "size": "M",
      "price": 16.67,
      "status": "Very good"
    }
  ],
  "hunt": {
    "target_type": "...",
    "target_sizes": ["M", "L"],
    "notes": "..."
  }
}
```

**Prompt rules (normative)**

- This is a BUNDLE / value haul hunt. Do not judge only by individual resale value.
- A haul can be outstanding when: at least three useful pieces fit the buyer (or two if delivered per useful item is steal-level); one shipping charge; low delivered cost per useful item; condition very good or better; pieces genuinely usable for gym/training; little filler.
- Ordinary gym brands: under ~30 GBP delivered per useful item = strong; under ~25 = excellent; around ~20 or less = steal.
- Reject hauls whose low price depends on wrong sizes, worn-out pieces, casual cotton tees with little gym value, or items the buyer is unlikely to use.

**Output**

```json
{
  "deal_score": 9,
  "value_band": "steal",
  "useful_item_count": 6,
  "effective_price_per_useful_item": 21.2,
  "hunt_fit": true,
  "scam_risk": "low",
  "reason": "...",
  "reject_ids": []
}
```

**Alert condition**

All of:

- `hunt_fit` is true
- `value_band` in `keep_value_bands` (steal, hunt)
- `deal_score` ≥ `min_deal_score` (8)
- `scam_risk` is not `high`
- After removing `reject_ids`, useful count still passes the same gate (using LLM `effective_price_per_useful_item` for the 2-item steal path)

## Alerts and persistence

- **ntfy**: dedicated copy, e.g. `value haul 6 @ robert_k2000: ~21 GBP/item (127 total)`, short reason, profile URL, item titles. Distinct from keep-bundle notifications.
- **`data/best_bundles.json`**: add `kind: "value_haul" | "keep_bundle"`. Existing rows without `kind` treat as `keep_bundle`.
- **Dedup**: reuse `alerted_bundle_keys` with fingerprint `seller_id:sorted_useful_ids` (exclude `reject_ids`).
- **Seen keys**: seed listings still recorded as `listing_id + hunt_name` so they are not re-processed as solo score targets; haul fingerprint is independent.
- **Bundle pool (v1)**: do **not** write value-haul members into `bundle_pool.json`. Closet crawls on later runs can rediscover still-listed items. Cross-run haul merge is deferred.

Cap alerts with `max_value_hauls_per_run` (default 3), separate from `max_bundles_per_run`.

## Dashboard

- Bundles view: badge or filter for `value_haul` vs `keep_bundle`.
- Top sellers: count value-haul finds toward seller stats.

## Error handling

- Closet fetch failure for one seller: skip that seller; continue the run (same spirit as today).
- LLM failure or unparseable JSON: no alert; log to stderr.
- Missing seller country: use checkout-extra `default`.

## Testing

Unit tests (no live Vinted/LLM):

1. Gate: 3 candidates → eligible; 2 at 18 GBP rough/item → eligible; 2 at 35 → not; 1 → not.
2. `bundle_hunt` seeds never satisfy `is_keep`.
3. Fingerprint uses useful ids only (`reject_ids` dropped).
4. Payload/prompt builder smoke test with fixed fixture items.

## Success criteria

- A robert_k2000-style cart (several M/L gym tees, ~20–25 GBP delivered each) can alert as a value haul with no keep.
- A lone 35 GBP H&M tee from a bundle-hunt watch never alerts.
- Existing premium solo keeps and keep-bundles behave as today.
- Value-haul and keep-bundle alerts are distinguishable in ntfy and the dashboard.

## Implementation notes

Primary code: `scripts/vinted_bot.py`, `scripts/config.json`, `CONTEXT.md`, tests under `scripts/test_*.py`, dashboard bundle rendering under `dashboard/` / `scripts/serve_dashboard.py` as needed.

Search and closet I/O stay on the existing vinted CLI path; no new scrape host.
