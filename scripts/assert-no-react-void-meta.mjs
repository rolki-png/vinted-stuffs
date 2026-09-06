/**
 * Regression: React treats HTML void tags (meta, img, br, …) as self-closing.
 * Using <meta>…</meta> as a presentational wrapper throws minified error #137.
 * Vanilla dashboard/app.js may still use <meta> via innerHTML; React must not.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import React from 'react'
import { renderToString } from 'react-dom/server'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dealDesk = fs.readFileSync(path.join(root, 'src/components/DealDesk.tsx'), 'utf8')

const voidMetaWithChildren = /<meta\b[^>]*>[\s\S]*?<\/meta>/i
if (voidMetaWithChildren.test(dealDesk)) {
  console.error('RED: DealDesk.tsx still uses <meta>…</meta> (React void element #137)')
  process.exit(1)
}

try {
  renderToString(React.createElement('meta', null, 'must not have children'))
  console.error('RED: expected React to reject <meta> children')
  process.exit(1)
} catch (e) {
  const msg = String(e && e.message)
  if (!/meta|void|self-closing/i.test(msg)) {
    console.error('RED: unexpected throw:', msg)
    process.exit(1)
  }
}

const html = renderToString(
  React.createElement('p', { className: 'bundle-meta' }, 'ok ', React.createElement('strong', null, 'x')),
)
if (!html.includes('bundle-meta') || !html.includes('<strong>x</strong>')) {
  console.error('RED: proposed wrapper render mismatch:', html)
  process.exit(1)
}

console.log('GREEN: no React void <meta> wrappers in DealDesk')
