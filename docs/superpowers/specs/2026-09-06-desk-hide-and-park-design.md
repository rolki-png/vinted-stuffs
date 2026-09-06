# Desk Hide and Park

Date: 2026-09-06  
Status: ready-for-agent  
Repo: `vinted-stuffs`  
Domain: see root `CONTEXT.md` (**Hide**, **Park**, Keep, Bundle, Seen key)

## Problem Statement

High-scoring listings sometimes should not stay on top of the desk — e.g. a Tiffany Rose maternity midi scored 10 with a strong reason, but it is a wedding/occasion dress the buyer does not want right now. There is no way to remove or soft-rank an individual listing on the dashboard; hunt notes would also permanently bias search, which the buyer rejects (they may want wedding dresses later). The veto must be manual, reversible, and for Hide must also stop future alerts.

## Solution

Add buyer **Hide** and **Park** actions on Finds and Bundles (including index rows). Vetoes are keyed by listing id, stored in Cockroach, authenticated with the existing dashboard secret. Hide removes the listing from the desk and suppresses bot ntfy/persist for that id. Park keeps it visible but tagged and sorted below active rows without suppressing the bot. A Hidden/Parked filter lets the buyer undo. Tiffany Rose and other hunts stay unchanged.

## User Stories

1. As a buyer, I want to Hide a listing from Finds, so that a wedding midi scored 10 no longer tops the desk.
2. As a buyer, I want to Park a listing, so that I can soft-rank it down without losing it.
3. As a buyer, I want Hide and Park on Bundles and index rows, so that the same veto works everywhere I browse.
4. As a buyer, I want vetoes keyed by listing id across all hunts, so that the same dress does not reappear under another maternity hunt.
5. As a buyer, I want Hide to stop future ntfy and keep/bundle persistence for that listing, so that I am not re-alerted.
6. As a buyer, I want Park to remain dashboard-only for alerts, so that soft-ranking does not silence the bot.
7. As a buyer, I want Hidden listings omitted from the default desk view, so that the desk stays actionable.
8. As a buyer, I want Parked listings tagged and sorted after non-parked rows, so that I can still find them.
9. As a buyer, I want a Hidden/Parked filter (or status filter) to review and undo vetoes, so that mistakes are recoverable.
10. As a buyer, I want Undo after Hide/Park (toast or immediate control), so that a mis-click is cheap.
11. As a buyer, when I Hide one item in a bundle, I want that item dropped from the cart display, so that the remaining pieces stay usable.
12. As a buyer, when a bundle has fewer than two useful items after Hide, I want the whole bundle row gone, so that singleton carts do not linger.
13. As a buyer, I want vetoes stored in Cockroach, so that they survive deploys and are shared with the bot.
14. As a buyer, I want the same DASHBOARD_SECRET as Run hunt to authorize Hide/Park, so that I do not manage a second credential.
15. As a buyer, I do not want Tiffany Rose hunt notes changed, so that occasion dresses remain discoverable until I Hide them.
16. As a developer, I want one veto store seam with pure apply helpers for finds and bundles, so that bot and API stay thin.
17. As a developer, I want unit tests for hide/park/clear and bundle member dropping, so that desk math does not regress.
18. As a buyer, I want the snapshot API to expose veto status on rows (or apply filtering server-side), so that the UI does not invent its own persistence.
19. As a buyer, I want Hide of an already-parked listing to upgrade to hidden, so that one clear end state exists per id.
20. As a buyer, I want clearing a veto to restore normal desk behaviour on the next refresh, so that undo is complete.

## Implementation Decisions

1. **Table `listing_vetoes`.** Columns at least: `item_id` (BIGINT PK), `status` (`hidden` | `parked`), `updated_at` (timestamptz). Optional `note` omitted in v1. Ensure via the same schema-ensure path used for scored listings.

2. **Single store seam.** Module helpers: load veto map; set status; clear; predicates `is_hidden` / `is_parked`; `apply_to_finds(rows, vetoes)` (filter hidden by default unless include_hidden; mark parked; sort parked after active); `apply_to_bundles(rows, vetoes)` (strip hidden item ids; drop bundle if fewer than 2 items remain; mark parked if any remaining member is parked or policy: park bundle if any member parked — prefer: bundle is parked only if all remaining members are parked OR if the buyer parked from the bundle row targeting the bundle’s primary listing set — **simpler v1:** apply per-item: remove hidden members; if any remaining member is parked, tag the bundle parked and sort down).

3. **API.** Authenticated POST/DELETE (or POST with action) under existing Vercel API style, secret via `x-dashboard-secret` / Bearer. Body: `{ item_id, status: "hidden"|"parked" }` or clear. GET snapshot continues to build desk data and applies vetoes before response (hidden omitted unless `?veto=hidden|parked|all`).

4. **Dashboard UI.** On each Find row and each bundle item (and bundle-level controls as convenience): Hide, Park. After action, refresh snapshot or patch local state. Status filter: Active (default) | Parked | Hidden | All. Toast/Undo calls clear.

5. **Bot.** Once per run, load all `hidden` item ids. Skip solo ntfy, keep selection, and omit hidden ids from bundle/haul useful sets (re-run useful count; skip haul alert if &lt; threshold). Do not treat parked as suppress.

6. **No hunt config changes** for Tiffany Rose or bridal notes.

7. **ADR.** Record why Cockroach (not git `data/`) for vetoes: shared with serverless dashboard write path without Actions commit races.

## Testing Decisions

- Good tests assert external behaviour of veto apply helpers: given finds/bundles + veto map → expected visible rows, tags, and bundle membership.
- Cover: hide removes find; park sorts after and tags; clear restores; hide member in 3-item bundle → 2-item bundle; hide leaving 1 → bundle removed; hidden id skipped by bot predicate helper; park does not count as hidden for bot.
- Prior art: scored_store / value_haul / bundle_offer unit tests.
- API: optional auth rejection test if pattern exists; otherwise manual check with secret.
- No full browser E2E required for v1.

## Out of Scope

- Changing hunt notes / target_type for bridal or occasion dresses
- localStorage-only vetoes
- Separate auth secret
- Permanent non-undoable hide
- Veto by hunt name or seller
- Auto-hide from rules/LLM
- Syncing vetoes into git JSON dumps as source of truth

## Further Notes

- Domain terms **Hide** and **Park** already in `CONTEXT.md`.
- Example trigger: Tiffany Rose midi “Perfect match… score 10” — Hide, not hunt rewrite.
- Issue tracker labels not configured; this file under `docs/superpowers/specs/` is the agent-ready publish target.
