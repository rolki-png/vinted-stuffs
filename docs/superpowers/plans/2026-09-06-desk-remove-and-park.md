# Desk Remove and Park Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Hide with permanent Remove (Cockroach tombstone `removed`) across Python bot, TanStack desk, and snapshot sellers.

**Architecture:** Rename veto status `hidden`→`removed`; always omit removed from desk modes; migrate DB rows on ensure; rebuild sellers from post-apply finds/bundles; UI Remove with no undo.

**Tech Stack:** TanStack Start (`src/`), Python `listing_vetoes` + unittest, Cockroach `listing_vetoes`.

## Global Constraints

- Modes: `active` | `parked` | `all` only (no `hidden` filter mode).
- Removed listings never appear on desk (including `all`).
- Park unchanged; Undo only for parked.
- Legacy API `status: "hidden"` stores as `removed`.
- No DASHBOARD_SECRET; no hard purge of scored_listings/git JSON.

---

### Task 1: Python veto seam + tests

**Files:**
- Modify: `python/listing_vetoes.py`
- Modify: `python/tests/test_listing_vetoes.py`
- Modify: `python/vinted_bot.py` (load_removed_ids)
- Modify: `CONTEXT.md`
- Modify: `python/sql/002_listing_vetoes.sql` (comment)

- [x] Tests for remove omit, no hidden mode, migration normalize, bot predicate
- [x] Implement STATUS_REMOVED, ensure migrate, aliases
- [x] Bot uses load_removed_ids
- [x] Commit

### Task 2: TanStack server + DealDesk UI

**Files:**
- Modify: `src/server/listingVetoes.ts`
- Modify: `src/server/snapshot.ts` (rebuild sellers after apply)
- Modify: `src/routes/api/dashboard.ts`
- Modify: `src/components/DealDesk.tsx`
- Modify: `src/styles.css` (`.pill.removed`)

- [x] Mirror Python semantics in TS
- [x] Sellers from applied finds/bundles
- [x] UI Remove / filter / no undo for removed
- [x] Commit + push prod

---
