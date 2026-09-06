# Safe GitHub Contents writes for hunt config

Research for wayfinder ticket `issues/02-github-contents-config-write.md`.
Question: how the Deal desk should update `python/config.json` on `main` via the GitHub Contents API for hunt add/replace/remove.

## Verdict (decision-ready)

Reuse the existing Vercel `GITHUB_TOKEN` / `GITHUB_REPO` / `GITHUB_REF` env (already used for Contents **reads** and workflow dispatch). Implement **read-modify-write** of a single path `python/config.json` on `main`:

1. `GET /repos/{owner}/{repo}/contents/python/config.json?ref=main` → decode JSON, keep response **`sha`** (blob SHA).
2. Mutate only the `watches` array in memory; leave every other top-level key untouched.
3. `PUT` the same path with `message`, Base64 `content`, `sha`, and `branch: main` (or `GITHUB_REF`).
4. Treat **HTTP 409** as optimistic-lock / tip race: re-GET; if the file blob `sha` changed, surface a conflict to the operator; if only the branch tip moved while the config blob is unchanged, retry the PUT once with the same payload + same blob `sha`.

No new PAT scopes beyond what the desk already documents for dispatch + live `data/` reads. Bot commits under `data/` are path-disjoint and already rebase-before-push; they do not overwrite config, but they **can** still cause transient Contents **409**s when they move `main` mid-save.

---

## Primary sources

### Official GitHub API

