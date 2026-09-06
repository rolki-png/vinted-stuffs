# Desk hunt configuration

Label: `wayfinder:map`

## Destination

A design spec for configuring **hunts** from the Deal desk: add, replace, and remove entries in the live `python/config.json` `watches` array that GitHub Actions already runs — ready to hand to a plan/build session.

## Notes

- Domain: vinted hunt / Deal desk (`CONTEXT.md`). Prefer **Hunt** in UI copy; `watches` / `watch` remain config keys only.
- Skills every session should consult: `grilling`, `domain-modeling`; `research` for catalogue/API tickets; `writing-plans` only after this map closes.
- Persistence preference (charting): desk commits straight to `main` via GitHub Contents API (same source of truth as hand edits).
- Auth preference (charting): v1 same openness as veto/trigger (server-side `GITHUB_TOKEN` only); note blast-radius risk in the spec.
- Surface preference (charting): new **Hunts** tab (list + form + Add / Save / Remove).
- Fields preference (charting): common hunt fields for v1, **plus a Vinted brand picker** if research shows the desk can resolve brand IDs the same way search already does; otherwise `brand_ids` stays a deferred/advanced path.
- Remove preference (charting): drop from `watches` only — do not purge `seen_keys` / score history. Keeping `name` on replace preserves hunt identity; rename = new identity.
- Plan, don't implement, inside this map unless Notes are later overridden.

## Decisions so far

<!-- index: one line per closed ticket -->
- [Vinted brand picker from the desk](issues/01-vinted-brand-picker-from-desk.md): Yes — desk server route via `@googlarz/vinted-client` `opBrands` → `/api/v2/brands`; proxy/rate-limit/open-desk constraints for v1
- [Safe GitHub Contents writes for hunt config](issues/02-github-contents-config-write.md): Contents GET→R-M-W `watches`→PUT with blob sha on `main`; existing `repo`/Contents-write PAT; tip races with bot `data/` → 409 retry; conflict if config sha moved

## Not yet specified

- Size (and possibly category) pickers using Vinted catalogues, same spirit as brand picker
- Whether Save should offer an optional one-shot “Run hunt” after a successful commit (existing trigger stays either way)
- Exact conflict copy when another writer changed `config.json` between load and save

## Out of scope

- Editing top-level scoring / `value_haul` / checkout knobs from the desk
- Multi-user auth / accounts for the desk
- Parallel config store or PR-only workflow (ruled out in favour of direct `main` Contents commits)
- Automatic workflow dispatch on every hunt save (unless a later ticket revisits the optional Save+Run idea above)
