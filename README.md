# vinted-stuffs

Buyer-side Vinted hunt bot and Deal desk dashboard.

- **Bot** (`python/`): searches Vinted, scores listings (Vercel AI Gateway / Gemini), builds bundle opportunities, alerts via ntfy, commits `data/*.json`.
- **Dashboard** (TanStack Start): filterable finds, bundles, sellers, and Actions triggers — deploys to Vercel.

## Architecture

| Piece | Where | Role |
|---|---|---|
| `python/vinted_bot.py` | local / GitHub Actions | Search, score, bundles, ntfy, commit `data/` |
| `.github/workflows/vinted-bot.yml` | GitHub | Every 15 min + manual / dashboard trigger |
| TanStack Start (`src/`) | Vercel | Deal desk UI + `/api/*` server routes |

Vercel does **not** scrape Vinted listings. It reads committed JSON (and optional Cockroach score cache), can dispatch the Actions workflow, and (Hunts tab only) looks up Vinted **catalogue** brands/sizes.

## Local bot

```bash
set -a && source .env && set +a
uv run --with-requirements python/requirements.txt python python/vinted_bot.py
FULL_SWEEP=1 uv run --with-requirements python/requirements.txt python python/vinted_bot.py
```

## Local dashboard

```bash
npm install
npm run dev
# → http://127.0.0.1:3000/
```

## Tests

```bash
cd python && python3 -m unittest discover -s tests -v
```

## Deploy dashboard to Vercel

```bash
npx vercel
```

Project env vars (Production):

| Var | Purpose |
|---|---|
| `GITHUB_TOKEN` | PAT: `repo` + `actions:write` (also Contents write for Hunts tab) |
| `GITHUB_REPO` | `owner/repo` |
| `GITHUB_REF` | usually `main` |
| `GITHUB_WORKFLOW` | `vinted-bot.yml` |
| `CRON_SECRET` | optional; Vercel Cron `Authorization: Bearer …` |
| `DATABASE_URL` | optional Cockroach / Postgres for live score index + vetoes |
| `VINTED_PROXY_URL` | optional; catalogue brand/size lookups from Vercel if direct egress is blocked |

After deploy: open the Vercel URL → **Run hunt** / **Remove** / **Park** / **Hunts** work with no pasted secret. Data updates when Actions commits `data/*`; hunt list updates when the Hunts tab saves `python/config.json`. Hit Refresh for finds.

### Schedulers

1. **Primary:** GitHub Actions `*/15 * * * *` (already in the workflow).
2. **Optional backup:** Vercel Cron hits `/api/cron` once daily at 06:00 UTC (`vercel.json`; Hobby plan limit). Keep GitHub Actions as the real 15‑min schedule.

## Repo layout

```
src/                 TanStack Start app (UI + server routes)
  components/        Deal desk React UI
  routes/            File routes including /api/*
  server/            Snapshot, GitHub dispatch, DB helpers
python/              Hunt bot package
  tests/             Python unit tests
  sql/               Schema migrations
data/                Bot-committed JSON snapshots
docs/                Design specs & ADRs
```

## Dashboard features

- Finds: filter by hunt / band / score / source, sort by score / price / date
- Bundles and top sellers (once seller ids are in the pool / keeps)
- Runs tab: last score histogram + recent Actions runs
- **Hunts** tab: add / replace / remove entries in live `python/config.json` via GitHub Contents (next cron/dispatch picks them up)
- Brand and size pickers: desk server routes call Vinted **catalogue** APIs only (`@googlarz/vinted-client`); optional `VINTED_PROXY_URL` if cloud egress is blocked
- Trigger buttons dispatch `workflow_dispatch` on the hunt workflow

Vercel does **not** scrape Vinted listings. Catalogue lookup (brands / size groups) for the Hunts form is the intentional exception.

## Known limits

- Search results have no description, so "pay outside the app" will not show up.
- Missing seller history is elevated scam risk.
- GitHub-hosted runners may get DataDome-blocked; local or self-hosted is more reliable for sweeps.
- Hunts tab write API is open like veto/trigger (server-side `GITHUB_TOKEN`); treat the Vercel URL as private.
