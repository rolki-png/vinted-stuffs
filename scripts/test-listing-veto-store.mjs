import assert from "node:assert/strict"
import pg from "pg"

const inserts = []

class FakeClient {
  async connect() {}

  async query(sql, params = []) {
    if (sql.includes("INSERT INTO listing_vetoes")) {
      inserts.push({ sql, params })
    }
    return { rows: [] }
  }

  async end() {}
}

pg.Client = FakeClient
process.env.DATABASE_URL = "postgresql://test.invalid/vetoes"

const { setVetoStatus } = await import("../src/server/listingVetoes.ts")

const metadata = {
  hunt_name: "Gym",
  hunt_family: "gym",
  brand: "Craft",
  size: "L",
  price_ron: 80,
  title: "Technical shorts",
}

await setVetoStatus(7, "bought", {
  ...metadata,
  score_version: 2,
  buy_score: 88,
  buy_band: "keep",
})
await setVetoStatus(7, "bought", {
  ...metadata,
  score_version: 2,
  buy_score: 91,
})
await setVetoStatus(7, "removed", {
  ...metadata,
  deal_score: 9,
  value_band: "steal",
})

assert.equal(inserts.length, 3)
for (const { sql, params } of inserts) {
  const columns = sql
    .match(/INSERT INTO listing_vetoes \(([\s\S]*?)\)\s*VALUES/)[1]
    .split(",")
    .map((column) => column.trim())
  assert.equal(columns.length, 15)
  assert.equal(Math.max(...[...sql.matchAll(/\$(\d+)/g)].map((match) => Number(match[1]))), 15)
  assert.equal(params.length, 15)
}

const scoreParams = ({ params }) => ({
  deal_score: params[9],
  value_band: params[8],
  score_version: params[10],
  buy_score: params[11],
  buy_band: params[12],
  decision: params[14],
})
assert.deepEqual(scoreParams(inserts[0]), {
  deal_score: null,
  value_band: null,
  score_version: 2,
  buy_score: 88,
  buy_band: "keep",
  decision: "v2",
})
assert.deepEqual(scoreParams(inserts[1]), {
  deal_score: null,
  value_band: null,
  score_version: null,
  buy_score: null,
  buy_band: null,
  decision: "preserve",
})
assert.deepEqual(scoreParams(inserts[2]), {
  deal_score: 9,
  value_band: "steal",
  score_version: null,
  buy_score: null,
  buy_band: null,
  decision: "legacy",
})

const applyDecision = (current, update) => {
  if (update.decision === "preserve") return { ...current }
  if (update.decision === "v2") {
    return {
      deal_score: null,
      value_band: null,
      score_version: update.score_version,
      buy_score: update.buy_score,
      buy_band: update.buy_band,
    }
  }
  return {
    deal_score: update.deal_score,
    value_band: update.value_band,
    score_version: null,
    buy_score: null,
    buy_band: null,
  }
}

let stored = applyDecision({}, scoreParams(inserts[0]))
stored = applyDecision(stored, scoreParams(inserts[1]))
assert.equal(stored.buy_score, 88)
assert.equal(stored.buy_band, "keep")
stored = applyDecision(stored, scoreParams(inserts[2]))
assert.equal(stored.score_version, null)
assert.equal(stored.buy_score, null)
assert.equal(stored.deal_score, 9)

console.log("ok listing-veto-store")
