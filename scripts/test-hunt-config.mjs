/**
 * Unit tests for hunt config mutate/validate/serialize/409 classify.
 * Run: node scripts/test-hunt-config.mjs
 */
import assert from "node:assert/strict"
import {
  normalizeHunt,
  applyWatchMutation,
  serializeConfigJson,
  classifyContents409,
} from "../src/server/huntConfig.js"

function baseConfig(watches) {
  return {
    min_deal_score: 9,
    value_haul: { min_items: 3 },
    watches: watches || [],
  }
}

async function testNormalizeOmitsEmptyAndForcesRo() {
  const { ok, hunt } = normalizeHunt({
    name: "  Foo ",
    query: " bar ",
    target_type: "shorts",
    country: "pl",
    brand_ids: [],
    size_ids: [1739, 1740],
    bundle_hunt: false,
    family: "",
    min_deal_score: "",
    per_page: 24,
    price_to: 100,
    hunt_price: 50,
    target_sizes: "M, L",
    notes: "n",
  })
  assert.equal(ok, true)
  assert.equal(hunt.country, "ro")
  assert.equal(hunt.name, "Foo")
  assert.deepEqual(hunt.size_ids, [1739, 1740])
  assert.equal("brand_ids" in hunt, false)
  assert.equal("bundle_hunt" in hunt, false)
  assert.equal("family" in hunt, false)
  assert.equal("min_deal_score" in hunt, false)
  assert.deepEqual(hunt.target_sizes, ["M", "L"])
}

async function testPreserveUnknownKeysOnReplace() {
  const existing = {
    name: "A",
    query: "q",
    country: "ro",
    target_type: "t",
    target_sizes: ["M"],
    notes: "old",
    full_sweep_max: 99,
    mystery: true,
  }
  const cfg = baseConfig([existing])
  const res = applyWatchMutation(cfg, {
    mode: "replace",
    originalName: "A",
    hunt: {
      name: "A",
      query: "q2",
      target_type: "t2",
      notes: "new",
      target_sizes: ["L"],
      per_page: 10,
      price_to: 1,
      hunt_price: 1,
    },
  })
  assert.equal(res.ok, true)
  assert.equal(res.config.min_deal_score, 9)
  assert.deepEqual(res.config.value_haul, { min_items: 3 })
  const w = res.config.watches[0]
  assert.equal(w.query, "q2")
  assert.equal(w.full_sweep_max, 99)
  assert.equal(w.mystery, true)
  assert.equal(w.country, "ro")
}

async function testAddReplaceRemoveAndUniqueName() {
  let cfg = baseConfig([{ name: "A", query: "q", country: "ro", target_type: "t", notes: "" }])
  let res = applyWatchMutation(cfg, {
    mode: "add",
    hunt: { name: "B", query: "q", target_type: "t", notes: "" },
  })
  assert.equal(res.ok, true)
  assert.equal(res.message.includes("add hunt B"), true)
  assert.equal(res.config.watches.length, 2)

  res = applyWatchMutation(res.config, {
    mode: "add",
    hunt: { name: "A", query: "q", target_type: "t", notes: "" },
  })
  assert.equal(res.ok, false)

  res = applyWatchMutation(cfg, {
    mode: "replace",
    originalName: "A",
    hunt: { name: "A2", query: "q", target_type: "t", notes: "" },
  })
  assert.equal(res.ok, true)
  assert.equal(res.config.watches[0].name, "A2")

  res = applyWatchMutation(res.config, { mode: "remove", originalName: "A2" })
  assert.equal(res.ok, true)
  assert.equal(res.config.watches.length, 0)
  assert.equal(res.message.includes("remove hunt A2"), true)
}

async function testSerializeAnd409() {
  const s = serializeConfigJson({ a: 1, watches: [] })
  assert.equal(s.endsWith("\n"), true)
  assert.equal(s.includes('"a": 1'), true)
  assert.deepEqual(classifyContents409("abc", "abc"), { kind: "tip_race", retry: true })
  assert.deepEqual(classifyContents409("abc", "xyz"), { kind: "conflict", retry: false })
}

async function testValidationRequired() {
  const cfg = baseConfig([])
  const res = applyWatchMutation(cfg, {
    mode: "add",
    hunt: { name: "", query: "q", target_type: "t" },
  })
  assert.equal(res.ok, false)
  assert.match(res.error, /name/i)
}

await testNormalizeOmitsEmptyAndForcesRo()
await testPreserveUnknownKeysOnReplace()
await testAddReplaceRemoveAndUniqueName()
await testSerializeAnd409()
await testValidationRequired()
console.log("ok hunt-config")
