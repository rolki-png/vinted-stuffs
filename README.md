# vinted-stuffs

Buyer-side Vinted hunt bot and Deal desk dashboard.

- **Bot** (`python/`): searches Vinted, scores listings (Vercel AI Gateway / Gemini), builds bundle opportunities, alerts via ntfy, commits `data/*.json`.
- **Dashboard** (TanStack Start): filterable finds, bundles, sellers, and Actions triggers — deploys to Vercel.

## Architecture

| Piece                              | Where                  | Role                                         |
| ---------------------------------- | ---------------------- | -------------------------------------------- |
| `python/vinted_bot.py`             | local / GitHub Actions | Search, score, bundles, ntfy, commit `data/` |
| `.github/workflows/vinted-bot.yml` | GitHub                 | Every 15 min + manual / dashboard trigger    |
| TanStack Start (`src/`)            | Vercel                 | Deal desk UI + `/api/*` server routes        |

Vercel does **not** scrape Vinted listings. It reads committed JSON (and optional Cockroach score cache), can dispatch the Actions workflow, and (Hunts tab only) looks up Vinted **catalogue** brands/sizes.

## Local bot

```bash
set -a && source .env && set +a
uv run --project python python python/vinted_bot.py
FULL_SWEEP=1 uv run --project python python python/vinted_bot.py
```

## Scoring

V2 separates extraction from scoring. The LLM extracts evidence and confidence
for usefulness, quality, condition, versatility, replacement cost, fit, and
duplication. Deterministic code then calculates `buy_score` as purchase utility
on a 0–100 scale, including delivered cost and an uncertainty interval.
Unknown evidence is pulled toward neutral rather than treated as proof of risk.

`buy_band` labels the calculated score: `skip` below 60, `bundle` at 60–74,
`good` at 75–84, `keep` at 85–94, and `exceptional` at 95–100. A Keep also
requires hunt fit, score confidence of at least `min_keep_confidence`
(default 0.60), and no blocking verification concern. Pairwise comparisons rank
only qualifying candidates
whose uncertainty intervals overlap; rank orders close choices but never
changes `buy_score` or promotes a sub-threshold listing. Legacy 1–10 scores are
shown only as labelled history and are never compared with v2 scores.

## Local dashboard

```bash
npm install
npm run dev
# → http://127.0.0.1:3000/
```

## Tests

```bash
uv run --project python python -m unittest discover -s python/tests -v
npm run test:desk
```

`npm test` runs the same Python discovery command through `uv` plus a small
set of dashboard contracts. CI Python installs use `uv sync --project python`;
`python/requirements.txt` mirrors those dependencies for non-uv environments.

## Deploy dashboard to Vercel

```bash
npx vercel
```

Project env vars (Production):

| Var                     | Purpose                                                                 |
| ----------------------- | ----------------------------------------------------------------------- |
| `GITHUB_TOKEN`          | PAT: `repo` + `actions:write` (also Contents write for Hunts tab)       |
| `GITHUB_REPO`           | `owner/repo`                                                            |
| `GITHUB_REF`            | usually `main`                                                          |
| `GITHUB_WORKFLOW`       | `vinted-bot.yml`                                                        |
| `CRON_SECRET`           | optional; Vercel Cron `Authorization: Bearer …`                         |
| `DATABASE_URL`          | optional Cockroach / Postgres for live score index + vetoes             |
| `VINTED_PROXY_URL`      | optional; catalogue brand/size lookups from Vercel if direct egress is blocked |
| `VINTED_COUNTRY`        | Catalog country code. Default `uk`. Desk brand/size APIs and hunt writes use this. |
| `VINTED_FORCE_COUNTRY`  | If set, every hunt search uses this country even when config says otherwise. |
| `VINTED_CURRENCY`       | Fallback currency in prompts, ntfy, and score rows. Default `GBP`.      |
| `VINTED_SITE_HOST`      | Host for member profile links. Default `www.vinted.co.uk`.              |

GitHub Actions (bot) extra:

| Var                  | Purpose |
| -------------------- | ------- |
| `VINTED_CONFIG`      | Optional path to a private hunt config JSON (replaces committed `python/config.json` for the bot). |
| `VINTED_CONFIG_JSON` | **Secret**: full config JSON written to a temp file at job start. Do not commit this. Set the same market vars as Vercel if the live catalog is not UK. |

Committed hunts, fees, and copy default to the UK catalog. To run a different catalog, set the env vars above and keep that catalog’s hunt list in `VINTED_CONFIG` / `VINTED_CONFIG_JSON` — do not put non-UK defaults back into the public tree. `data/*` snapshots follow whichever catalog the bot last ran.

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
- GitHub-hosted runners may get DataDome-blocked; local or self-hosted is more reliable for sweeps.
- Hunts tab write API is open like veto/trigger (server-side `GITHUB_TOKEN`); treat the Vercel URL as private.
