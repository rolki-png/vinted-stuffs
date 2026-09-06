// @ts-nocheck
import { offerFields, DEFAULTS } from './bundleOffer'
import fs from "node:fs"
import path from "node:path"
import os from "node:os"
import pg from "pg"

/**
 * Live scored_listings from Cockroach / Postgres (DATABASE_URL).
 * Used by the Vercel dashboard snapshot so Finds tracks the backfill without waiting for git.
 */

function databaseUrl() {
  return (
    process.env.DATABASE_URL ||
    process.env.COCKROACH_DATABASE_URL ||
    ""
  ).trim() || null;
}

function exportRow(row) {
  const scoredAt = row.scored_at
    ? row.scored_at instanceof Date
      ? row.scored_at.toISOString()
      : String(row.scored_at)
    : null;
  let price = row.price;
  if (price != null) {
    const n = Number(price);
    price = Number.isFinite(n) ? n : null;
  }
  return {
    id: row.item_id != null ? Number(row.item_id) : null,
    watch: row.hunt_name,
    title: row.title || "",
    price,
    currency: row.currency || "RON",
    brand: row.brand,
    size: row.size,
    condition: row.condition,
    url: row.url,
    favourite_count: row.favourite_count,
    seller_id: row.seller_id != null ? Number(row.seller_id) : null,
    seller: row.seller_login,
    seller_country: row.seller_country,
    deal_score: row.deal_score != null ? Number(row.deal_score) : null,
    value_band: row.value_band,
    hunt_fit: row.hunt_fit,
    scam_risk: row.scam_risk,
    reason: row.reason,
    has_score: Boolean(row.has_score),
    scored_at: scoredAt,
    index_source: row.source,
    source: "index",
  };
}

function indexBundleOpportunities(exportRows, { minItems = 2, minDealScore = 6 } = {}) {
  const bySeller = new Map();
  for (const row of exportRows) {
    if (row.hunt_fit === false) continue;
    if (row.value_band === "skip") continue;
    if (row.reason === "unavailable during backfill") continue;
    if (row.has_score) {
      const ds = Number(row.deal_score || 0);
      if (ds < minDealScore) continue;
    } else if (row.hunt_fit !== true) {
      continue;
    }
    if (row.seller_id == null) continue;
    const key = String(row.seller_id);
    if (!bySeller.has(key)) bySeller.set(key, []);
    bySeller.get(key).push(row);
  }

  const out = [];
  const defaultExtra = DEFAULTS.default_checkout_extra_ron;
  for (const [sid, rows] of bySeller) {
    const best = new Map();
    for (const r of rows) {
      const id = String(r.id);
      const prev = best.get(id);
      if (!prev || Number(r.deal_score || 0) > Number(prev.deal_score || 0)) {
        best.set(id, r);
      }
    }
    const members = [...best.values()];
    if (members.length < minItems) continue;
    members.sort((a, b) => Number(b.deal_score || 0) - Number(a.deal_score || 0));
    let listingSum = 0;
    for (const r of members) listingSum += Number(r.price || 0);
    const seller = members.find((r) => r.seller)?.seller || null;
    const country = members.find((r) => r.seller_country)?.seller_country || null;
    const keeps = members.filter(
      (r) => Number(r.deal_score || 0) >= 9 && (r.value_band === "steal" || r.value_band === "hunt")
    );
    const kind =
      keeps.length && members.length > keeps.length
        ? "index_keep_bundle"
        : "index_near_bundle";
    const watchName = members.find((r) => r.watch)?.watch || null;
    const extra = defaultExtra;
    const row = {
      kind,
      kept_at: members.map((r) => r.scored_at || "").sort().reverse()[0] || null,
      seller,
      seller_id: /^\d+$/.test(sid) ? Number(sid) : sid,
      country,
      checkout_extra_ron: extra,
      listing_sum: listingSum,
      checkout_total: listingSum + extra,
      value_band: "opportunity",
      reason: "Indexed same-seller listings (live from score cache)",
      items: members.map((r) => ({
        role:
          Number(r.deal_score || 0) >= 9 && (r.value_band === "steal" || r.value_band === "hunt")
            ? "keep"
            : "extra",
        id: r.id,
        title: r.title,
        price: r.price,
        url: r.url,
        watch: r.watch,
        deal_score: r.deal_score,
        seller_id: r.seller_id,
        seller: r.seller || seller,
      })),
    };
    Object.assign(row, offerFields(listingSum, extra, members.length, { kind, watchName }));
    out.push(row);
  }
  out.sort((a, b) => String(b.kept_at || "").localeCompare(String(a.kept_at || "")));
  return out;
}

function sslConfig() {
  const caPath =
    process.env.PGSSLROOTCERT ||
    path.join(os.homedir(), ".postgresql", "root.crt");
  if (fs.existsSync(caPath)) {
    return { ca: fs.readFileSync(caPath), rejectUnauthorized: true };
  }
  // Vercel / serverless: public CA chain (Cockroach Cloud uses ISRG) usually works.
  return { rejectUnauthorized: true };
}

/**
 * @returns {Promise<{ rows: object[], count: number, source: string } | null>}
 */
async function loadIndexedFromDb(limit = 10000) {
  const url = databaseUrl();
  if (!url) return null;
  const { Client } = pg;

  // Avoid sslmode=verify-full fighting Node when no local CA file on Vercel.
  let connectionString = url;
  if (!fs.existsSync(path.join(os.homedir(), ".postgresql", "root.crt"))) {
    connectionString = url.replace(/sslmode=verify-full/gi, "sslmode=require");
  }

  const client = new Client({
    connectionString,
    ssl: sslConfig(),
    connectionTimeoutMillis: 8000,
    query_timeout: 15000,
  });

  try {
    await client.connect();
    const countRes = await client.query(
      `SELECT COUNT(*)::int AS n FROM scored_listings
       WHERE has_score = true
         AND COALESCE(reason, '') <> 'unavailable during backfill'`
    );
    const count = countRes.rows[0]?.n ?? 0;
    const res = await client.query(
      `SELECT item_id, hunt_name, title, price, currency, brand, size, condition, url,
              favourite_count, seller_id, seller_login, seller_country,
              deal_score, value_band, hunt_fit, scam_risk, reason, has_score, scored_at, source
       FROM scored_listings
       WHERE has_score = true
         AND COALESCE(reason, '') <> 'unavailable during backfill'
       ORDER BY scored_at DESC
       LIMIT $1`,
      [limit]
    );
    return {
      rows: res.rows.map(exportRow),
      count,
      source: "cockroach",
    };
  } catch (err) {
    console.error("scoredDb: query failed:", err.message || err);
    return null;
  } finally {
    try {
      await client.end();
    } catch {
      /* ignore */
    }
  }
}

export {
databaseUrl,
  loadIndexedFromDb,
  indexBundleOpportunities,
  exportRow,
}
