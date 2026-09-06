vinted deal bot

Hunts Vinted (men's gym / sneakers / knit + maternity L–XL), scores with Vercel AI Gateway, alerts via ntfy, and writes `data/*.json` for the dashboard. Cron runs on **GitHub Actions**; the **dashboard deploys to Vercel** and can trigger those runs.

Search uses **vinted-mcp-cli** (sibling checkout, `npx @googlarz/vinted-client`, or Actions install). Scoring uses **Vercel AI Gateway** first, then optional Gemini. Do not point the cron at the Cursor Agent SDK.

## Architecture

| Piece | Where | Role |
|---|---|---|
| `scripts/vinted_bot.py` | local / GitHub Actions | Search, score, bundles, ntfy, commit `data/` |
| `.github/workflows/vinted-bot.yml` | GitHub | Every 15 min + manual / dashboard trigger |
| `dashboard/` + `api/` | Vercel | Filterable finds, bundles, top sellers, Run hunt |

Vercel does **not** scrape Vinted (too slow / blocked). It reads committed JSON from GitHub and dispatches the Actions workflow.

## Local bot

```bash
set -a && source .env && set +a
uv run python scripts/vinted_bot.py
# one-shot backfill:
FULL_SWEEP=1 uv run python scripts/vinted_bot.py
```

Local dashboard (filesystem data):

```bash
uv run python scripts/serve_dashboard.py
# → http://127.0.0.1:8765/
```

## Deploy dashboard to Vercel

```bash
cd /path/to/vinted-stuffs
npx vercel
```

Vercel project env vars (Production):

| Var | Purpose |
|---|---|
| `GITHUB_TOKEN` | PAT: `repo` + `actions:write` (or fine-grained Contents read + Actions write) |
| `GITHUB_REPO` | `owner/repo` e.g. `rolki-png/vinted-stuffs` |
| `GITHUB_REF` | usually `main` |
| `GITHUB_WORKFLOW` | `vinted-bot.yml` |
| `CRON_SECRET` | optional; Vercel Cron sends it as `Authorization: Bearer …` |

GitHub Actions secrets (unchanged): `AI_GATEWAY_API_KEY`, `NTFY_TOPIC`, optional `GEMINI_API_KEY`. Repo variable `AI_GATEWAY_MODEL` optional.

After deploy: open the Vercel URL → **Run hunt** / **Hide** / **Park** work with no pasted secret. Data updates when Actions commits `data/*`; hit Refresh.

### Schedulers

1. **Primary:** GitHub Actions `*/15 * * * *` (already in the workflow).
2. **Optional backup:** Vercel Cron hits `/api/cron` once daily at 06:00 UTC (`vercel.json`; Hobby plan limit). Keep GitHub Actions as the real 15‑min schedule.

## Dashboard features

- Finds: filter by hunt / band / score / source, sort by score / price / date
- Bundles and top sellers (once seller ids are in the pool / keeps)
- Runs tab: last score histogram + recent Actions runs
- Trigger buttons dispatch `workflow_dispatch` on the hunt workflow

## Config notes

- Omit `price_from` — high-recall search; the scorer judges cheap listings.
- Default keep bar is deal_score ≥ 9 (crème only). Solo clothing floor defaults to 0; if raised, hunt-band clothing under it is blocked unless steal-band.
- `FULL_SWEEP=1` / dashboard Full sweep: paginate hunts, no 10-item cap.

## Known limits

- Search results have no description, so "pay outside the app" will not show up.
- Missing seller history is elevated scam risk.
- GitHub-hosted runners may get DataDome-blocked; local or self-hosted is more reliable for sweeps.
