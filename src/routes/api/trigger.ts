import { createFileRoute } from '@tanstack/react-router'
import { triggerWorkflow } from '#/server/github'

export const Route = createFileRoute('/api/trigger')({
  server: {
    handlers: {
      POST: async ({ request }) => {
        // Open from the desk UI — auth is GITHUB_TOKEN server-side, not a pasted secret.
        try {
          const body = (await request.json().catch(() => ({}))) as Record<
            string,
            unknown
          >
          const result = await triggerWorkflow({
            fullSweep: Boolean(body.full_sweep || body.fullSweep),
            skipScoring: Boolean(body.skip_scoring || body.skipScoring),
          })
          return Response.json(result, {
            headers: { 'Cache-Control': 'no-store' },
          })
        } catch (err: any) {
          return Response.json(
            {
              error: 'trigger_failed',
              message: String(err?.message || err),
            },
            {
              status: err?.status || 500,
              headers: { 'Cache-Control': 'no-store' },
            },
          )
        }
      },
    },
  },
})
