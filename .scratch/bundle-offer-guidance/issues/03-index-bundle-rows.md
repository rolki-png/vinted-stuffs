# 03: Index bundle rows

**What to build:** Index-derived bundle rows on the Bundles tab that already carry listing sum, checkout extra, and useful items also store and display suggested bundle offer fields, so index near/keep bundles match live haul rows.

**Blocked by:** 01 — Suggest offer on value/near hauls (dashboard)

**Status:** done

- [x] Index keep-bundle equivalents use the alerted haircut band when computing the suggestion
- [x] Index near equivalents use the near haircut band
- [x] Persisted index bundle rows include `suggested_offer_ron` and `offer_weak` when inputs are present
- [x] Bundles tab shows those fields without a separate JS formula
- [x] Rows lacking listing sum / item count still omit the suggestion safely
