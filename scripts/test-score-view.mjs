import assert from 'node:assert/strict'
import {
  buyBandPresentation,
  factorRows,
  filterScore,
  findComparator,
  histogramRows,
  isDeclaredV2,
  isKeep,
  isV2,
  keepCounts,
  matchesBandFilter,
  matchesScoreFilter,
  numericScore,
  scoreLabel,
  scoreScaleLabel,
  sellerComparator,
  sortFinds,
  usableRank,
  vetoPayload,
  vetoScoreContext,
} from '../src/components/scoreView.js'

const v2 = {
  score_version: 2,
  buy_score: 87,
  buy_band: 'keep',
  score_interval_low: 82,
  score_interval_high: 92,
}
const legacy = { deal_score: 9, value_band: 'hunt' }
const malformedV2 = {
  score_version: 2,
  buy_score: 101,
  buy_band: 'exceptional',
  deal_score: 10,
  value_band: 'steal',
}

assert.equal(scoreLabel(v2), '87 (90% interval 82–92)')
assert.equal(scoreLabel({ deal_score: 9 }), '9 legacy')
assert.equal(scoreLabel(malformedV2), 'Invalid v2 score')
assert.equal(scoreLabel({}), '—')
assert.equal(numericScore(v2), 87)
assert.equal(numericScore(legacy), 9)
assert.equal(numericScore(malformedV2), 0)
assert.equal(filterScore(v2), 87)
assert.equal(filterScore(legacy), null)
assert.equal(filterScore(malformedV2), null)
assert.equal(scoreScaleLabel(v2), 'V2 utility /100')
assert.equal(scoreScaleLabel(legacy), 'Legacy /10')
assert.equal(scoreScaleLabel(malformedV2), 'Invalid v2')
assert.equal(isV2(v2), true)
assert.equal(isDeclaredV2(malformedV2), true)
assert.equal(isKeep({ ...v2, hunt_fit: true, score_confidence: 0.8 }), true)
assert.deepEqual(
  usableRank({ ...v2, rank_position: 2, rank_confidence: 'medium' }),
  { position: 2, confidence: 'medium' },
)
assert.equal(
  usableRank({ ...v2, rank_position: 2, rank_confidence: 'unknown' }),
  null,
)
assert.equal(
  usableRank({ ...v2, rank_position: 0, rank_confidence: 'high' }),
  null,
)
assert.deepEqual(buyBandPresentation(v2), {
  label: 'keep',
  className: 'keep',
})
assert.deepEqual(buyBandPresentation({ ...v2, buy_band: null }), {
  label: 'Unknown v2 band',
  className: 'unknown',
})
assert.deepEqual(buyBandPresentation({ ...v2, buy_band: 'surprise' }), {
  label: 'Unknown v2 band',
  className: 'unknown',
})
assert.equal(matchesScoreFilter(v2, 'v2:85'), true)
assert.equal(matchesScoreFilter({ ...v2, buy_score: 84 }, 'v2:85'), false)
assert.equal(matchesScoreFilter(legacy, 'v2:85'), false)
assert.equal(matchesScoreFilter(legacy, 'legacy'), true)
assert.equal(matchesScoreFilter(v2, 'legacy'), false)
assert.equal(matchesScoreFilter(malformedV2, 'legacy'), false)
assert.equal(matchesScoreFilter(malformedV2, ''), true)
assert.equal(matchesBandFilter(v2, 'v2:keep'), true)
assert.equal(matchesBandFilter(legacy, 'v2:keep'), false)
assert.equal(matchesBandFilter(legacy, 'legacy:hunt'), true)
assert.equal(matchesBandFilter(v2, 'legacy:hunt'), false)
assert.deepEqual(
  keepCounts([
    { ...v2, hunt_fit: true, score_confidence: 0.8 },
    {
      ...v2,
      buy_score: 70,
      hunt_fit: true,
      score_confidence: 0.8,
      source: 'keep',
    },
    legacy,
    malformedV2,
  ]),
  { v2: 1, legacy: 1 },
)

