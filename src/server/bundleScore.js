import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const BUNDLE_SCORE_VERSION = 1
const DEFAULTS = {
  extras_weight: 0.15,
  quality_gap_penalty: 0.05,
  fee_relief_scale: 6,
  extras_term_min: -8,
  extras_term_max: 12,
  score_version: BUNDLE_SCORE_VERSION,
}
const UNRANKED_KINDS = new Set(['near_haul', 'index_near_bundle'])

function clamp(value, low, high) {
  return Math.max(low, Math.min(high, Number(value)))
}

function scoreConfig(config) {
  const raw = (config && config.bundle_scoring) || {}
  const out = { ...DEFAULTS }
  for (const key of Object.keys(DEFAULTS)) {
    if (raw[key] != null) out[key] = raw[key]
  }
  const version = Number(raw.score_version)
  out.score_version = Number.isFinite(version) ? version : BUNDLE_SCORE_VERSION
  return out
}

function confidenceLabel(confidence) {
  if (confidence == null || !Number.isFinite(Number(confidence))) return null
  const value = Number(confidence)
  if (value < 0.6) return 'low'
  if (value < 0.8) return 'medium'
  return 'high'
}

function number(value) {
  if (typeof value === 'boolean') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function intScore(value) {
  const n = number(value)
  if (n == null) return null
  const asInt = Math.round(n)
  return asInt >= 0 && asInt <= 100 ? asInt : null
}

function isV2Member(member) {
  return Number(member?.score_version) === 2 && intScore(member?.buy_score) != null
}

function eligibleMembers(members) {
  const out = []
  for (const member of members || []) {
    if (!member || typeof member !== 'object') continue
    if (!isV2Member(member)) continue
    if (member.verification_concern === 'block') continue
    const buy = intScore(member.buy_score)
    const conf = number(member.score_confidence)
    if (buy == null || conf == null || conf < 0 || conf > 1) continue
    out.push({ ...member, buy_score: buy, score_confidence: conf })
  }
  return out
}

function isKeepMember(member, config) {
  if (String(member?.role || '').toLowerCase() === 'keep') return true
  const buy = intScore(member?.buy_score)
  const conf = number(member?.score_confidence)
  if (buy == null || conf == null) return false
  const keepMin = Number(config?.buy_scoring?.keep_min_score ?? 85)
  const minConf = Number(config?.buy_scoring?.min_keep_confidence ?? 0.6)
  return (
    buy >= keepMin &&
    conf >= minConf &&
    member.verification_concern !== 'block' &&
    member.hunt_fit !== false
  )
}

function nullResult(version) {
  return {
    bundle_score: null,
    bundle_score_version: version,
    bundle_confidence: null,
    bundle_anchor_item_id: null,
    bundle_rank_position: null,
  }
}

function splitAnchorExtras(eligible, anchor) {
  const extras = []
  let seenAnchor = false
  for (const member of eligible) {
    const same =
      member.buy_score === anchor.buy_score &&
      String(member.id) === String(anchor.id) &&
      member.score_confidence === anchor.score_confidence
    if (!seenAnchor && same) {
      seenAnchor = true
      continue
    }
    extras.push(member)
  }
  return extras
}

function calculateBundleScore(members, { kind = 'keep_bundle', config = null } = {}) {
  const cfg = scoreConfig(config)
  const version = Number(cfg.score_version)
  const kindKey = kind || 'keep_bundle'
  if (UNRANKED_KINDS.has(kindKey)) return nullResult(version)

  const eligible = eligibleMembers(members)
  if (!eligible.length) return nullResult(version)

  let anchorPool = eligible
  if (kindKey === 'keep_bundle' || kindKey === 'index_keep_bundle') {
    const keepPool = eligible.filter((m) => isKeepMember(m, config))
    anchorPool = keepPool.length ? keepPool : eligible
  }

  const anchor = [...anchorPool].sort((a, b) => {
    if (a.buy_score !== b.buy_score) return a.buy_score - b.buy_score
    if (a.score_confidence !== b.score_confidence) {
      return a.score_confidence - b.score_confidence
    }
    return String(a.id || '').localeCompare(String(b.id || ''))
  }).at(-1)

  const extras = splitAnchorExtras(eligible, anchor)
  const n = eligible.length
  const feeRelief = clamp(
    Number(cfg.fee_relief_scale) * ((n - 1) / n),
    0,
    Number(cfg.fee_relief_scale),
  )
  let extrasTerm = 0
  if (extras.length) {
    const extraMean =
      extras.reduce((sum, m) => sum + m.buy_score, 0) / extras.length
    const qualityGap = anchor.buy_score - extraMean
    extrasTerm = clamp(
      Number(cfg.extras_weight) * (extraMean - 50) -
        Number(cfg.quality_gap_penalty) * Math.max(qualityGap, 0) +
        feeRelief,
      Number(cfg.extras_term_min),
      Number(cfg.extras_term_max),
    )
  }

  const raw = clamp(anchor.buy_score + extrasTerm, 0, 100)
  const meanConf =
    eligible.reduce((sum, m) => sum + m.score_confidence, 0) / eligible.length
  const bundleConfidence = Math.min(anchor.score_confidence, meanConf)

  return {
    bundle_score: Math.round(raw),
    bundle_score_version: version,
    bundle_confidence: Number(bundleConfidence.toFixed(4)),
    bundle_anchor_item_id: anchor.id ?? null,
    bundle_rank_position: null,
  }
}

function applyToRow(row, config = null) {
  const out = { ...(row || {}) }
  const kind = out.kind || 'keep_bundle'
  Object.assign(out, calculateBundleScore(out.items || [], { kind, config }))
  return out
}

function fingerprint(row) {
  const sid = row?.seller_id
  const ids = (row?.items || [])
    .filter((it) => it && it.id != null)
    .map((it) => String(it.id))
    .sort()
  return `${sid}:${ids.join(',')}`
}

function assignBundleRanks(rows) {
  const decorated = (rows || []).map((row) => ({ ...(row || {}) }))
  const scored = []
  for (let index = 0; index < decorated.length; index += 1) {
    const score = intScore(decorated[index].bundle_score)
    if (score == null) {
      decorated[index].bundle_rank_position = null
      continue
    }
    scored.push({
      index,
      score,
      keptAt: String(decorated[index].kept_at || ''),
      fingerprint: fingerprint(decorated[index]),
    })
  }
  scored.sort((a, b) => a.fingerprint.localeCompare(b.fingerprint))
  scored.sort((a, b) => b.keptAt.localeCompare(a.keptAt))
  scored.sort((a, b) => b.score - a.score)
  scored.forEach((entry, position) => {
    decorated[entry.index].bundle_rank_position = position + 1
  })
  return decorated
}

function loadGoldenCases() {
  const here = path.dirname(fileURLToPath(import.meta.url))
  const goldenPath = path.join(
    here,
    '../../python/tests/fixtures/bundle_score_golden.json',
  )
  return JSON.parse(readFileSync(goldenPath, 'utf8'))
}

export {
  BUNDLE_SCORE_VERSION,
  UNRANKED_KINDS,
  scoreConfig,
  confidenceLabel,
  calculateBundleScore,
  applyToRow,
  assignBundleRanks,
  loadGoldenCases,
}