| Claim | Source |
|---|---|
| Create/replace file: `PUT /repos/{owner}/{repo}/contents/{path}` | [REST: Create or update file contents](https://docs.github.com/en/rest/repos/contents#create-or-update-file-contents) |
| Body requires `message` + Base64 `content`; **`sha` required when updating** (“blob SHA of the file being replaced”) | same |
| Optional `branch` (default: repo default branch) | same |
| Classic PAT / OAuth: **`repo` scope** for this endpoint; extra `workflow` only if editing `.github/workflows` | same |
| Parallel Contents create/update/delete “will conflict”; use serially | same |
| Status codes include **200 / 201 / 404 / 409 / 422** | same |
| GET returns file `sha` + Base64 `content` for files ≤1MB | [REST: Get repository content](https://docs.github.com/en/rest/repos/contents#get-repository-content) |
| Fine-grained PAT: `PUT …/contents/{path}` needs repository **Contents: write** | [Permissions for fine-grained PATs — Contents](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens#repository-permissions-for-contents) |
| Fine-grained PAT: `POST …/actions/workflows/{id}/dispatches` needs repository **Actions: write** | [Permissions for fine-grained PATs — Actions](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens#repository-permissions-for-actions) |
| Workflow dispatch: classic tokens need **`repo`** | [REST: Create a workflow dispatch event](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event) |

### This repo

| Claim | Source |
|---|---|
| Live dashboard reads GitHub Contents for `data/*` with `GITHUB_TOKEN` + `GITHUB_REPO` + `GITHUB_REF` (default `main`) | [`src/server/snapshot.ts`](../../../src/server/snapshot.ts) (`fetchGithubJson`) |
| Contents payloads decoded via base64 or `download_url` when >1MB | [`src/server/githubContents.js`](../../../src/server/githubContents.js) |
| Desk already dispatches Actions with the same Bearer token | [`src/server/github.ts`](../../../src/server/github.ts), [`src/routes/api/trigger.ts`](../../../src/routes/api/trigger.ts) |
| Documented env: `GITHUB_TOKEN` = PAT **`repo` + `actions:write`** | [`README.md`](../../../README.md) (Deploy dashboard to Vercel) |
| Bot loads config from `python/config.json` (override `VINTED_CONFIG`) at run start | [`python/vinted_bot.py`](../../../python/vinted_bot.py) (`CONFIG_PATH`, `load_config`) |
| Workflow: checkout → run bot → commit **only** listed `data/*.json` → `git pull --rebase origin main` → push; message `Update hunt state [skip ci]` | [`.github/workflows/vinted-bot.yml`](../../../.github/workflows/vinted-bot.yml) |
| Workflow triggers: `schedule` + `workflow_dispatch` only (no `push`) | same |
| Job `permissions: contents: write` (Actions `GITHUB_TOKEN` for bot push, not the Vercel PAT) | same |
| Vetoes avoided git `data/` writes partly because of push races; git JSON remains hunt-output cache | [`docs/adr/0003-listing-vetoes-cockroach.md`](../../../docs/adr/0003-listing-vetoes-cockroach.md) |
| Charting preference: desk commits straight to `main` via Contents (same SoT as hand edits) | [map Notes](../map.md) |

Secondary confirmation (not authoritative alone): concurrent Contents updates of **different paths** still **409** when the branch tip moves — reported in [PyGithub#1787](https://github.com/PyGithub/PyGithub/issues/1787) (`"is at … but expected …"`). Aligns with GitHub’s “use serially” note.

---

## PAT scopes

**For config writes alone (Contents PUT):**

- Classic PAT: `repo` (official Contents docs).
- Fine-grained PAT: repository **Contents: Read and write**.

**For the desk as already deployed (read `data/` + dispatch + proposed config write):**

- README’s `repo` + `actions:write` matches: classic `repo` covers Contents + dispatch; fine-grained needs **Contents: write** and **Actions: write**.
- No additional scope is required specifically for `python/config.json` vs `data/*` reads.
- Do **not** need classic `workflow` scope: that is only for modifying files under `.github/workflows` (Contents docs).

**Blast radius (spec must note):** the same long-lived Vercel secret can rewrite any path the token can write and can dispatch hunts. Map already prefers v1 openness like veto/trigger; call out that a leaked token is not “config-only.”

---

## Sha optimistic locking

- On **update**, PUT body **`sha`** must be the **blob SHA** from GET (not the commit SHA of `main`). Official docs: “Required if you are updating a file. The blob SHA of the file being replaced.”
- Flow for the desk:
  - Load form: GET → parse JSON → retain `sha` with the loaded document.
  - Save: PUT with that `sha` + full new file bytes (pretty-printed JSON with trailing newline is fine; match existing file style if practical).
- **Lost-update protection for `config.json`:** if another writer changed the file, blob `sha` mismatches → **409**.
- **Tip races with bot `data/` commits:** even when `python/config.json` blob is unchanged, a concurrent push that advances `main` can still **409** Contents PUT (GitHub serial Contents note + observed tip-mismatch errors). Spec should allow **one automatic retry** after re-GET when the re-fetched config blob `sha` equals the sha used for the failed PUT (tip-only race). If re-fetched blob `sha` differs, **do not** blind-overwrite — surface conflict (exact UX is ticket 05).

Current codebase only **GETs** Contents; there is no PUT helper yet (`github.ts` is dispatch-only; `snapshot.ts` / `githubContents.js` are read/decode).

---

## Commit message shape

Bot precedent: `Update hunt state [skip ci]` ([`.github/workflows/vinted-bot.yml`](../../../.github/workflows/vinted-bot.yml)).

Recommend desk messages that are grep-friendly and name the hunt:

- `desk: add hunt <name>`
- `desk: replace hunt <name>`
- `desk: remove hunt <name>`

Optional `[skip ci]` suffix: **not required today** because the hunt workflow does not trigger on `push` (only schedule + `workflow_dispatch`). Including it matches bot habit and future-proofs if a push-triggered job appears later; either choice is fine if documented.

Committer identity: omit custom `committer` unless you want a fixed “vinted-desk” identity; default is the authenticated PAT user (Contents API).

---

## Interaction with bot `data/` commits on the same branch

| Concern | Behavior |
|---|---|
| Paths | Bot stages only `data/seen_listings.json`, `best_deals.json`, `best_bundles.json`, `bundle_pool.json`, `last_run.json`, `indexed_scores.json`. Desk writes **`python/config.json` only**. No intentional file overlap. |
| Bot push safety | After local commit, bot `git pull --rebase origin main` then `push` — absorbs intervening desk config commits on different paths. |
| In-flight hunt | Bot reads config once from checkout at job start. A desk save mid-run does **not** change that run; the **next** schedule/dispatch run loads the new watches. |
| Contents race | Bot push vs desk PUT can yield **409** on either side of the race; bot recovers via rebase; desk must retry or surface conflict. |
| Auto-run | Map out-of-scope: do not auto `workflow_dispatch` on every save unless a later ticket adds optional Save+Run. Durability = commit on `main`; next cron (`*/15`) picks it up. |
| Why not Cockroach for config | Charting chose git Contents as SoT (same as hand edits). ADR 0003’s race argument applied to high-churn `data/` vetoes; config edits are infrequent and single-file. |

`python/config.json` is currently ~30KB — well under the Contents **1MB** inline limit (GET notes; repo already handles >1MB via `download_url` for `indexed_scores.json`).

---

## Failure modes the design spec must call out

1. **409 Conflict — stale config blob** — another config writer (hand edit, second desk tab, or concurrent Save). Re-GET + show conflict; do not overwrite without operator intent.
2. **409 Conflict — branch tip race** — bot (or other) advanced `main` while config blob unchanged. Safe to retry PUT once after re-GET confirms same blob `sha`.
3. **401 / 403** — missing/expired token or insufficient Contents write (fine-grained Contents read-only would fail PUT while GET still works).
4. **404** — wrong `GITHUB_REPO`, wrong path, or ref.
5. **422** — missing `sha` on update, invalid Base64, malformed committer, or spam/validation failure.
6. **Network / 5xx** — never report success; allow explicit retry.
7. **Read-modify-write bugs** — PUT replaces the **entire file**; dropping top-level scoring / `value_haul` / checkout keys is a data-loss failure mode. Always GET full JSON, mutate `watches` only, PUT full document.
8. **Invalid payload** — schema/validation failures should reject **before** PUT (ticket 04); GitHub will happily commit invalid JSON that breaks the next bot run.
9. **Durability lag** — successful commit ≠ immediate hunt effect; next Actions checkout must include the commit (usually next cron). Optional Save+Run is separate.
10. **Token blast radius** — same secret as trigger; can rewrite arbitrary repo paths if the API is abused or the env is leaked.
11. **Branch protection** — if `main` later requires PR reviews or blocks the PAT, Contents PUT fails; today the bot already pushes to `main` with Actions `contents: write`, so assume direct push is allowed for the configured credential unless protection changes.
12. **No partial multi-file commits** — Contents API is one path per request; do not attempt parallel PUTs.

---

## Recommended server shape (for the later plan — not implementing here)

Mirror existing GitHub client style in `github.ts` / `snapshot.ts`:

- `getConfigJson()` → `{ config, sha, path: "python/config.json", ref }`
- `putConfigJson({ config, sha, message })` → Base64 body, `branch: process.env.GITHUB_REF || "main"`, headers aligned with existing (`Accept: application/vnd.github+json`, `Authorization: Bearer`, `X-GitHub-Api-Version: 2022-11-28`, `User-Agent: vinted-hunt-dashboard`)
- Map HTTP status onto API errors for ticket 05 (conflict vs auth vs validation).

---

## Out of scope for this ticket

- UI conflict copy (map “Not yet specified” + grilling ticket 05).
- Implementing the write route or Hunts tab.
- Switching persistence away from Contents (ruled out in map Out of scope).
