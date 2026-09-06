import { createFileRoute } from '@tanstack/react-router'
import { triggerWorkflow } from '#/server/github'

async function handleCron(request: Request) {
  const cronSecret = process.env.CRON_SECRET || ''
  const auth = request.headers.get('authorization') || ''
  const ok = Boolean(cronSecret) && auth === `Bearer ${cronSecret}`

  if (!ok) {
    return Response.json(
      { error: 'unauthorized' },
      { status: 401, headers: { 'Cache-Control': 'no-store' } },
    )
  }

  try {
    const result = await triggerWorkflow({ fullSweep: false })
    return Response.json(
      { ...result, via: 'cron' },
      { headers: { 'Cache-Control': 'no-store' } },
    )
  } catch (err: any) {
    return Response.json(
      {
        error: 'cron_trigger_failed',
        message: String(err?.message || err),
      },
      {
        status: err?.status || 500,
        headers: { 'Cache-Control': 'no-store' },
      },
    )
  }
}

export const Route = createFileRoute('/api/cron')({
  server: {
    handlers: {
      GET: async ({ request }) => handleCron(request),
      POST: async ({ request }) => handleCron(request),
    },
  },
})
