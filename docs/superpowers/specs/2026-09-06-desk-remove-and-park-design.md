# Desk Remove and Park

Date: 2026-09-06  
Status: ready-for-agent  
Repo: `vinted-stuffs`  
Stack: TanStack Start deal desk (post-migrate)  
Domain: see root `CONTEXT.md` (**Remove**, **Park**, Keep, Bundle, Seen key)

## Problem Statement

Listings on the desk are sometimes already sold (or otherwise permanently unwanted). **Hide** was a reversible soft veto with a Hidden filter; that is the wrong tool for sold inventory. The buyer needs a permanent **Remove** that never shows the listing again on Finds, Bundles, Top sellers, or one-off surfaces, and that stops bot alerts — without hard-deleting Cockroach score rows or rewriting git JSON. **Park** remains the soft “deal with later” mark.

## Solution

Replace **Hide** with permanent **Remove**: a Cockroach tombstone (`listing_vetoes.status = removed`) keyed by listing id. Snapshot and apply helpers always omit removed ids from finds, bundles, and seller aggregates. Bot loads removed ids once per run and suppresses like former hide. **Park** unchanged. No Undo and no Hidden filter for Remove. Status filter: Active | Parked | All. Migrate existing `hidden` rows to `removed` on schema ensure / first open. Accept legacy API `status: "hidden"` as `removed`. No dashboard secret (already removed).

## User Stories

1. As a buyer, I want to Remove a sold listing from Finds, so that it never tops the desk again.
2. As a buyer, I want Remove to drop that id from Bundles (and drop the bundle if fewer than 2 items remain), so that carts stay actionable.
3. As a buyer, I want Remove to clear that listing from Top sellers / one-off surfaces rebuilt from desk data, so that dead inventory does not inflate seller views.
4. As a buyer, I want Remove to suppress future ntfy and keep/bundle persistence for that id, so that I am not re-alerted.
5. As a buyer, I want Remove to be permanent (no Undo, no Hidden filter), so that sold items stay gone.
6. As a buyer, I want Park unchanged: tagged, sorted below active, still alerts, Undo when parked.
7. As a buyer, I want status filter Active | Parked | All (no Hidden), so that the desk matches Remove semantics.
8. As a buyer, I want Remove of an already-parked listing to upgrade the tombstone to removed.
9. As a developer, I want one veto store seam with pure apply helpers, shared by TanStack desk routes and the Python bot.
10. As a developer, I want existing `hidden` vetoes migrated to `removed` automatically.
11. As a buyer, I do not want hunt notes changed for bridal/occasion dresses — Remove is manual per listing.

## Implementation Decisions

1. **Table `listing_vetoes`.** `item_id` BIGINT PK, `status` (`removed` | `parked`), `updated_at`. On ensure/open: `UPDATE listing_vetoes SET status = 'removed' WHERE status = 'hidden'`.

2. **Store seam (Python + JS).** Rename predicates/helpers: `is_removed` / `load_removed_ids`; keep `is_parked`. `apply_to_finds` / `apply_to_bundles`: always omit `removed` (no `mode=hidden`); modes `active` | `parked` | `all`. Rebuild seller rows in the snapshot from post-apply finds+bundles only.

3. **TanStack Start desk.** Wire Remove/Park actions to the existing veto server route (no secret). UI label **Remove** (not Hide). Toast may confirm Remove but must not offer Undo for removed. Park keeps Undo. Filter control: Active | Parked | All.

4. **API body.** `{ item_id, status: "removed"|"parked" }` or clear (clear allowed for parked undo only in UI; server may still clear any status if called). Legacy `"hidden"` → store `"removed"`.

5. **Bot.** Load `removed` ids once per run; suppress solo/bundle/haul as today’s hidden path. Parked not suppressed.

6. **No hard purge** of `scored_listings` or git `data/*.json` in v1 (tombstone only).

7. **ADR / glossary.** Update `CONTEXT.md`: **Remove** replaces **Hide**. Optional short ADR note or amend 0003 that status values are `removed`|`parked`.

## Testing Decisions

- Unit tests: remove omits find; park tags/sorts; clear park restores; bundle shrink/drop on removed member; removed ≠ parked for bot; sellers rebuilt without removed-only contribution; migration maps hidden→removed.
- Desk: manual click Remove on a find and confirm absence under Active/All; Park still undoable.
- No full browser E2E required for v1.

## Out of Scope

- Hard-deleting Cockroach scored rows or rewriting git JSON dumps
- Auto-detect sold via availability check on click
- Bringing back Hide or a Hidden filter
- Undo for Remove
- Hunt config / Tiffany Rose note changes
- Reintroducing DASHBOARD_SECRET

## Further Notes

- Supersedes desk semantics in `docs/superpowers/specs/2026-09-06-desk-hide-and-park-design.md` for Hide→Remove; Park and Cockroach tombstone ADR intent remain.
- Implement against current TanStack Start desk layout on `main` after pull.
