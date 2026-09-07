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
requires hunt fit, score confidence of at least 0.60, and no blocking
verification concern. Pairwise comparisons rank only qualifying candidates
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
```

## Legacy v2 rollout

The production legacy migration has not been run by this change. The preferred
rollout is a manual **vinted-deal-bot** GitHub Actions dispatch with
`legacy_active_v2` enabled. That path injects the repository's `DATABASE_URL`,
AI gateway/Gemini, and Vinted CLI settings without exposing their values. Each
dispatch availability-checks one bounded batch before any paid scoring call,
commits the export and progress state, and reports:

- exit `0`: no available active-hunt legacy gaps remain;
- exit `3`: a partial batch was committed; dispatch the rollout again;
- any other nonzero exit: an operational failure.

Confirmed unavailable rows keep their historical score and rationale and are
tracked outside the score row, so they do not consume later batches or count as
active completion gaps. Fetch failures remain retryable. Normal manual and
scheduled bot runs do not enter this rollout path.

For a deliberate local rollout with the same database and provider environment
configured:

```bash
uv run --project python python python/backfill_scored_listings.py \
  --legacy-active-v2 --limit 10000 --export
```

This command can incur paid LLM usage.

## Deploy dashboard to Vercel

```bash
npx vercel
```

Project env vars (Production):

| Var                | Purpose                                                                        |
| ------------------ | ------------------------------------------------------------------------------ |
| `GITHUB_TOKEN`     | PAT: `repo` + `actions:write` (also Contents write for Hunts tab)              |
| `GITHUB_REPO`      | `owner/repo`                                                                   |
| `GITHUB_REF`       | usually `main`                                                                 |
| `GITHUB_WORKFLOW`  | `vinted-bot.yml`                                                               |
| `CRON_SECRET`      | optional; Vercel Cron `Authorization: Bearer …`                                |
| `DATABASE_URL`     | optional Cockroach / Postgres for live score index + vetoes                    |
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
- GitHub-hosted runners may get DataDome-blocked; local or self-hosted is more reliable for sweeps.
- Hunts tab write API is open like veto/trigger (server-side `GITHUB_TOKEN`); treat the Vercel URL as private.
