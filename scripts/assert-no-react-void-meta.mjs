/**
 * Regression: React treats HTML void tags (meta, img, br, …) as self-closing.
 * Using <meta>…</meta> as a presentational wrapper throws minified error #137.
 * Vanilla dashboard/app.js may still use <meta> via innerHTML; React src/ must not.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const srcRoot = path.join(root, 'src')
const voidMetaWithChildren = /<meta\b[^>]*>[\s\S]*?<\/meta>/i

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(p, out)
    else if (/\.(tsx|jsx)$/.test(entry.name)) out.push(p)
  }
  return out
}

const offenders = []
for (const file of walk(srcRoot)) {
  const text = fs.readFileSync(file, 'utf8')
  if (voidMetaWithChildren.test(text)) offenders.push(path.relative(root, file))
}

if (offenders.length) {
  console.error('RED: React void <meta>…</meta> wrappers found in:')
  for (const f of offenders) console.error(' -', f)
  process.exit(1)
}

console.log('GREEN: no React void <meta> wrappers under src/')
