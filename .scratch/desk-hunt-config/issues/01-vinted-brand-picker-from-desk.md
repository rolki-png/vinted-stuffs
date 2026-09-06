# Vinted brand picker from the desk

Type: research
Status: resolved
Blocked by:

## Question

Can the Deal desk (Vercel TanStack server routes) offer a Vinted **brand picker** that resolves keyword → numeric `brand_ids` suitable for `config.watches[]`, and if so what is the concrete call path (reuse `vinted-mcp-cli` / `/api/v2/brands`, proxy, MCP, or something else)? What constraints (auth, DataDome, country, rate limits) should the design spec assume for v1?

## Answer

**Yes.** Add a TanStack server route that imports `opBrands` (picker list) / optionally `resolveBrandIds` from `@googlarz/vinted-client` — same private `GET /api/v2/brands?keyword=` path the hunt bot already uses. Do not use MCP, browser→Vinted, or Actions as the interactive path.

**v1 constraints:** anonymous catalog-cookie auth (no Vinted login); desk stays open like veto/trigger; DataDome/Playwright is for item details only — brands fail as 403/bootstrap on bad cloud IPs → `VINTED_PROXY_URL`; query with hunt `country` (usually `ro`; catalogues shared); rate limit ~3 req/s/country + 60s cache; require explicit pick (don’t auto-write first-hit). This is the first intentional Vercel→Vinted call — keep it server-side catalogue-only.

Full write-up: [assets/01-vinted-brand-picker.md](../assets/01-vinted-brand-picker.md)

**Note:** `.scratch/` is gitignored; research files were force-added onto branch `research/desk-brand-picker` so the throwaway commit could capture them.
