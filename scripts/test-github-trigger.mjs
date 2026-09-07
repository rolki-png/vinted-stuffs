/**
 * Desk workflow dispatch must be able to start the legacy v2 rollout.
 * Run: node --disable-warning=ExperimentalWarning --experimental-strip-types scripts/test-github-trigger.mjs
 */
import assert from 'node:assert/strict'
import { triggerWorkflow } from '../src/server/github.ts'

async function withFetch(handler, fn) {
  const original = globalThis.fetch
  globalThis.fetch = handler
  try {
    return await fn()
  } finally {
    globalThis.fetch = original
  }
}

async function testLegacyDispatchSendsWorkflowInput() {
  process.env.GITHUB_REPO = 'rolki-png/vinted-stuffs'
  process.env.GITHUB_TOKEN = 'test-token'
  process.env.GITHUB_REF = 'main'
  let payload = null
  const result = await withFetch(async (url, init) => {
    assert.equal(
      url,
      'https://api.github.com/repos/rolki-png/vinted-stuffs/actions/workflows/vinted-bot.yml/dispatches',
    )
    payload = JSON.parse(init.body)
    return { status: 204, ok: true, async text() { return '' } }
  }, () => triggerWorkflow({ legacyActiveV2: true }))

  assert.equal(payload.ref, 'main')
  assert.equal(payload.inputs.legacy_active_v2, 'true')
  assert.equal(payload.inputs.full_sweep, 'false')
  assert.equal(payload.inputs.skip_scoring, 'false')
  assert.equal(result.legacy_active_v2, true)
  assert.equal(result.full_sweep, false)
}

async function testNormalHuntDoesNotEnableLegacyRollout() {
  process.env.GITHUB_REPO = 'rolki-png/vinted-stuffs'
  process.env.GITHUB_TOKEN = 'test-token'
  let payload = null
  await withFetch(async (_url, init) => {
    payload = JSON.parse(init.body)
    return { status: 204, ok: true, async text() { return '' } }
  }, () => triggerWorkflow({ fullSweep: true }))

  assert.equal(payload.inputs.legacy_active_v2, 'false')
  assert.equal(payload.inputs.full_sweep, 'true')
}

await testLegacyDispatchSendsWorkflowInput()
await testNormalHuntDoesNotEnableLegacyRollout()
console.log('ok github-trigger')
