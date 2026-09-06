import { createFileRoute } from '@tanstack/react-router'
import { loadHunts, mutateHunts } from '#/server/githubConfig.js'

function json(data: unknown, status = 200) {
  return Response.json(data, {
    status,
    headers: { 'Cache-Control': 'no-store' },
  })
}

export const Route = createFileRoute('/api/hunts')({
  server: {
    handlers: {
      GET: async () => {
        try {
          const result = await loadHunts()
          return json(result)
        } catch (err: any) {
          return json(
            {
              error: err?.code || 'upstream',
              message: String(err?.message || err),
              sha: err?.sha,
            },
            err?.status || 500,
          )
        }
      },
      POST: async ({ request }) => {
        try {
          const body = (await request.json().catch(() => ({}))) as Record<
            string,
            unknown
          >
          const mode = String(body.mode || '')
          const result = await mutateHunts({
            mode: mode as 'add' | 'replace' | 'remove',
            hunt: body.hunt as object | undefined,
            originalName:
              body.originalName != null ? String(body.originalName) : undefined,
            sha: body.sha != null ? String(body.sha) : '',
          })
          return json(result)
        } catch (err: any) {
          return json(
            {
              error: err?.code || 'upstream',
              message: String(err?.message || err),
              sha: err?.sha,
            },
            err?.status || 500,
          )
        }
      },
    },
  },
})
