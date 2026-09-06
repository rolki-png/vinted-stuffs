# 03: Bot suppress for Hide

**What to build:** Each hunt run loads hidden listing ids from Cockroach and treats them as full suppress: no solo ntfy, no keep persist, strip from value-haul / keep-bundle useful sets (skip alert if below thresholds). Parked ids are not suppressed.

**Blocked by:** 01 — Veto store + apply helpers

**Status:** done

- [x] Bot loads hidden id set once per run (safe no-op if DB unavailable, with stderr note)
- [x] Solo keep path skips hidden listing ids for alert and best_deals persist
- [x] Bundle / value-haul paths drop hidden members before alert/persist gates
- [x] Parked listings still alert and persist as today
- [x] Focused unit or helper test proves hidden predicate gates the keep/alert check
