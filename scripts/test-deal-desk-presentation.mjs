import assert from 'node:assert/strict'
import fs from 'node:fs'

const source = fs.readFileSync(
  new URL('../src/components/DealDesk.tsx', import.meta.url),
  'utf8',
)
const styles = fs.readFileSync(
  new URL('../src/styles.css', import.meta.url),
  'utf8',
)

assert.doesNotMatch(source, /#\/server\/scoreSemantics\.js/)
assert.match(source, /usableRank\(row\)/)
assert.match(source, /buyBandPresentation\(f\)/)
assert.doesNotMatch(source, /f\.buy_band \|\| 'skip'/)

const controlsStart = source.indexOf('className="remove-controls"')
const controlsEnd = source.indexOf('</span>', controlsStart)
assert.ok(controlsStart >= 0 && controlsEnd > controlsStart)
const controls = source.slice(controlsStart, controlsEnd)
assert.ok(
  controls.indexOf('className="remove-reason"') <
    controls.indexOf("setStatus('removed'"),
  'Remove reason selector must precede Remove in keyboard order',
)
assert.doesNotMatch(controls, /\btitle=/)
assert.match(
  controls,
  /Other and Sold\/unavailable do not affect taste learning\./,
)
assert.match(styles, /\.pill\.unknown\s*\{/)
assert.match(styles, /\.remove-learning-note\s*\{/)
assert.doesNotMatch(styles, /\.risk-(?:high|medium|low)\s*\{/)

console.log('ok deal-desk-presentation')
