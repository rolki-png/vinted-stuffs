import { createFileRoute } from '@tanstack/react-router'
import { authorized } from '#/server/github'
import { clearVeto, setVetoStatus } from '#/server/listingVetoes'

async function handleVeto(request: Request) {
  if (!authorized(request)) {
    return Response.json(
      { error: 'unauthorized' },
      { status: 401, headers: { 'Cache-Control': 'no-store' } },
    )
  }
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
    const result = await setVetoStatus(itemId, body.status)
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
