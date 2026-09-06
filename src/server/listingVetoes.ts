// @ts-nocheck
import fs from "node:fs"
import path from "node:path"
import os from "node:os"
import pg from "pg"
import { resolveFamily } from "#/server/tasteLearning"

/**
 * Listing vetoes (Remove / Park / Bought) — Cockroach map + pure desk apply helpers.
 * Mirrors python/listing_vetoes.py.
 */

const STATUS_REMOVED = "removed"
const STATUS_PARKED = "parked"
const STATUS_BOUGHT = "bought"
const STATUS_HIDDEN_LEGACY = "hidden"
const VALID = new Set([STATUS_REMOVED, STATUS_PARKED, STATUS_BOUGHT])
const VALID_MODES = new Set(["active", "parked", "bought", "all"])

const ENRICHMENT_FIELDS = [
  "hunt_name",
  "hunt_family",
  "brand",
  "size",
  "price_ron",
  "value_band",
  "deal_score",
  "title",
]

const DDL = `
CREATE TABLE IF NOT EXISTS listing_vetoes (
  item_id BIGINT NOT NULL PRIMARY KEY,
  status TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  hunt_name TEXT NULL,
  hunt_family TEXT NULL,
  brand TEXT NULL,
  size TEXT NULL,
  price_ron DOUBLE PRECISION NULL,
  value_band TEXT NULL,
  deal_score INT NULL,
  title TEXT NULL
);
`

const MIGRATE_HIDDEN_SQL =
  "UPDATE listing_vetoes SET status = 'removed' WHERE status = 'hidden'"

const ALTER_COLUMNS_SQL = [
  "ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS hunt_name TEXT NULL",
  "ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS hunt_family TEXT NULL",
  "ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS brand TEXT NULL",
  "ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS size TEXT NULL",
  "ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS price_ron DOUBLE PRECISION NULL",
  "ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS value_band TEXT NULL",
  "ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS deal_score INT NULL",
  "ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS title TEXT NULL",
]

function databaseUrl() {
  return (
    process.env.DATABASE_URL ||
    process.env.COCKROACH_DATABASE_URL ||
    ""
  ).trim() || null
}

function sslConfig() {
  return { rejectUnauthorized: false }
}

function normalizeStatus(status) {
  if (status == null) return null
  const st = String(status)
  if (st === STATUS_HIDDEN_LEGACY) return STATUS_REMOVED
  return st
}

function coerceWriteStatus(status) {
  const st = normalizeStatus(status)
  if (!VALID.has(st)) {
    const err = new Error("invalid_status")
    err.status = 400
    throw err
  }
  return st
}

function coerceEnrichment(enrichment) {
  const out = {}
  for (const key of ENRICHMENT_FIELDS) out[key] = null
  if (!enrichment || typeof enrichment !== "object") return out
  for (const key of ENRICHMENT_FIELDS) {
    if (enrichment[key] == null) continue
    if (key === "price_ron") {
      const n = Number(enrichment[key])
      out[key] = Number.isFinite(n) ? n : null
    } else if (key === "deal_score") {
      const n = Number(enrichment[key])
      out[key] = Number.isFinite(n) ? Math.trunc(n) : null
    } else {
      const s = String(enrichment[key]).trim()
      out[key] = s || null
    }
  }
  if (!out.hunt_family && out.hunt_name) {
    out.hunt_family = resolveFamily(out.hunt_name)
  }
  return out
}

function itemId(rowOrId) {
  const raw =
    rowOrId && typeof rowOrId === "object"
      ? rowOrId.id ?? rowOrId.item_id
      : rowOrId
  if (raw == null) return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}

function statusFor(vetoes, rowOrId) {
  const id = itemId(rowOrId)
  if (id == null) return null
  return normalizeStatus(vetoes[id] || vetoes[String(id)] || null)
}

function isRemoved(vetoes, rowOrId) {
  return statusFor(vetoes, rowOrId) === STATUS_REMOVED
}

function isParked(vetoes, rowOrId) {
  return statusFor(vetoes, rowOrId) === STATUS_PARKED
}

function isBought(vetoes, rowOrId) {
  return statusFor(vetoes, rowOrId) === STATUS_BOUGHT
}

const isHidden = isRemoved

function deskRank(st) {
  if (st === STATUS_PARKED) return 1
  if (st === STATUS_BOUGHT) return 2
  return 0
}

function applyToFinds(rows, vetoes, { mode = "active" } = {}) {
  if (!VALID_MODES.has(mode)) {
    throw new Error(`unknown veto mode: ${mode}`)
  }
  const out = []
  for (const row of rows || []) {
    const st = statusFor(vetoes, row)
    if (st === STATUS_REMOVED) continue
    if (mode === "parked" && st !== STATUS_PARKED) continue
    if (mode === "bought" && st !== STATUS_BOUGHT) continue
    if (mode === "active" && st === STATUS_BOUGHT) continue
    const tagged = { ...row }
    if (st) tagged.veto_status = st
    else delete tagged.veto_status
    out.push(tagged)
  }
  return out.sort((a, b) => deskRank(a.veto_status) - deskRank(b.veto_status))
}

