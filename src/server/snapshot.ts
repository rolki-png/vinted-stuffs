// @ts-nocheck
import { loadIndexedFromDb, indexBundleOpportunities } from './scoredDb'
import { loadVetoMap, applyToFinds, applyToBundles } from './listingVetoes'
import { jsonFromGithubContents } from './githubContents.js'
import fs from "node:fs"
import path from "node:path"

/**
 * Shared snapshot builder for Vercel APIs and local Node tooling.
 * On Vercel: reads data/* live from GitHub (bot commits after each run).
 * Locally: prefers filesystem under data/.
 */

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function score(v) {
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? n : 0;
}

async function fetchGithubJson(relPath) {
  const repo = process.env.GITHUB_REPO;
  const token = process.env.GITHUB_TOKEN;
  const ref = process.env.GITHUB_REF || "main";
  if (!repo || !token) {
    throw new Error("GITHUB_REPO and GITHUB_TOKEN required to load live data");
  }
  const url = `https://api.github.com/repos/${repo}/contents/${relPath}?ref=${encodeURIComponent(ref)}`;
  const res = await fetch(url, {
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "User-Agent": "vinted-hunt-dashboard",
      "X-GitHub-Api-Version": "2022-11-28",
    },
  });
  if (res.status === 404) return null;
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`GitHub ${res.status} for ${relPath}: ${text.slice(0, 200)}`);
  }
  const body = await res.json();
  return jsonFromGithubContents(body, relPath, { token });
}

function readLocalJson(relPath, fallback) {
  const full = path.join(process.cwd(), relPath);
  if (!fs.existsSync(full)) return fallback;
  try {
    return JSON.parse(fs.readFileSync(full, "utf8"));
  } catch {
    return fallback;
  }
}

async function loadJson(name, fallback) {
  const rel = `data/${name}`;
  if (process.env.GITHUB_TOKEN && process.env.GITHUB_REPO) {
    try {
      const remote = await fetchGithubJson(rel);
      return remote == null ? fallback : remote;
    } catch (err) {
      // Fall back to files shipped with the deployment if GitHub is down.
      const local = readLocalJson(rel, null);
      if (local != null) return local;
      throw err;
    }
  }
  return readLocalJson(rel, fallback);
}

function bumpSeller(sellers, { sid, login, country, dealScore, band, isKeep, itemId, watch }) {
  if (sid == null && !login) return;
  const key = String(sid || login);
  const row = sellers.get(key) || {
    seller_id: sid || null,
    seller: login || null,
    country: country || null,
    count: 0,
    keeps: 0,
    score_sum: 0,
    best_score: 0,
    bands: {},
    item_ids: new Set(),
    watches: new Set(),
  };
  if (login && !row.seller) row.seller = login;
  if (sid && !row.seller_id) row.seller_id = sid;
  if (country && !row.country) row.country = country;
  if (itemId != null) row.item_ids.add(String(itemId));
  if (watch) row.watches.add(watch);
  const s = score(dealScore);
  row.count += 1;
  row.score_sum += s;
  row.best_score = Math.max(row.best_score, s);
  if (isKeep || band === "steal") row.keeps += 1;
  if (band) row.bands[band] = (row.bands[band] || 0) + 1;
  sellers.set(key, row);
}

