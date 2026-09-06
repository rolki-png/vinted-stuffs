/**
 * Active hunt names for the desk dropdown — from config.watches, not historical finds.
 * Run: node scripts/test-active-watches.mjs
 */
import assert from "node:assert/strict"
import { activeWatchNamesFromConfig } from "../src/server/activeWatches.js"

assert.deepEqual(
  activeWatchNamesFromConfig({
    watches: [
      { name: "Broad gym shorts M-L" },
      { name: "Devold merino M-L" },
      { name: "" },
      {},
      { name: "Zimmerli polo M-L" },
    ],
  }),
  ["Broad gym shorts M-L", "Devold merino M-L", "Zimmerli polo M-L"],
)

assert.deepEqual(activeWatchNamesFromConfig(null), [])
assert.deepEqual(activeWatchNamesFromConfig({}), [])
assert.deepEqual(activeWatchNamesFromConfig({ watches: "nope" }), [])

console.log("ok active-watches")
