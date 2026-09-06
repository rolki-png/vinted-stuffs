# Bundle offer guidance

Date: 2026-09-06  
Status: implemented  
Repo: `vinted-stuffs`  
Domain: see root `CONTEXT.md` (**Bundle offer**, Bundle, Value haul, Keep-bundle, Checkout extra)

## Problem Statement

When several hunt-fit listings sit with one seller, the useful move is a multi-item checkout and a **bundle offer** on the goods total (for example five Mama / Mamalicious pieces listed at ~227 RON, offer submitted at 187 RON, fees still at checkout). The hunt already finds keep-bundles, value hauls, and near hauls and shows listing sum plus checkout extra — but it never suggests **what goods total to type into Vinted**. The buyer still has to invent the bid by hand.

## Solution

For every persisted multi-item cart (value haul, near haul, keep-bundle, and index bundle kinds that already carry listing sum / checkout extra / items), compute and store a **suggested bundle offer**: a goods total below listing sum aimed at a category delivered-cost-per-useful-item target, clamped to a haircut band. Surface that number on ntfy for alerted carts and on the dashboard Bundles tab for all kinds (including near hauls). The buyer still submits the offer on Vinted; the system does not send offers or track pending/accepted/rejected state.

## User Stories

1. As a buyer, I want a suggested goods total for a multi-item seller cart, so that I can submit a bundle offer without inventing the number.
2. As a buyer, I want the suggestion to target delivered cost per useful item, so that the bid matches how I actually judge hauls.
3. As a buyer, I want gym carts aimed at about 30 RON delivered per useful item, so that ordinary gym wardrobe hauls stay cheap after fees.
4. As a buyer, I want maternity carts aimed at about 50 RON delivered per useful item, so that Mama-style hauls match real accepted offers.
5. As a buyer, I want the suggestion never above 90% of listing sum (at least ~10% off), so that the number still reads as an offer, not full price.
6. As a buyer, I want alerted carts clamped to at most ~25% off listing sum, so that strong hauls do not look insulting.
7. As a buyer, I want near hauls allowed up to ~35% off listing sum, so that weaker closets still get a usable stretch bid.
8. As a buyer, I want a suggestion even when the category target is unreachable at max haircut, so that I always have a number to type.
9. As a buyer, I want those unreachable suggestions marked weak/stretch, so that I know the bid is a long shot.
10. As a buyer, I want the same item set as the haul row used for the math, so that the offer matches the cart I already decided to consider.
11. As a buyer, I want the same formula on keep-bundles and value/near hauls, so that one playbook covers gym and maternity shopping.
12. As a buyer, I want ntfy alerts for value hauls and keep-bundles to include “offer ~X RON”, so that I can act from my phone.
13. As a buyer, I want the Bundles dashboard to show suggested offer (and weak flag) for every kind including near haul, so that I can act without a push.
14. As a buyer, I want suggested offer persisted on the bundle record, so that ntfy and dashboard never disagree.
15. As a buyer, I want index-derived bundle rows to get the same fields when they already expose listing sum, checkout extra, and useful items, so that the Bundles tab stays consistent.
16. As a buyer, I want category (gym vs maternity) inferred from the haul’s watch / target type the same way value-haul scoring already distinguishes maternity, so that caps stay aligned with hunt intent.
17. As a buyer, I want config knobs for target RON/item and haircut bounds, so that I can tune without code changes.
18. As a buyer, I do not want the bot to submit the offer on Vinted, so that I keep control of timing and negotiation.
19. As a buyer, I do not want pending/accepted/rejected offer CRM in v1, so that Vinted remains source of truth for offer state.
20. As a buyer, I do not want a second cart optimizer that drops items to hit the cap, so that v1 stays a thin suggestion on the existing cart.
21. As a developer, I want one pure suggest function as the only formula seam, so that tests lock behaviour without scraping the bot.
22. As a developer, I want unit tests that encode the ~227→~187 maternity shape and gym/near/weak cases, so that regressions in clamps are obvious.
23. As a developer, I want display layers to only render stored fields, so that JavaScript does not reimplement offer math.

## Implementation Decisions

