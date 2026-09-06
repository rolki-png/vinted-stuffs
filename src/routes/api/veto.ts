import { createFileRoute } from '@tanstack/react-router'
import { clearVeto, setVetoStatus } from '#/server/listingVetoes'

const ENRICHMENT_KEYS = [
  'hunt_name',
  'hunt_family',
  'brand',
  'size',
  'price_ron',
  'value_band',
  'deal_score',
  'title',
] as const

function enrichmentFromBody(body: Record<string, unknown>) {
  const out: Record<string, unknown> = {}
  const nested =
    body.enrichment && typeof body.enrichment === 'object'
      ? (body.enrichment as Record<string, unknown>)
      : body
  for (const key of ENRICHMENT_KEYS) {
    if (nested[key] != null) out[key] = nested[key]
  }
  // Accept common desk field aliases
  if (out.hunt_name == null && nested.watch != null) out.hunt_name = nested.watch
  if (out.price_ron == null && nested.price != null) out.price_ron = nested.price
  if (out.deal_score == null && nested.deal_score != null)
    out.deal_score = nested.deal_score
  return out
}

async function handleVeto(request: Request) {
  try {
    const body = (await request.json().catch(() => ({}))) as Record<
      string,
      unknown
    >
    const itemId = body.item_id ?? body.itemId
    const clear =
      request.method === 'DELETE' ||
      body.clear === true ||
      body.action === 'clear' ||
      body.status === 'clear'
    if (clear) {
      const result = await clearVeto(itemId)
      return Response.json(
        { ok: true, ...result },
        { headers: { 'Cache-Control': 'no-store' } },
      )
    }
    const result = await setVetoStatus(
      itemId,
      body.status,
      enrichmentFromBody(body),
    )
    return Response.json(
      { ok: true, ...result },
      { headers: { 'Cache-Control': 'no-store' } },
    )
  } catch (err: any) {
    return Response.json(
      { error: String(err?.message || err) },
      {
        status: err?.status || 500,
        headers: { 'Cache-Control': 'no-store' },
      },
    )
  }
}

export const Route = createFileRoute('/api/veto')({
  server: {
    handlers: {
      POST: async ({ request }) => handleVeto(request),
      DELETE: async ({ request }) => handleVeto(request),
    },
  },
})
