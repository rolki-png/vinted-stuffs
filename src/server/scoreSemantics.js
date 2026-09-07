const V2_FIELDS = [
  "score_version",
  "buy_score",
  "buy_band",
  "score_confidence",
  "score_interval_low",
  "score_interval_high",
  "score_factors",
  "factor_evidence",
  "verification_concern",
  "verification_reason",
  "rank_position",
  "rank_confidence",
]

function isV2(row) {
  return (
    Number(row?.score_version || 0) === 2 &&
    row?.buy_score != null &&
    Number.isFinite(Number(row?.buy_score))
  )
}

function displayScore(row) {
  if (isV2(row)) return Number(row.buy_score)
  if (row?.deal_score == null) return null
  const legacy = Number(row?.deal_score)
  return Number.isFinite(legacy) ? legacy : null
}

function isKeep(row) {
  if (isV2(row)) {
    return (
      Number(row.buy_score) >= 85 &&
      Number(row.score_confidence || 0) >= 0.6 &&
      row.hunt_fit === true &&
      row.verification_concern !== "block"
    )
  }
  return (
    Number(row?.deal_score || 0) >= 9 &&
    (row?.value_band === "steal" || row?.value_band === "hunt")
  )
}

function sellerScoreRows(rows) {
  const v2 = (rows || []).filter(isV2)
  return v2.length ? v2 : (rows || []).filter((row) => !isV2(row))
}

function preferredScoreRow(current, incoming) {
  if (!current) return incoming
  if (!incoming) return current
  if (isV2(current) && !isV2(incoming)) return current
  if (isV2(incoming) && !isV2(current)) return incoming
  return incoming
}

function mergeScoreRows(current, incoming) {
  const winner = preferredScoreRow(current, incoming)
  const other = winner === current ? incoming : current
  const merged = {}
  for (const row of [other, winner]) {
    for (const [key, value] of Object.entries(row || {})) {
      if (value != null) merged[key] = value
    }
  }
  if (isV2(winner)) {
    delete merged.deal_score
    delete merged.value_band
    delete merged.scam_risk
  } else {
    for (const field of V2_FIELDS) delete merged[field]
  }
  return merged
}

function finiteNumber(value) {
  if (value == null) return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function jsonObject(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) return value
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value)
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed
      }
    } catch {
      // Invalid historical JSON should not break the dashboard read model.
    }
  }
  return {}
}

function scoreFields(row) {
  return {
    score_version: finiteNumber(row?.score_version),
    buy_score: finiteNumber(row?.buy_score),
    buy_band: row?.buy_band ?? null,
    score_confidence: finiteNumber(row?.score_confidence),
    score_interval_low: finiteNumber(row?.score_interval_low),
    score_interval_high: finiteNumber(row?.score_interval_high),
    score_factors: jsonObject(row?.score_factors),
    factor_evidence: jsonObject(row?.factor_evidence),
    verification_concern: row?.verification_concern ?? null,
    verification_reason: row?.verification_reason ?? null,
    rank_position: finiteNumber(row?.rank_position),
    rank_confidence: row?.rank_confidence ?? null,
    legacy_score: !isV2(row),
  }
}

function rankPosition(row) {
  if (row?.rank_position == null) return null
  const rank = Number(row.rank_position)
  return Number.isInteger(rank) && rank > 0 ? rank : null
}

function compareScoreRows(left, right) {
  const leftV2 = isV2(left)
  const rightV2 = isV2(right)
  if (leftV2 !== rightV2) return leftV2 ? -1 : 1
  if (leftV2) {
    const leftRank = rankPosition(left)
    const rightRank = rankPosition(right)
    if (leftRank != null || rightRank != null) {
      if (leftRank == null) return 1
      if (rightRank == null) return -1
      if (leftRank !== rightRank) return leftRank - rightRank
    }
  }
  return (displayScore(right) ?? -Infinity) - (displayScore(left) ?? -Infinity)
}

function sortScoreRows(rows) {
  return [...(rows || [])].sort(compareScoreRows)
}

function histogramBins(histogram) {
  return Object.entries(histogram || {})
    .filter(([label]) => /^\d+-\d+$/.test(label))
    .sort(
      ([left], [right]) =>
        Number(left.split("-")[0]) - Number(right.split("-")[0]),
    )
    .map(([label, count]) => ({
      label: label.replace("-", "–"),
      count: Number(count || 0),
    }))
}

export {
  V2_FIELDS,
  isV2,
  displayScore,
  isKeep,
  preferredScoreRow,
  mergeScoreRows,
  scoreFields,
  compareScoreRows,
  sortScoreRows,
  sellerScoreRows,
  histogramBins,
}