function applyToBundles(rows, vetoes, { mode = "active" } = {}) {
  if (!VALID_MODES.has(mode)) {
    throw new Error(`unknown veto mode: ${mode}`)
  }
  const out = []
  for (const bundle of rows || []) {
    const items = Array.isArray(bundle.items) ? bundle.items : []
    let kept = []
    for (const it of items) {
      const st = statusFor(vetoes, it)
      if (st === STATUS_REMOVED) continue
      if (st === STATUS_BOUGHT && (mode === "active" || mode === "parked")) continue
      const tagged = { ...it }
      if (st) tagged.veto_status = st
      else delete tagged.veto_status
      kept.push(tagged)
    }
    if (mode === "bought") {
      kept = kept.filter((it) => it.veto_status === STATUS_BOUGHT)
      if (kept.length < 1) continue
    } else if (kept.length < 2) {
      continue
    }
    if (
      mode === "parked" &&
      !kept.some((it) => it.veto_status === STATUS_PARKED)
    ) {
      continue
    }

    const row = { ...bundle, items: kept }
    let listingSum = 0
    for (const it of kept) {
      const p = Number(it.price)
      if (Number.isFinite(p)) listingSum += p
    }
    row.listing_sum = listingSum
    if (row.checkout_extra_ron != null) {
      const extra = Number(row.checkout_extra_ron)
      if (Number.isFinite(extra)) row.checkout_total = listingSum + extra
    }
    if (kept.some((it) => it.veto_status === STATUS_PARKED)) {
      row.veto_status = STATUS_PARKED
    } else if (kept.some((it) => it.veto_status === STATUS_BOUGHT)) {
      row.veto_status = STATUS_BOUGHT
    } else {
      delete row.veto_status
    }
    out.push(row)
  }
  return out.sort((a, b) => deskRank(a.veto_status) - deskRank(b.veto_status))
}

async function withClient(fn) {
  const url = databaseUrl()
  if (!url) return null
  const { Client } = pg
  let connectionString = url
  if (!fs.existsSync(path.join(os.homedir(), ".postgresql", "root.crt"))) {
    connectionString = url.replace(/sslmode=verify-full/gi, "sslmode=require")
  }
  const client = new Client({
    connectionString,
    ssl: sslConfig(),
    connectionTimeoutMillis: 8000,
    query_timeout: 15000,
  })
  try {
    await client.connect()
    await client.query(DDL)
    for (const stmt of ALTER_COLUMNS_SQL) {
      try {
        await client.query(stmt)
      } catch (err) {
        console.error("listingVetoes alter note:", err.message || err)
      }
    }
    try {
      await client.query(MIGRATE_HIDDEN_SQL)
    } catch (err) {
      console.error("listingVetoes migrate note:", err.message || err)
    }
    return await fn(client)
  } catch (err) {
    console.error("listingVetoes:", err.message || err)
    return null
  } finally {
    try {
      await client.end()
    } catch {
      /* ignore */
    }
  }
}

async function loadVetoMap() {
  const map = await withClient(async (client) => {
    const res = await client.query("SELECT item_id, status FROM listing_vetoes")
    const out = {}
    for (const row of res.rows) {
      out[Number(row.item_id)] = normalizeStatus(String(row.status))
    }
    return out
  })
  return map || {}
}

async function setVetoStatus(itemId, status, enrichment) {
  const id = Number(itemId)
  if (!Number.isFinite(id)) {
    const err = new Error("invalid_item_id")
    err.status = 400
    throw err
  }
  const st = coerceWriteStatus(status)
  const enr = coerceEnrichment(enrichment)
  const ok = await withClient(async (client) => {
    await client.query(
      `INSERT INTO listing_vetoes (
         item_id, status, updated_at,
         hunt_name, hunt_family, brand, size, price_ron, value_band, deal_score, title
       )
       VALUES ($1, $2, now(), $3, $4, $5, $6, $7, $8, $9, $10)
       ON CONFLICT (item_id) DO UPDATE SET
         status = EXCLUDED.status,
         updated_at = EXCLUDED.updated_at,
         hunt_name = COALESCE(EXCLUDED.hunt_name, listing_vetoes.hunt_name),
         hunt_family = COALESCE(EXCLUDED.hunt_family, listing_vetoes.hunt_family),
         brand = COALESCE(EXCLUDED.brand, listing_vetoes.brand),
         size = COALESCE(EXCLUDED.size, listing_vetoes.size),
         price_ron = COALESCE(EXCLUDED.price_ron, listing_vetoes.price_ron),
         value_band = COALESCE(EXCLUDED.value_band, listing_vetoes.value_band),
         deal_score = COALESCE(EXCLUDED.deal_score, listing_vetoes.deal_score),
         title = COALESCE(EXCLUDED.title, listing_vetoes.title)`,
      [
        id,
        st,
        enr.hunt_name,
        enr.hunt_family,
        enr.brand,
        enr.size,
        enr.price_ron,
        enr.value_band,
        enr.deal_score,
        enr.title,
      ],
    )
    return true
  })
  if (!ok) {
    const err = new Error("veto_db_unavailable")
    err.status = 503
    throw err
  }
  return { item_id: id, status: st }
}

async function clearVeto(itemId) {
  const id = Number(itemId)
  if (!Number.isFinite(id)) {
    const err = new Error("invalid_item_id")
    err.status = 400
    throw err
  }
  const ok = await withClient(async (client) => {
    await client.query("DELETE FROM listing_vetoes WHERE item_id = $1", [id])
    return true
  })
  if (!ok) {
    const err = new Error("veto_db_unavailable")
    err.status = 503
    throw err
  }
  return { item_id: id, cleared: true }
}

export {
  STATUS_REMOVED,
  STATUS_PARKED,
  STATUS_BOUGHT,
  STATUS_HIDDEN_LEGACY,
  databaseUrl,
  isRemoved,
  isHidden,
  isParked,
  isBought,
  applyToFinds,
  applyToBundles,
  loadVetoMap,
  setVetoStatus,
  clearVeto,
  normalizeStatus,
  coerceEnrichment,
}
