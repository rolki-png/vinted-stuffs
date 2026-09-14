import { createFileRoute } from '@tanstack/react-router'
import { opBrands } from '@googlarz/vinted-client'
import { getVintedClient } from '#/server/vintedCatalogue.js'
import { defaultCountry } from '#/server/marketDefaults.js'

export const Route = createFileRoute('/api/brands')({
  server: {
    handlers: {
      GET: async ({ request }) => {
        try {
          const url = new URL(request.url)
          const q = String(url.searchParams.get('q') || '').trim()
          const country = String(url.searchParams.get('country') || defaultCountry())
          const limit = Math.min(
            20,
            Math.max(1, Number(url.searchParams.get('limit') || 10) || 10),
          )
          if (!q) {
            return Response.json(
              { brands: [] },
              { headers: { 'Cache-Control': 'no-store' } },
            )
          }
          const brands = await opBrands(getVintedClient(), {
            query: q,
            country: country as any,
            limit,
          })
          return Response.json(
            { brands },
            { headers: { 'Cache-Control': 'no-store' } },
          )
        } catch (err: any) {
          return Response.json(
            {
              error: 'brands_unavailable',
              message: String(err?.message || err),
              brands: [],
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
