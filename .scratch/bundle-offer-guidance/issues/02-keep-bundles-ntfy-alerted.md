# 02: Keep-bundles + ntfy for alerted carts

**What to build:** Keep-bundles get the same suggested bundle offer fields as value/near hauls. Fresh ntfy alerts for value hauls and keep-bundles include a clear `offer ~X RON` line (and weak/stretch when set), so the buyer can act from the phone without opening the dashboard.

**Blocked by:** 01 — Suggest offer on value/near hauls (dashboard)

**Status:** done

- [x] New `keep_bundle` records store `suggested_offer_ron` and `offer_weak` using the same formula (alerted haircut band)
- [x] Bundles tab shows the suggestion for keep-bundles (same display path as ticket 01)
- [x] Value-haul ntfy includes the suggested goods total and weak marker when set
- [x] Keep-bundle ntfy includes the suggested goods total and weak marker when set
- [x] Near hauls still do not ntfy (dashboard-only unchanged)
