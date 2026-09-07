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

const VALID_STATUSES = new Set(['removed', 'parked', 'bought'])

function coerceWriteStatus(status) {
  const rawStatus = String(status)
  const normalized = rawStatus === 'hidden' ? 'removed' : rawStatus
  if (!VALID_STATUSES.has(normalized)) {
    const error = new Error('invalid_status')
    error.status = 400
    throw error
  }
  return normalized
}

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
  const normalizedStatus = coerceWriteStatus(status)
  return [
    id,
    normalizedStatus,
    coerceRemoveReason(normalizedStatus, reasonCode),
    enrichment || {},
  ]
}

export { VALID_REMOVE_REASONS, coerceRemoveReason, feedbackParams }
