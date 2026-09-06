# Desk Hunt Configuration

Date: 2026-09-06  
Status: ready-for-agent  
Repo: `vinted-stuffs`  
Stack: TanStack Start Deal desk + GitHub Contents API + `@googlarz/vinted-client` catalogue helpers  
Domain: see root `CONTEXT.md` (**Hunt**; config key remains `watches`)  
Wayfinder: [`.scratch/desk-hunt-config/map.md`](../../../.scratch/desk-hunt-config/map.md)

## Problem Statement

Hunts live only in `python/config.json` and are edited by hand (git). The Deal desk can filter by hunt name and dispatch Actions, but cannot add, replace, or remove hunts. Changing discovery means a local edit + push, which is slow for the buyer who already lives on the desk.

## Solution

Add a **Hunts** tab on the Deal desk that loads and mutates the live `watches` array in `python/config.json` on `main` via GitHub Contents (read-modify-write with blob `sha`). Brand and size pickers call Vinted catalogue APIs through new desk server routes (same client library the hunt bot already uses). Auth stays open like veto/trigger (server-side `GITHUB_TOKEN` / optional `VINTED_PROXY_URL` only). Next scheduled or manually triggered hunt run picks up the new list; Save does not auto-dispatch.

## User Stories

1. As a buyer, I want a **Hunts** tab after Runs, so that configuring searches sits with the rest of the desk.
2. As a buyer, I want to browse all hunts and edit one in a master–detail layout, so that I can scan ~50 hunts without losing place.
3. As a buyer, I want **New hunt** and **Duplicate**, so that blank and variant hunts are both easy.
4. As a buyer, I want **Save** to commit hunt changes to git config, so that the next bot run uses them.
5. As a buyer, I want **Remove** to stop searching a hunt without erasing score/seen history, so that identity cleanup is intentional and separate.
6. As a buyer, I want a rename warning when `name` changes, so that I know seen-key identity will start fresh.
7. As a buyer, I want brand typeahead and size-group pickers from Vinted, so that I do not hand-edit numeric IDs.
8. As a buyer, I want country locked to the RO catalog, so that I am not switching marketplaces by accident.
9. As a buyer, I want clear conflict/reload behavior when config changed under me, so that I do not silently overwrite another edit.
10. As a developer, I want Contents PUT to mutate only `watches` and preserve all other top-level keys, so that scoring/`value_haul`/checkout config cannot be wiped by a desk save.

## Implementation Decisions

### Persistence

1. **Source of truth:** `python/config.json` on `GITHUB_REF` (default `main`), path unchanged. Bot continues to load via `VINTED_CONFIG` / default path at run start.
2. **Write path:** Contents `GET` → decode JSON → mutate **`watches` only** → Contents `PUT` with blob **`sha`**, Base64 content, `branch` from env. Never invent a parallel DB/PR config store in v1.
3. **Helpers:** Extend GitHub server helpers alongside existing read/dispatch (`getConfigJson` / `putConfigJson` shape). Reuse env: `GITHUB_TOKEN`, `GITHUB_REPO`, `GITHUB_REF`. Classic `repo` (or fine-grained Contents write + existing Actions write) — no new scopes beyond what the desk already needs for reads + dispatch.
4. **Commit messages:** `desk: add|replace|remove hunt <name> [skip ci]`.
5. **Tip race:** On Contents `409`, re-GET once; if blob `sha` unchanged, retry PUT once (transparent). If blob `sha` changed → conflict response (no blind overwrite).
6. **In-flight bot:** A save mid-run does not retarget that run; the **next** schedule/`workflow_dispatch` loads the new watches. Bot `data/` commits are path-disjoint but can cause tip races.

### Auth and blast radius

7. Hunt load/write and catalogue routes are **unauthenticated at the HTTP edge**, same as `/api/veto` and `/api/trigger`. Spec and README must note: anyone with the Vercel URL can rewrite hunts and burn Vinted catalogue quota; the PAT can write other repo paths if abused.

### Desk UI — Hunts tab

