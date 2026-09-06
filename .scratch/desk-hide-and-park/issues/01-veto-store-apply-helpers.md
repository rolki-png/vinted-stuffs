# 01: Veto store + apply helpers

**What to build:** Cockroach `listing_vetoes` table (item_id → hidden|parked) with load/set/clear helpers, plus pure apply functions that filter/sort Finds and shrink Bundles when members are hidden (drop bundle if fewer than 2 items remain). Parked rows stay visible, tagged, sorted after active.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] Schema ensure creates `listing_vetoes` with item_id PK and status
- [x] set/clear/load veto map works against memory or DB store seam
- [x] `apply_to_finds` hides by default, tags/sorts parked, supports include-hidden for the filter
- [x] `apply_to_bundles` strips hidden members; removes bundle when &lt;2 items left; parks when remaining members warrant it
- [x] Unit tests cover hide/park/clear, bundle shrink to 2, bundle drop at 1, park ≠ hidden for bot predicate
