import assert from "node:assert/strict"
import {
  displayScore,
  isV2,
  isKeep,
  mergeScoreRows,
  preferredScoreRow,
  scoreFields,
  sortScoreRows,
  sellerScoreRows,
  histogramBins,
} from "../src/server/scoreSemantics.js"

const v2 = {
  score_version: 2,
  buy_score: 88,
  buy_band: "keep",
  score_confidence: 0.7,
  hunt_fit: true,
  verification_concern: "none",
}
const legacy = { deal_score: 9, value_band: "steal", hunt_fit: true }
assert.equal(displayScore(v2), 88)
assert.equal(displayScore(legacy), 9)
assert.equal(displayScore({}), null)
assert.equal(isV2({ ...v2, buy_score: null }), false)
assert.equal(isKeep(v2), true)
assert.equal(isKeep({ ...v2, score_confidence: 0.59 }), false)
assert.deepEqual(sellerScoreRows([legacy, v2]), [v2])
assert.equal(preferredScoreRow(legacy, v2), v2)
assert.equal(preferredScoreRow(v2, legacy), v2)
assert.deepEqual(
  mergeScoreRows(
    { id: 7, title: "legacy title", source: "keep", ...legacy },
    {
      id: 7,
      source: "index",
      ...v2,
      score_factors: { value: 91 },
      factor_evidence: { value: "strong utility" },
    },
  ),
  {
    id: 7,
    title: "legacy title",
    source: "index",
    ...v2,
    score_factors: { value: 91 },
    factor_evidence: { value: "strong utility" },
  },
)
assert.deepEqual(
  scoreFields({
    ...v2,
    score_interval_low: "82",
    score_interval_high: 93,
    score_factors: { value: 91 },
    factor_evidence: { value: "strong utility" },
    verification_reason: "check fabric",
    rank_position: "2",
    rank_confidence: "medium",
  }),
  {
    score_version: 2,
    buy_score: 88,
    buy_band: "keep",
    score_confidence: 0.7,
    score_interval_low: 82,
    score_interval_high: 93,
    score_factors: { value: 91 },
    factor_evidence: { value: "strong utility" },
    verification_concern: "none",
    verification_reason: "check fabric",
    rank_position: 2,
    rank_confidence: "medium",
    legacy_score: false,
  },
)
assert.deepEqual(
  scoreFields({
    ...v2,
    score_factors: '{"value":91}',
    factor_evidence: null,
  }).score_factors,
  { value: 91 },
)
assert.deepEqual(
  scoreFields({ ...v2, factor_evidence: null }).factor_evidence,
  {},
)
assert.deepEqual(
  sortScoreRows([
    { id: 1, ...legacy, deal_score: 10 },
    { id: 2, ...v2, buy_score: 92, rank_position: 2 },
    { id: 3, ...v2, buy_score: 86, rank_position: 1 },
    { id: 4, ...v2, buy_score: 95, rank_position: null },
  ]).map((row) => row.id),
  [3, 2, 4, 1],
)
assert.deepEqual(
  histogramBins({ "80-89": 4, "90-100": 2 }),
  [
    { label: "80–89", count: 4 },
    { label: "90–100", count: 2 },
  ],
)
console.log("ok score-semantics")
