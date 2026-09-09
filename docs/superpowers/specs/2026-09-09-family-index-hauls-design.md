# Family index hauls (scored same-seller carts)

Date: 2026-09-09
Status: approved for planning
Repo: `vinted-stuffs`
Depends on: `2026-09-07-bundle-checkout-ranking-design.md`, hunt-family resolution (`tasteLearning` / `taste_learning`)
Supersedes (partial): checkout-ranking non-goal “do not score `index_near_bundle`”.

## Problem

The desk already scores individual Mamalicious (and other family) listings, and
many sellers have several hunt-fit pieces. Bundles still fail the buyer:

1. A classic keep-bundle needs a Keep (`buy_score` ≥ 85) plus extras ≥ 60.
   Wardrobe sellers often have several 60–84 pieces and **no Keep**, so they
   never become a hunt-time keep-bundle.
2. The score-cache assembler groups **all** eligible listings from a seller into
   one cart, mixing families.
3. Carts without a Keep are stored as `index_near_bundle` with **`bundle_score`
   always null**, so Best sort cannot rank them.

The buyer wants one maternity (or gym, …) ranked list of **same-seller hauls**
that save a second checkout extra — including carts with no crème Keep.

## Goal

This round: rebuild index carts from **already scored** listings, keyed by
**seller + hunt family**, members at the existing extra bar (`buy_score` ≥ 60,
hunt fit, v2, not blocked). **Score every such cart**, including no-Keep
`index_near_bundle`. Filter Bundles by family; sort Best.

Success: a seller with three Mamalicious hunt-fit listings at 71, 68, and 64
appears as one scored maternity haul; a gym extra from the same seller is a
separate gym cart (or omitted if that family has fewer than two members).

## Non-goals

- Closet crawl expansion (more of each seller’s wardrobe). Follow-up.
- Scoring hunt-time `near_haul` (still fee-gate / unscored until crawl work).
- Changing listing Keep rules, `bundle_min_score` (stays 60), or offer math.
- ntfy for index family hauls.
- Auto-sending Vinted offers.
- Cross-run merge of sold/unlisted items (still current scored rows only).
- Pairwise ranking between bundles.

## Decisions

| Topic | Decision |
|---|---|
| Member bar | v2, `hunt_fit === true`, `verification_concern != "block"`, `buy_score` ≥ 60 (`buy_band` in bundle / good / keep / exceptional) |
| Group key | `seller_id` + hunt family (`resolveFamily` on hunt name; same needles as Finds Family) |
| Dedup | One listing id per cart; keep the higher `buy_score` if scored on two hunts |
| Min size | 2 members |
| Kinds | `index_keep_bundle` if at least one Keep **and** at least one extra; otherwise `index_near_bundle` (no-Keep wardrobe haul, now scored) |
| Unranked kinds | `near_haul` only (plus carts with no valid v2 members) |
| Formula | Existing keep-anchored extras/fee-relief; for `index_near_bundle` the anchor is the best eligible member |
| Desk | Bundles Family filter; persist `family` on the cart row |
| Hunt-time keep-bundles / value hauls | Unchanged grouping and scoring |
| Data source | Live `scoredDb.indexBundleOpportunities` and Python `index_bundle_opportunities` stay equivalent |

## Grouping

```
scored listings (v2, hunt fit, ≥60, not block)
        │
        ▼
  group by (seller_id, family)
        │
        ▼
  dedup item_id (max buy_score)
        │
        ▼
  drop groups with < 2 members
        │
        ├─ has Keep and extra → index_keep_bundle
        └─ else               → index_near_bundle
        │
        ▼
  apply bundle_score + offer fields + family
```

Family is `resolveFamily(hunt_name)` (maternity, gym, sneakers, knitwear, other).
A seller can emit **zero or more** index carts, at most one per family.

Skip-band hunt-fit listings do not join. They remain on Finds only.

## Scoring

Remove `index_near_bundle` from `UNRANKED_KINDS` in `python/bundle_score.py` and
`src/server/bundleScore.js`.

- Eligible members: v2 `buy_score` 0–100, not blocked, with usable confidence
  (existing `_eligible_members`).
- **`index_keep_bundle` / `keep_bundle`:** anchor = max Keep-qualified member,
  else best eligible (existing fallback).
- **`index_near_bundle` / `value_haul`:** anchor = max eligible member.
- Extras term and clamp unchanged (`bundle_scoring` in config).
- `assign_bundle_ranks` then includes these carts in Best order.

`near_haul` stays `bundle_score: null`.

## Desk

- Bundles tab: Family `<select>` (All + the five families). Filter carts by
  `family`. Changing family does not clear hunt-time kinds that lack family
  until those rows get `family` filled from the first item’s hunt name
  (apply `resolveFamily` when assembling **and** when presenting if missing).
- Sort Best uses existing `bundle_score` (scored first; remaining nulls sink).
- Card shows family label plus existing Bundle N / rank.
- Finds Family filter unchanged.

## Persistence / snapshot

No new table. Index carts are derived each snapshot from scored listings
(Cockroach on Vercel; Python export path locally / bot). Git `best_bundles.json`
hunt-time rows still merge in; they are not regrouped by family this round.

## Error handling

- Missing `seller_id`: listing cannot join a cart.
- Unknown hunt name → family `other`.
- Mixed-family listing ids cannot exist in one cart by construction.
- If JS and Python assemblers diverge, tests that share the same fixture fail.

## Testing (public seams)

1. `index_bundle_opportunities` / `indexBundleOpportunities`: family split +
   no-Keep scored haul + skip-band excluded.
2. `calculate_bundle_score` / JS equivalent: `index_near_bundle` returns a
   finite score when members are v2 ≥ 60.
3. Deal desk presentation: Family control on Bundles; maternity filter hides a
   gym-only cart.

Do not mock internal collaborators. Fixture listings with known scores.

## Follow-up (explicitly later)

Closet crawl: for sellers who already have a family haul or a family seed,
fetch more wardrobe items, score against hunts in that family, then rebuild.
