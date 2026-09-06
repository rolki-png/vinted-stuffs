/**
 * Listing vetoes (Hide / Park) — Cockroach map + pure desk apply helpers.
 * Mirrors scripts/listing_vetoes.py.
 */
const fs = require("fs");
const path = require("path");
const os = require("os");

const STATUS_HIDDEN = "hidden";
const STATUS_PARKED = "parked";
const VALID = new Set([STATUS_HIDDEN, STATUS_PARKED]);

const DDL = `
CREATE TABLE IF NOT EXISTS listing_vetoes (
  item_id BIGINT NOT NULL PRIMARY KEY,
  status TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
`;

function databaseUrl() {
  return (
    process.env.DATABASE_URL ||
    process.env.COCKROACH_DATABASE_URL ||
    ""
  ).trim() || null;
}

function sslConfig() {
  return { rejectUnauthorized: false };
}

function itemId(rowOrId) {
  const raw =
    rowOrId && typeof rowOrId === "object"
      ? rowOrId.id ?? rowOrId.item_id
      : rowOrId;
  if (raw == null) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

function statusFor(vetoes, rowOrId) {
  const id = itemId(rowOrId);
  if (id == null) return null;
  return vetoes[id] || vetoes[String(id)] || null;
}

function isHidden(vetoes, rowOrId) {
  return statusFor(vetoes, rowOrId) === STATUS_HIDDEN;
}

function isParked(vetoes, rowOrId) {
  return statusFor(vetoes, rowOrId) === STATUS_PARKED;
}

function sortVetoKey(row) {
  const st = row.veto_status;
  if (st === STATUS_PARKED) return 1;
  if (st === STATUS_HIDDEN) return 2;
  return 0;
}

function applyToFinds(rows, vetoes, { mode = "active" } = {}) {
  if (!["active", "parked", "hidden", "all"].includes(mode)) {
    throw new Error(`unknown veto mode: ${mode}`);
  }
  const out = [];
  for (const row of rows || []) {
    const st = statusFor(vetoes, row);
    if (mode === "active" && st === STATUS_HIDDEN) continue;
    if (mode === "parked" && st !== STATUS_PARKED) continue;
    if (mode === "hidden" && st !== STATUS_HIDDEN) continue;
    const tagged = { ...row };
    if (st) tagged.veto_status = st;
    else delete tagged.veto_status;
    out.push(tagged);
  }
  return out.sort((a, b) => sortVetoKey(a) - sortVetoKey(b));
}

function applyToBundles(rows, vetoes, { mode = "active" } = {}) {
  if (!["active", "parked", "hidden", "all"].includes(mode)) {
    throw new Error(`unknown veto mode: ${mode}`);
  }
  const out = [];
  for (const bundle of rows || []) {
    const items = Array.isArray(bundle.items) ? bundle.items : [];
    const kept = [];
    for (const it of items) {
      const st = statusFor(vetoes, it);
      if (mode === "active" && st === STATUS_HIDDEN) continue;
      if (mode === "parked" && st === STATUS_HIDDEN) continue;
      if (mode === "hidden" && st !== STATUS_HIDDEN) continue;
      const tagged = { ...it };
      if (st) tagged.veto_status = st;
      else delete tagged.veto_status;
      kept.push(tagged);
    }
    if (mode === "hidden") {
      if (!kept.length) continue;
    } else if (kept.length < 2) {
      continue;
    } else if (
      mode === "parked" &&
      !kept.some((it) => it.veto_status === STATUS_PARKED)
    ) {
      continue;
    }

    const row = { ...bundle, items: kept };
    let listingSum = 0;
    for (const it of kept) {
      const p = Number(it.price);
      if (Number.isFinite(p)) listingSum += p;
    }
    row.listing_sum = listingSum;
    if (row.checkout_extra_ron != null) {
      const extra = Number(row.checkout_extra_ron);
      if (Number.isFinite(extra)) row.checkout_total = listingSum + extra;
    }
    const anyParked = kept.some((it) => it.veto_status === STATUS_PARKED);
    const anyHidden = kept.some((it) => it.veto_status === STATUS_HIDDEN);
    if (mode === "hidden" || (mode === "all" && anyHidden && !anyParked)) {
      row.veto_status = STATUS_HIDDEN;
    } else if (anyParked) {
      row.veto_status = STATUS_PARKED;
    } else {
      delete row.veto_status;
    }
    out.push(row);
  }
  return out.sort((a, b) => sortVetoKey(a) - sortVetoKey(b));
}

async function withClient(fn) {
  const url = databaseUrl();
  if (!url) return null;
  let Client;
  try {
    ({ Client } = require("pg"));
  } catch {
    console.error("listingVetoes: pg package missing");
    return null;
  }
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
    await client.query(DDL);
    return await fn(client);
  } catch (err) {
    console.error("listingVetoes:", err.message || err);
    return null;
  } finally {
    try {
      await client.end();
    } catch {
      /* ignore */
    }
  }
}

async function loadVetoMap() {
  const map = await withClient(async (client) => {
    const res = await client.query("SELECT item_id, status FROM listing_vetoes");
    const out = {};
    for (const row of res.rows) {
      out[Number(row.item_id)] = String(row.status);
    }
    return out;
  });
  return map || {};
}

async function setVetoStatus(itemId, status) {
  const id = Number(itemId);
  if (!Number.isFinite(id)) {
    const err = new Error("invalid_item_id");
    err.status = 400;
    throw err;
  }
  if (!VALID.has(status)) {
    const err = new Error("invalid_status");
    err.status = 400;
    throw err;
  }
  const ok = await withClient(async (client) => {
    await client.query(
      `INSERT INTO listing_vetoes (item_id, status, updated_at)
       VALUES ($1, $2, now())
       ON CONFLICT (item_id) DO UPDATE SET
         status = EXCLUDED.status,
         updated_at = EXCLUDED.updated_at`,
      [id, status]
    );
    return true;
  });
  if (!ok) {
    const err = new Error("veto_db_unavailable");
    err.status = 503;
    throw err;
  }
  return { item_id: id, status };
}

async function clearVeto(itemId) {
  const id = Number(itemId);
  if (!Number.isFinite(id)) {
    const err = new Error("invalid_item_id");
    err.status = 400;
    throw err;
  }
  const ok = await withClient(async (client) => {
    await client.query("DELETE FROM listing_vetoes WHERE item_id = $1", [id]);
    return true;
  });
  if (!ok) {
    const err = new Error("veto_db_unavailable");
    err.status = 503;
    throw err;
  }
  return { item_id: id, cleared: true };
}

module.exports = {
  STATUS_HIDDEN,
  STATUS_PARKED,
  databaseUrl,
  isHidden,
  isParked,
  applyToFinds,
  applyToBundles,
  loadVetoMap,
  setVetoStatus,
  clearVeto,
};
