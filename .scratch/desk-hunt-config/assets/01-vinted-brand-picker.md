# Research: Vinted brand picker from the Deal desk

**Ticket:** [01-vinted-brand-picker-from-desk](../issues/01-vinted-brand-picker-from-desk.md)  
**Question:** Can the Deal desk (Vercel TanStack server routes) offer a Vinted brand picker that resolves keyword → numeric `brand_ids` for `config.watches[]`, and if so what call path? Constraints for v1?

**Verdict:** **Yes.** Prefer a new desk server route that calls `@googlarz/vinted-client`’s `opBrands` / `resolveBrandIds` (same `/api/v2/brands?keyword=` path the hunt bot already depends on). Do **not** route the picker through MCP or through GitHub Actions for interactive typing. Treat cloud IP / proxy and “Vercel now talks to Vinted” as the main v1 design constraints.

---

## 1. What `config.watches[].brand_ids` already is

Live hunts already store numeric brand IDs and pass them into search.

Example from [`python/config.json`](../../../python/config.json) (Lulu Pace Breaker hunt):

```json
"brand_ids": [198238]
```

The bot wires those IDs into the CLI search args:

```183:184:python/vinted_bot.py
    if watch.get("brand_ids"):
        args += ["--brand-ids", ",".join(str(i) for i in watch["brand_ids"])]
```

and into the batch search plan as `brandIds` ([`python/vinted_bot.py`](../../../python/vinted_bot.py) around the `_watch_search_plan` path).

So a picker’s job is: **keyword → list of `{id, title, …}` → user picks → persist `number[]` as `brand_ids`**. That matches how watches are already authored by hand today.

---

## 2. Primary call path (as implemented in `vinted-mcp-cli`)

There is **no official public Vinted API**. [`vinted-mcp-cli/README.md`](../../../../vinted-mcp-cli/README.md) states the library bootstraps session cookies from the public catalog page and calls the private JSON API the web app uses.

### Endpoint

[`searchBrands`](../../../../vinted-mcp-cli/src/client/endpoints.ts):

```288:305:../../../../vinted-mcp-cli/src/client/endpoints.ts
export async function searchBrands(
  client: VintedClient,
  keyword: string,
  country: Country = 'fr',
): Promise<BrandHit[]> {
  if (!keyword.trim()) return [];
  const data = await client.apiGet<{ brands?: any[] }>(
    country,
    `/api/v2/brands?keyword=${encodeURIComponent(keyword)}`,
  );
  return (data.brands ?? []).map((b) => ({
    id: Number(b.id),
    title: String(b.title ?? ''),
    slug: String(b.slug ?? ''),
    itemCount: b.item_count,
    favouriteCount: b.favourite_count,
  }));
}
```

Wire shape of each hit: `id`, `title`, `slug`, optional `itemCount` / `favouriteCount`.

### Session / auth (anonymous cookies, not user login)

[`VintedClient.apiGet`](../../../../vinted-mcp-cli/src/client/session.ts):

1. `GET https://{domain}/catalog` → collect `Set-Cookie` pairs (skips empty values).
2. Cache session per country for **10 minutes**.
3. `GET https://{domain}/api/v2/brands?keyword=…` with browser-like headers + `Cookie`, `Referer`, `X-Requested-With: XMLHttpRequest`.
4. On **401**, drop session and re-bootstrap (retry). On **403**, fail with guidance to set `VINTED_PROXY_URL` or use `--browser` for gated endpoints.
5. On **429**, retry up to 3 times with `Retry-After` or exponential backoff.

No Vinted account credentials are involved for brands.

### Rate limit & cache

From [`VintedClient` defaults](../../../../vinted-mcp-cli/src/client/session.ts) / README:

| Knob | Default | Notes |
|---|---|---|
| Token bucket | **3 req/s per country**, burst **6** | Env: `VINTED_RATE_LIMIT_PER_SEC`, `VINTED_RATE_LIMIT_BURST` |
| Response cache TTL | **60s** | Env: `VINTED_CACHE_TTL_MS`; `0` disables |
| Brands vs static catalogues | Brands use **default 60s** TTL | Categories/colors/size groups pass `STATIC_TTL_MS` (1h); **brands do not** |

Picker UX that debounces keystrokes still benefits from the 60s path cache and from `resolveBrandIds`’s in-process name→id memo ([`src/ops/brands.ts`](../../../../vinted-mcp-cli/src/ops/brands.ts)).

### Country

- Domains for 19 countries live in [`DOMAIN`](../../../../vinted-mcp-cli/src/client/types.ts) (includes `ro`).
- MCP `search_brands` documents: *“brand catalogues are shared across countries”* ([`src/mcp.ts`](../../../../vinted-mcp-cli/src/mcp.ts)).
- Library default country for brands is **`fr`**; hunt config / bot default country is **`ro`** ([`_country`](../../../python/vinted_bot.py)).
- **v1 recommendation:** query with the hunt’s `country` (almost always `ro` here) for session consistency with search; IDs should still be usable across sites per the MCP note. Do not invent a second catalogue.

### Exact-match vs first-hit (important for picker UX)

[`resolveBrandIds`](../../../../vinted-mcp-cli/src/ops/brands.ts) (used by CLI `--brand` and MCP `brand[]`):

1. Prefer hit whose `title` equals the query (case-insensitive).
2. Else take **first** hit.
3. Else mark unresolved.

Unit coverage: [`test/brands.test.mjs`](../../../../vinted-mcp-cli/test/brands.test.mjs).

For a **desk picker**, prefer `opBrands` (returns up to `limit`, default 10) and let the human choose — do not auto-commit `resolveBrandIds`’s first-hit fallback into `config.json` without confirmation.

