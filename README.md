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

Vercel does **not** scrape Vinted. It reads committed JSON (and optional Cockroach score cache) and can dispatch the Actions workflow.

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
cd python && python -m unittest discover -s tests -v
```

## Deploy dashboard to Vercel

```bash
npx vercel
```

Project env vars (Production):

| Var | Purpose |
|---|---|
| `GITHUB_TOKEN` | PAT: `repo` + `actions:write` |
| `GITHUB_REPO` | `owner/repo` |
| `GITHUB_REF` | usually `main` |
| `GITHUB_WORKFLOW` | `vinted-bot.yml` |
| `DASHBOARD_SECRET` | long random string — paste into the desk UI to run hunts / veto |
| `CRON_SECRET` | optional; Vercel Cron `Authorization: Bearer …` |
| `DATABASE_URL` | optional Cockroach / Postgres for live score index + vetoes |

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
