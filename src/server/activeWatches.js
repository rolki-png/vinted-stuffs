// @ts-nocheck
/**
 * Active hunt names from python/config.json watches[] — desk filter dropdown.
 * Historical find.watch values may include retired hunts; do not use those for the list.
 */

function activeWatchNamesFromConfig(config) {
  const watches = config && Array.isArray(config.watches) ? config.watches : []
  const names = []
  const seen = new Set()
  for (const w of watches) {
    const name = w && typeof w.name === "string" ? w.name.trim() : ""
    if (!name || seen.has(name)) continue
    seen.add(name)
    names.push(name)
  }
  return names.sort((a, b) => a.localeCompare(b))
}

function filterToActiveWatches(watchList, activeNames) {
  if (!activeNames || !activeNames.length) {
    return [...new Set((watchList || []).filter(Boolean))].sort((a, b) =>
      String(a).localeCompare(String(b)),
    )
  }
  const allow = new Set(activeNames)
  return [...new Set((watchList || []).filter((w) => w && allow.has(w)))].sort(
    (a, b) => String(a).localeCompare(String(b)),
  )
}

export { activeWatchNamesFromConfig, filterToActiveWatches }
