# Desk Taste Learning (Remove / Park / Bought)

Date: 2026-09-06  
Status: ready-for-agent  
Repo: `vinted-stuffs`  
Stack: TanStack Start deal desk + Python hunt bot + Cockroach  
Domain: see root `CONTEXT.md` (Remove, Park, Keep); this spec adds **Bought** and **taste learning**

## Problem Statement

Desk actions today only change visibility and exact-id alert suppression. Remove and Park do not teach the scorer; there is no Bought signal. The buyer wants a learning loop: fewer bad alerts first, with ranking and hunt-config tuning able to consume the same outcomes later.

## Goals (phased)

1. **Phase 1 (this spec):** Fewer bad alerts via hybrid learning + Bought UI/history.
2. **Later (out of scope here):** Desk re-ranking from outcomes; auto-tuning hunt notes / gates.

## Signal model

| Action | Desk | Exact-id suppress | Learning weight |
|--------|------|-------------------|-----------------|
| **Remove** | Gone forever from desk surfaces | Yes | Strong negative |
| **Park** | Tagged, sorted below active; Undo | No | ~0 (ignored by learner) |
| **Bought** | Off Active; shown in Bought history; Undo | Yes (already purchased) | Strong positive |

## Solution overview

1. Extend Cockroach `listing_vetoes` with status `bought` and outcome snapshot columns captured at click time.
2. Desk: Bought button, filter mode `bought`, Bought history section; enrich veto writes from scored cache / find row.
3. Bot: suppress exact ids for `removed` **and** `bought`; inject family-scoped taste few-shots into the scoring prompt; apply a conservative hard-suppress rule for repeated Remove patterns with no Bought counter-examples.
4. Hunt **families** scope learning: maternity / gym / sneakers / knitwear / other (shared within family, not global).

## User Stories

1. As a buyer, I want to mark a listing **Bought**, so it leaves Active and becomes a positive taste signal.
2. As a buyer, I want a **Bought** history on the desk (filter or section), so I can see what I confirmed and Undo a mis-click.
3. As a buyer, I want Remove to remain a strong “don’t keep / don’t alert similar” signal within the same hunt family.
4. As a buyer, I want Park to stay “not now” without poisoning taste.
5. As a buyer, I want fewer ntfy/keeps that match patterns I repeatedly Remove in that family.
6. As a developer, I want outcome rows reusable later for ranking and config tuning without a second feedback store.

## Data model

### `listing_vetoes` (extend in place)

| Column | Type | Notes |
|--------|------|--------|
| `item_id` | BIGINT PK | unchanged |
| `status` | TEXT | `removed` \| `parked` \| `bought` (`hidden` still normalizes to `removed`) |
| `updated_at` | TIMESTAMPTZ | unchanged |
| `hunt_name` | TEXT NULL | hunt that surfaced the listing when known |
| `hunt_family` | TEXT NULL | resolved family at write time |
| `brand` | TEXT NULL | normalized brand string |
| `size` | TEXT NULL | size label if known |
| `price_ron` | DOUBLE PRECISION NULL | listing price at decision |
| `value_band` | TEXT NULL | steal/hunt/acceptable/skip if known |
| `deal_score` | INT NULL | score at decision |
| `title` | TEXT NULL | short title snapshot |

