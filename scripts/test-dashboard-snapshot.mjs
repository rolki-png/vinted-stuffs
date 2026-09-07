import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { buildSnapshot } from "../src/server/snapshot.ts"
import {
  exportRow,
  indexBundleOpportunities,
} from "../src/server/scoredDb.ts"

const root = fs.mkdtempSync(path.join(os.tmpdir(), "dashboard-snapshot-"))
const data = path.join(root, "data")
fs.mkdirSync(data)

const v2 = (id, buyScore, rankPosition, extra = {}) => ({
  id,
  watch: "Gym",
  title: `v2 ${id}`,
  price: 50,
  seller_id: 10,
  seller: "mixed-seller",
  score_version: 2,
  buy_score: buyScore,
  buy_band: "keep",
  score_confidence: 0.8,
  score_interval_low: buyScore - 5,
  score_interval_high: buyScore + 5,
  score_factors: { usefulness: buyScore },
  factor_evidence: { usefulness: "frequent use" },
  verification_concern: "none",
  verification_reason: "",
  rank_position: rankPosition,
  rank_confidence: "high",
  hunt_fit: true,
  has_score: true,
  ...extra,
})

const exported = exportRow({
  item_id: 99,
  hunt_name: "Gym",
  title: "DB row",
  score_version: 2,
  buy_score: 89,
  buy_band: "keep",
  score_confidence: 0.75,
  score_interval_low: 84,
  score_interval_high: 94,
  score_factors: { usefulness: 89 },
  factor_evidence: { usefulness: "frequent use" },
  verification_concern: "inspect",
  verification_reason: "check seams",
  rank_position: 3,
  rank_confidence: "medium",
  deal_score: 10,
  value_band: "steal",
  scam_risk: "low",
  reason: "stale legacy reason",
  has_score: true,
})
assert.equal(exported.legacy_score, false)
assert.equal(exported.buy_score, 89)
assert.equal(exported.deal_score, null)
assert.equal(exported.value_band, undefined)
assert.equal(exported.reason, undefined)
assert.equal(exported.verification_reason, "check seams")
assert.deepEqual(exported.score_factors, { usefulness: 89 })
assert.deepEqual(exported.factor_evidence, { usefulness: "frequent use" })

const bundleRows = [
  v2(11, 90, 2),
  v2(12, 70, 1, { buy_band: "bundle" }),
  {
    id: 13,
    seller_id: 10,
    deal_score: 9,
    value_band: "steal",
    hunt_fit: true,
    has_score: true,
  },
  {
    id: 14,
    seller_id: 10,
    deal_score: 7,
    value_band: "acceptable",
    hunt_fit: true,
    has_score: true,
  },
]
const opportunities = indexBundleOpportunities(bundleRows)
assert.equal(opportunities.length, 2)
assert.deepEqual(
  opportunities
    .map((bundle) => bundle.items.map((item) => item.id))
    .sort((left, right) => left[0] - right[0]),
  [
    [11, 12],
    [13, 14],
  ],
)
const v2Bundle = opportunities.find((bundle) => bundle.items[0].id === 11)
assert.equal(v2Bundle.items[0].buy_score, 90)
assert.equal(v2Bundle.items[0].legacy_score, false)

