# SQL-paged Finds

Date: 2026-09-07  
Status: approved for implementation  
Repo: `vinted-stuffs`

## Problem

`/api/dashboard` embeds the full finds list (up to ~10k indexed rows). Loading the desk is slow because of payload size and client work.

## Decision

- Slim dashboard: omit finds rows; keep run/meta/bundles/sellers/watches and summary counts.
- `GET /api/finds` pages from Cockroach `scored_listings` with SQL `LIMIT`/`OFFSET`, veto join, and desk filters/sort.
- Default page size 50 (max 100).
- Tiny sources (`keep` / `pool` / `scored`) use in-memory paging over those sets.
- No DB → page `indexed_scores.json` in memory with the same response shape.

## Non-goals

Infinite scroll, keyset cursors, perfect inclusion of keep-only rows never written to `scored_listings` in the default SQL list.
