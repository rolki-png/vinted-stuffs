import { createFileRoute } from '@tanstack/react-router'
import { buildFindsPage } from '#/server/findsPage.js'

export const Route = createFileRoute('/api/finds')({
  server: {
    handlers: {
      GET: async ({ request }) => {
        try {
          const url = new URL(request.url)
          const page = await buildFindsPage({
            page: url.searchParams.get('page'),
            limit: url.searchParams.get('limit'),
            veto:
              url.searchParams.get('veto') ||
              url.searchParams.get('veto_mode') ||
              'active',
            watch: url.searchParams.get('watch'),
            band: url.searchParams.get('band'),
            min_score:
              url.searchParams.get('min_score') ||
              url.searchParams.get('minScore'),
            source: url.searchParams.get('source'),
            q: url.searchParams.get('q'),
            sort: url.searchParams.get('sort'),
          })
          return Response.json(page, {
            headers: { 'Cache-Control': 'no-store' },
          })
        } catch (err) {
          return Response.json(
            {
              error: 'finds_failed',
              message: String(err instanceof Error ? err.message : err),
            },
            { status: 500, headers: { 'Cache-Control': 'no-store' } },
          )
        }
      },
    },
  },
})
