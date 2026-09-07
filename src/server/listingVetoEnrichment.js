const ENRICHMENT_FIELDS = [
  "hunt_name",
  "hunt_family",
  "brand",
  "size",
  "price_ron",
  "value_band",
  "deal_score",
  "score_version",
  "buy_score",
  "buy_band",
  "title",
]

const INTEGER_FIELDS = new Set(["deal_score", "score_version", "buy_score"])

function coerceEnrichment(enrichment) {
  const out = Object.fromEntries(ENRICHMENT_FIELDS.map((key) => [key, null]))
  if (!enrichment || typeof enrichment !== "object") return out
  for (const key of ENRICHMENT_FIELDS) {
    if (enrichment[key] == null) continue
    if (key === "price_ron") {
      const value = Number(enrichment[key])
      out[key] = Number.isFinite(value) ? value : null
    } else if (INTEGER_FIELDS.has(key)) {
      const value = Number(enrichment[key])
      out[key] = Number.isFinite(value) ? Math.trunc(value) : null
    } else {
      const value = String(enrichment[key]).trim()
      out[key] = value || null
    }
  }
  return out
}

function mergeEnrichment(previous, incoming) {
  const current = coerceEnrichment(previous)
  const next = coerceEnrichment(incoming)
  const merged = {}
  for (const key of ENRICHMENT_FIELDS) {
    merged[key] = next[key] != null ? next[key] : current[key]
  }

  const hasV2Context =
    next.score_version != null ||
    next.buy_score != null ||
    next.buy_band != null
  const hasLegacyContext = next.deal_score != null || next.value_band != null
  if (hasV2Context) {
    merged.deal_score = null
    merged.value_band = null
    for (const key of ["score_version", "buy_score", "buy_band"]) {
      merged[key] = next[key]
    }
  } else if (hasLegacyContext) {
    merged.score_version = null
    merged.buy_score = null
    merged.buy_band = null
  }
  return merged
}

export { ENRICHMENT_FIELDS, coerceEnrichment, mergeEnrichment }