Ensure/migrate: `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for each new column. No separate outcomes table in v1.

### Write path

Desk `POST /api/veto` accepts optional enrichment fields (or server looks up scored row by `item_id`). Prefer **client sends known find fields + server fills gaps from scored cache** so Park/Remove/Bought all snapshot when possible. Missing enrichment is allowed (status-only write still works).

### Load paths

- Desk map: `item_id → status` (as today) plus optional full rows for Bought history.
- Bot suppress set: ids where status ∈ `{removed, bought}` (and legacy `hidden`).
- Bot learner: load recent `removed` and `bought` rows with enrichment for the active hunt’s family (Park excluded).

## Desk UX

- **Bought** button beside Remove/Park on finds and bundle line items.
- When status is `bought`: show Undo (clear veto); pill `bought`.
- When status is `removed`: unchanged (no Undo).
- Filter: `active` | `parked` | `bought` | `all`.
  - `active`: omit removed and bought; tag/sort parked.
  - `parked`: only parked.
  - `bought`: only bought.
  - `all`: active + parked + bought; **removed always omitted**.
- Bundles: bought members stripped like removed for Active (item already purchased); if &lt;2 remain, drop bundle. Bought filter shows bundles that still contain a bought member only if useful — v1: apply same member strip; Bought history is primarily **finds** (and bundle line-item actions still write vetoes).
- Toast: Bought confirms with Undo id; Park unchanged; Remove no Undo.
- Snapshot API `?veto=` accepts `bought`.

## Hunt families

Resolve family from hunt name (case-insensitive contains), first match wins:

| Family | Name contains (examples) |
|--------|---------------------------|
| `maternity` | maternity, mama, mamalicious, seraphine, noppies, hatch, storq, legoe, bae the label, tiffany rose, boob, ripe, envie, jojo, beyond nine, isabella oliver, pietro brunelli, next maternity, asos maternity, h&m mama, leggings |
| `sneakers` | new balance, asics, diadora |
| `gym` | gym, running, gorewear, 2xu, craft, saysky, falke, odlo, lululemon, ten thousand, rhone, vuori, tracksmith, h&m sport |
| `knitwear` | merino, cashmere, johnstons, cruciani, gran sasso, fedeli, sunspel, zimmerli, hanro, merz, cdlp, devold, smartwool, ortovox, woolpower, polo |
| `other` | default |

Optional per-watch `"family": "..."` in config overrides inference. Pure helper shared conceptually in Python + TS (duplicate small function OK; keep tests in sync).

Config block (optional knobs, defaults in code if omitted):

```json
"taste_learning": {
  "enabled": true,
  "prompt_examples_per_polarity": 5,
  "hard_suppress_min_removes": 3,
  "hard_suppress_require_zero_bought": true
}
```

## Learning loop (Phase 1)

### Soft bias (always when enabled and outcomes exist)

Before LLM scoring for a hunt, build a short **Buyer taste** appendix for that hunt’s family:

- Up to N recent **Bought** rows (title, brand, size, price, band, score, reason-free).
- Up to N recent **Removed** rows (same fields).
- Explicit instruction: prefer patterns like Bought; avoid patterns like Removed; Park is not listed.

Append to scoring prompt (token-budgeted; truncate titles). If no rows, skip appendix.

### Hard suppress (conservative)

Pattern key within family: `(family, brand_normalized, size_normalized)` where empty brand → no hard rule (skip). Size may be empty string (brand-only key).

If count(removed for key) ≥ `hard_suppress_min_removes` AND count(bought for key) == 0 (when require_zero_bought): treat candidate as **not a keep** and **do not alert**, even if LLM would keep. Still may score/store for cache. Log `taste_hard_suppress` with key + counts.

Park never increments remove/bought counts.

### Exact-id suppress

`load_suppress_ids()` = removed ∪ bought (replace bot’s removed-only set for alert/keep persistence filters). Desk omit rules as above.

## Architecture

```
DealDesk Bought/Remove/Park
    → POST /api/veto (+ enrichment)
    → listing_vetoes (Cockroach)

Bot run
    → load suppress ids (removed+bought)
    → load family outcomes
    → append taste prompt block
    → score LLM
    → is_keep + hard_suppress gate
    → alert / persist
```

Pure modules:

- `python/taste_learning.py` — family resolve, prompt block, hard-suppress decision (unit-tested).
- Mirror minimal family + apply mode helpers in `src/server/listingVetoes.ts` / small `tasteLearning.ts` if needed for desk filter modes.

## Error handling

- Enrichment failure: still write status; learning degrades gracefully.
- DB down: Null store (bot); desk 503 on write (unchanged).
- Invalid status: 400.
- Clear: allowed for parked and bought (Undo); UI does not clear removed.

## Testing

- Python unit: family resolution; prompt block includes bought/removed not parked; hard suppress at threshold; hard suppress blocked by any bought on same key; apply_to_finds modes for bought; suppress ids include bought.
- JS/TS unit or pure helpers: apply modes + bought omit; coerce status bought.
- Desk: manual Bought → appears under Bought filter, gone from Active; Undo restores.
- Bot: dry-run / unit for suppress set membership (no live Vinted required).

## Out of scope

- Desk re-ranking from taste scores
- Auto-rewrite of hunt `notes` / `min_deal_score`
- ML / embeddings classifier
- Global (cross-family) learning
- Hard-deleting scored_listings rows
- Auto-detect sold on Open
- Changing Park alert behavior

## Glossary additions (CONTEXT.md)

**Bought**: Buyer-confirmed purchase of a listing id. Off Active desk; listed in Bought history; suppresses re-alerts for that id; strong positive taste signal within hunt family. Reversible Undo.

**Hunt family**: Coarse taste bucket (maternity / gym / sneakers / knitwear / other) used to scope learning so maternity Removes do not affect gym scoring.

**Taste learning**: Hybrid use of desk outcomes — prompt few-shots plus conservative hard suppress of keep/alert for repeated Remove patterns with no Bought counter-example in-family.

## Implementation notes

- Prefer extending existing veto seam over a parallel feedback table.
- Keep Python and TS apply semantics aligned (modes, omit rules).
- Phase 1 success metric: after several Removes of the same brand+size in a family, similar Keeps stop alerting; Bought examples appear in prompt for that family.
