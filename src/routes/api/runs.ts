import { createFileRoute } from '@tanstack/react-router'
import { listWorkflowRuns } from '#/server/github'

export const Route = createFileRoute('/api/runs')({
  server: {
    handlers: {
      GET: async () => {
        try {
          const data = await listWorkflowRuns()
          return Response.json(data, {
            headers: { 'Cache-Control': 'no-store' },
          })
        } catch (err: any) {
          return Response.json(
            {
              error: 'status_failed',
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
