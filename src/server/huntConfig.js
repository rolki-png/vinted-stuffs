// @ts-nocheck
/**
 * Pure helpers for desk hunt config: validate, serialize, mutate watches[].
 */

const CONFIG_PATH = "python/config.json"
const FAMILIES = new Set(["maternity", "gym", "sneakers", "knitwear", "other"])
const FORM_KEYS = new Set([
  "name",
  "query",
  "country",
  "order",
  "per_page",
  "price_to",
  "hunt_price",
  "target_type",
  "target_sizes",
  "notes",
  "bundle_hunt",
  "family",
  "min_deal_score",
  "brand_ids",
  "size_ids",
])

function positiveIntList(v, label) {
  if (v == null) return { ok: true, value: undefined }
  if (!Array.isArray(v)) return { ok: false, error: `${label} must be an array of positive integers` }
  if (!v.length) return { ok: true, value: undefined }
  const out = []
  for (const x of v) {
    const n = Number(x)
    if (!Number.isInteger(n) || n <= 0) {
      return { ok: false, error: `${label} must be positive integers` }
    }
    out.push(n)
  }
  return { ok: true, value: out }
}

function nonNegNumber(v, label, { required = false } = {}) {
  if (v == null || v === "") {
    if (required) return { ok: false, error: `${label} is required` }
    return { ok: true, value: undefined }
  }
  const n = Number(v)
  if (!Number.isFinite(n) || n < 0) return { ok: false, error: `${label} must be a number ≥ 0` }
  return { ok: true, value: n }
}

/**
 * Normalize a hunt object for write: force country ro, omit empties, keep extras if provided via base.
 * @param {object} raw form fields
 * @param {object|null} base existing watch to preserve unknown keys
 */
function normalizeHunt(raw, base = null) {
  const src = raw && typeof raw === "object" ? raw : {}
  const out = base && typeof base === "object" ? { ...base } : {}

  // Drop form-managed keys that may be cleared, then re-apply.
  for (const k of FORM_KEYS) {
    if (k in out && (k === "brand_ids" || k === "size_ids" || k === "min_deal_score" || k === "family" || k === "bundle_hunt")) {
      delete out[k]
    }
  }

  const name = String(src.name ?? "").trim()
  const query = String(src.query ?? "").trim()
  const target_type = String(src.target_type ?? "").trim()
  const notes = src.notes != null ? String(src.notes) : out.notes != null ? String(out.notes) : ""
  const order = String(src.order ?? out.order ?? "newest_first").trim() || "newest_first"

  let target_sizes = src.target_sizes
  if (typeof target_sizes === "string") {
    target_sizes = target_sizes
      .split(/[,;\n]/)
      .map((s) => s.trim())
      .filter(Boolean)
  }
  if (!Array.isArray(target_sizes)) target_sizes = Array.isArray(out.target_sizes) ? out.target_sizes : []

  out.name = name
  out.query = query
  out.country = "ro"
  out.order = order
  out.target_type = target_type
  out.target_sizes = target_sizes
  out.notes = notes

  const perPage = nonNegNumber(src.per_page ?? out.per_page, "per_page")
  if (!perPage.ok) return { ok: false, error: perPage.error }
  if (perPage.value != null) out.per_page = Math.trunc(perPage.value)

  const priceTo = nonNegNumber(src.price_to ?? out.price_to, "price_to")
  if (!priceTo.ok) return { ok: false, error: priceTo.error }
  if (priceTo.value != null) out.price_to = priceTo.value

  const huntPrice = nonNegNumber(src.hunt_price ?? out.hunt_price, "hunt_price")
  if (!huntPrice.ok) return { ok: false, error: huntPrice.error }
  if (huntPrice.value != null) out.hunt_price = huntPrice.value

  const brands = positiveIntList(src.brand_ids, "brand_ids")
  if (!brands.ok) return { ok: false, error: brands.error }
  if (brands.value) out.brand_ids = brands.value

  const sizes = positiveIntList(src.size_ids, "size_ids")
  if (!sizes.ok) return { ok: false, error: sizes.error }
  if (sizes.value) out.size_ids = sizes.value

  if (src.bundle_hunt === true || src.bundle_hunt === "true") {
    out.bundle_hunt = true
  }

  const family = src.family != null ? String(src.family).trim().toLowerCase() : ""
  if (family) {
    if (!FAMILIES.has(family)) return { ok: false, error: `family must be one of ${[...FAMILIES].join(", ")}` }
    out.family = family
  }

  const minScore = nonNegNumber(src.min_deal_score, "min_deal_score")
  if (!minScore.ok) return { ok: false, error: minScore.error }
  if (minScore.value != null) out.min_deal_score = Math.trunc(minScore.value)

  return { ok: true, hunt: out }
}

