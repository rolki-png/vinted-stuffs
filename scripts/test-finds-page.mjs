import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { buildFindsPage, parseFilters } from '../src/server/findsPage.js'

assert.equal(parseFilters({ page: '2', limit: '50' }).page, 2)
assert.equal(parseFilters({ limit: '999' }).limit, 100)
assert.equal(parseFilters({}).limit, 50)

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'finds-page-'))
const data = path.join(root, 'data')
fs.mkdirSync(data)

const rows = []
for (let i = 1; i <= 60; i += 1) {
  rows.push({
    id: i,
    title: `item ${i}`,
    watch: 'Gym',
    seller: 's',
    seller_id: 1,
    score_version: 2,
    buy_score: 100 - (i % 40),
    buy_band: 'keep',
    score_confidence: 0.8,
    score_interval_low: 80,
    score_interval_high: 95,
    verification_concern: 'none',
    hunt_fit: true,
    has_score: true,
    price: 10 + i,
    source: 'index',
  })
}
fs.writeFileSync(path.join(data, 'indexed_scores.json'), JSON.stringify(rows))
fs.writeFileSync(path.join(data, 'best_deals.json'), '[]')
fs.writeFileSync(path.join(data, 'bundle_pool.json'), '[]')
fs.writeFileSync(path.join(data, 'last_run.json'), '{}')
fs.writeFileSync(path.join(data, 'seen_listings.json'), '{}')

const previousCwd = process.cwd()
delete process.env.DATABASE_URL
delete process.env.COCKROACH_DATABASE_URL
delete process.env.GITHUB_TOKEN
delete process.env.GITHUB_REPO
try {
  process.chdir(root)
  const page1 = await buildFindsPage({ page: 1, limit: 50, sort: 'score-desc' })
  assert.equal(page1.finds.length, 50)
  assert.equal(page1.total, 60)
  assert.equal(page1.pages, 2)
  assert.equal(page1.page, 1)
  const page2 = await buildFindsPage({ page: 2, limit: 50, sort: 'score-desc' })
  assert.equal(page2.finds.length, 10)
  assert.equal(page2.page, 2)
  const filtered = await buildFindsPage({
    page: 1,
    limit: 50,
    min_score: 'v2:95',
  })
  assert.ok(filtered.finds.every((row) => Number(row.buy_score) >= 95))
  assert.ok(filtered.total < 60)
} finally {
  process.chdir(previousCwd)
  fs.rmSync(root, { recursive: true, force: true })
}

const desk = fs.readFileSync(
  new URL('../src/components/DealDesk.tsx', import.meta.url),
  'utf8',
)
assert.match(desk, /\/api\/finds/)
assert.match(desk, /setPage/)
assert.match(desk, /Prev/)

console.log('ok finds-page')
