# 02: Dashboard API + UI

**What to build:** Authenticated Hide/Park/Undo on the live desk (DASHBOARD_SECRET). Snapshot applies vetoes so Finds and Bundles reflect Hide/Park; UI adds actions plus Active / Parked / Hidden / All filter and undo.

**Blocked by:** 01 — Veto store + apply helpers

**Status:** done

- [x] API set/clear veto requires dashboard secret; rejects unauthorized
- [x] Snapshot omits hidden by default; can return parked/hidden views via filter
- [x] Finds rows expose Hide / Park (and Undo when vetoed)
- [x] Bundles expose Hide / Park per item (and behave after refresh)
- [x] Status filter Active | Parked | Hidden | All works without a second formula client-side beyond calling the API/snapshot
