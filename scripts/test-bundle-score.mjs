import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

import {
  calculateBundleScore,
  loadGoldenCases,
} from '../src/server/bundleScore.js'
import { sortBundles } from '../src/components/scoreView.js'

const cases = loadGoldenCases()
for (const caseRow of cases) {
  const result = calculateBundleScore(caseRow.members, {
    kind: caseRow.kind,
    config: {},
  })
  assert.equal(
    result.bundle_score,
    caseRow.expected_score,
    `${caseRow.name}: expected ${caseRow.expected_score}, got ${result.bundle_score}`,
  )
  if (caseRow.better_than) {
    const other = cases.find((row) => row.name === caseRow.better_than)
    assert.ok(other, caseRow.better_than)
    const otherResult = calculateBundleScore(other.members, {
      kind: other.kind,
      config: {},
    })
    assert.ok(
      result.bundle_score > otherResult.bundle_score,
      `${caseRow.name} should beat ${caseRow.better_than}`,
    )
  }
}

const sorted = sortBundles(
  [
    { bundle_score: null, kept_at: '2026-09-07T12:00:00Z', seller: 'near' },
    { bundle_score: 90, kept_at: '2026-09-06T12:00:00Z', seller: 'mid' },
    { bundle_score: 95, kept_at: '2026-09-05T12:00:00Z', seller: 'top' },
  ],
  'best-desc',
)
assert.equal(sorted[0].seller, 'top')
assert.equal(sorted[1].seller, 'mid')
assert.equal(sorted[2].seller, 'near')

const newest = sortBundles(
  [
    { bundle_score: 95, kept_at: '2026-09-05T12:00:00Z', seller: 'old' },
    { bundle_score: null, kept_at: '2026-09-07T12:00:00Z', seller: 'new' },
  ],
  'new-desc',
)
assert.equal(newest[0].seller, 'new')

const desk = readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), '../src/components/DealDesk.tsx'),
  'utf8',
)
assert.match(desk, /Newest → oldest/)
assert.match(desk, /Best → worst/)
assert.match(desk, /bundleSort/)

console.log('ok bundle-score')
