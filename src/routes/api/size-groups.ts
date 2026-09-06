import { createFileRoute } from '@tanstack/react-router'
import { opGetSizeGroups } from '@googlarz/vinted-client'
import { getVintedClient } from '#/server/vintedCatalogue.js'

export const Route = createFileRoute('/api/size-groups')({
  server: {
    handlers: {
      GET: async ({ request }) => {
        try {
          const url = new URL(request.url)
          const country = String(url.searchParams.get('country') || 'ro')
          const groups = await opGetSizeGroups(getVintedClient(), {
            country: country as any,
          })
          // Drop empty groups for UI noise reduction
          const size_groups = (groups || [])
            .map((g) => ({
              id: g.id,
              caption: g.caption,
              description: g.description,
              sizes: (g.sizes || []).map((s) => ({ id: s.id, title: s.title })),
            }))
            .filter((g) => g.sizes.length > 0)
          return Response.json(
            { size_groups },
            {
              headers: {
                'Cache-Control': 'public, max-age=3600',
              },
            },
          )
        } catch (err: any) {
          return Response.json(
            {
              error: 'size_groups_unavailable',
              message: String(err?.message || err),
              size_groups: [],
            },
            {
              status: 502,
              headers: { 'Cache-Control': 'no-store' },
            },
          )
        }
      },
    },
  },
})