fs.writeFileSync(
  path.join(data, "best_deals.json"),
  JSON.stringify([
    {
      id: 1,
      title: "old keep",
      seller_id: 10,
      seller: "mixed-seller",
      deal_score: 10,
      value_band: "steal",
      hunt_fit: true,
      reason: "legacy keep reason",
    },
    v2(6, 89, null, {
      seller_id: 30,
      seller: "standalone-v2",
      source: "keep",
      deal_score: 10,
      value_band: "steal",
      scam_risk: "low",
      reason: "stale legacy reason",
      verification_reason: "verify fabric",
    }),
    {
      id: 7,
      seller_id: 40,
      seller: "malformed-v2",
      score_version: 2,
      buy_score: 101,
      buy_band: "exceptional",
      deal_score: 10,
      value_band: "steal",
      reason: "must not become legacy",
    },
  ]),
)
fs.writeFileSync(path.join(data, "best_bundles.json"), "[]")
fs.writeFileSync(
  path.join(data, "indexed_scores.json"),
  JSON.stringify([
    v2(1, 88, null),
    {
      id: 2,
      title: "legacy same seller",
      seller_id: 10,
      seller: "mixed-seller",
      deal_score: 9,
      value_band: "steal",
      hunt_fit: true,
      has_score: true,
    },
    {
      id: 3,
      title: "legacy only seller",
      seller_id: 20,
      seller: "legacy-seller",
      deal_score: 10,
      value_band: "steal",
      hunt_fit: true,
      has_score: true,
    },
    v2(4, 92, 2),
    v2(5, 86, 1),
    {
      id: 8,
      title: "valid legacy sibling",
      seller_id: 40,
      seller: "malformed-v2",
      deal_score: 8,
      value_band: "acceptable",
      hunt_fit: true,
      has_score: true,
    },
  ]),
)
fs.writeFileSync(
  path.join(data, "bundle_pool.json"),
  JSON.stringify([
    {
      item: {
        id: 4,
        title: "stale pool copy",
        price: { amount: 50, currency_code: "RON" },
        user: { id: 10, login: "mixed-seller" },
      },
      watch: "Gym",
      score: {
        deal_score: 10,
        value_band: "steal",
        hunt_fit: true,
      },
    },
  ]),
)
fs.writeFileSync(
  path.join(data, "last_run.json"),
  JSON.stringify({
    top: [
      {
        id: 5,
        deal_score: 10,
        value_band: "steal",
        hunt_fit: true,
      },
    ],
    score_histogram: { "80-89": 4, "90-100": 2 },
  }),
)
fs.writeFileSync(path.join(data, "seen_listings.json"), "{}")

const previousCwd = process.cwd()
delete process.env.DATABASE_URL
delete process.env.COCKROACH_DATABASE_URL
delete process.env.GITHUB_TOKEN
delete process.env.GITHUB_REPO
try {
  process.chdir(root)
  const snapshot = await buildSnapshot()
  assert.deepEqual(
    new Set(snapshot.finds.slice(0, 4).map((row) => row.id)),
    new Set([1, 4, 5, 6]),
  )
  assert.deepEqual(snapshot.finds.slice(4).map((row) => row.id), [3, 2, 8, 7])
  const upgraded = snapshot.finds.find((row) => row.id === 1)
  assert.equal(upgraded.score_version, 2)
  assert.equal(upgraded.buy_score, 88)
  assert.equal(upgraded.legacy_score, false)
  assert.equal(upgraded.source, "keep")
  assert.equal(upgraded.deal_score, null)
  assert.equal(upgraded.reason, undefined)
  assert.deepEqual(upgraded.score_factors, { usefulness: 88 })

  const standalone = snapshot.finds.find((row) => row.id === 6)
  assert.equal(standalone.deal_score, null)
  assert.equal(standalone.value_band, undefined)
  assert.equal(standalone.reason, undefined)
  assert.equal(standalone.verification_reason, "verify fabric")

  const legacy = snapshot.finds.find((row) => row.id === 3)
  assert.equal(legacy.deal_score, 10)
  assert.equal(legacy.legacy_score, true)

  const mixedSeller = snapshot.sellers.find((row) => row.seller_id === 10)
  assert.equal(mixedSeller.score_version, 2)
  assert.equal(mixedSeller.best_score, 92)
  assert.equal(mixedSeller.avg_score, 88.67)
  assert.equal(mixedSeller.keeps, 3)
  assert.equal(mixedSeller.listings, 4)
  const legacySeller = snapshot.sellers.find((row) => row.seller_id === 20)
  assert.equal(legacySeller.legacy_score, true)
  assert.equal(legacySeller.avg_score, 10)
  const mixedMalformedSeller = snapshot.sellers.find(
    (row) => row.seller_id === 40,
  )
  assert.equal(mixedMalformedSeller.score_version, null)
  assert.equal(mixedMalformedSeller.legacy_score, true)
  assert.equal(mixedMalformedSeller.score_tier, 1)
  assert.equal(mixedMalformedSeller.avg_score, 8)
  assert.deepEqual(snapshot.run.score_histogram_bins, [
    { label: "80–89", count: 4 },
    { label: "90–100", count: 2 },
  ])
} finally {
  process.chdir(previousCwd)
  fs.rmSync(root, { recursive: true, force: true })
}

console.log("ok dashboard-snapshot")