8. **Tab:** Label **Hunts** (not Watchlist), placed after **Runs**.
9. **Layout:** Master–detail (list left / form right; stack on narrow viewports).
10. **List:** Primary `name`; secondary query · RO · size hint · `bundle_hunt` badge · brand count. Filter/search on name/query.
11. **Actions:** List **New hunt**; form **Save** (dirty+valid only) + **Remove** (disabled on blank New); **Duplicate** secondary. Busy-disable Save/Remove while a write is in flight.
12. **Remove confirm:** “Stop searching **{name}**? History and seen keys stay.” No Undo.
13. **Rename:** Inline warning when name ≠ loaded name — new hunt identity / fresh seen keys; old name history remains. No second modal.
14. **Dirty navigate:** Confirm Discard / Stay when changing selection or New with unsaved edits. No auto-save.
15. **After Save:** Stay on hunt, clear dirty, refresh from response. **After Remove:** Clear selection. Feedback via existing ops-message strip. Success copy: saved/removed applies on the **next** hunt run (not immediate search).
16. **Load/empty:** Ops error on load failure; empty `watches` → empty list + New CTA; form disabled until selection or New. Conflict → “Config changed on GitHub since you loaded it” + **Reload hunts** (confirm discard if dirty). No force-overwrite.

### Form fields and validation

17. **Visible fields:** `name`, `query`, `order`, `per_page`, `price_to`, `hunt_price`, `target_type`, `target_sizes`, `notes`, `bundle_hunt`, `family` (maternity | gym | sneakers | knitwear | other | empty), optional `min_deal_score`.
18. **Country:** Always persist `country: "ro"`. Hide control or show read-only “RO catalog”. No PL/HU site switcher; no seller-origin filter.
19. **Brands:** Debounced typeahead → desk brands API → explicit multi-select chips → `brand_ids`. No first-hit auto-fill. Empty → omit key. Catalogue failure → inline warning; Save still allowed.
20. **Sizes:** Size-groups API → choose group (men’s / women’s / shoes / kids / …) → multi-select chips → `size_ids`. Optional. No raw-ID escape hatch in v1. `target_sizes` stays free-text for the scorer.
21. **Omit from UI:** `price_from`, `category_id`, `condition`, `full_sweep_max`. **Preserve unknown keys** on replace of an existing hunt object.
22. **Write style:** Omit unset optionals; `bundle_hunt: true` only when checked (match existing config).
23. **Validation (client + server before PUT):** Required non-empty `name`, `query`, `target_type`; unique `name` among watches (case-sensitive as stored); positive int IDs; numerics ≥ 0 where set; force `country: "ro"`.

### Catalogue APIs (first Vercel→Vinted calls)

24. Add dependency on `@googlarz/vinted-client`. Server routes only (no browser→Vinted).
25. **Brands:** e.g. `/api/brands?q=&country=ro` → `opBrands` / `GET /api/v2/brands?keyword=`. Anonymous catalog cookies; rate limit ~3 req/s/country; 60s cache; honor `VINTED_PROXY_URL` for cloud egress/403.
26. **Size groups:** e.g. `/api/size-groups?country=ro` → library size-groups (`/api/v2/size_groups`), longer cache OK (static catalogue).
27. Update README: Vercel remains non-scraping for listings; **catalogue lookup** (brands/sizes) is the intentional exception.

### Hunt write API shape

28. Load: watches + blob `sha`.
29. Save/Remove: mutation + `sha` → success `{ ok, sha, watches }` or typed errors (`400` validation, conflict, auth, not found, upstream).
30. Remove from config only — do **not** purge `seen_keys`, Cockroach scores, or git `data/*`.

## Testing Decisions

- Unit/server: validate unique name / required fields; RMW preserves non-`watches` keys; tip-race retry when sha unchanged; conflict when sha changed; omit-empty serialization matches config style.
- Catalogue routes: map library hits to JSON; empty query → empty list; error surfacing without crashing Save path.
- Desk manual: New / Duplicate / Save / Remove / rename warning / dirty discard / conflict reload; brand and size pickers select real IDs that appear in committed config.
- No full browser E2E required for v1.

## Out of Scope

- Editing top-level scoring / `value_haul` / checkout knobs from the desk
- Multi-user auth / accounts
- Parallel config store or PR-only write workflow
- Automatic `workflow_dispatch` on every save (optional Save+Run deferred)
- Multi-market hunt search (`pl` / `hu` sites)
- Category catalogue picker
- Force-overwrite on conflict
- Purging seen keys / scores when removing a hunt
- Playwright / DataDome browser path for catalogues on Vercel

## Further Notes

- Research assets: [`.scratch/desk-hunt-config/assets/01-vinted-brand-picker.md`](../../../.scratch/desk-hunt-config/assets/01-vinted-brand-picker.md), [`.scratch/desk-hunt-config/assets/02-github-contents-config-write.md`](../../../.scratch/desk-hunt-config/assets/02-github-contents-config-write.md).
- UI copy: **Hunt** / **Hunts**; keep `watches` / `watch` as config and data keys only.
- Next step: implementation plan via writing-plans, then build.