### DataDome / browser fallback

- README: HTML/browser fallback is for **item pages blocked by DataDome**, not for brand search.
- [`fetchItemDetailsViaBrowser`](../../../../vinted-mcp-cli/src/client/browser.ts) only hits `/api/v2/items/{id}/details` inside Playwright. **Not applicable to brands.**
- Practical failure mode for brands on Vercel is the same as other `apiGet` paths: **bootstrap / 403 / Cloudflare on cloud IPs** → set `VINTED_PROXY_URL` (README “Proxy support”). Playwright on Vercel serverless is a non-starter for this feature.

---

## 3. Call-path options for the Deal desk

### Context: what the desk does today

[`README.md`](../../../README.md): *“Vercel does **not** scrape Vinted. It reads committed JSON … and can dispatch the Actions workflow.”* Existing open desk routes (`/api/trigger`, `/api/veto`, …) use server-side secrets only (`GITHUB_TOKEN`, etc.) — no pasted user auth ([`src/routes/api/trigger.ts`](../../../src/routes/api/trigger.ts)). Map charting preference: v1 same openness as veto/trigger.

[`package.json`](../../../package.json): desk deps today are TanStack/React/`pg` only — **no** `@googlarz/vinted-client` yet.

Hunt bot already resolves the same CLI package (sibling checkout or `npx @googlarz/vinted-client`) and Actions checks out `rolki-png/vinted-mcp-cli` ([`.github/workflows/vinted-bot.yml`](../../../.github/workflows/vinted-bot.yml), [`python/vinted_bot.py`](../../../python/vinted_bot.py)).

### Options

| Path | Feasible? | Notes |
|---|---|---|
| **A. TanStack server route + library import** (`opBrands` from `@googlarz/vinted-client`) | **Yes — recommended** | Same code path as CLI/MCP. Add dep (or path to sibling). New `/api/brands?q=` (name TBD). Server-only so cookies never hit the browser. |
| **B. TanStack route shelling out to `vinted brands`** | Possible, worse | Mirrors Python `_vinted_json`; heavier cold start; JSON parsing already exists in CLI. Prefer import. |
| **C. Browser → Vinted directly** | **No** | Needs catalog cookies + same-origin style headers; CORS / cookie jar won’t work from the desk origin. |
| **D. MCP `search_brands`** | **No for desk UI** | MCP is a Cursor/stdio tool surface (`vinted-mcp` bin), not an HTTP service the Vercel app can call. |
| **E. GitHub Actions / bot as proxy** | Awkward | Latency and workflow-dispatch UX unfit for typeahead. Keep Actions for hunt runs only. |
| **F. Hand-rolled fetch of `/api/v2/brands`** | Avoid | Reimplements session, rate limit, 401/429 handling already in `VintedClient`. |

### Recommended concrete shape (design-spec fodder, not implementation)

1. Add dependency on `@googlarz/vinted-client` (published name of [`vinted-mcp-cli`](../../../../vinted-mcp-cli/package.json); public exports include `VintedClient`, `opBrands`, `resolveBrandIds`, `BrandHit` — [`src/index.ts`](../../../../vinted-mcp-cli/src/index.ts)).
2. New server route under `src/routes/api/…` that:
   - accepts `query` (+ optional `country`, `limit`);
   - constructs a module-scoped or request-scoped `VintedClient` (respect `VINTED_PROXY_URL`);
   - returns `opBrands` hits as JSON;
   - stays **unauthenticated at the HTTP edge** like `/api/veto` / `/api/trigger` (blast radius = anyone who can hit the desk URL can burn Vinted quota / probe brands — note in design spec).
3. Hunts form stores selected IDs into `watches[].brand_ids: number[]`.
4. Optional: longer TTL for brand responses than the library default if typeahead is chatty (library default 60s is already reasonable).

This **does** change the README claim that Vercel never talks to Vinted — limit the exception to **catalogue lookup** (brands; later sizes/categories per map “Not yet specified”).

---

## 4. v1 constraints checklist

| Constraint | Assumption for design spec |
|---|---|
| **Auth (Vinted)** | Anonymous catalog-cookie session via `VintedClient`; no buyer login. |
| **Auth (desk)** | Same openness as veto/trigger: no end-user secret; server env only (`VINTED_PROXY_URL` if needed). Document blast radius. |
| **DataDome** | Not the brands path; do not plan Playwright on Vercel. Failures look like 403/bootstrap — fix with proxy. |
| **Country** | Use hunt `country` (default `ro` in this repo). Catalogues shared; don’t dual-query. |
| **Rate limits** | Client-side 3/s/country + burst 6; handle 429. Debounce UI; rely on 60s cache. |
| **Cold start / serverless** | Re-bootstrap cookies per instance (10 min TTL in-process only). Keep requests light; no browser deps. |
| **Proxy** | Expect Vercel egress may need `VINTED_PROXY_URL`; same as CI/cloud guidance in mcp-cli README. |
| **UX correctness** | Show multiple hits; require explicit pick. Don’t silently write first-hit IDs. |
| **Architecture note** | First intentional Vercel→Vinted call; keep it server-side and catalogue-only. |

---

## 5. Sources

All claims above are from:

- `/home/rolki/projects/vinted-mcp-cli` — `src/client/endpoints.ts`, `session.ts`, `ops/brands.ts`, `mcp.ts`, `index.ts`, `browser.ts`, `README.md`, `package.json`, `test/brands.test.mjs`
- `/home/rolki/projects/vinted-stuffs` — `python/config.json`, `python/vinted_bot.py`, `package.json`, `README.md`, `src/routes/api/trigger.ts`, `.github/workflows/vinted-bot.yml`, desk-hunt-config map notes
