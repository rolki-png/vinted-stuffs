const VALID_REMOVE_REASONS = new Set([
  'sold_unavailable',
  'wrong_size',
  'bad_fit_style',
  'low_quality_condition',
  'poor_value',
  'rarely_useful',
  'already_own_similar',
  'other',
])

function coerceRemoveReason(status, reasonCode) {
  if (
    status !== 'removed' ||
    reasonCode == null ||
    String(reasonCode).trim() === ''
  ) {
    return null
  }
  const reason = String(reasonCode).trim()
  if (!VALID_REMOVE_REASONS.has(reason)) {
    const error = new Error('invalid_remove_reason')
    error.status = 400
    throw error
  }
  return reason
}

function feedbackParams(itemId, status, enrichment, reasonCode) {
  const id = Number(itemId)
  if (!Number.isFinite(id)) {
    const error = new Error('invalid_item_id')
    error.status = 400
    throw error
  }
  return [id, status, coerceRemoveReason(status, reasonCode), enrichment || {}]
}

export { VALID_REMOVE_REASONS, coerceRemoveReason, feedbackParams }
