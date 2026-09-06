# Maternity leggings + XL / L/XL size focus

Date: 2026-09-06  
Status: approved design  
Repo: `vinted-stuffs` (`python/config.json` + maternity scoring rules in `python/vinted_bot.py`)

## Problem

Maternity hunting currently targets `["L", "XL", "L/XL"]`. Plain **L** and the scorer’s **M/L may qualify** exception pull pieces that no longer fit. The partner prefers **L/XL** and **XL** only.

Separately, **maternity leggings** are high-value for her: usable at the gym and everyday. Existing brand notes barely mention them, and there are no product-language watches that search for leggings directly — so good pairs only appear when they happen to sit under a brand query.

## Goal

1. **Tighten maternity sizes** to `L/XL` + `XL` only across all maternity brand watches and Mama bundle seeds.
2. **Hard-reject** plain `L`, `M`, `M/L`, and other smaller bands in maternity scoring (remove the measurements exception).
3. **Prefer leggings** in existing maternity notes (gym + everyday use), without dropping other useful maternity categories.
4. **Add dedicated maternity leggings watches** so search discovers them by product language and favourite brands, not only as incidental brand hits.

## Non-goals (v1)

- Non-maternity / pure gym-brand leggings (Nike, Gymshark, Lululemon, etc.)
- Vinted `size_ids` filters (no reliable `L/XL` size id; women’s `L` id would reintroduce the wrong band)
- Changing men’s gym, sneaker, or knitwear watches
- Raising `max_new_items_per_watch` or adding a FULL_SWEEP maternity config
- Changing bundle-offer delivered-per-item targets

## Architecture

Two layers, mostly config:

| Layer | Change | Runtime effect |
|---|---|---|
| Maternity watches | `target_sizes: ["L/XL", "XL"]`; notes prefer leggings | LLM + value-haul `size_matches` only keep XL / L/XL |
| Maternity scorer rules | Rewrite size sentence in `_scoring_prompt` | No more M/L or plain-L exceptions |
| New leggings watches | 5 normal (non-`bundle_hunt`) watches | Search → score → keep if steal/hunt |

```text
[existing maternity brand + Mama seeds]  --sizes-->  L/XL + XL only; notes prefer leggings
[new maternity leggings watches]         --search-->  colanti / maternity leggings / brand×leggings
[vinted_bot maternity_rules]            --score--->  reject plain L and M/L hard
```

## Config changes

### Shared maternity size policy

- Country: `ro` (unchanged)
- `target_sizes`: `["L/XL", "XL"]` on every maternity watch and Mama/Next/ASOS maternity seed
- Accept text variants via notes / rules: `L-XL`, `L / XL`, `LXL` when they clearly mean the L/XL band
- Reject: plain `L`, `M`, `M/L`, `S/M`, `S`, `XL/XXL`, `XXL`, and similar off-target bands
- No `size_ids` in v1

### Existing maternity brand + seed watches

- Keep queries, `price_to`, `hunt_price`, `per_page`, `brand_ids`, `bundle_hunt`, `min_deal_score`
- **Rename** watch `name` suffixes from `L-XL` → `XL-L/XL` for clarity. Note: `seen_keys` are per hunt name, so this starts a fresh seen namespace for those hunts (acceptable one-time re-score).
- **Notes:** lead with leggings preferred (maternity/over-bump or nursing-friendly; gym + everyday). Then existing category preferences (dresses, trousers, knitwear, outerwear, etc.)
- **Exception:** Tiffany Rose remains occasion-dress-only — do not add a leggings preference there; still rename size suffix and tighten `target_sizes`
- Bundle-seed notes: prefer closets with several useful **L/XL or XL** maternity pieces, especially leggings

### New dedicated maternity leggings watches

Not `bundle_hunt`. Shared fields unless noted:

- `country`: `ro`
- `order`: `newest_first`
- `per_page`: 30
- `target_type`: `women's maternity or nursing leggings`
- `target_sizes`: `["L/XL", "XL"]`
- `min_deal_score`: 8
- `notes`: Prefer true maternity/over-bump or nursing-friendly leggings suitable for gym and everyday. Reject fashion-only non-maternity leggings and wrong sizes (plain L, M/L). Brand-agnostic for broad watches; brand watches stay on that brand.

| name | query | price_to | hunt_price |
|---|---|---|---|
| Broad maternity leggings RO XL-L/XL | `colanti maternity` | 180 | 100 |
| Broad maternity leggings EN XL-L/XL | `maternity leggings` | 180 | 100 |
| Mamalicious leggings XL-L/XL | `mamalicious leggings` | 180 | 100 |
| Seraphine leggings XL-L/XL | `seraphine leggings` | 220 | 120 |
| H&M Mama leggings XL-L/XL | `h&m mama leggings` | 120 | 70 |

Reuse known `brand_ids` from parent watches: Seraphine `133550`, Mamalicious `4694493`. H&M Mama leggings stays query-only (no brand id on the existing seed).

## Scorer change (`python/vinted_bot.py`)

In `_scoring_prompt` maternity_rules:

- Replace “Size target is women's L-XL. M/L or XL/XXL may qualify only when…” with a hard rule: **only `L/XL` (and clear text equivalents) and `XL` qualify; plain `L`, `M/L`, `XL/XXL`, and `XXL` never qualify.**
- Mention leggings among preferred high-value garment types (alongside dresses, trousers, knitwear, outerwear).

No other Python behaviour changes required for v1. `value_haul.size_matches` already does substring/token matching against `target_sizes`; dropping `"L"` stops plain-L closet matches.

## Limits and trade-offs

- Without `size_ids`, wrong-size listings can still enter the LLM batch; notes + maternity_rules + `require_hunt_fit` are the filter.
- Renaming hunt `name`s resets that hunt’s `seen_keys` namespace — accepted one-time re-score cost.
- Broad `colanti maternity` / `maternity leggings` may return non-maternity fashion noise; notes must reject those.
- Everyday runs still use `max_new_items_per_watch` (15); five new watches add LLM cost proportionally.

## Success criteria

- Maternity watches no longer treat plain `L`, `M/L`, or `XXL` as hunt-fit.
- Desk / alerts show maternity leggings from the new dedicated watches, not only incidental brand hits.
- Existing brand maternity keeps still surface non-legging pieces when they are strong XL / L/XL fits.
- Tiffany Rose behaviour unchanged except size list.

## Implementation notes

- Primary edit: `python/config.json` maternity block + five new watches.
- Small edit: maternity_rules string in `python/vinted_bot.py`.
- Add/adjust a focused unit test if maternity size-rule wording is asserted anywhere; otherwise verify via config JSON parse + a small `size_matches` check that `L` fails against `["L/XL", "XL"]` while `L/XL` and `XL` pass.
- Do not commit secrets or `data/` runtime artifacts.
