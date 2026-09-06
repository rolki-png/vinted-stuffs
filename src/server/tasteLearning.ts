// @ts-nocheck
/**
 * Hunt-family resolution for taste enrichment — mirrors python/taste_learning.py.
 */

const FAMILY_RULES = [
  [
    "maternity",
    [
      "maternity",
      "mama",
      "mamalicious",
      "seraphine",
      "noppies",
      "hatch",
      "storq",
      "legoe",
      "bae the label",
      "tiffany rose",
      "boob",
      "ripe",
      "envie",
      "jojo",
      "beyond nine",
      "isabella oliver",
      "pietro brunelli",
      "next maternity",
      "asos maternity",
      "h&m mama",
      "leggings",
    ],
  ],
  ["sneakers", ["new balance", "asics", "diadora"]],
  [
    "gym",
    [
      "gym",
      "running",
      "gorewear",
      "2xu",
      "craft",
      "saysky",
      "falke",
      "odlo",
      "lululemon",
      "ten thousand",
      "rhone",
      "vuori",
      "tracksmith",
      "h&m sport",
    ],
  ],
  [
    "knitwear",
    [
      "merino",
      "cashmere",
      "johnstons",
      "cruciani",
      "gran sasso",
      "fedeli",
      "sunspel",
      "zimmerli",
      "hanro",
      "merz",
      "cdlp",
      "devold",
      "smartwool",
      "ortovox",
      "woolpower",
      "polo",
    ],
  ],
]

function resolveFamily(huntName, watch) {
  if (watch && watch.family) {
    const f = String(watch.family).trim().toLowerCase()
    return f || "other"
  }
  const name = String(huntName || "").toLowerCase()
  for (const [family, needles] of FAMILY_RULES) {
    for (const needle of needles) {
      if (name.includes(needle)) return family
    }
  }
  return "other"
}

export { resolveFamily }
