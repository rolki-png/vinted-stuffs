# Pause men’s gym tees; prefer shorts; drop wool/knitwear hunts

Date: 2026-09-06  
Status: approved  
Repo: `vinted-stuffs`  
Related: `docs/superpowers/specs/2026-09-05-gym-shorts-broad-discovery-design.md` (discovery channel; this spec **hard-rejects tees** and adds wool cleanup)

## Problem

1. **Gym tees are saturated.** The desk and alerts are flooded with men’s gym T-shirts / koszulki from `Gym bundle seeds M-L` (`h&m sport`) and premium gym watches whose notes still allow tops. The buyer no longer wants more tees.
2. **Shorts are still wanted.** Ordinary and premium men’s gym/training shorts remain useful finds.
3. **Wool / hard-care is out.** Cruciani (premium knit) and maternity notes that push knitwear/wool conflict with “no wool or hard-to-care items.” Premium cotton basics (Zimmerli, Hanro, Merz, CDLP) stay.

Notes alone are not enough: the LLM still scores tees and can keep them. Value-haul prefilter currently treats `tee` / `koszulka` / `tricou` as valid gym garments.

## Goal

- **Stop** men’s gym T-shirt discovery, scoring keeps, and haul filler.
- **Keep / widen** men’s gym **shorts** discovery (broad queries + retargeted premium brands + shorts-leaning seeds).
- **Drop** wool/knitwear hunting (Cruciani + maternity knitwear preference wording).
- Leave sneakers, maternity (non-knitwear), and premium cotton basics unchanged in intent.

## Non-goals

- Pausing all men’s gym hunting
- Dropping Zimmerli / Hanro / Merz / CDLP
- Changing sneaker watches
- HU/PL markets or `category_id` filters
- Purging historical `data/*` or Cockroach rows (desk vetoes remain the way to hide old tees)
- Implementing the one-shot FULL_SWEEP file from the 2026-09-05 shorts design unless already present (optional follow-up)

## Decisions

| Topic | Decision |
|---|---|
| Gym garment policy | Men’s gym path: **shorts yes, tees no** |
| Tee rejection | Hard prefilter + scoring notes (not notes-only) |
| Bundle / value haul | Useful items = shorts (and other non-tee gym bottoms/tops only if not tee-shaped); tees never count as useful |
| Wool | Remove Cruciani watch; strip knitwear/wool preference from maternity notes |
| Premium cotton | Keep Zimmerli, Hanro, Merz, CDLP |

## Architecture

```text
Search watches (shorts-focused config)
        │
        ├─► solo score  ── hard tee reject / notes skip tee ──► keep only shorts steals
        │
        └─► bundle_hunt seed ── closet ── prefilter drops tees ──► haul of shorts (+non-tee)
```

Two layers:

1. **Config** — what Vinted is searched for and what the LLM is told.
2. **Code** — cheap reject so tees never burn gateway quota or land as keeps/haul members.

## Config changes (`python/config.json`)

### Broad shorts watches (add if missing)

Align with the 2026-09-05 shorts design (names/queries may match that spec):

- Broad gym shorts queries on `ro`, M/L via `size_ids: [1739, 1740]` + `target_sizes: ["M","L"]`
- `target_type`: men's gym or training shorts
- Notes: technical gym/training shorts; skip kits, cargo, fashion shorts unless exceptional steal

### Replace gym bundle seed

- Remove `"Gym bundle seeds M-L"` (`h&m sport` as the sole seed).
- Add shorts-oriented seeds (at least one `short sport` / `gym shorts` seed; optional multi-brand seeds whose notes say **shorts preferred, never solo-alert on tees**).
- Seed `target_type` / notes: closet-hunt for multi-piece **shorts**-heavy hauls; tees are not useful.

### Premium gym watches (Lululemon … 2XU)

- Keep brand queries and prices.
- Set `target_type` to men's gym/training **shorts** (or “prefer shorts; skip T-shirts”).
- Notes: **Skip all T-shirts / koszulki / tricouri / basic tees.** Prefer shorts; other non-tee technical pieces only if exceptional; casual non-gym = skip.

### Wool / knitwear

- **Delete** watch `"Cruciani M-L"`.
- In maternity watches that mention “knitwear”, rewrite notes to prefer dresses, trousers, leggings, outerwear, easy-care pieces — **do not prefer knitwear/wool/merino/cashmere**.
- Do **not** remove Zimmerli / Hanro / Merz / CDLP.

### Taste family (optional small cleanup)

- `taste_learning` / `FAMILY_RULES` may keep a `knitwear` family for historical veto enrichment; no new knitwear watches. No change required unless tests assume Cruciani exists.

## Code changes

### Tee detector (shared helper)

Add a small predicate, e.g. `looks_like_mens_gym_tee(item) -> bool`, used by gym/value-haul paths:

- Positive signals (title/brand blob): `t-shirt`, `tshirt`, `tee`, `koszulka`, `tricou`, `póló`/`polo` when clearly a tee context, etc.
- **Do not** flag shorts: if blob clearly indicates shorts (`short`, `spoden`, `pantaloni scurti`, …), return false even if “tee” appears in a brand line edge case.
- Scope: only apply on **men’s gym / training / value-haul gym** watches — not maternity, not sneakers, not premium cotton basics watches.

### Value-haul prefilter

- In `looks_like_haul_fit` for non-maternity gym watches: if `looks_like_mens_gym_tee`, return **false**.
- Remove or stop treating bare tee tokens as sufficient `GYM_GARMENTS` success without a shorts (or non-tee garment) signal — tees must not pass the gym haul fit gate.

### Solo scoring prompt

- For men’s gym watches, add an explicit line: men’s gym T-shirts are always skip / not keep, regardless of price; shorts remain the target.

### Tests

- Tee title rejected by gym haul prefilter; shorts title accepted.
- Shorts + “sport” still pass; “H&M Sport koszulka” fails.
- Maternity paths unchanged by tee reject.
- Config still loads; Cruciani absent.

## Success criteria

1. New runs do not keep or alert solo men’s gym tees.
2. Value hauls / near-hauls do not include tee filler as useful items.
3. Shorts still searchable via broad + premium + seeds.
4. Cruciani gone; maternity notes no longer push knitwear/wool.
5. Zimmerli / Hanro / Merz / CDLP still present.

## Out of scope for desk UI

No dashboard changes. Old tee rows may remain until vetoed or aged out of finds.
