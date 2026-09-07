import {
  compareScoreRows,
  displayScore,
  histogramBins,
  isDeclaredV2,
  isKeep,
  isV2,
  scoreTier,
} from '../server/scoreSemantics.js'

const BUY_BANDS = new Set(['skip', 'bundle', 'good', 'keep', 'exceptional'])
const RANK_CONFIDENCE = new Set(['low', 'medium', 'high'])

function finiteNumber(value) {
  if (value == null || typeof value === 'boolean') return null
  if (typeof value === 'string' && value.trim() === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function numericScore(row) {
  return displayScore(row) ?? 0
}

function filterScore(row) {
  return isV2(row) ? displayScore(row) : null
}

function matchesScoreFilter(row, filter) {
  if (!filter) return true
  if (filter === 'legacy') {
    return !isDeclaredV2(row) && displayScore(row) != null
  }
  const match = /^v2:(\d+)$/.exec(filter)
  if (!match) return false
  const score = filterScore(row)
  return score != null && score >= Number(match[1])
}

function matchesBandFilter(row, filter) {
  if (!filter) return true
  const [scale, band] = String(filter).split(':', 2)
  if (!band) return false
  if (scale === 'v2') return isV2(row) && row?.buy_band === band
  return scale === 'legacy' && !isDeclaredV2(row) && row?.value_band === band
}

function scoreLabel(row) {
  if (isDeclaredV2(row) && !isV2(row)) return 'Invalid v2 score'
  if (!isV2(row)) {
    const legacy = displayScore(row)
    return legacy == null ? '—' : `${legacy} legacy`
  }
  const score = displayScore(row)
  const low = finiteNumber(row?.score_interval_low)
  const high = finiteNumber(row?.score_interval_high)
  if (low != null && high != null) {
    return `${score} (90% interval ${low}–${high})`
  }
  return String(score)
}

function scoreScaleLabel(row) {
  if (isV2(row)) return 'V2 utility /100'
  if (isDeclaredV2(row)) return 'Invalid v2'
  return displayScore(row) == null ? 'Unscored' : 'Legacy /10'
}

function usableRank(row) {
  const position = finiteNumber(row?.rank_position)
  if (
    Number.isInteger(position) &&
    position >= 1 &&
    RANK_CONFIDENCE.has(row?.rank_confidence)
  ) {
    return { position, confidence: row.rank_confidence }
  }
  return null
}

function hasCurrentRank(row) {
  return usableRank(row) != null
}

function buyBandPresentation(row) {
  if (BUY_BANDS.has(row?.buy_band)) {
    return { label: row.buy_band, className: row.buy_band }
  }
  return { label: 'Unknown v2 band', className: 'unknown' }
}

function vetoStatusTier(row) {
  if (!row?.veto_status || row.veto_status === 'active') return 0
  if (row.veto_status === 'parked') return 1
  return 2
}

function findComparator(sort, { useRanks = false } = {}) {
  return (left, right) => {
    const statusDifference = vetoStatusTier(left) - vetoStatusTier(right)
    if (statusDifference) return statusDifference
    if (sort === 'score-desc' || sort === 'score-asc') {
      const tierDifference = scoreTier(right) - scoreTier(left)
      if (tierDifference) return tierDifference
      if (scoreTier(left) === 2 && useRanks) {
        const ranked = compareScoreRows(left, right)
        return sort === 'score-desc' ? ranked : -ranked
      }
      const difference = numericScore(left) - numericScore(right)
      return sort === 'score-asc' ? difference : -difference
    }
    switch (sort) {
      case 'price-asc':
        return (
          (finiteNumber(left?.price_num) ?? Infinity) -
          (finiteNumber(right?.price_num) ?? Infinity)
        )
      case 'price-desc':
        return (
          (finiteNumber(right?.price_num) ?? -Infinity) -
          (finiteNumber(left?.price_num) ?? -Infinity)
        )
      case 'date-desc':
        return String(right?.kept_at || '').localeCompare(
          String(left?.kept_at || ''),
        )
      case 'watch':
        return String(left?.watch || '').localeCompare(
          String(right?.watch || ''),
        )
      default:
        return 0
    }
  }
}

function sortFinds(rows, sort) {
  const copy = [...(rows || [])]
  const useRanksByStatus = new Map()
  if (sort === 'score-desc' || sort === 'score-asc') {
    for (const status of [0, 1, 2]) {
      const v2Rows = copy.filter(
        (row) => vetoStatusTier(row) === status && isV2(row),
      )
      useRanksByStatus.set(
        status,
        v2Rows.length > 0 && v2Rows.every((row) => hasCurrentRank(row)),
      )
    }
  }
  return copy.sort((left, right) => {
    const status = vetoStatusTier(left)
    return findComparator(sort, {
      useRanks:
        status === vetoStatusTier(right) &&
        useRanksByStatus.get(status) === true,
    })(left, right)
  })
}

function keepCounts(rows) {
  return (rows || []).reduce(
    (counts, row) => {
      if (!isKeep(row)) return counts
      if (isV2(row)) counts.v2 += 1
      else if (!isDeclaredV2(row)) counts.legacy += 1
      return counts
    },
    { v2: 0, legacy: 0 },
  )
}

function sellerTier(row) {
  const explicit = finiteNumber(row?.score_tier)
  if (Number.isInteger(explicit) && explicit >= 0 && explicit <= 2) {
    return explicit
  }
  const best = finiteNumber(row?.best_score)
  if (
    Number(row?.score_version) === 2 &&
    best != null &&
    best >= 0 &&
    best <= 100
  ) {
    return 2
  }
  if (row?.legacy_score === true && best != null) return 1
  return 0
}

function sellerComparator(sort) {
  return (left, right) => {
    if (sort === 'listings') {
      return (
        (finiteNumber(right?.listings) ?? 0) -
        (finiteNumber(left?.listings) ?? 0)
      )
    }
    if (sort === 'keeps') {
      return (
        (finiteNumber(right?.keeps) ?? 0) - (finiteNumber(left?.keeps) ?? 0) ||
        sellerTier(right) - sellerTier(left) ||
        (finiteNumber(right?.best_score) ?? -Infinity) -
          (finiteNumber(left?.best_score) ?? -Infinity)
      )
    }
    const tierDifference = sellerTier(right) - sellerTier(left)
    if (tierDifference) return tierDifference
    const field = sort === 'avg' ? 'avg_score' : 'best_score'
    return (
      (finiteNumber(right?.[field]) ?? -Infinity) -
        (finiteNumber(left?.[field]) ?? -Infinity) ||
      (finiteNumber(right?.keeps) ?? 0) - (finiteNumber(left?.keeps) ?? 0)
    )
  }
}

function vetoScoreContext(row) {
  if (isDeclaredV2(row)) {
    const score = displayScore(row)
    if (!isV2(row) || !BUY_BANDS.has(row?.buy_band)) return {}
    return {
      score_version: 2,
      buy_score: score,
      buy_band: row.buy_band,
    }
  }
  const score = displayScore(row)
  if (
    !Number.isInteger(score) ||
    score < 1 ||
    score > 10 ||
    typeof row?.value_band !== 'string' ||
    row.value_band.trim() === ''
  ) {
    return {}
  }
  return { deal_score: score, value_band: row.value_band.trim() }
}

function vetoPayload(itemId, status, row, reasonCode) {
  const id = Number(itemId)
  if (status == null) return { item_id: id, clear: true }
  const body = {
    item_id: id,
    status,
    hunt_name: row?.watch || null,
    brand: row?.brand || null,
    size: row?.size || null,
    price_ron: row?.price_num ?? row?.price ?? null,
    title: row?.title || null,
    ...vetoScoreContext(row),
  }
  if (status === 'removed' && reasonCode) body.reason_code = reasonCode
  return body
}

function factorRows(row) {
  const factors =
    row?.score_factors &&
    typeof row.score_factors === 'object' &&
    !Array.isArray(row.score_factors)
      ? row.score_factors
      : {}
  const evidence =
    row?.factor_evidence &&
    typeof row.factor_evidence === 'object' &&
    !Array.isArray(row.factor_evidence)
      ? row.factor_evidence
      : {}
  return Object.entries(factors)
    .filter(
      ([key, value]) =>
        typeof value === 'number' &&
        Number.isFinite(value) &&
        !key.endsWith('_ron'),
    )
    .map(([key, value]) => ({
      key,
      label: key.replaceAll('_', ' '),
      value: Number(value).toFixed(key.includes('probability') ? 2 : 0),
      evidence: typeof evidence[key] === 'string' ? evidence[key] : '',
    }))
}

function histogramRows(histogram) {
  return histogramBins(histogram)
}

function bundleConfidenceLabel(confidence) {
  const value = finiteNumber(confidence)
  if (value == null) return null
  if (value < 0.6) return 'low'
  if (value < 0.8) return 'medium'
  return 'high'
}

function sortBundles(rows, sort) {
  const list = [...(rows || [])]
  if (sort === 'best-desc') {
    list.sort((left, right) => {
      const leftScore = finiteNumber(left?.bundle_score)
      const rightScore = finiteNumber(right?.bundle_score)
      const leftRanked = leftScore != null
      const rightRanked = rightScore != null
      if (leftRanked !== rightRanked) return leftRanked ? -1 : 1
      if (leftRanked && rightRanked && leftScore !== rightScore) {
        return rightScore - leftScore
      }
      const leftPos = finiteNumber(left?.bundle_rank_position)
      const rightPos = finiteNumber(right?.bundle_rank_position)
      if (leftPos != null && rightPos != null && leftPos !== rightPos) {
        return leftPos - rightPos
      }
      return String(right?.kept_at || '').localeCompare(String(left?.kept_at || ''))
    })
    return list
  }
  list.sort((left, right) =>
    String(right?.kept_at || '').localeCompare(String(left?.kept_at || '')),
  )
  return list
}

export {
  buyBandPresentation,
  bundleConfidenceLabel,
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
  sortBundles,
  sortFinds,
  usableRank,
  vetoPayload,
  vetoScoreContext,
}
