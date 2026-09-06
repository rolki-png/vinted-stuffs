# Safe GitHub Contents writes for hunt config

Type: research
Status: resolved
Blocked by:

## Question

How should the desk update `python/config.json` on `main` via the GitHub Contents API so add/replace/remove of hunts is durable for the next Actions run: required PAT scopes, sha optimistic locking, commit message shape, and how this interacts with the bot already committing under `data/` on the same branch? What failure modes must the design spec call out?

## Answer

Reuse the existing Vercel `GITHUB_TOKEN` (classic `repo`, or fine-grained Contents **write** + Actions **write** already needed for dispatch). Read-modify-write `python/config.json` on `main` via Contents GET→mutate `watches` only→PUT with blob **`sha`**. Use messages like `desk: add|replace|remove hunt <name>`. Bot `data/` commits are path-disjoint and rebase-safe, but can still 409 the PUT when they advance the tip — retry once if blob sha unchanged; surface conflict if config changed. Spec must call out 409/auth/422, full-file overwrite risk, and token blast radius.

Full write-up: [assets/02-github-contents-config-write.md](../assets/02-github-contents-config-write.md)