assert.deepEqual(
  sortFinds(
    [
      { id: 'legacy', ...legacy, deal_score: 10 },
      {
        id: 'ranked-low-score',
        ...v2,
        buy_score: 80,
        rank_position: 1,
        rank_confidence: 'high',
      },
      { id: 'unranked-high-score', ...v2, buy_score: 95 },
      { id: 'malformed', ...malformedV2 },
    ],
    'score-desc',
  ).map((row) => row.id),
  ['unranked-high-score', 'ranked-low-score', 'legacy', 'malformed'],
)
assert.deepEqual(
  sortFinds(
    [
      {
        id: 'rank-two',
        ...v2,
        buy_score: 95,
        rank_position: 2,
        rank_confidence: 'high',
      },
      {
        id: 'rank-one',
        ...v2,
        buy_score: 80,
        rank_position: 1,
        rank_confidence: 'medium',
      },
      { id: 'legacy', ...legacy, deal_score: 10 },
      { id: 'malformed', ...malformedV2 },
    ],
    'score-desc',
  ).map((row) => row.id),
  ['rank-one', 'rank-two', 'legacy', 'malformed'],
)
assert.deepEqual(
  sortFinds(
    [
      { id: 'legacy-high', ...legacy, deal_score: 10 },
      { id: 'v2-high', ...v2, buy_score: 95 },
      { id: 'v2-low', ...v2, buy_score: 60 },
      { id: 'legacy-low', ...legacy, deal_score: 1 },
      { id: 'malformed', ...malformedV2 },
    ],
    'score-asc',
  ).map((row) => row.id),
  ['v2-low', 'v2-high', 'legacy-low', 'legacy-high', 'malformed'],
)
assert.deepEqual(
  sortFinds(
    [
      {
        id: 'parked-v2',
        ...v2,
        buy_score: 100,
        veto_status: 'parked',
      },
      {
        id: 'active-rank-two',
        ...v2,
        buy_score: 95,
        rank_position: 2,
        rank_confidence: 'high',
      },
      {
        id: 'bought-v2',
        ...v2,
        buy_score: 99,
        veto_status: 'bought',
      },
      {
        id: 'active-rank-one',
        ...v2,
        buy_score: 80,
        rank_position: 1,
        rank_confidence: 'medium',
      },
      {
        id: 'parked-legacy',
        ...legacy,
        deal_score: 10,
        veto_status: 'parked',
      },
      {
        id: 'active-legacy',
        ...legacy,
        deal_score: 10,
        veto_status: 'active',
      },
      {
        id: 'removed-legacy',
        ...legacy,
        deal_score: 10,
        veto_status: 'removed',
      },
      { id: 'active-malformed', ...malformedV2 },
    ],
    'score-desc',
  ).map((row) => row.id),
  [
    'active-rank-one',
    'active-rank-two',
    'active-legacy',
    'active-malformed',
    'parked-v2',
    'parked-legacy',
    'bought-v2',
    'removed-legacy',
  ],
)
assert.deepEqual(
  sortFinds(
    [
      {
        id: 'parked-cheap',
        ...legacy,
        price_num: 10,
        veto_status: 'parked',
      },
      { id: 'active-expensive', ...v2, price_num: 100 },
    ],
    'price-asc',
  ).map((row) => row.id),
  ['active-expensive', 'parked-cheap'],
)
assert.deepEqual(
  [
    { id: 'expensive', ...v2, price_num: 100 },
    { id: 'cheap', ...legacy, price_num: 10 },
  ]
    .sort(findComparator('price-asc'))
    .map((row) => row.id),
  ['cheap', 'expensive'],
)
const sellers = [
  {
    id: 'legacy',
    score_version: null,
    legacy_score: true,
    score_tier: 1,
    best_score: 10,
    avg_score: 9,
    keeps: 2,
  },
  {
    id: 'v2',
    score_version: 2,
    legacy_score: false,
    score_tier: 2,
    best_score: 85,
    avg_score: 80,
    keeps: 1,
  },
  {
    id: 'malformed',
    score_version: 2,
    legacy_score: false,
    score_tier: 0,
    best_score: null,
    avg_score: null,
    keeps: 99,
  },
]
assert.deepEqual(
  [...sellers].sort(sellerComparator('best')).map((row) => row.id),
  ['v2', 'legacy', 'malformed'],
)
assert.deepEqual(
  [...sellers].sort(sellerComparator('avg')).map((row) => row.id),
  ['v2', 'legacy', 'malformed'],
)

assert.deepEqual(vetoScoreContext(v2), {
  score_version: 2,
  buy_score: 87,
  buy_band: 'keep',
})
assert.deepEqual(vetoScoreContext(legacy), {
  deal_score: 9,
  value_band: 'hunt',
})
for (const row of [
  { score_version: 2, buy_score: 87 },
  { score_version: 2, buy_score: 87, buy_band: 'unknown' },
  { deal_score: 9 },
  malformedV2,
]) {
  assert.deepEqual(vetoScoreContext(row), {})
}
assert.deepEqual(vetoPayload(7, 'removed', v2, 'poor_value'), {
  item_id: 7,
  status: 'removed',
  hunt_name: null,
  brand: null,
  size: null,
  price_ron: null,
  title: null,
  score_version: 2,
  buy_score: 87,
  buy_band: 'keep',
  reason_code: 'poor_value',
})
assert.deepEqual(vetoPayload(8, 'bought', legacy, 'poor_value'), {
  item_id: 8,
  status: 'bought',
  hunt_name: null,
  brand: null,
  size: null,
  price_ron: null,
  title: null,
  deal_score: 9,
  value_band: 'hunt',
})
assert.deepEqual(vetoPayload(9, null, legacy), {
  item_id: 9,
  clear: true,
})

assert.deepEqual(
  factorRows({
    score_factors: {
      usefulness: 90,
      fit_probability: 0.75,
      total_ron: 40,
      ignored: 'bad',
    },
    factor_evidence: { usefulness: 'frequent use' },
  }),
  [
    {
      key: 'usefulness',
      label: 'usefulness',
      value: '90',
      evidence: 'frequent use',
    },
    {
      key: 'fit_probability',
      label: 'fit probability',
      value: '0.75',
      evidence: '',
    },
  ],
)
assert.deepEqual(
  factorRows({ score_factors: null, factor_evidence: 'bad' }),
  [],
)

assert.deepEqual(histogramRows({ '80-89': 3, '90-100': 1, 9: 99 }), [
  { label: '80–89', count: 3 },
  { label: '90–100', count: 1 },
])
console.log('ok score-view')
