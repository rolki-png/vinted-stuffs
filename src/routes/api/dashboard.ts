import { createFileRoute } from '@tanstack/react-router'
import { buildSnapshot } from '#/server/snapshot'

function vetoModeFromUrl(url: URL) {
  const raw =
    url.searchParams.get('veto') ||
    url.searchParams.get('veto_mode') ||
    'active'
  return ['active', 'parked', 'hidden', 'all'].includes(raw) ? raw : 'active'
}

export const Route = createFileRoute('/api/dashboard')({
  server: {
    handlers: {
      GET: async ({ request }) => {
        try {
          const snapshot = await buildSnapshot({
            vetoMode: vetoModeFromUrl(new URL(request.url)),
          })
          return Response.json(snapshot, {
            headers: { 'Cache-Control': 'no-store' },
          })
        } catch (err) {
          return Response.json(
            {
              error: 'snapshot_failed',
              message: String(err instanceof Error ? err.message : err),
            },
            { status: 500, headers: { 'Cache-Control': 'no-store' } },
          )
        }
      },
    },
  },
})
