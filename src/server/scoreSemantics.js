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

function boundedInteger(value, minimum, maximum) {
  if (
    value == null ||
    typeof value === "boolean" ||
    (typeof value === "string" && value.trim() === "")
  ) {
    return null
  }
  const number = Number(value)
  return Number.isInteger(number) && number >= minimum && number <= maximum
    ? number
    : null
}

function isDeclaredV2(row) {
  return boundedInteger(row?.score_version, 2, 2) === 2
}

function buyScore(row) {
  return boundedInteger(row?.buy_score, 0, 100)
}

function isV2(row) {
  return isDeclaredV2(row) && buyScore(row) != null
}

function scoreTier(row) {
  if (isV2(row)) return 2
  if (isDeclaredV2(row)) return 0
  return 1
}

function displayScore(row) {
  if (isV2(row)) return buyScore(row)
  if (isDeclaredV2(row)) return null
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
  if (isDeclaredV2(row)) return false
  return (
    Number(row?.deal_score || 0) >= 9 &&
    (row?.value_band === "steal" || row?.value_band === "hunt")
  )
}

function sellerScoreRows(rows) {
  const v2 = (rows || []).filter(isV2)
  return v2.length
    ? v2
    : (rows || []).filter((row) => !isDeclaredV2(row))
}

function preferredScoreRow(current, incoming) {
  if (!current) return incoming
  if (!incoming) return current
  const currentTier = scoreTier(current)
  const incomingTier = scoreTier(incoming)
  if (currentTier > incomingTier) return current
  if (incomingTier > currentTier) return incoming
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
  if (isDeclaredV2(winner)) {
    delete merged.deal_score
    delete merged.value_band
    delete merged.scam_risk
    delete merged.reason
  } else {
    for (const field of V2_FIELDS) delete merged[field]
  }
  const hadKeepSource =
    current?.source === "keep" || incoming?.source === "keep"
  if (hadKeepSource && !isDeclaredV2(winner)) {
    merged.source = "keep"
  } else if (hadKeepSource && isV2(winner) && isKeep(winner)) {
    merged.source = "keep"
  } else if (merged.source === "keep") {
    const fallbackSource =
      winner === current ? incoming?.source : current?.source
    if (fallbackSource && fallbackSource !== "keep") {
      merged.source = fallbackSource
    } else {
      delete merged.source
    }
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
  const declaredV2 = isDeclaredV2(row)
  const validV2 = isV2(row)
  return {
    score_version: declaredV2 ? 2 : null,
    buy_score: validV2 ? buyScore(row) : null,
    buy_band: validV2 ? row?.buy_band ?? null : null,
    score_confidence: finiteNumber(row?.score_confidence),
    score_interval_low: finiteNumber(row?.score_interval_low),
    score_interval_high: finiteNumber(row?.score_interval_high),
    score_factors: jsonObject(row?.score_factors),
    factor_evidence: jsonObject(row?.factor_evidence),
    verification_concern: row?.verification_concern ?? null,
    verification_reason: row?.verification_reason ?? null,
    rank_position: validV2 ? rankPosition(row) : null,
    rank_confidence: validV2 ? row?.rank_confidence ?? null : null,
    legacy_score: !declaredV2,
  }
}

function sanitizeScoreRow(row) {
  const out = { ...(row || {}), ...scoreFields(row) }
  if (isDeclaredV2(row)) {
    out.deal_score = null
    delete out.value_band
    delete out.scam_risk
    delete out.reason
  }
  return out
}

function rankPosition(row) {
  return boundedInteger(row?.rank_position, 1, Number.MAX_SAFE_INTEGER)
}

function currentRank(row) {
  const position = rankPosition(row)
  return position != null &&
    ["low", "medium", "high"].includes(row?.rank_confidence)
    ? position
    : null
}

function compareScoreRows(left, right) {
  const leftTier = scoreTier(left)
  const rightTier = scoreTier(right)
  if (leftTier !== rightTier) return rightTier - leftTier
  if (leftTier === 2) {
    const leftRank = currentRank(left)
    const rightRank = currentRank(right)
    if (leftRank != null && rightRank != null) {
      if (leftRank !== rightRank) return leftRank - rightRank
    }
  }
  return (displayScore(right) ?? -Infinity) - (displayScore(left) ?? -Infinity)
}

function sortScoreRows(rows) {
  const tiers = [[], [], []]
  for (const row of rows || []) tiers[scoreTier(row)].push(row)
  const validV2 = tiers[2]
  const allRanksCurrent =
    validV2.length > 0 && validV2.every((row) => currentRank(row) != null)
  validV2.sort((left, right) =>
    allRanksCurrent
      ? compareScoreRows(left, right)
      : (displayScore(right) ?? -Infinity) -
        (displayScore(left) ?? -Infinity),
  )
  tiers[1].sort(compareScoreRows)
  return [...validV2, ...tiers[1], ...tiers[0]]
}

function compareBundleScoreRows(left, right) {
  const leftTier = scoreTier(left)
  const rightTier = scoreTier(right)
  if (leftTier !== rightTier) return rightTier - leftTier
  const scoreDifference =
    (displayScore(right) ?? -Infinity) - (displayScore(left) ?? -Infinity)
  return scoreDifference || 0
}

function sortBundleScoreRows(rows) {
  return [...(rows || [])].sort(compareBundleScoreRows)
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
  isDeclaredV2,
  isV2,
  scoreTier,
  displayScore,
  isKeep,
  preferredScoreRow,
  mergeScoreRows,
  scoreFields,
  sanitizeScoreRow,
  compareScoreRows,
  sortScoreRows,
  compareBundleScoreRows,
  sortBundleScoreRows,
  sellerScoreRows,
  histogramBins,
}