/**
 * @param {object} hunt normalized hunt
 * @param {object[]} watches current watches
 * @param {{ mode: 'add'|'replace'|'remove', originalName?: string }} opts
 */
function validateHuntMutation(hunt, watches, opts) {
  const list = Array.isArray(watches) ? watches : []
  const mode = opts?.mode
  if (!mode || !["add", "replace", "remove"].includes(mode)) {
    return { ok: false, error: "mode must be add, replace, or remove" }
  }

  if (mode === "remove") {
    const name = String(opts.originalName || hunt?.name || "").trim()
    if (!name) return { ok: false, error: "name is required to remove" }
    if (!list.some((w) => w && w.name === name)) {
      return { ok: false, error: `hunt not found: ${name}` }
    }
    return { ok: true, name }
  }

  if (!hunt || typeof hunt !== "object") return { ok: false, error: "hunt is required" }
  if (!hunt.name) return { ok: false, error: "name is required" }
  if (!hunt.query) return { ok: false, error: "query is required" }
  if (!hunt.target_type) return { ok: false, error: "target_type is required" }
  if (hunt.country !== "ro") return { ok: false, error: "country must be ro" }

  if (mode === "add") {
    if (list.some((w) => w && w.name === hunt.name)) {
      return { ok: false, error: `hunt name already exists: ${hunt.name}` }
    }
    return { ok: true }
  }

  // replace
  const originalName = String(opts.originalName || "").trim()
  if (!originalName) return { ok: false, error: "originalName is required for replace" }
  const idx = list.findIndex((w) => w && w.name === originalName)
  if (idx < 0) return { ok: false, error: `hunt not found: ${originalName}` }
  if (hunt.name !== originalName && list.some((w) => w && w.name === hunt.name)) {
    return { ok: false, error: `hunt name already exists: ${hunt.name}` }
  }
  return { ok: true, index: idx }
}

/**
 * Apply add|replace|remove to a config object. Mutates a shallow copy.
 * @returns {{ ok: true, config: object, message: string, name: string } | { ok: false, error: string }}
 */
function applyWatchMutation(config, { mode, hunt: rawHunt, originalName }) {
  if (!config || typeof config !== "object" || Array.isArray(config)) {
    return { ok: false, error: "config must be an object" }
  }
  const next = { ...config, watches: Array.isArray(config.watches) ? [...config.watches] : [] }

  if (mode === "remove") {
    const check = validateHuntMutation(null, next.watches, { mode, originalName })
    if (!check.ok) return check
    const name = check.name
    next.watches = next.watches.filter((w) => !(w && w.name === name))
    return {
      ok: true,
      config: next,
      name,
      message: `desk: remove hunt ${name} [skip ci]`,
    }
  }

  const base =
    mode === "replace"
      ? next.watches.find((w) => w && w.name === String(originalName || "").trim()) || null
      : null
  const norm = normalizeHunt(rawHunt, base)
  if (!norm.ok) return norm
  const check = validateHuntMutation(norm.hunt, next.watches, { mode, originalName })
  if (!check.ok) return check

  if (mode === "add") {
    next.watches.push(norm.hunt)
    return {
      ok: true,
      config: next,
      name: norm.hunt.name,
      message: `desk: add hunt ${norm.hunt.name} [skip ci]`,
    }
  }

  next.watches[check.index] = norm.hunt
  return {
    ok: true,
    config: next,
    name: norm.hunt.name,
    message: `desk: replace hunt ${norm.hunt.name} [skip ci]`,
  }
}

function serializeConfigJson(config) {
  return `${JSON.stringify(config, null, 2)}\n`
}

/**
 * Decide tip-race retry vs real conflict after a 409.
 * @param {string} attemptedSha blob sha used in failed PUT
 * @param {string|null} freshSha blob sha from re-GET
 */
function classifyContents409(attemptedSha, freshSha) {
  if (freshSha && attemptedSha && freshSha === attemptedSha) {
    return { kind: "tip_race", retry: true }
  }
  return { kind: "conflict", retry: false }
}

export {
  CONFIG_PATH,
  FAMILIES,
  FORM_KEYS,
  normalizeHunt,
  validateHuntMutation,
  applyWatchMutation,
  serializeConfigJson,
  classifyContents409,
}
