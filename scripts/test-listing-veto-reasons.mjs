import assert from 'node:assert/strict'
import {
  coerceRemoveReason,
  feedbackParams,
} from '../src/server/listingFeedback.js'

assert.equal(coerceRemoveReason('removed', 'poor_value'), 'poor_value')
assert.equal(coerceRemoveReason('removed', null), null)
assert.equal(coerceRemoveReason('bought', 'poor_value'), null)
assert.throws(
  () => coerceRemoveReason('removed', 'brand_bad'),
  /invalid_remove_reason/,
)
assert.deepEqual(
  feedbackParams(7, 'removed', {}, 'rarely_useful').slice(0, 3),
  [7, 'removed', 'rarely_useful'],
)
assert.deepEqual(feedbackParams(8, 'hidden', {}, 'poor_value').slice(0, 3), [
  8,
  'removed',
  'poor_value',
])
console.log('ok listing-veto-reasons')