1. **Single formula seam.** One pure function (bundle-offer guidance) takes listing sum, checkout extra, useful-item count, category target (gym vs maternity), and kind class (alerted vs near). It returns suggested offer (whole RON), whether the offer is weak, and the target delivered-per-item used. No I/O inside the function.

2. **Back-solve then clamp.** Compute the maximum goods total that still meets `(offer + checkout_extra) / n_useful ≤ target_per_item`. Round down to whole RON. Then clamp into `[listing_sum * (1 - max_haircut), listing_sum * (1 - min_haircut)]`. If listing sum is zero or useful count is below 2, return no suggestion (omit fields).

3. **Targets.** Gym target delivered per useful item: 30 RON. Maternity: 50 RON. Live in config next to existing value-haul caps (or a dedicated `bundle_offer` config block that the pure function reads via passed numbers — prefer passing resolved numbers into the pure function so tests do not load config).

4. **Haircut bands.** Min haircut 10% for all. Max haircut 25% for alerted kinds (`value_haul`, `keep_bundle`, and index keep-bundle equivalents). Max haircut 35% for near kinds (`near_haul`, index near). Weak = true when the unclamped target-meeting offer would sit below the max-haircut floor (i.e. even the most aggressive allowed bid misses the per-item target).

5. **Item set.** Use exactly the items already on the haul/bundle row. Do not drop expensive pieces to hit the target in v1.

6. **Kind coverage.** Attach suggestion when persisting value haul, near haul, and keep-bundle rows. Apply the same helper when writing index bundle rows that already have the needed inputs. Solo keeps unchanged.

7. **Category detection.** Reuse existing maternity-vs-gym detection from the value-haul path (watch name / target type). Default to gym caps when unknown.

8. **Persistence shape.** On each bundle record, store at least: `suggested_offer_ron` (number), `offer_weak` (bool). Optional display helpers: `offer_target_per_item_ron`. Do not store offer lifecycle state.

9. **ntfy.** For newly alerted value hauls and keep-bundles, include a clear line with the suggested goods total and weak marker when set. Near hauls remain dashboard-only (existing rule).

10. **Dashboard.** Bundles tab shows suggested offer next to listing/checkout totals; weak suggestions get distinct but calm labelling (not a second alert system).

11. **No dual math.** Dashboard and ntfy only read persisted fields. Snapshot / local dashboard serve must pass the new fields through unchanged.

12. **ADR.** Record the formula choice (delivered-per-item + haircut clamps vs fixed % vs fair-price sum) in `docs/adr/` so future readers know why.

## Testing Decisions

- Good tests assert **external behaviour of the pure suggest function**: given inputs, exact offer, weak flag, and clamp behaviour — not bot wiring or DOM.
- Cover at least: maternity shape consistent with ~18% off a ~227 listing toward ~50/item; gym cart that hits 30/item inside 10–25%; near haul that needs up to 35%; weak flag when target unreachable at max haircut; min 10% off even when full price already beats target; omit/empty when n &lt; 2 or listing sum ≤ 0; keep-bundle uses same path as value haul.
- Prior art: value-haul and keep-rules unit tests (table-driven pure helpers).
- Thin smoke optional: record builders include the new fields when the helper is wired — only if existing record-builder tests already live nearby; do not invent heavy bot integration tests for v1.
- Dashboard: no separate formula tests; visual/manual check that the field renders.

## Out of Scope

- Auto-submitting bundle offers on Vinted
- Tracking pending / accepted / rejected offers
- Manual “I offered” dashboard notes
- A second cart optimizer that subsets items to hit the RON/item target
- Changing discovery, closet crawl limits, value-haul gates, or hunt config beyond offer-guidance knobs
- Offer guidance on solo keeps
- Syncing Vinted’s live fee quote into the formula (keep existing checkout-extra estimates)

## Further Notes

- Domain term **Bundle offer** is already in `CONTEXT.md`.
- Example primary source for maternity feel: seller cart ~227.15 RON listing / submitted 187 RON goods (~18% off), buy-now delivered picture ~310 RON — fees are context; the typed offer is goods-only.
- Follow-up if needed later: per-watch overrides, fair-price sum for premium keep-bundles, or light manual offer notes — not this spec.
- Issue tracker labels are not configured in this repo; this file under `docs/superpowers/specs/` is the agent-ready publish target (`Status: ready-for-agent`).