async function buildSnapshot({ vetoMode = "active" } = {}) {
  const mode = ["active", "parked", "bought", "all"].includes(vetoMode)
    ? vetoMode
    : "active";

  // Prefer Cockroach for indexed finds. Skip the GitHub export when DB has rows —
  // indexed_scores.json often exceeds GitHub's 1MB Contents inline limit (~4MB+).
  const dbIndexedPromise = loadIndexedFromDb(10000);
  const [deals, bundlesRaw, pool, run, seen, dbIndexed, vetoes] =
    await Promise.all([
      loadJson("best_deals.json", []),
      loadJson("best_bundles.json", []),
      loadJson("bundle_pool.json", []),
      loadJson("last_run.json", {}),
      loadJson("seen_listings.json", {}),
      dbIndexedPromise,
      loadVetoMap(),
    ]);

  const indexedFile =
    dbIndexed && Array.isArray(dbIndexed.rows) && dbIndexed.rows.length
      ? []
      : await loadJson("indexed_scores.json", []);

  const indexed =
    dbIndexed && Array.isArray(dbIndexed.rows) && dbIndexed.rows.length
      ? dbIndexed.rows
      : Array.isArray(indexedFile)
        ? indexedFile
        : [];
  const indexedSource = dbIndexed?.source || (indexed.length ? "indexed_scores.json" : "none");
  const indexedTotal = dbIndexed?.count ?? indexed.length;

  let bundles = Array.isArray(bundlesRaw) ? [...bundlesRaw] : [];
  if (dbIndexed?.rows?.length) {
    const indexOpps = indexBundleOpportunities(dbIndexed.rows);
    // Prefer existing haul/keep rows; append index opps that don't duplicate seller+items loosely
    const existingFp = new Set(
      bundles.map((b) => {
        const ids = (b.items || []).map((it) => String(it.id)).filter(Boolean).sort().join(",");
        return `${b.seller_id || ""}:${ids}`;
      })
    );
    for (const opp of indexOpps) {
      const ids = (opp.items || []).map((it) => String(it.id)).filter(Boolean).sort().join(",");
      const fp = `${opp.seller_id || ""}:${ids}`;
      if (!existingFp.has(fp)) {
        bundles.push(opp);
        existingFp.add(fp);
      }
    }
  }

  const findsById = new Map();

  for (const row of Array.isArray(deals) ? deals : []) {
    if (row.id == null) continue;
    findsById.set(String(row.id), {
      ...row,
      source: "keep",
      price_num: num(row.price),
      deal_score: score(row.deal_score),
    });
  }

  for (const row of indexed) {
    if (row.id == null) continue;
    const id = String(row.id);
    const existing = findsById.get(id);
    if (existing && existing.source === "keep") {
      // Keep rows win on ranking fields, but fill brand/size gaps from cache.
      findsById.set(id, {
        ...existing,
        brand: existing.brand ?? row.brand ?? null,
        size: existing.size ?? row.size ?? null,
        title: existing.title || row.title || existing.title,
        url: existing.url || row.url || existing.url,
      });
      continue;
    }
    findsById.set(id, {
      ...(existing || {}),
      ...Object.fromEntries(Object.entries(row).filter(([, v]) => v != null)),
      source: existing?.source === "scored" || existing?.source === "pool" ? existing.source : "index",
      price_num: num(row.price != null ? row.price : existing?.price),
      deal_score: score(row.deal_score != null ? row.deal_score : existing?.deal_score),
      hunt_fit: row.hunt_fit != null ? row.hunt_fit : existing?.hunt_fit,
    });
  }

  for (const row of run.top || []) {
    if (row.id == null) continue;
    const id = String(row.id);
    const base = findsById.get(id) || {};
    findsById.set(id, {
      ...base,
      ...Object.fromEntries(Object.entries(row).filter(([, v]) => v != null)),
      source: base.source === "keep" ? "keep" : base.source || "scored",
      price_num: num(row.price != null ? row.price : base.price),
      deal_score: score(row.deal_score != null ? row.deal_score : base.deal_score),
      kept_at: base.kept_at || null,
    });
  }

  for (const raw of Array.isArray(pool) ? pool : []) {
    const item = raw.item || {};
    const sc = raw.score || {};
    if (item.id == null) continue;
    const id = String(item.id);
    const user = item.user || {};
    const price =
      item.price && typeof item.price === "object" ? item.price.amount : item.price;
    const currency =
      item.price && typeof item.price === "object"
        ? item.price.currency_code
        : null;
    const existing = findsById.get(id) || {};
    findsById.set(id, {
      ...existing,
      id: item.id,
      title: item.title || existing.title,
      price: price != null ? price : existing.price,
      price_num: price != null ? num(price) : existing.price_num,
      currency: currency || existing.currency || "RON",
      url: item.url || existing.url,
      watch: raw.watch || existing.watch,
      deal_score: score(sc.deal_score != null ? sc.deal_score : existing.deal_score),
      value_band: sc.value_band || existing.value_band,
      scam_risk: sc.scam_risk || existing.scam_risk,
      hunt_fit: sc.hunt_fit != null ? sc.hunt_fit : existing.hunt_fit,
      reason: sc.reason || existing.reason,
      seller_id: raw.seller_id || user.id || existing.seller_id,
      seller: user.login || raw.seller || existing.seller,
      seller_country: (item._profile && item._profile.country_code) || existing.seller_country,
      source: existing.source || "pool",
    });
  }

  // Propagate known usernames onto finds/bundles that only have seller_id.
  const loginBySid = new Map();
  for (const f of findsById.values()) {
    if (f.seller_id != null && f.seller) loginBySid.set(String(f.seller_id), f.seller);
  }
  for (const b of Array.isArray(bundles) ? bundles : []) {
    if (b.seller_id != null && b.seller) loginBySid.set(String(b.seller_id), b.seller);
    for (const it of b.items || []) {
      if ((it.seller_id || b.seller_id) != null && (it.seller || b.seller)) {
        loginBySid.set(String(it.seller_id || b.seller_id), it.seller || b.seller);
      }
    }
  }
  for (const f of findsById.values()) {
    if (!f.seller && f.seller_id != null && loginBySid.has(String(f.seller_id))) {
      f.seller = loginBySid.get(String(f.seller_id));
    }
  }
  for (const b of Array.isArray(bundles) ? bundles : []) {
    if (!b.seller && b.seller_id != null && loginBySid.has(String(b.seller_id))) {
      b.seller = loginBySid.get(String(b.seller_id));
    }
    for (const it of b.items || []) {
      const sid = it.seller_id || b.seller_id;
      if (!it.seller && sid != null && loginBySid.has(String(sid))) {
        it.seller = loginBySid.get(String(sid));
      }
      if (!it.seller && b.seller) it.seller = b.seller;
    }
  }

  const finds = [...findsById.values()];

  const dataSource =
    indexedSource === "cockroach"
      ? `cockroach+${
          process.env.GITHUB_TOKEN && process.env.GITHUB_REPO
            ? `github:${process.env.GITHUB_REPO}`
            : "json"
        }`
      : process.env.GITHUB_TOKEN && process.env.GITHUB_REPO
        ? `github:${process.env.GITHUB_REPO}@${process.env.GITHUB_REF || "main"}`
        : "local-filesystem";

  const findsApplied = applyToFinds(finds, vetoes, { mode });
  const bundlesApplied = applyToBundles(
    Array.isArray(bundles) ? bundles : [],
    vetoes,
    { mode }
  );

  // Rebuild sellers from post-veto desk rows so Remove drops sold inventory
  // from Top sellers / one-off aggregates.
  const sellers = new Map();
  for (const f of findsApplied) {
    bumpSeller(sellers, {
      sid: f.seller_id,
      login: f.seller,
      country: f.seller_country,
      dealScore: f.deal_score,
      band: f.value_band,
      isKeep: f.source === "keep" || f.value_band === "steal" || f.value_band === "hunt",
      itemId: f.id,
      watch: f.watch,
    });
  }
  for (const b of bundlesApplied) {
    bumpSeller(sellers, {
      sid: b.seller_id,
      login: b.seller,
      country: b.country,
      dealScore: 0,
      band: null,
      isKeep: false,
      itemId: null,
      watch: null,
    });
    for (const it of b.items || []) {
      bumpSeller(sellers, {
        sid: b.seller_id,
        login: b.seller,
        country: b.country,
        dealScore: it.deal_score,
        band: it.role === "keep" ? "steal" : "hunt",
        isKeep: it.role === "keep",
        itemId: it.id,
        watch: it.watch,
      });
    }
  }

  const sellerRows = [...sellers.values()]
    .map((row) => {
      const n = Math.max(row.count, 1);
      return {
        seller_id: row.seller_id,
        seller: row.seller || `user ${row.seller_id}`,
        country: row.country,
        listings: row.item_ids.size || row.count,
        keeps: row.keeps,
        avg_score: Math.round((row.score_sum / n) * 100) / 100,
        best_score: row.best_score,
        bands: row.bands,
        watches: [...row.watches].sort(),
        profile_url: row.seller_id
          ? `https://www.vinted.ro/member/${row.seller_id}`
          : null,
      };
    })
    .sort((a, b) => b.best_score - a.best_score || b.avg_score - a.avg_score || b.keeps - a.keeps);

  return {
    finds: findsApplied,
    bundles: bundlesApplied,
    sellers: sellerRows,
    watches: [...new Set(findsApplied.map((f) => f.watch).filter(Boolean))].sort(),
    veto_mode: mode,
    run: {
      finished_at: run.finished_at || null,
      scored: run.scored ?? null,
      solo_keeps: run.solo_keeps ?? null,
      bundles: run.bundles ?? null,
      alerts: run.alerts ?? null,
      score_histogram: run.score_histogram || {},
      seen_keys: (seen.seen_keys || []).length,
      run_count: seen.run_count ?? null,
      last_run: seen.last_run || null,
    },
    meta: {
      source: dataSource,
      generated_at: new Date().toISOString(),
      indexed_count: indexedTotal,
      indexed_source: indexedSource,
      veto_count: Object.keys(vetoes || {}).length,
    },
  };
}

export {
buildSnapshot
}
